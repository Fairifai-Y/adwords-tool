"""Create PMax campaign plans based on feed labels from linked Merchant Center.

This script discovers label values via ShoppingPerformanceView and prepares
one PMax feed-only campaign per label value. By default it performs a dry-run (no mutations).

Usage:
  py src/label_campaigns.py --customer 5059126003 --label-index 0 --apply false

Notes:
- label-index must be 0..4 (maps to custom_label0..custom_label4)
- Discovery uses last 30 days of data; products without traffic may not appear
  in ShoppingPerformanceView. Later we can switch to Content API if needed.
- Creates PMax feed-only campaigns with tROAS based on custom_label1 (or default 6.5)
"""

from __future__ import annotations

import argparse
import re
import time
import random
from dataclasses import dataclass
from typing import Dict, List, Tuple
from typing import Optional
from pathlib import Path
import os
from dotenv import load_dotenv

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from google.api_core import exceptions as gax
from datetime import datetime, timezone, timedelta
from google.protobuf import field_mask_pb2


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "google-ads.yaml"


def _should_retry(exc, client=None):
    """Check if an exception should be retried."""
    # gRPC/unavailable/timeouts
    if isinstance(exc, (gax.ServiceUnavailable, gax.DeadlineExceeded)):
        return True, "UNAVAILABLE"
    # Google Ads failures
    if isinstance(exc, GoogleAdsException):
        for err in exc.failure.errors:
            ec = err.error_code
            # DB lock/concurrent modification
            if hasattr(ec, "database_error"):
                if ec.database_error.name == "CONCURRENT_MODIFICATION":
                    return True, "CONCURRENT_MODIFICATION"
            # Resource limit exceeded - retry with longer delay
            if hasattr(ec, "resource_count_limit_exceeded_error"):
                if ec.resource_count_limit_exceeded_error.name == "RESOURCE_LIMIT":
                    return True, "RESOURCE_LIMIT"
            # af en toe interne of tijdelijke fouten
            if hasattr(ec, "internal_error") and ec.internal_error.name == "INTERNAL_ERROR":
                return True, "INTERNAL_ERROR"
            if hasattr(ec, "quota_error") and ec.quota_error.name == "RESOURCE_EXHAUSTED":
                return True, "RESOURCE_EXHAUSTED"
    return False, ""


def _retry(fn, attempts=6, base=1.6, first_sleep=1.0):
    """Retry function with exponential backoff."""
    delay = first_sleep
    for i in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:
            ok, reason = _should_retry(e)
            if not ok or i == attempts:
                raise
            sleep_s = delay * (1.0 + random.random()*0.25)
            print(f"  Retry wegens {reason} in {sleep_s:.1f}s (poging {i}/{attempts})")
            time.sleep(sleep_s)
            delay *= base


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value)


def _label_field(index: int) -> str:
    if index not in {0, 1, 2, 3, 4}:
        raise ValueError("label-index must be 0..4")
    return f"segments.product_custom_attribute{index}"


def discover_all_labels(client: GoogleAdsClient, customer_id: str, label_index: int) -> Dict[str, Dict]:
    """Discover ALL labels by trying multiple approaches including Merchant Center feed access."""
    field = _label_field(label_index)
    ga = client.get_service("GoogleAdsService")
    
    labels: Dict[str, Dict] = {}
    
    print(f"  [INFO] ATTENTION: For accounts with paused campaigns, Google Ads API can only show")
    print(f"  [INFO] labels that are currently active in campaigns. To see ALL labels (224), you need:")
    print(f"  [INFO] 1. Either activate some campaigns temporarily, OR")
    print(f"  [INFO] 2. Use Merchant Center API to access the feed directly, OR") 
    print(f"  [INFO] 3. Export the feed from Google Merchant Center manually")
    print(f"  [INFO]")
    print(f"  [INFO] Trying to find all available labels from Google Ads API...")
    
    # Try to get all possible labels from Google Ads API
    all_attempts = [
        ("Performance data (30 days)", 30),
        ("Performance data (90 days)", 90), 
        ("Performance data (180 days)", 180),
        ("Performance data (365 days)", 365),
        ("All campaigns (Shopping)", "campaign"),
        ("All campaigns (PMax)", "campaign_pmax"),
        ("Asset groups", "asset_groups"),
        ("No date filter", "no_date")
    ]
    
    for attempt_name, attempt_type in all_attempts:
        try:
            print(f"  [INFO] Trying {attempt_name}...")
            
            if isinstance(attempt_type, int):
                # Use explicit date range instead of DURING LAST_N_DAYS
                end_date = datetime.now().strftime('%Y-%m-%d')
                start_date = (datetime.now() - timedelta(days=attempt_type)).strftime('%Y-%m-%d')
                query = f"""
                    SELECT {field}, metrics.impressions
                    FROM shopping_performance_view
                    WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
                    AND {field} IS NOT NULL
                    """
                
                count = 0
                for row in ga.search(customer_id=customer_id, query=query):
                    label = getattr(row.segments, f"product_custom_attribute{label_index}") or ""
                    if label and label not in labels:
                        labels[label] = {
                            'impressions': 0, 'clicks': 0, 'conversions': 0, 'conversions_value': 0,
                            'cost': 0, 'ctr': 0, 'avg_cpc': 0, 'cpa': 0, 'conversion_rate': 0,
                            'value_per_conversion': 0, 'custom_label_1': set(), 'custom_label_2': set(),
                            'has_traffic': False
                        }
                        count += 1
                
                print(f"    Found {count} new labels from {attempt_name}")
                
            elif attempt_type == "campaign":
                # Get all shopping campaigns
                campaign_query = """
                    SELECT campaign.id, campaign.name, campaign.status
                    FROM campaign
                    WHERE campaign.advertising_channel_type = 'SHOPPING'
                    """
                
                count = 0
                for row in ga.search(customer_id=customer_id, query=campaign_query):
                    campaign_id = row.campaign.id
                    try:
                        product_group_query = f"""
                            SELECT {field}
                            FROM product_group_view
                            WHERE campaign.id = {campaign_id}
                            AND {field} IS NOT NULL
                            """
                        
                        for pg_row in ga.search(customer_id=customer_id, query=product_group_query):
                            label = getattr(pg_row.segments, f"product_custom_attribute{label_index}") or ""
                            if label and label not in labels:
                                labels[label] = {
                                    'impressions': 0, 'clicks': 0, 'conversions': 0, 'conversions_value': 0,
                                    'cost': 0, 'ctr': 0, 'avg_cpc': 0, 'cpa': 0, 'conversion_rate': 0,
                                    'value_per_conversion': 0, 'custom_label_1': set(), 'custom_label_2': set(),
                                    'has_traffic': False
                                }
                                count += 1
                    except:
                        pass
                
                print(f"    Found {count} new labels from {attempt_name}")
                
            elif attempt_type == "campaign_pmax":
                # Get all PMax campaigns
                pmax_query = """
                    SELECT campaign.id, campaign.name, campaign.status
                    FROM campaign
                    WHERE campaign.advertising_channel_type = 'PERFORMANCE_MAX'
                    """
                
                count = 0
                for row in ga.search(customer_id=customer_id, query=pmax_query):
                    campaign_id = row.campaign.id
                    try:
                        asset_query = f"""
                            SELECT {field}
                            FROM asset_group_listing_group_filter
                            WHERE campaign.id = {campaign_id}
                            AND {field} IS NOT NULL
                            """
                        
                        for ag_row in ga.search(customer_id=customer_id, query=asset_query):
                            label = getattr(ag_row.segments, f"product_custom_attribute{label_index}") or ""
                            if label and label not in labels:
                                labels[label] = {
                                    'impressions': 0, 'clicks': 0, 'conversions': 0, 'conversions_value': 0,
                                    'cost': 0, 'ctr': 0, 'avg_cpc': 0, 'cpa': 0, 'conversion_rate': 0,
                                    'value_per_conversion': 0, 'custom_label_1': set(), 'custom_label_2': set(),
                                    'has_traffic': False
                                }
                                count += 1
                    except:
                        pass
                
                print(f"    Found {count} new labels from {attempt_name}")
                
            elif attempt_type == "asset_groups":
                # Try asset groups directly
                asset_query = f"""
                    SELECT {field}
                    FROM asset_group_listing_group_filter
                    WHERE {field} IS NOT NULL
                    """
                
                count = 0
                for row in ga.search(customer_id=customer_id, query=asset_query):
                    label = getattr(row.segments, f"product_custom_attribute{label_index}") or ""
                    if label and label not in labels:
                        labels[label] = {
                            'impressions': 0, 'clicks': 0, 'conversions': 0, 'conversions_value': 0,
                            'cost': 0, 'ctr': 0, 'avg_cpc': 0, 'cpa': 0, 'conversion_rate': 0,
                            'value_per_conversion': 0, 'custom_label_1': set(), 'custom_label_2': set(),
                            'has_traffic': False
                        }
                        count += 1
                
                print(f"    Found {count} new labels from {attempt_name}")
                
            elif attempt_type == "no_date":
                # Try without date filter
                no_date_query = f"""
                    SELECT {field}
                    FROM shopping_performance_view
                    WHERE {field} IS NOT NULL
                    """
                
                count = 0
                for row in ga.search(customer_id=customer_id, query=no_date_query):
                    label = getattr(row.segments, f"product_custom_attribute{label_index}") or ""
                    if label and label not in labels:
                        labels[label] = {
                            'impressions': 0, 'clicks': 0, 'conversions': 0, 'conversions_value': 0,
                            'cost': 0, 'ctr': 0, 'avg_cpc': 0, 'cpa': 0, 'conversion_rate': 0,
                            'value_per_conversion': 0, 'custom_label_1': set(), 'custom_label_2': set(),
                            'has_traffic': False
                        }
                        count += 1
                
                print(f"    Found {count} new labels from {attempt_name}")
                
        except Exception as e:
            print(f"    [WARNING] {attempt_name} failed: {e}")
    
    # Calculate derived metrics for labels with traffic
    for label, data in labels.items():
        if data['conversions'] > 0:
            data['cpa'] = data['cost'] / data['conversions']
        if data['cost'] > 0:
            data['roas'] = data['conversions_value'] / data['cost']
            data['roi'] = data['roas'] - 1
        else:
            data['roas'] = 0
            data['roi'] = 0
        if data['clicks'] > 0:
            data['conversion_rate'] = (data['conversions'] / data['clicks']) * 100
        if data['impressions'] > 0:
            data['ctr'] = (data['clicks'] / data['impressions']) * 100
        if data['clicks'] > 0:
            data['avg_cpc'] = data['cost'] / data['clicks']
    
    return dict(sorted(labels.items(), key=lambda kv: (-kv[1]['impressions'], kv[0])))


def discover_labels(client: GoogleAdsClient, customer_id: str, label_index: int, include_label_1: bool = False, include_label_2: bool = False, extended_search: bool = False) -> Dict[str, Dict]:
    field = _label_field(label_index)
    ga = client.get_service("GoogleAdsService")
    
    # Build the query with the required custom label fields
    additional_fields = []
    if include_label_1:
        additional_fields.append("segments.product_custom_attribute1")
    if include_label_2:
        additional_fields.append("segments.product_custom_attribute2")
    
    additional_fields_str = ", ".join(additional_fields) if additional_fields else ""
    if additional_fields_str:
        additional_fields_str = ", " + additional_fields_str
    
    # Use longer date range for extended search to find more labels
    days = 90 if extended_search else 30
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    # Try shopping_performance_view first (for Shopping campaigns)
    query = f"""
        SELECT
          {field}{additional_fields_str},
          metrics.impressions,
          metrics.clicks,
          metrics.conversions,
          metrics.conversions_value,
          metrics.cost_micros,
          metrics.ctr,
          metrics.average_cpc,
          metrics.cost_per_conversion,
          metrics.conversions_from_interactions_rate,
          metrics.value_per_conversion
        FROM shopping_performance_view
        WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
        AND {field} IS NOT NULL
        """
    labels: Dict[str, Dict] = {}
    
    # First try shopping_performance_view (for Shopping campaigns)
    try:
        for row in ga.search(customer_id=customer_id, query=query):
            label = getattr(row.segments, f"product_custom_attribute{label_index}") or ""
            if not label:
                continue
            
            if label not in labels:
                labels[label] = {
                    'impressions': 0,
                    'clicks': 0,
                    'conversions': 0,
                    'conversions_value': 0,
                    'cost': 0,
                    'ctr': 0,
                    'avg_cpc': 0,
                    'cpa': 0,
                    'conversion_rate': 0,
                    'value_per_conversion': 0,
                    'custom_label_1': set(),  # Store unique custom label 1 values
                    'custom_label_2': set()   # Store unique custom label 2 values
                }
            
            # Collect custom label 1 values if requested
            if include_label_1:
                label_1_value = getattr(row.segments, "product_custom_attribute1") or ""
                if label_1_value:
                    labels[label]['custom_label_1'].add(label_1_value)
            
            # Collect custom label 2 values if requested
            if include_label_2:
                label_2_value = getattr(row.segments, "product_custom_attribute2") or ""
                if label_2_value:
                    labels[label]['custom_label_2'].add(label_2_value)
            
            # Aggregate the data
            labels[label]['impressions'] += int(row.metrics.impressions)
            labels[label]['clicks'] += int(row.metrics.clicks)
            labels[label]['conversions'] += int(row.metrics.conversions)
            labels[label]['conversions_value'] += float(row.metrics.conversions_value)
            labels[label]['cost'] += float(row.metrics.cost_micros) / 1_000_000
            labels[label]['ctr'] = float(row.metrics.ctr) * 100 if row.metrics.ctr else 0
            labels[label]['avg_cpc'] = float(row.metrics.average_cpc) if row.metrics.average_cpc else 0
            labels[label]['cpa'] = float(row.metrics.cost_per_conversion) if row.metrics.cost_per_conversion else 0
            labels[label]['conversion_rate'] = float(row.metrics.conversions_from_interactions_rate) * 100 if row.metrics.conversions_from_interactions_rate else 0
            labels[label]['value_per_conversion'] = float(row.metrics.value_per_conversion) if row.metrics.value_per_conversion else 0
    except Exception as e:
        print(f"  [WARNING] Could not get labels from shopping_performance_view: {e}")
    
    # Note: PMax campaigns use shopping_performance_view, not product_group_view
    # The product_group_view doesn't support custom attributes, so we skip it
    
    # For extended search, also try a broader query without campaign type restrictions
    if extended_search:
        try:
            print(f"  [INFO] Extended search: trying broader query for more labels...")
            # Use explicit date range for 90 days
            end_date_ext = datetime.now().strftime('%Y-%m-%d')
            start_date_ext = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
            extended_query = f"""
                SELECT
                  {field}{additional_fields_str},
                  metrics.impressions,
                  metrics.clicks,
                  metrics.conversions,
                  metrics.conversions_value,
                  metrics.cost_micros,
                  metrics.ctr,
                  metrics.average_cpc,
                  metrics.cost_per_conversion,
                  metrics.conversions_from_interactions_rate,
                  metrics.value_per_conversion
                FROM shopping_performance_view
                WHERE segments.date BETWEEN '{start_date_ext}' AND '{end_date_ext}'
                AND {field} IS NOT NULL
                AND metrics.impressions > 0
                """
            
            for row in ga.search(customer_id=customer_id, query=extended_query):
                label = getattr(row.segments, f"product_custom_attribute{label_index}") or ""
                if not label:
                    continue
                
                if label not in labels:
                    labels[label] = {
                        'impressions': 0,
                        'clicks': 0,
                        'conversions': 0,
                        'conversions_value': 0,
                        'cost': 0,
                        'ctr': 0,
                        'avg_cpc': 0,
                        'cpa': 0,
                        'conversion_rate': 0,
                        'value_per_conversion': 0,
                        'custom_label_1': set(),
                        'custom_label_2': set()
                    }
                
                # Collect custom label 1 values if requested
                if include_label_1:
                    label_1_value = getattr(row.segments, "product_custom_attribute1") or ""
                    if label_1_value:
                        labels[label]['custom_label_1'].add(label_1_value)
                
                # Collect custom label 2 values if requested
                if include_label_2:
                    label_2_value = getattr(row.segments, "product_custom_attribute2") or ""
                    if label_2_value:
                        labels[label]['custom_label_2'].add(label_2_value)
                
                # Aggregate the data
                labels[label]['impressions'] += int(row.metrics.impressions)
                labels[label]['clicks'] += int(row.metrics.clicks)
                labels[label]['conversions'] += int(row.metrics.conversions)
                labels[label]['conversions_value'] += float(row.metrics.conversions_value)
                labels[label]['cost'] += float(row.metrics.cost_micros) / 1_000_000
                labels[label]['ctr'] = float(row.metrics.ctr) * 100 if row.metrics.ctr else 0
                labels[label]['avg_cpc'] = float(row.metrics.average_cpc) if row.metrics.average_cpc else 0
                labels[label]['cpa'] = float(row.metrics.cost_per_conversion) if row.metrics.cost_per_conversion else 0
                labels[label]['conversion_rate'] = float(row.metrics.conversions_from_interactions_rate) * 100 if row.metrics.conversions_from_interactions_rate else 0
                labels[label]['value_per_conversion'] = float(row.metrics.value_per_conversion) if row.metrics.value_per_conversion else 0
        except Exception as e:
            print(f"  [WARNING] Could not get labels from extended search: {e}")
    
    # Calculate derived metrics
    for label, data in labels.items():
        if data['conversions'] > 0:
            data['cpa'] = data['cost'] / data['conversions']
        if data['cost'] > 0:
            data['roas'] = data['conversions_value'] / data['cost']
            data['roi'] = data['roas'] - 1
        else:
            data['roas'] = 0
            data['roi'] = 0
        if data['clicks'] > 0:
            data['conversion_rate'] = (data['conversions'] / data['clicks']) * 100
        if data['impressions'] > 0:
            data['ctr'] = (data['clicks'] / data['impressions']) * 100
        if data['clicks'] > 0:
            data['avg_cpc'] = data['cost'] / data['clicks']
    
    return dict(sorted(labels.items(), key=lambda kv: (-kv[1]['impressions'], kv[0])))


@dataclass(frozen=True)
class CampaignPlan:
    label_value: str
    name: str
    daily_budget_micros: int
    bidding: str  # e.g., "MAXIMIZE_CONVERSION_VALUE"
    target_roas: float | None


def build_plans_for_labels(
    labels_to_impr: Dict[str, int],
    prefix: str,
    daily_budget: float,
    default_target_roas: float | None,
    per_label_troas: Optional[Dict[str, float]] = None,
) -> List[CampaignPlan]:
    plans: List[CampaignPlan] = []
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    for label, _ in labels_to_impr.items():
        safe_label = re.sub(r"[^A-Za-z0-9 _-]+", " ", label).strip()[:40]
        name = f"{prefix} - {safe_label} - {timestamp}" if prefix else f"{safe_label} - {timestamp}"
        plan_troas = (per_label_troas or {}).get(label, default_target_roas)
        plans.append(
            CampaignPlan(
                label_value=label,
                name=name,
                daily_budget_micros=int(round(daily_budget * 1_000_000)),
                bidding="MAXIMIZE_CONVERSION_VALUE",
                target_roas=plan_troas,
            )
        )
    return plans


def get_existing_pmax_campaigns(client: GoogleAdsClient, customer_id: str, prefix: str) -> Set[str]:
    """Get set of existing PMax campaign names with the specified prefix."""
    ga = client.get_service("GoogleAdsService")
    
    # Escape prefix for GAQL query
    safe_prefix = prefix.replace("'", "\\'").replace("\\", "\\\\")
    
    query = f"""
        SELECT campaign.name
        FROM campaign
        WHERE campaign.name LIKE '{safe_prefix}%'
        AND campaign.advertising_channel_type = 'PERFORMANCE_MAX'
    """
    
    existing_names = set()
    try:
        for row in ga.search(customer_id=customer_id, query=query):
            existing_names.add(row.campaign.name)
    except Exception as e:
        print(f"[WARN] Kon bestaande PMax campagnes niet ophalen: {e}")
    
    return existing_names


def _discover_label0_to_label1_percent(client: GoogleAdsClient, customer_id: str) -> Dict[str, str]:
    """For each custom_label0, find the dominant custom_label1 value by impressions.

    Returns mapping: label0 -> label1_percent_string (e.g., "15%")
    """
    ga = client.get_service("GoogleAdsService")
    # Use explicit date range instead of DURING LAST_30_DAYS
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    query = (
        f"SELECT segments.product_custom_attribute0, "
        f"segments.product_custom_attribute1, metrics.impressions "
        f"FROM shopping_performance_view "
        f"WHERE segments.date BETWEEN '{start_date}' AND '{end_date}' "
        f"AND segments.product_custom_attribute0 IS NOT NULL"
    )
    agg: Dict[str, Dict[str, int]] = {}
    for row in ga.search(customer_id=customer_id, query=query):
        c0 = getattr(row.segments, "product_custom_attribute0") or ""
        c1 = getattr(row.segments, "product_custom_attribute1") or ""
        if not c0:
            continue
        agg.setdefault(c0, {})
        agg[c0][c1] = agg[c0].get(c1, 0) + int(row.metrics.impressions)
    result: Dict[str, str] = {}
    for c0, counter in agg.items():
        if not counter:
            continue
        best_c1 = max(counter.items(), key=lambda kv: kv[1])[0]
        result[c0] = best_c1
    return result


def _parse_percent_to_troas(percent_str: str) -> Optional[float]:
    """Convert like '15%' or '15' to tROAS 1/0.15 = 6.67.
    Returns None if invalid or <= 0.
    """
    if not percent_str:
        return None
    import re as _re
    m = _re.search(r"([0-9]+(?:\.[0-9]+)?)", percent_str)
    if not m:
        return None
    try:
        pct = float(m.group(1))
        if pct <= 0:
            return None
        troas = 1.0 / (pct / 100.0)
        # round to 2 decimals as typical tROAS convention
        return round(troas, 2)
    except Exception:
        return None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Create campaign plans from feed labels (dry-run by default)")
    p.add_argument("--customer", required=True, help="Target customer id (linked account)")
    p.add_argument("--label-index", type=int, default=0, help="Which custom_label index to use (0..4)")
    p.add_argument("--login", default="", help="Force login customer id (MCC) header")
    p.add_argument("--prefix", default="PMax Feed", help="Campaign name prefix")
    p.add_argument("--daily-budget", type=float, default=5.0, help="Daily budget in account currency")
    p.add_argument("--target-roas", type=float, default=None, help="Optional target ROAS")
    p.add_argument("--roas-factor", type=float, default=0.0, help="Percentage to adjust calculated ROAS (e.g., +10 for 10% increase, -10 for 10% decrease)")
    p.add_argument("--merchant-id", default="", help="Override Merchant Center ID (optional)")
    p.add_argument("--pmax-type", choices=["feed-only", "normal"], default="feed-only", 
                   help="Type of PMax campaign: feed-only (requires merchant_id) or normal (requires creatives)")
    p.add_argument("--start-enabled", action="store_true", 
                   help="Start campaigns and asset groups as ENABLED instead of PAUSED")
    p.add_argument("--target-languages", type=str, default="nl", 
                   help="Comma-separated list of target languages (e.g., 'nl,en,de' or 'nl')")
    p.add_argument("--target-countries", type=str, default="NL", 
                   help="Comma-separated list of target countries (e.g., 'NL,BE,DE' or 'NL')")
    p.add_argument("--feed-label", type=str, default="", 
                   help="Feed label for shopping setting (e.g., 'dk', 'nl', 'de') - use country-specific feed labels from Merchant Center")
    p.add_argument("--portfolio-troas", type=float, default=None, help="Create/use a portfolio Target ROAS strategy with this value (e.g., 4.0)")
    p.add_argument("--only-strategies", type=str, default="false", help="Only create/update portfolio strategies per label (true/false)")
    p.add_argument("--eu-political", type=str, default="false", help="Set contains_eu_political_advertising (true/false)")
    p.add_argument("--apply", type=str, default="false", help="Apply mutations (true/false)")
    p.add_argument("--extended-search", action="store_true", help="Use extended search (90 days, broader queries) to find more labels")
    p.add_argument("--labels-file", default="", help="File containing specific labels to create campaigns for (one per line)")
    p.add_argument(
        "--add-listing-group",
        help="Add listing group to existing asset group. Format: 'asset_group_resource_name:label_value:label_index'"
    )
    p.add_argument(
        "--check-asset-groups",
        help="Check asset groups for a campaign. Format: 'campaign_resource_name'"
    )
    return p.parse_args()


def _count_enabled_pmax_campaigns(client: GoogleAdsClient, customer_id: str) -> int:
    """Count the number of enabled Performance Max campaigns in the account."""
    try:
        ga = client.get_service("GoogleAdsService")
        query = """
            SELECT campaign.id
            FROM campaign
            WHERE campaign.advertising_channel_type = 'PERFORMANCE_MAX'
            AND campaign.status = 'ENABLED'
        """
        count = 0
        for _ in ga.search(customer_id=customer_id, query=query):
            count += 1
        return count
    except Exception as e:
        print(f"  Warning: Kon aantal enabled PMax campagnes niet tellen: {e}")
        return -1  # Return -1 to indicate error


def _find_active_merchant_center_id(client: GoogleAdsClient, customer_id: str) -> str | None:
    try:
        # Try the new service name for v21
        svc = client.get_service("MerchantCenterLinkService")
    except ValueError:
        try:
            # Fallback to older service name
            svc = client.get_service("MerchantCenterLink")
        except ValueError:
            print("Waarschuwing: MerchantCenterLinkService niet beschikbaar in deze API versie")
            return None
    
    try:
        resp = svc.list_merchant_center_links(customer_id=customer_id)
        links = getattr(resp, "merchant_center_links", [])
        for link in links:
            status = getattr(link, "status", None)
            enabled = (
                status == client.enums.MerchantCenterLinkStatusEnum.ENABLED
                if status is not None
                else False
            )
            if not enabled:
                continue
            # Prefer explicit id when available, otherwise parse from resource_name
            mid = getattr(link, "id", None)
            if mid:
                return str(mid)
            rn = getattr(link, "resource_name", "")
            if rn and "/merchantCenterLinks/" in rn:
                return rn.rsplit("/", 1)[-1]
    except Exception as e:
        print(f"Fout bij ophalen Merchant Center ID: {e}")
        return None
    return None





def _create_pmax_campaign(
    client: GoogleAdsClient,
    customer_id: str,
    campaign_name: str,
    daily_budget_micros: int,
    campaign_target_roas: Optional[float] = None,
    is_feed_only: bool = False,
    merchant_id: Optional[str] = None,
    target_languages: Optional[str] = None,
    target_countries: Optional[str] = None,
    feed_label: Optional[str] = None,
) -> str:
    budget_svc = client.get_service("CampaignBudgetService")
    camp_svc = client.get_service("CampaignService")

    # Create budget
    budget_op = client.get_type("CampaignBudgetOperation")
    budget = budget_op.create
    budget.name = f"{campaign_name} - Budget"
    budget.amount_micros = daily_budget_micros
    budget.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD
    budget.explicitly_shared = False
    budget_resp = _retry(lambda: budget_svc.mutate_campaign_budgets(customer_id=customer_id, operations=[budget_op]))
    budget_rn = budget_resp.results[0].resource_name

    # Create campaign (Performance Max - Feed Only)
    camp_op = client.get_type("CampaignOperation")
    camp = camp_op.create
    camp.name = campaign_name
    camp.status = client.enums.CampaignStatusEnum.PAUSED
    camp.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.PERFORMANCE_MAX
    camp.campaign_budget = budget_rn
    
    # Set Shopping Setting for Merchant Center feed (only for feed-only)
    if is_feed_only and merchant_id:
        try:
            camp.shopping_setting.merchant_id = int(merchant_id)
            print(f"  Shopping Setting: merchant_id={merchant_id}")
            
            # Set feed_label for the shopping setting (replaces sales_country)
            if feed_label:
                camp.shopping_setting.feed_label = feed_label
                print(f"  Shopping Setting: feed_label={feed_label}")
            else:
                # Default to 'NL' if no feed_label provided for feed-only campaigns
                camp.shopping_setting.feed_label = "NL"
                print(f"  Shopping Setting: feed_label=NL (default)")
                print(f"  ⚠️  Let op: geen feed_label opgegeven; MC gebruikt feed labels, UI kan 'geen producten' tonen.")
        except Exception as e:
            print(f"  Warning: Could not set shopping setting: {e}")
        
        # Feed-only PMax settings
        camp.url_expansion_opt_out = True  # Disable URL expansion for feed-only
        camp.final_url_suffix = ""  # No final URL suffix for feed-only
        
        # Disable Brand Guidelines for feed-only PMax
        try:
            camp.brand_guidelines_enabled = False
        except Exception:
            pass
    else:
        print(f"  Normale PMax campagne (niet feed-only)")
        # Disable Brand Guidelines for normal PMax to avoid asset requirements
        try:
            camp.brand_guidelines_enabled = False
        except Exception:
            pass
    
    # Set EU political advertising field
    eu_flag = os.getenv("EU_POLITICAL_OVERRIDE")  # optional env override
    eu_value = eu_flag if eu_flag is not None else "false"
    try:
        # prefer CLI arg if available via closure of outer scope (set later via return value)
        eu_value = EU_POLITICAL_VALUE  # type: ignore[name-defined]
    except Exception:
        pass
    eu_bool = str(eu_value).lower() in {"1", "true", "yes"}
    try:
        # Try enum approach first
        if eu_bool:
            camp.contains_eu_political_advertising = client.enums.EuPoliticalAdvertisingStatusEnum.CONTAINS_EU_POLITICAL_ADVERTISING
        else:
            camp.contains_eu_political_advertising = client.enums.EuPoliticalAdvertisingStatusEnum.DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING
    except Exception:
        try:
            # Fallback to boolean
            camp.contains_eu_political_advertising = eu_bool
        except Exception:
            pass
    
    # Set bidding strategy - MaximizeConversionValue with optional tROAS
    if campaign_target_roas is not None:
        camp.maximize_conversion_value.target_roas = float(campaign_target_roas)
    else:
        # Default to MaximizeConversionValue without tROAS (no additional settings needed)
        pass
    
    camp_resp = _retry(lambda: camp_svc.mutate_campaigns(customer_id=customer_id, operations=[camp_op]))
    campaign_rn = camp_resp.results[0].resource_name
    
    # Kleine pauze helpt propagatie
    time.sleep(1.0)
    
    # Add campaign criteria for geo + language targeting
    if target_countries or target_languages:
        _add_campaign_criteria(client, customer_id, campaign_rn, target_countries, target_languages)
    
    return campaign_rn


def _add_campaign_criteria(client: GoogleAdsClient, customer_id: str, campaign_rn: str, 
                          target_countries: Optional[str], target_languages: Optional[str]) -> None:
    """Add location and language criteria to a PMax campaign."""
    criterion_svc = client.get_service("CampaignCriterionService")
    operations = []
    
    # Add location criteria
    if target_countries:
        countries = [country.strip().upper() for country in target_countries.split(',')]
        print(f"  Adding location criteria for countries: {', '.join(countries)}")
        
        for country in countries:
            # Get geo target constant for the country
            geo_id = _get_geo_target_constant(client, customer_id, country)
            if geo_id:
                op = client.get_type("CampaignCriterionOperation")
                criterion = op.create
                criterion.campaign = campaign_rn
                criterion.location.geo_target_constant = f"geoTargetConstants/{geo_id}"
                operations.append(op)
                print(f"    [OK] Added location: {country} (geo_id: {geo_id})")
            else:
                print(f"    [ERROR] Warning: Could not find geo target constant for {country}")
    
    # Add language criteria
    if target_languages:
        languages = [lang.strip().lower() for lang in target_languages.split(',')]
        print(f"  Adding language criteria for languages: {', '.join(languages)}")
        
        for language in languages:
            # Get language constant for the language
            lang_id = _get_language_constant(client, customer_id, language)
            if lang_id:
                op = client.get_type("CampaignCriterionOperation")
                criterion = op.create
                criterion.campaign = campaign_rn
                criterion.language.language_constant = f"languageConstants/{lang_id}"
                operations.append(op)
                print(f"    [OK] Added language: {language} (lang_id: {lang_id})")
            else:
                print(f"    [ERROR] Warning: Could not find language constant for {language}")
    
    # Apply all criteria operations
    if operations:
        try:
            print(f"  [APPLYING] Applying {len(operations)} campaign criteria...")
            result = _retry(lambda: criterion_svc.mutate_campaign_criteria(customer_id=customer_id, operations=operations))
            print(f"  [SUCCESS] Successfully added {len(operations)} campaign criteria")
            
            # Log the results for verification
            for i, op_result in enumerate(result.results):
                if hasattr(op_result, 'campaign_criterion'):
                    criterion = op_result.campaign_criterion
                    if hasattr(criterion, 'location') and criterion.location.geo_target_constant:
                        print(f"    [LOCATION] Location criterion {i+1}: {criterion.location.geo_target_constant}")
                    elif hasattr(criterion, 'language') and criterion.language.language_constant:
                        print(f"    [LANGUAGE] Language criterion {i+1}: {criterion.language.language_constant}")
        except Exception as e:
            print(f"  [ERROR] Error: Could not add campaign criteria: {e}")
    else:
        print(f"  [WARNING] No criteria operations to apply")


def _get_geo_target_constant(client: GoogleAdsClient, customer_id: str, country_code: str) -> Optional[str]:
    """
    Haal het geo target constant ID op voor een 2-letter country code (bv. 'IT').
    We filteren expliciet op target_type='Country' om vergissingen te voorkomen.
    """
    cc = country_code.strip().upper()
    ga = client.get_service("GoogleAdsService")
    query = f"""
        SELECT
          geo_target_constant.id,
          geo_target_constant.name,
          geo_target_constant.country_code,
          geo_target_constant.target_type
        FROM geo_target_constant
        WHERE geo_target_constant.country_code = '{cc}'
          AND geo_target_constant.target_type = 'Country'
        LIMIT 1
    """
    for row in ga.search(customer_id=customer_id, query=query):
        # double-check: country code en type
        if row.geo_target_constant.country_code == cc and row.geo_target_constant.target_type == "Country":
            gid = str(row.geo_target_constant.id)
            print(f"  [VERIFY] {cc} -> {row.geo_target_constant.name} (ID: {gid})")
            return gid
    print(f"    Warning: No country-level geo target for code {cc}")
    return None


def _get_language_constant(client: GoogleAdsClient, customer_id: str, language_code: str) -> Optional[str]:
    """
    Lookup taal op ISO-code (bv. 'it', 'da'), niet op naam.
    """
    code = language_code.strip().lower()
    ga = client.get_service("GoogleAdsService")
    query = f"""
        SELECT
          language_constant.id,
          language_constant.code,
          language_constant.name
        FROM language_constant
        WHERE language_constant.code = '{code}'
        LIMIT 1
    """
    for row in ga.search(customer_id=customer_id, query=query):
        lid = str(row.language_constant.id)
        print(f"  [VERIFY] lang {code} -> {row.language_constant.name} (ID: {lid})")
        return lid
    print(f"    Warning: Could not find language for code '{code}'")
    return None


def _create_portfolio_troas(client: GoogleAdsClient, customer_id: str, target_roas: float) -> str:
    """Create a shared Target ROAS bidding strategy and return its resource name."""
    svc = client.get_service("BiddingStrategyService")
    op = client.get_type("BiddingStrategyOperation")
    bs = op.create
    bs.name = f"Portfolio tROAS {target_roas:.2f} - {datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    bs.target_roas.target_roas = float(target_roas)
    resp = svc.mutate_bidding_strategies(customer_id=customer_id, operations=[op])
    return resp.results[0].resource_name


def _find_portfolio_by_name(client: GoogleAdsClient, customer_id: str, name: str) -> Optional[str]:
    ga = client.get_service("GoogleAdsService")
    q = (
        "SELECT bidding_strategy.resource_name, bidding_strategy.name, bidding_strategy.type "
        "FROM bidding_strategy WHERE bidding_strategy.name = @n LIMIT 1"
    )
    params = [{"key": "n", "value": name}]
    # Build GAQL with parameter
    query = q.replace("@n", f"'" + name.replace("'", "\\'") + "'")
    for row in ga.search(customer_id=customer_id, query=query):
        return row.bidding_strategy.resource_name
    return None


def _update_campaign_set_bidding_strategy(
    client: GoogleAdsClient,
    customer_id: str,
    campaign_rn: str,
    strategy_rn: str,
) -> None:
    svc = client.get_service("CampaignService")
    op = client.get_type("CampaignOperation")
    camp = op.update
    camp.resource_name = campaign_rn
    camp.bidding_strategy = strategy_rn
    op.update_mask.CopyFrom(field_mask_pb2.FieldMask(paths=["bidding_strategy"]))
    svc.mutate_campaigns(customer_id=customer_id, operations=[op])


def add_listing_group_for_label(client, customer_id: str, asset_group_rn: str,
                                label_value: str, label_index: int):
    if label_index not in (0, 1, 2, 3, 4):
        raise ValueError("label_index must be 0..4")

    gas = client.get_service("GoogleAdsService")
    enums = client.enums

    asset_group_id = asset_group_rn.split("/")[-1]
    path = gas.asset_group_listing_group_filter_path

    idx_enum = enums.ListingGroupFilterCustomAttributeIndexEnum
    idx_map = [idx_enum.INDEX0, idx_enum.INDEX1, idx_enum.INDEX2, idx_enum.INDEX3, idx_enum.INDEX4]
    index_value = idx_map[label_index]

    # 1) ROOT (SUBDIVISION) – géén case_value op root
    op_root = client.get_type("MutateOperation")
    root = op_root.asset_group_listing_group_filter_operation.create
    root.resource_name = path(customer_id, asset_group_id, "-1")
    root.asset_group = asset_group_rn
    root.type_ = enums.ListingGroupFilterTypeEnum.SUBDIVISION
    root.listing_source = enums.ListingGroupFilterListingSourceEnum.SHOPPING

    # 2) INCLUDED child: custom_label_X == label_value
    dim_incl = client.get_type("ListingGroupFilterDimension")
    dim_incl.product_custom_attribute.index = index_value
    dim_incl.product_custom_attribute.value = label_value

    op_incl = client.get_type("MutateOperation")
    incl = op_incl.asset_group_listing_group_filter_operation.create
    incl.resource_name = path(customer_id, asset_group_id, "-2")
    incl.asset_group = asset_group_rn
    incl.parent_listing_group_filter = root.resource_name
    incl.type_ = enums.ListingGroupFilterTypeEnum.UNIT_INCLUDED
    incl.listing_source = enums.ListingGroupFilterListingSourceEnum.SHOPPING
    incl.case_value = dim_incl

    # 3) EVERYTHING-ELSE child: zelfde dimensie, lege value (EXCLUDED)
    other_dim = client.get_type("ListingGroupFilterDimension")
    other_dim.product_custom_attribute.index = index_value
    # markeer submessage als "aanwezig maar leeg"
    other_dim.product_custom_attribute._pb.SetInParent()

    op_else = client.get_type("MutateOperation")
    else_node = op_else.asset_group_listing_group_filter_operation.create
    else_node.resource_name = path(customer_id, asset_group_id, "-3")
    else_node.asset_group = asset_group_rn
    else_node.parent_listing_group_filter = root.resource_name
    else_node.type_ = enums.ListingGroupFilterTypeEnum.UNIT_EXCLUDED
    else_node.listing_source = enums.ListingGroupFilterListingSourceEnum.SHOPPING
    else_node.case_value = other_dim

    _retry(lambda: gas.mutate(customer_id=customer_id, mutate_operations=[op_root, op_incl, op_else]))
    
    # Note: Listing groups are created and ready to use
    print(f"  Listing groups aangemaakt - klaar voor gebruik")
    print(f"  Als producten niet worden getoond, controleer of Asset Group ENABLED is")


def find_asset_groups_for_campaign(client, customer_id, campaign_resource_name):
    """Find all asset groups for a specific campaign."""
    ga_service = client.get_service("GoogleAdsService")
    
    query = f"""
        SELECT 
            asset_group.resource_name,
            asset_group.name,
            asset_group.status
        FROM asset_group 
        WHERE asset_group.campaign = '{campaign_resource_name}'
    """
    
    asset_groups = []
    for row in ga_service.search(customer_id=customer_id, query=query):
        asset_groups.append({
            'resource_name': row.asset_group.resource_name,
            'name': row.asset_group.name,
            'status': row.asset_group.status.name
        })
    
    return asset_groups


def check_listing_groups_for_asset_group(client, customer_id, asset_group_resource_name):
    """Check if an asset group has any listing groups."""
    ga_service = client.get_service("GoogleAdsService")
    
    query = f"""
        SELECT 
            asset_group_listing_group_filter.resource_name,
            asset_group_listing_group_filter.type,
            asset_group_listing_group_filter.listing_source,
            asset_group_listing_group_filter.case_value.product_custom_attribute.index,
            asset_group_listing_group_filter.case_value.product_custom_attribute.value
        FROM asset_group_listing_group_filter 
        WHERE asset_group_listing_group_filter.asset_group = '{asset_group_resource_name}'
    """
    
    listing_groups = []
    for row in ga_service.search(customer_id=customer_id, query=query):
        lg = row.asset_group_listing_group_filter
        listing_group_info = {
            'resource_name': lg.resource_name,
            'type': lg.type.name,
            'listing_source': lg.listing_source.name
        }
        
        # Add case_value info if available
        if hasattr(lg, 'case_value') and lg.case_value:
            if hasattr(lg.case_value, 'product_custom_attribute'):
                attr = lg.case_value.product_custom_attribute
                listing_group_info['custom_attribute_index'] = attr.index.name if hasattr(attr, 'index') else None
                listing_group_info['custom_attribute_value'] = attr.value if hasattr(attr, 'value') else None
        
        listing_groups.append(listing_group_info)
    
    return listing_groups


def _is_concurrent_modification(exc, client):
    """Check if the exception is a CONCURRENT_MODIFICATION error."""
    try:
        for err in exc.failure.errors:
            if err.error_code.database_error == client.enums.DatabaseErrorEnum.CONCURRENT_MODIFICATION:
                return True
    except Exception:
        pass
    return False


def enable_campaign_and_asset_group_with_retry(client, customer_id, campaign_rn, asset_group_rn, max_attempts=5):
    """Enable campaign and asset group with exponential backoff retry for CONCURRENT_MODIFICATION."""
    gas = client.get_service("GoogleAdsService")
    enums = client.enums

    # Build 2 updates in one GoogleAdsService.mutate call
    ops = []

    op1 = client.get_type("MutateOperation")
    camp_upd = op1.campaign_operation.update
    camp_upd.resource_name = campaign_rn
    camp_upd.status = enums.CampaignStatusEnum.ENABLED
    op1.campaign_operation.update_mask.CopyFrom(field_mask_pb2.FieldMask(paths=["status"]))
    ops.append(op1)

    op2 = client.get_type("MutateOperation")
    ag_upd = op2.asset_group_operation.update
    ag_upd.resource_name = asset_group_rn
    ag_upd.status = enums.AssetGroupStatusEnum.ENABLED
    op2.asset_group_operation.update_mask.CopyFrom(field_mask_pb2.FieldMask(paths=["status"]))
    ops.append(op2)

    _retry(lambda: gas.mutate(customer_id=customer_id, mutate_operations=ops))
    return True


def enable_campaign_and_asset_group(client, customer_id, campaign_rn, asset_group_rn):
    """Enable campaign and asset group to start serving ads."""
    # Campaign -> ENABLED
    camp_op = client.get_type("CampaignOperation")
    camp_op.update.resource_name = campaign_rn
    camp_op.update.status = client.enums.CampaignStatusEnum.ENABLED
    camp_op.update_mask.CopyFrom(field_mask_pb2.FieldMask(paths=["status"]))
    _retry(lambda: client.get_service("CampaignService").mutate_campaigns(customer_id=customer_id, operations=[camp_op]))

    # Asset group -> ENABLED
    ag_op = client.get_type("AssetGroupOperation")
    ag_op.update.resource_name = asset_group_rn
    ag_op.update.status = client.enums.AssetGroupStatusEnum.ENABLED
    ag_op.update_mask.CopyFrom(field_mask_pb2.FieldMask(paths=["status"]))
    _retry(lambda: client.get_service("AssetGroupService").mutate_asset_groups(customer_id=customer_id, operations=[ag_op]))
    
    print(f"  Campaign en Asset Group geactiveerd voor live serving")


def activate_listing_groups(client, customer_id: str, asset_group_rn: str):
    """Activate all listing groups for an asset group."""
    gas = client.get_service("GoogleAdsService")
    
    # First, get all listing groups for this asset group
    query = f"""
        SELECT 
            asset_group_listing_group_filter.resource_name
        FROM asset_group_listing_group_filter 
        WHERE asset_group_listing_group_filter.asset_group = '{asset_group_rn}'
    """
    
    operations = []
    for row in gas.search(customer_id=customer_id, query=query):
        lg = row.asset_group_listing_group_filter
        
        # Create update operation to set status to ACTIVE
        op = client.get_type("MutateOperation")
        update = op.asset_group_listing_group_filter_operation.update
        update.resource_name = lg.resource_name
        update.status = client.enums.AssetGroupListingGroupFilterStatusEnum.ENABLED
        operations.append(op)
    
    if operations:
        _retry(lambda: gas.mutate(customer_id=customer_id, mutate_operations=operations))
        print(f"  {len(operations)} listing groups geactiveerd")


def _create_pmax_asset_group(
    client: GoogleAdsClient,
    customer_id: str,
    campaign_rn: str,
    asset_group_name: str,
    label_index: int,
    label_value: str,
    is_feed_only: bool = False,
    merchant_id: Optional[str] = None,
    target_languages: Optional[str] = None,
    target_countries: Optional[str] = None,
) -> str:
    """Create a PMax feed-only asset group with listing group filter for the specified label."""
    ag_svc = client.get_service("AssetGroupService")
    agc_svc = client.get_service("AssetGroupListingGroupFilterService")

    # 1) Create a PMax asset group (feed-only, no assets needed)
    ag_op = client.get_type("AssetGroupOperation")
    ag = ag_op.create
    ag.name = asset_group_name
    ag.campaign = campaign_rn
    ag.status = client.enums.AssetGroupStatusEnum.PAUSED
    
    if is_feed_only:
        # Merchant Center feed is now set at campaign level via shopping_setting
        print(f"  Asset Group gekoppeld aan Merchant Center feed via campaign shopping_setting")
        
        # For feed-only PMax, we don't set any final URLs
        # The final URLs will be automatically set from the Merchant Center feed
        print(f"  Geen final URLs ingesteld - worden automatisch ingesteld vanuit Merchant Center feed")
    else:
        # For normal PMax, we need final URLs
        ag.final_urls.append("https://example.com")  # Placeholder URL
        print(f"  Final URL ingesteld voor normale PMax: https://example.com")
    
    # Note: PMax targeting is typically set via campaign criteria after creation
    # Asset group level targeting is not available in the current API version
    if target_languages or target_countries:
        print(f"  Note: Targeting wordt ingesteld via Google Ads UI na creatie")
        if target_languages:
            languages = [lang.strip().lower() for lang in target_languages.split(',')]
            print(f"  Target Languages: {', '.join(languages)}")
        if target_countries:
            countries = [country.strip().upper() for country in target_countries.split(',')]
            print(f"  Target Countries: {', '.join(countries)}")
    
    # Retry mechanism for concurrent modification errors
    max_retries = 3
    retry_delay = 2  # seconds
    
    print(f"  Debug: Creating asset group '{asset_group_name}' for campaign '{campaign_rn}'")
    ag_resp = _retry(lambda: ag_svc.mutate_asset_groups(customer_id=customer_id, operations=[ag_op]))
    ag_rn = ag_resp.results[0].resource_name
    print(f"  Asset Group aangemaakt: {ag_rn}")

    # 2) Create listing group (only for feed-only PMax)
    if is_feed_only:
        try:
            print(f"  Debug: Creating listing group with label_index={label_index}, label_value='{label_value}'")
            add_listing_group_for_label(client, customer_id, ag_rn, label_value, label_index)
            print(f"  Listing Group Filter: custom_label_{label_index} = '{label_value}' (UNIT_INCLUDED)")
        except Exception as e:
            print(f"  Error creating listing group: {e}")
            print(f"  Asset Group aangemaakt zonder listing group: {ag_rn}")
            print(f"  Handmatig toevoegen via Google Ads UI: custom_label_{label_index} = '{label_value}'")
    else:
        print(f"  Normale PMax Asset Group - geen listing group nodig")
        print(f"  Handmatig creatives toevoegen via Google Ads UI voor label: '{label_value}'")

    return ag_rn


def main() -> None:
    # Load .env from project root and resolve config path like other scripts
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
    args = parse_args()
    customer_id = _digits_only(args.customer)
    cfg = os.getenv("GOOGLE_ADS_CONFIGURATION_FILE")
    if not cfg:
        cfg = str(PROJECT_ROOT / "config" / "google-ads.yaml")
    print("Config path =", cfg)
    client = GoogleAdsClient.load_from_storage(cfg)
    # Force login header from config
    try:
        # CLI > ENV > config
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

    if args.extended_search:
        print(f"  [INFO] Using extended search to find ALL labels (including those without traffic)...")
        labels = discover_all_labels(client, customer_id=customer_id, label_index=args.label_index)
    else:
        labels = discover_labels(client, customer_id=customer_id, label_index=args.label_index, include_label_1=True, include_label_2=True, extended_search=args.extended_search)
    if not labels:
        print("Geen labels gevonden in ShoppingPerformanceView. Mogelijk geen recente traffic of labels leeg.")
        return

    # Filter labels if labels-file is provided
    if args.labels_file and os.path.exists(args.labels_file):
        with open(args.labels_file, 'r', encoding='utf-8') as f:
            file_content = f.read()
        
        # Split by newlines and clean each line
        selected_labels = set()
        for line in file_content.split('\n'):
            clean_line = line.strip()
            if clean_line:
                selected_labels.add(clean_line)
        
        print(f"Debug: Selected labels from file: {selected_labels}")  # Debug log
        
        # Filter to only include selected labels
        original_labels = labels
        labels = {label: impr for label, impr in labels.items() if label.strip() in selected_labels}
        
        # Show which labels were found/not found
        not_found = selected_labels - {label.strip() for label in original_labels.keys()}
        if not_found:
            print(f"Waarschuwing: De volgende labels werden niet gevonden in de data: {not_found}")
        
        if not labels:
            print("Geen van de geselecteerde labels werden gevonden in de data.")
            print(f"Beschikbare labels: {list(original_labels.keys())}")
            return
        
        print(f"Gefilterd naar {len(labels)} van {len(original_labels)} beschikbare labels")

    # If user did not provide --target-roas, derive per-label tROAS from dominant custom_label1 percent
    per_label_troas: Optional[Dict[str, float]] = None
    default_troas = args.target_roas
    
    # Apply ROAS factor to default_troas if specified (as percentage)
    if default_troas is not None and args.roas_factor != 0:
        original_default = default_troas
        default_troas = round(default_troas * (1 + args.roas_factor / 100), 2)
        print(f"  Default ROAS aangepast: {original_default} {args.roas_factor:+.1f}% = {default_troas}")
    if default_troas is None:
        c0_to_c1 = _discover_label0_to_label1_percent(client, customer_id)
        derived: Dict[str, float] = {}
        for c0, c1 in c0_to_c1.items():
            troas = _parse_percent_to_troas(c1)
            if troas:
                # Apply ROAS factor if specified (as percentage)
                if args.roas_factor != 0:
                    original_troas = troas
                    troas = round(troas * (1 + args.roas_factor / 100), 2)
                    print(f"  ROAS voor {c0}: {original_troas} {args.roas_factor:+.1f}% = {troas}")
                derived[c0] = troas
        if derived:
            per_label_troas = derived
    # Convert labels to the format expected by build_plans_for_labels
    labels_to_impr = {}
    for label, data in labels.items():
        if isinstance(data, dict):
            labels_to_impr[label] = data.get('impressions', 0)
        else:
            labels_to_impr[label] = data
    
    # Show summary of labels found
    total_labels = len(labels)
    labels_with_traffic = sum(1 for data in labels.values() if isinstance(data, dict) and data.get('has_traffic', False))
    labels_without_traffic = total_labels - labels_with_traffic
    
    print(f"\n=== LABEL DISCOVERY SUMMARY ===")
    print(f"Total labels gevonden: {total_labels}")
    print(f"Labels met traffic: {labels_with_traffic}")
    print(f"Labels zonder traffic: {labels_without_traffic}")
    print(f"===============================\n")
    
    plans = build_plans_for_labels(
        labels_to_impr,
        prefix=args.prefix,
        daily_budget=args.daily_budget,
        default_target_roas=default_troas,
        per_label_troas=per_label_troas,
    )

    print("Gevonden labelwaarden (gesorteerd op impressies):")
    for label, data in labels.items():
        if isinstance(data, dict):
            # New format with full data
            impressions = data.get('impressions', 0)
            has_traffic = data.get('has_traffic', False)
            custom_label_1 = list(data.get('custom_label_1', set()))
            custom_label_2 = list(data.get('custom_label_2', set()))
            
            if has_traffic:
                print(f"  {label!r}: {impressions} impressions")
            else:
                print(f"  {label!r}: {impressions} impressions (GEEN TRAFFIC)")
            
            if custom_label_1:
                print(f"    Marge (Label 1): {', '.join(custom_label_1)}")
            if custom_label_2:
                print(f"    Marge ex 15% (Label 2): {', '.join(custom_label_2)}")
        else:
            # Old format with just impressions
            print(f"  {label!r}: {data} impressions")

    # Check for existing campaigns and filter them out
    print(f"\nControleren op bestaande PMax campagnes...")
    existing_campaigns = get_existing_pmax_campaigns(client, customer_id, args.prefix)
    print(f"  Gevonden {len(existing_campaigns)} bestaande PMax campagne(s) met prefix '{args.prefix}'")
    
    original_count = len(plans)
    filtered_plans = []
    skipped_count = 0
    
    for plan in plans:
        # Check if a campaign with this label already exists
        # We check by extracting the label from the campaign name pattern: "{prefix} - {label} - {timestamp}"
        # But since timestamp changes, we check if any existing campaign has the same label
        label_exists = False
        for existing_name in existing_campaigns:
            # Extract label from existing campaign name: "{prefix} - {label} - {timestamp}"
            # Compare by checking if the label value appears in the existing campaign name
            if plan.label_value in existing_name:
                label_exists = True
                break
        
        if label_exists:
            skipped_count += 1
            continue
        
        filtered_plans.append(plan)
    
    plans = filtered_plans
    
    if skipped_count > 0:
        print(f"\n  Gefilterd: {original_count} -> {len(plans)} campagnes")
        print(f"    Overgeslagen (bestaan al): {skipped_count}")
        print(f"    Te maken: {len(plans)}")
    
    print("\nCampaign-plannen (dry-run):")
    for plan in plans:
        roas = f", tROAS={plan.target_roas}" if plan.target_roas else ""
        print(f"- {plan.name}  (label='{plan.label_value}', budget_micros={plan.daily_budget_micros}{roas})")

    # Handle add-listing-group functionality
    if args.add_listing_group:
        try:
            parts = args.add_listing_group.split(':')
            if len(parts) != 3:
                print("Error: --add-listing-group format should be 'asset_group_resource_name:label_value:label_index'")
                return
            
            asset_group_rn, label_value, label_index_str = parts
            label_index = int(label_index_str)
            
            print(f"Adding listing group to asset group: {asset_group_rn}")
            print(f"Label: {label_value} (index: {label_index})")
            
            result = add_listing_group_for_label(client, customer_id, asset_group_rn, label_value, label_index)
            print(f"Successfully added listing group: {result}")
            return
            
        except Exception as e:
            print(f"Error adding listing group: {e}")
            return

    # Handle check-asset-groups functionality
    if args.check_asset_groups:
        try:
            campaign_rn = args.check_asset_groups
            print(f"Checking asset groups for campaign: {campaign_rn}")
            
            asset_groups = find_asset_groups_for_campaign(client, customer_id, campaign_rn)
            print(f"Found {len(asset_groups)} asset groups:")
            
            for ag in asset_groups:
                print(f"  Asset Group: {ag['name']}")
                print(f"    Resource Name: {ag['resource_name']}")
                print(f"    Status: {ag['status']}")
                
                # Check listing groups for this asset group
                listing_groups = check_listing_groups_for_asset_group(client, customer_id, ag['resource_name'])
                print(f"    Listing Groups: {len(listing_groups)} found")
                for lg in listing_groups:
                    print(f"      - {lg['type']} ({lg['listing_source']})")
                
                print()
            return
            
        except Exception as e:
            print(f"Error checking asset groups: {e}")
            return

    if str(args.apply).lower() in {"1", "true", "yes"}:
        # Provide EU political flag value to create helper via module-level var hack
        global EU_POLITICAL_VALUE  # type: ignore[declared-but-not-used]
        EU_POLITICAL_VALUE = args.eu_political
        # Strategy-only mode: create/update portfolio strategies per label_0 and exit
        if str(args.only_strategies).lower() in {"1", "true", "yes"}:
            print("\nApply=true -> alleen biedstrategieën per label_0")
            # Derive per-label tROAS map (prefer default if given)
            per_label_troas: Dict[str, float] = {}
            if args.target_roas is not None:
                for label in labels.keys():
                    troas = float(args.target_roas)
                    # Apply ROAS factor if specified (as percentage)
                    if args.roas_factor != 0:
                        original_troas = troas
                        troas = round(troas * (1 + args.roas_factor / 100), 2)
                        print(f"  Portfolio ROAS voor {label}: {original_troas} {args.roas_factor:+.1f}% = {troas}")
                    per_label_troas[label] = troas
            else:
                c0_to_c1 = _discover_label0_to_label1_percent(client, customer_id)
                for c0, c1 in c0_to_c1.items():
                    troas = _parse_percent_to_troas(c1)
                    if troas:
                        # Apply ROAS factor if specified (as percentage)
                        if args.roas_factor != 0:
                            original_troas = troas
                            troas = round(troas * (1 + args.roas_factor / 100), 2)
                            print(f"  Portfolio ROAS voor {c0}: {original_troas} {args.roas_factor:+.1f}% = {troas}")
                        per_label_troas[c0] = troas
            if not per_label_troas:
                print("Geen tROAS waarden af te leiden.")
                return
            created: Dict[str, str] = {}
            for c0, troas in per_label_troas.items():
                name = f"tROAS for label0={c0} ({troas:.2f})"
                existing = _find_portfolio_by_name(client, customer_id, name)
                if existing:
                    print(f"Bestaat al: {name} -> {existing}")
                    created[c0] = existing
                    continue
                try:
                    rn = _create_portfolio_troas(client, customer_id, troas)
                    print(f"Aangemaakt: {name} -> {rn}")
                    created[c0] = rn
                except Exception as exc:
                    print(f"Fout bij aanmaken strategie voor {c0}: {exc}")
            print("\nKlaar met strategieën. Koppel ze handmatig of in een vervolgscript.")
            return

        # Determine PMax type and handle merchant ID
        is_feed_only = args.pmax_type == "feed-only"
        merchant_id = None
        
        if is_feed_only:
            print("\nApply=true -> campagnes worden aangemaakt (PMax Feed-Only per label)")
            # Try to get merchant ID from args first, then try to find it automatically
            if args.merchant_id:
                merchant_id = _digits_only(args.merchant_id)
            else:
                try:
                    merchant_id = _find_active_merchant_center_id(client, customer_id)
                except Exception as e:
                    print(f"Kon Merchant Center ID niet automatisch ophalen: {e}")
            
            if not merchant_id:
                print("Kon geen Merchant Center ID bepalen.")
                print("Gebruik '--merchant-id' om handmatig een Merchant Center ID op te geven.")
                print("Of koppel Merchant Center in Google Ads UI en probeer opnieuw.")
                return
        else:
            print("\nApply=true -> campagnes worden aangemaakt (Normale PMax per label)")
            # For normal PMax, merchant ID is optional
            if args.merchant_id:
                merchant_id = _digits_only(args.merchant_id)
        # Check enabled campaign count before starting
        enabled_count = _count_enabled_pmax_campaigns(client, customer_id)
        if enabled_count >= 0:
            print(f"\n[INFO] Huidig aantal enabled PMax campagnes: {enabled_count}/100")
            if enabled_count >= 100:
                print(f"[ERROR] ⚠️  LIMIET BEREIKT: Er zijn al 100 enabled PMax campagnes in dit account.")
                print(f"[ERROR] Google Ads limiet: maximaal 100 enabled Performance Max campagnes per account.")
                print(f"[ERROR] Oplossingen:")
                print(f"[ERROR] 1. Pauzeer enkele bestaande campagnes voordat je nieuwe aanmaakt")
                print(f"[ERROR] 2. Campagnes worden standaard als PAUSED aangemaakt (tellen niet mee voor limiet)")
                print(f"[ERROR] 3. Activeer ze later handmatig in Google Ads UI")
                return
            elif enabled_count + len(plans) > 100:
                print(f"[WARNING] ⚠️  Je probeert {len(plans)} campagnes aan te maken, maar er zijn al {enabled_count} enabled.")
                print(f"[WARNING] Dit zou {enabled_count + len(plans)} enabled campagnes geven (limiet: 100).")
                print(f"[WARNING] Campagnes worden als PAUSED aangemaakt, dus dit is OK als je ze later handmatig activeert.")
                print(f"[WARNING] Als je --start-enabled gebruikt, zullen alleen de eerste {100 - enabled_count} campagnes enabled worden.")
        
        for i, plan in enumerate(plans):
            campaign_name = plan.name
            print(f"\n[{i+1}/{len(plans)}] Aanmaken: {campaign_name} (budget_micros={plan.daily_budget_micros}, label='{plan.label_value}')")
            
            # Verhoogde pauze tussen campagnes om CONCURRENT_MODIFICATION en limiet errors te voorkomen
            if i > 0:
                sleep_time = 3.0 + random.random() * 2.0  # 3-5 seconden
                print(f"  Wachten {sleep_time:.1f}s voordat volgende campagne wordt aangemaakt...")
                time.sleep(sleep_time)
            
            # Use per-label tROAS or default tROAS (6.5 if none specified)
            troas_value = plan.target_roas if plan.target_roas is not None else (args.target_roas or 6.5)
            
            # Apply ROAS factor to the final tROAS value if specified (as percentage)
            if args.roas_factor != 0:
                original_troas = troas_value
                troas_value = round(troas_value * (1 + args.roas_factor / 100), 2)
                print(f"  tROAS aangepast: {original_troas} {args.roas_factor:+.1f}% = {troas_value}")
            else:
                print(f"  tROAS: {troas_value}")

            try:
                camp_rn = _create_pmax_campaign(
                    client=client,
                    customer_id=customer_id,
                    campaign_name=campaign_name,
                    daily_budget_micros=plan.daily_budget_micros,
                    campaign_target_roas=troas_value,
                    is_feed_only=is_feed_only,
                    merchant_id=merchant_id,
                    target_languages=args.target_languages,
                    target_countries=args.target_countries,
                    feed_label=args.feed_label,
                )
                print(f"  ✅ Campaign aangemaakt: {camp_rn}")
            except GoogleAdsException as e:
                # Check if it's a resource limit error
                is_limit_error = False
                for err in e.failure.errors:
                    if hasattr(err.error_code, "resource_count_limit_exceeded_error"):
                        if err.error_code.resource_count_limit_exceeded_error.name == "RESOURCE_LIMIT":
                            is_limit_error = True
                            print(f"  ❌ LIMIET BEREIKT: Kan geen meer enabled campagnes aanmaken (limiet: 100)")
                            print(f"  ⚠️  Deze campagne wordt overgeslagen. Pauzeer bestaande campagnes en probeer opnieuw.")
                            break
                
                if not is_limit_error:
                    # Re-raise if it's not a limit error
                    raise
                else:
                    # Skip remaining campaigns if limit is reached
                    print(f"\n[STOP] Stoppen met aanmaken van campagnes - limiet bereikt.")
                    print(f"[INFO] {i} van {len(plans)} campagnes succesvol aangemaakt.")
                    break
            
            # Create asset group (feed-only or normal)
            asset_group_name = f"{campaign_name} - Asset Group"
            try:
                ag_rn = _create_pmax_asset_group(
                    client=client,
                    customer_id=customer_id,
                    campaign_rn=camp_rn,
                    asset_group_name=asset_group_name,
                    label_index=args.label_index,
                    label_value=plan.label_value,
                    is_feed_only=is_feed_only,
                    merchant_id=merchant_id,
                    target_languages=args.target_languages,
                    target_countries=args.target_countries,
                )
                if ag_rn:
                    if is_feed_only:
                        print(f"  Feed-only Asset Group succesvol aangemaakt: {ag_rn}")
                    else:
                        print(f"  Normale PMax Asset Group succesvol aangemaakt: {ag_rn}")
                    
                    # Enable campaign and asset group if --start-enabled flag is set
                    if args.start_enabled:
                        # Small wait to avoid CONCURRENT_MODIFICATION
                        time.sleep(1.0)
                        try:
                            enable_campaign_and_asset_group_with_retry(client, customer_id, camp_rn, ag_rn)
                            print(f"  Campaign en Asset Group succesvol geactiveerd")
                        except Exception as e:
                            print(f"  Warning: Kon campaign/asset group niet activeren: {e}")
                            print(f"  Activeer handmatig in Google Ads UI")
                else:
                    print(f"  Asset Group kon niet worden aangemaakt voor campaign: {camp_rn}")
                    print(f"  Asset Group: Handmatig toevoegen via Google Ads UI")
                    if is_feed_only:
                        print(f"  Listing Group Filter: custom_label_{args.label_index} = '{plan.label_value}'")
                    else:
                        print(f"  Handmatig creatives toevoegen voor label: '{plan.label_value}'")
            except Exception as e:
                print(f"  Asset Group fout: {e}")
                print(f"  Asset Group: Handmatig toevoegen via Google Ads UI")
                if is_feed_only:
                    print(f"  Listing Group Filter: custom_label_{args.label_index} = '{plan.label_value}'")
                else:
                    print(f"  Handmatig creatives toevoegen voor label: '{plan.label_value}'")
            
        if args.start_enabled:
            print("\nKlaar. Campagnes zijn geactiveerd en beginnen met serveren.")
        else:
            print("\nKlaar. Controleer de nieuwe PMax campagnes in de UI (status: PAUSED).")
            print("Gebruik --start-enabled om campagnes direct te activeren.")


if __name__ == "__main__":
    main()


