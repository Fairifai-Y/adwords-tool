"""Adjust tROAS for PMax campaigns that have target_roas set directly in the campaign.

This script finds all PMax campaigns with target_roas set and adjusts their target ROAS
by a specified percentage, or resets them based on seller margin (custom_label_1).

Usage:
  py src/adjust_pmax_roas.py --customer 5059126003 --percentage -20 --apply false
  py src/adjust_pmax_roas.py --customer 5059126003 --percentage +10 --apply true
  py src/adjust_pmax_roas.py --customer 5059126003 --reset --apply true
  py src/adjust_pmax_roas.py --customer 5059126003 --prefix "PMax ALL" --percentage -15 --apply true
"""

from __future__ import annotations

import argparse
import re
import time
import random
from pathlib import Path
import os
from typing import List, Dict, Optional, Tuple
from dotenv import load_dotenv

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from google.api_core import exceptions as gax
from google.protobuf import field_mask_pb2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "google-ads.yaml"


def _should_retry(exc, client=None):
    """Check if an exception should be retried."""
    if isinstance(exc, (gax.ServiceUnavailable, gax.DeadlineExceeded)):
        return True, "UNAVAILABLE"
    if isinstance(exc, GoogleAdsException):
        for err in exc.failure.errors:
            ec = err.error_code
            if hasattr(ec, "database_error"):
                if ec.database_error.name == "CONCURRENT_MODIFICATION":
                    return True, "CONCURRENT_MODIFICATION"
            if hasattr(ec, "internal_error") and ec.internal_error.name == "INTERNAL_ERROR":
                return True, "INTERNAL_ERROR"
            if hasattr(ec, "quota_error") and ec.quota_error.name == "RESOURCE_EXHAUSTED":
                return True, "RESOURCE_EXHAUSTED"
    return False, "UNKNOWN"


def _retry(fn, attempts=6, base=1.6, first_sleep=1.0, context=""):
    """Retry function with exponential backoff."""
    delay = first_sleep
    for i in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:
            ok, reason = _should_retry(e)
            if not ok or i == attempts:
                if context:
                    print(f"  [FATAL] {context} failed after {attempts} attempts: {e}")
                raise
            sleep_s = delay * (1.0 + random.random() * 0.25)
            context_msg = f" ({context})" if context else ""
            print(f"  [RETRY] {reason}{context_msg}, retrying in {sleep_s:.1f}s (attempt {i}/{attempts})")
            time.sleep(sleep_s)
            delay *= base


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value)


def _extract_seller_from_campaign_name(campaign_name: str) -> Optional[str]:
    """Extract seller name from PMax campaign name like 'PMax ALL - seller_name - timestamp'."""
    # PMax campaign names are typically: "{prefix} - {label_value} - {timestamp}"
    # We want to extract the label_value (which is often the seller name for label_0)
    parts = campaign_name.split(' - ')
    if len(parts) >= 2:
        # Return the middle part (label_value)
        return parts[1].strip()
    return None


def _get_margin_for_seller(client: GoogleAdsClient, customer_id: str, seller_name: str) -> Tuple[Optional[float], Optional[str]]:
    """Get margin percentage (custom_label_1) for a seller (custom_label_0).
    Returns (margin, None) on success, or (None, reason) when margin could not be determined.
    """
    ga = client.get_service("GoogleAdsService")
    
    # Escape GAQL string literal
    def _escape_gaql(value: str) -> str:
        if value is None:
            return ""
        return value.replace("\\", "\\\\").replace("'", "\\'")
    
    safe_seller = _escape_gaql(seller_name)
    # Use explicit date range instead of DURING LAST_N_DAYS
    from datetime import datetime, timedelta
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    
    query = (
        "SELECT segments.date, segments.product_custom_attribute0, segments.product_custom_attribute1, metrics.impressions "
        "FROM shopping_performance_view "
        f"WHERE segments.date BETWEEN '{start_date}' AND '{end_date}' "
        f"AND segments.product_custom_attribute0 = '{safe_seller}' "
        "AND segments.product_custom_attribute1 IS NOT NULL"
    )
    
    # Track all label_1 values with their dates, then pick the most recent
    label_1_by_date = {}  # date_str -> label_1
    
    try:
        for row in ga.search(customer_id=customer_id, query=query):
            label_1 = getattr(row.segments, "product_custom_attribute1") or ""
            date_str = str(row.segments.date)
            if label_1:
                # Store the label_1 for this date (if we haven't seen this date yet, or if this date is newer)
                if date_str not in label_1_by_date or date_str > max(label_1_by_date.keys(), default=""):
                    label_1_by_date[date_str] = label_1
        
        # Find the most recent date and its corresponding label_1
        if not label_1_by_date:
            return None, "geen traffic in laatste 30 dagen met deze sellernaam (custom_label_0) en custom_label_1; controleer of de campagnenaam exact overeenkomt met label_0"
        
        latest_date = max(label_1_by_date.keys())
        latest_label_1 = label_1_by_date[latest_date]
    except Exception as e:
        return None, f"API-fout: {e}"
    
    if not latest_label_1:
        return None, "geen traffic in laatste 30 dagen met deze sellernaam (custom_label_0) en custom_label_1; controleer of de campagnenaam exact overeenkomt met label_0"
    
    # Parse percentage from label_1 (assuming format like "17.5%" or "15%")
    try:
        clean_value = latest_label_1.replace('%', '').strip()
        percentage = float(clean_value)
        if percentage <= 0:
            return None, f"custom_label_1 waarde '{latest_label_1}' is geen geldig margepercentage (>0)"
        return percentage, None
    except ValueError:
        return None, f"custom_label_1 waarde '{latest_label_1}' is geen getal (verwacht bijv. '15%' of '17.5%')"


MIN_TROAS = 3.0  # Failsafe: tROAS nooit lager dan 300% (3.0)


def _apply_min_troas(value: float) -> float:
    """Zorg dat tROAS nooit onder MIN_TROAS (3.0 = 300%) komt."""
    return round(max(float(value), MIN_TROAS), 2)


def _calculate_standard_troas(margin_percentage: float) -> float:
    """Calculate standard tROAS from margin percentage."""
    if margin_percentage <= 0:
        return 6.5  # Default fallback
    return round(1.0 / (margin_percentage / 100.0), 2)


def find_pmax_campaigns_with_roas(client: GoogleAdsClient, customer_id: str, prefix: Optional[str] = None) -> List[Dict]:
    """Find all ENABLED PMax campaigns with target_roas set directly in the campaign."""
    ga = client.get_service("GoogleAdsService")
    
    # Build query
    where_clause = (
        "campaign.advertising_channel_type = 'PERFORMANCE_MAX' "
        "AND campaign.status = 'ENABLED' "
        "AND campaign.maximize_conversion_value.target_roas IS NOT NULL"
    )
    
    if prefix:
        safe_prefix = prefix.replace("'", "\\'").replace("\\", "\\\\")
        where_clause += f" AND campaign.name LIKE '{safe_prefix}%'"
    
    query = f"""
        SELECT 
            campaign.resource_name,
            campaign.id,
            campaign.name,
            campaign.maximize_conversion_value.target_roas
        FROM campaign
        WHERE {where_clause}
    """
    
    campaigns = []
    try:
        for row in ga.search(customer_id=customer_id, query=query):
            campaign_name = row.campaign.name
            current_roas = row.campaign.maximize_conversion_value.target_roas
            
            if current_roas is not None:
                campaigns.append({
                    'resource_name': row.campaign.resource_name,
                    'id': row.campaign.id,
                    'name': campaign_name,
                    'current_roas': float(current_roas)
                })
    except Exception as e:
        print(f"[ERROR] Kon PMax campagnes niet ophalen: {e}")
        raise
    
    return campaigns


def adjust_campaign_roas(
    client: GoogleAdsClient,
    customer_id: str,
    campaign_rn: str,
    new_roas: float,
    campaign_name: str
) -> bool:
    """Update a PMax campaign's target ROAS."""
    camp_svc = client.get_service("CampaignService")
    
    op = client.get_type("CampaignOperation")
    camp = op.update
    camp.resource_name = campaign_rn
    camp.maximize_conversion_value.target_roas = float(new_roas)
    
    # Set update mask
    fm = field_mask_pb2.FieldMask(paths=["maximize_conversion_value.target_roas"])
    op.update_mask.CopyFrom(fm)
    
    try:
        _retry(
            lambda: camp_svc.mutate_campaigns(customer_id=customer_id, operations=[op]),
            context=f"Update campaign {campaign_name}"
        )
        return True
    except Exception as e:
        print(f"  [ERROR] Kon campagne {campaign_name} niet updaten: {e}")
        return False


def main() -> None:
    """Main function."""
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
    parser = argparse.ArgumentParser(
        description="Adjust tROAS for PMax campaigns with target_roas set directly in campaign"
    )
    parser.add_argument("--customer", required=True, help="Customer ID")
    parser.add_argument("--login", help="Login customer ID (optional)")
    parser.add_argument("--prefix", type=str, default=None,
                       help="Optional: Only adjust campaigns with this prefix (e.g., 'PMax ALL')")
    parser.add_argument("--percentage", type=float, default=None,
                       help="Percentage adjustment (e.g., -20 for -20%%, +10 for +10%%)")
    parser.add_argument("--reset", action="store_true",
                       help="Reset all campaigns to standard tROAS based on seller margin (custom_label_1)")
    parser.add_argument("--apply", action="store_true", 
                       help="Actually apply changes (default: dry-run preview)")
    
    args = parser.parse_args()
    customer_id = _digits_only(args.customer)
    
    cfg = os.getenv("GOOGLE_ADS_CONFIGURATION_FILE")
    if not cfg:
        cfg = str(PROJECT_ROOT / "config" / "google-ads.yaml")
    print("Config path =", cfg)
    client = GoogleAdsClient.load_from_storage(cfg)
    
    # Force login header from config
    try:
        cli_login = _digits_only(args.login) if args.login else ""
        env_login = os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
        login_id = _digits_only(env_login) if env_login else ""
        if cli_login:
            login_id = cli_login
        if not login_id:
            text = CONFIG_PATH.read_text(encoding="utf-8")
            m = re.search(r"^\s*login_customer_id\s*:\s*(?:['\"])?([^'\"\n#]+)", text, re.M)
            if m:
                login_id = _digits_only(m.group(1))
        if login_id:
            client.login_customer_id = login_id
    except Exception:
        pass
    
    # Validate arguments: need at least one of reset or percentage (percentage can be 0 when combined with reset)
    if not args.reset and args.percentage is None:
        print("[ERROR] Geef --percentage of --reset op (of beide: eerst resetten, dan percentage toepassen)")
        return
    
    # Find all PMax campaigns with target_roas
    prefix_msg = f" met prefix '{args.prefix}'" if args.prefix else ""
    print(f"\nZoeken naar PMax campagnes{prefix_msg} met target_roas...")
    campaigns = find_pmax_campaigns_with_roas(client, customer_id, args.prefix)
    
    if not campaigns:
        print(f"Geen PMax campagnes gevonden{prefix_msg} met target_roas ingesteld.")
        return
    
    print(f"\nGevonden {len(campaigns)} PMax campagne(s):")
    for c in campaigns:
        print(f"  - {c['name']}: ROAS = {c['current_roas']:.2f}")
    
    # Percentage to apply (optional, used when --percentage is set or after reset)
    pct = args.percentage if args.percentage is not None else 0.0
    
    # Calculate new ROAS values
    adjustments = []
    
    if args.reset:
        # Reset mode: calculate standard tROAS from seller margin, then optionally apply percentage
        DEFAULT_TROAS_WHEN_MARGIN_UNKNOWN = 6.5
        print(f"\n[RESET MODE] Berekening standaard ROAS op basis van seller marge (custom_label_1, laatste 30 dagen)...")
        print(f"  Failsafe: tROAS wordt nooit lager dan {MIN_TROAS} (300%).")
        print(f"  Waarom soms geen marge? Geen traffic voor die seller in laatste 30 dagen, of custom_label_1 ontbreekt/geen percentage. Dan gebruiken we standaard tROAS {DEFAULT_TROAS_WHEN_MARGIN_UNKNOWN}.")
        if pct != 0:
            print(f"  Daarna percentage toegepast: {pct:+.1f}%")
        for c in campaigns:
            seller_name = _extract_seller_from_campaign_name(c['name'])
            if not seller_name:
                print(f"  [SKIP] Kon seller naam niet extraheren uit '{c['name']}' (verwacht formaat: 'prefix - sellernaam - timestamp')")
                continue
            
            margin, reason = _get_margin_for_seller(client, customer_id, seller_name)
            if margin is None:
                standard_roas = DEFAULT_TROAS_WHEN_MARGIN_UNKNOWN
                new_roas = _apply_min_troas(standard_roas * (1 + pct / 100))
                adjustments.append({
                    'campaign': c,
                    'new_roas': new_roas,
                    'margin': None,
                    'seller': seller_name
                })
                low_note = f" (min {MIN_TROAS})" if new_roas == MIN_TROAS else ""
                print(f"  [DEFAULT {DEFAULT_TROAS_WHEN_MARGIN_UNKNOWN}] {c['name']}: marge niet gevonden ({reason}) -> tROAS {standard_roas:.2f} -> {new_roas:.2f}{low_note}")
                continue
            
            standard_roas = _calculate_standard_troas(margin)
            new_roas = _apply_min_troas(standard_roas * (1 + pct / 100))
            adjustments.append({
                'campaign': c,
                'new_roas': new_roas,
                'margin': margin,
                'seller': seller_name
            })
            low_note = f" (failsafe min {MIN_TROAS})" if new_roas == MIN_TROAS else ""
            if pct != 0:
                print(f"  {c['name']}: {c['current_roas']:.2f} -> {standard_roas:.2f} (reset) -> {new_roas:.2f} (+ {pct:+.1f}%){low_note}")
            else:
                print(f"  {c['name']}: {c['current_roas']:.2f} -> {standard_roas:.2f} (marge: {margin}%){low_note}")
    else:
        # Percentage-only mode: apply percentage to current ROAS
        print(f"\nBerekening nieuwe ROAS waarden ({pct:+.1f}%), minimum tROAS = {MIN_TROAS} (300%):")
        for c in campaigns:
            new_roas = _apply_min_troas(c['current_roas'] * (1 + pct / 100))
            adjustments.append({
                'campaign': c,
                'new_roas': new_roas
            })
            low_note = f" (failsafe min {MIN_TROAS})" if new_roas == MIN_TROAS else ""
            print(f"  {c['name']}: {c['current_roas']:.2f} -> {new_roas:.2f}{low_note}")
    
    # Apply or preview
    if args.apply:
        print(f"\n[APPLY MODE] Aanpassen van {len(adjustments)} campagne(s)...")
        success_count = 0
        failed_count = 0
        
        for i, adj in enumerate(adjustments, 1):
            campaign = adj['campaign']
            new_roas = adj['new_roas']
            
            print(f"\n[{i}/{len(adjustments)}] Aanpassen: {campaign['name']}")
            print(f"  ROAS: {campaign['current_roas']:.2f} -> {new_roas:.2f}")
            
            if adjust_campaign_roas(client, customer_id, campaign['resource_name'], new_roas, campaign['name']):
                print(f"  [OK] Campagne aangepast")
                success_count += 1
                # Small delay between updates
                if i < len(adjustments):
                    time.sleep(0.5)
            else:
                failed_count += 1
        
        print(f"\n[RESULTAAT]")
        print(f"  Succesvol aangepast: {success_count}")
        print(f"  Mislukt: {failed_count}")
    else:
        print(f"\n[DRY-RUN MODE] Geen wijzigingen doorgevoerd.")
        print(f"Gebruik --apply om de wijzigingen daadwerkelijk door te voeren.")


if __name__ == "__main__":
    main()
