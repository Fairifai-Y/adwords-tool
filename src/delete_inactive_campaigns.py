"""Delete inactive campaigns (no impressions for N days).

This script:
- zoekt Shopping & Performance Max campagnes met 0 impressies in de laatste N dagen
- verwijdert die campagnes (optioneel, met --apply)
- toont bijbehorende portfolio TARGET_ROAS strategies die alleen nog aan deze campagnes hangen, 
  maar verwijdert GEEN biedstrategieën automatisch (dat blijft een handmatige beslissing)

Usage examples:
  py src/delete_inactive_campaigns.py --customer 1234567890 --days 60 --apply false
  py src/delete_inactive_campaigns.py --customer 1234567890 --days 60 --apply true
"""

from __future__ import annotations

import argparse
import os
import re
import time
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from dotenv import load_dotenv
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from google.api_core import exceptions as gax

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "google-ads.yaml"


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _should_retry(exc) -> Tuple[bool, str]:
    """Check if an exception should be retried."""
    if isinstance(exc, (gax.ServiceUnavailable, gax.DeadlineExceeded)):
        return True, "UNAVAILABLE"
    if isinstance(exc, GoogleAdsException):
        for err in exc.failure.errors:
            ec = err.error_code
            if hasattr(ec, "database_error") and ec.database_error.name == "CONCURRENT_MODIFICATION":
                return True, "CONCURRENT_MODIFICATION"
            if hasattr(ec, "internal_error") and ec.internal_error.name == "INTERNAL_ERROR":
                return True, "INTERNAL_ERROR"
            if hasattr(ec, "quota_error") and ec.quota_error.name == "RESOURCE_EXHAUSTED":
                return True, "RESOURCE_EXHAUSTED"
    return False, "UNKNOWN"


def _retry(fn, attempts: int = 6, base: float = 1.6, first_sleep: float = 1.0, context: str = ""):
    """Retry helper with exponential backoff."""
    delay = first_sleep
    for i in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:
            ok, reason = _should_retry(e)
            if not ok or i == attempts:
                if context:
                    print(f"[FATAL] {context} failed after {attempts} attempts: {e}")
                raise
            sleep_s = delay * (1.0 + random.random() * 0.25)
            ctx = f" ({context})" if context else ""
            print(f"[RETRY] {reason}{ctx}, retry in {sleep_s:.1f}s (attempt {i}/{attempts})")
            time.sleep(sleep_s)
            delay *= base


def _load_client(login_arg: Optional[str], customer_id: str) -> GoogleAdsClient:
    """Load GoogleAdsClient and set login_customer_id from arg/env/config if present."""
    cfg = os.getenv("GOOGLE_ADS_CONFIGURATION_FILE")
    if not cfg:
        cfg = str(CONFIG_PATH)
    print("Config path =", cfg)

    client = GoogleAdsClient.load_from_storage(cfg)

    # Force login header from CLI, env or config (like other tools)
    try:
        cli_login = _digits_only(login_arg) if login_arg else ""
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

    return client


def find_inactive_campaigns(
    client: GoogleAdsClient,
    customer_id: str,
    days: int,
) -> List[Dict]:
    """Return Shopping + PMax campaigns with 0 impressions in last N days."""
    ga = client.get_service("GoogleAdsService")

    # Bouw een expliciete datumrange i.p.v. LAST_X_DAYS (v21 ondersteunt niet alle literals)
    # We nemen dagen terug inclusief vandaag.
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=max(days - 1, 0))
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    # Eén rij per campagne met geaggregeerde metrics over de periode.
    # Daarna filteren we in Python op impressions == 0.
    query = f"""
        SELECT
          campaign.resource_name,
          campaign.id,
          campaign.name,
          campaign.advertising_channel_type,
          campaign.status,
          campaign.bidding_strategy,
          metrics.impressions
        FROM campaign
        WHERE segments.date BETWEEN '{start_str}' AND '{end_str}'
          AND campaign.advertising_channel_type IN ('PERFORMANCE_MAX', 'SHOPPING')
          AND campaign.status IN ('ENABLED', 'PAUSED')
    """

    campaigns: List[Dict] = []
    print(f"\n[STEP] Zoeken naar campagnes met 0 impressies in de laatste {days} dagen...")
    try:
        for row in ga.search(customer_id=customer_id, query=query):
            impressions = int(row.metrics.impressions or 0)
            if impressions != 0:
                continue
            campaigns.append(
                {
                    "resource_name": row.campaign.resource_name,
                    "id": int(row.campaign.id),
                    "name": row.campaign.name,
                    "channel": row.campaign.advertising_channel_type.name,
                    "status": row.campaign.status.name,
                    "bidding_strategy": getattr(row.campaign, "bidding_strategy", None) or "",
                }
            )
    except Exception as e:
        print(f"[ERROR] Kon inactieve campagnes niet ophalen: {e}")
        raise

    return campaigns


def find_strategies_to_delete(
    client: GoogleAdsClient,
    customer_id: str,
    campaigns: List[Dict],
) -> Set[str]:
    """Find portfolio bidding strategies only used by the to-be-deleted campaigns."""
    ga = client.get_service("GoogleAdsService")

    # Map strategies -> campaigns we delete
    strat_to_deleted_camps: Dict[str, Set[str]] = {}
    for c in campaigns:
        bs = c.get("bidding_strategy") or ""
        if not bs:
            continue
        strat_to_deleted_camps.setdefault(bs, set()).add(c["resource_name"])

    if not strat_to_deleted_camps:
        return set()

    strategies_to_delete: Set[str] = set()

    print("\n[STEP] Controleren welke biedstrategieën alleen aan deze campagnes hangen...")
    for strat_rn, deleted_camps in strat_to_deleted_camps.items():
        # Check if there are other (non-deleted) campaigns using this strategy
        q = f"""
            SELECT
              campaign.resource_name,
              campaign.id,
              campaign.status
            FROM campaign
            WHERE campaign.bidding_strategy = '{strat_rn}'
              AND campaign.status != 'REMOVED'
        """
        still_used_elsewhere = False
        try:
            for row in ga.search(customer_id=customer_id, query=q):
                rn = row.campaign.resource_name
                if rn not in deleted_camps:
                    still_used_elsewhere = True
                    break
        except Exception as e:
            print(f"  [WARN] Kon gebruik van strategy {strat_rn} niet controleren: {e}")
            continue

        if not still_used_elsewhere:
            strategies_to_delete.add(strat_rn)

    return strategies_to_delete


def delete_campaigns_and_strategies(
    client: GoogleAdsClient,
    customer_id: str,
    campaigns: List[Dict],
    strategies_to_delete: Set[str],
    apply: bool,
) -> None:
    """Preview or delete campaigns. Strategies are only reported, not deleted automatically."""
    print("\n[SUMMARY] Campagnes zonder impressies:")
    if not campaigns:
        print("  Geen campagnes gevonden met 0 impressies in de opgegeven periode.")
        return

    for c in campaigns:
        print(
            f"  - {c['name']} (id={c['id']}, channel={c['channel']}, "
            f"status={c['status']}, bidding_strategy={c.get('bidding_strategy') or 'n/a'})"
        )
    print(f"\n  Totaal inactieve campagnes (0 impressies in periode): {len(campaigns)}")

    print("\n[SUMMARY] Biedstrategieën die alleen aan deze campagnes hangen (informatie, NIET automatisch verwijderd):")
    if strategies_to_delete:
        for s in sorted(strategies_to_delete):
            print(f"  - {s}")
    else:
        print("  Geen portfolio strategies gevonden die alleen aan deze campagnes hangen.")

    if not apply:
        print(f"\n[DRY-RUN] Er zouden {len(campaigns)} campagnes worden verwijderd (zie lijst hierboven).")
        print("Geen campagnes verwijderd. Gebruik --apply om campagnes echt te verwijderen.")
        print("Let op: biedstrategieën worden NIET automatisch verwijderd; beoordeel die handmatig in de Google Ads UI.")
        return

    # APPLY mode – alleen campagnes verwijderen, geen strategies
    print(f"\n[APPLY] Verwijderen van {len(campaigns)} campagnes...")
    camp_svc = client.get_service("CampaignService")
    camp_ops = []
    for c in campaigns:
        op = client.get_type("CampaignOperation")
        op.remove = c["resource_name"]
        camp_ops.append(op)

    try:
        _retry(
            lambda: camp_svc.mutate_campaigns(customer_id=customer_id, operations=camp_ops),
            context="delete campaigns",
        )
        print(f"  [OK] {len(camp_ops)} campagnes verwijderd.")
    except Exception as e:
        print(f"  [ERROR] Fout bij verwijderen van campagnes: {e}")

    if strategies_to_delete:
        print("\n[INFO] De volgende biedstrategieën zijn alleen gekoppeld aan deze (nu verwijderde) campagnes:")
        for s in sorted(strategies_to_delete):
            print(f"  - {s}")
        print("Deze biedstrategieën worden NIET automatisch verwijderd. Verwijder ze handmatig in de Google Ads UI als dat gewenst is.")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Delete inactive Shopping & PMax campaigns (0 impressions for N days). "
            "Toont ongebruikte portfolio bidding strategies, maar verwijdert die niet automatisch."
        )
    )
    p.add_argument("--customer", required=True, help="Customer ID")
    p.add_argument("--login", help="Login customer ID (optioneel; override config/env)")
    p.add_argument(
        "--days",
        type=int,
        default=60,
        help="Aantal dagen zonder impressies (default: 60)",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Verwijder campagnes/strategieën echt (anders alleen preview/dry-run)",
    )
    return p.parse_args()


def main() -> None:
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
    args = parse_args()
    customer_id = _digits_only(args.customer)
    if not customer_id:
        print("[ERROR] Ongeldige customer ID")
        return

    client = _load_client(args.login, customer_id)

    # Vind campagnes zonder impressies
    campaigns = find_inactive_campaigns(client, customer_id, days=args.days)

    # Bepaal welke portfolio strategies alleen hieraan hangen
    strategies_to_delete = find_strategies_to_delete(client, customer_id, campaigns)

    # Preview of delete
    delete_campaigns_and_strategies(client, customer_id, campaigns, strategies_to_delete, apply=args.apply)


if __name__ == "__main__":
    main()

