from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Tuple, List

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "google-ads.yaml"


def load_client() -> GoogleAdsClient:
    return GoogleAdsClient.load_from_storage(path=str(CONFIG_PATH))


def find_label1_bps_for_seller(
    client: GoogleAdsClient,
    customer_id: str,
    seller_label0: str,
    days_back: int,
) -> Optional[int]:
    """
    Determine the current "hard" ROAS from custom label 1 for a seller (label 0),
    using the label1 value with the highest impressions in the last N days.

    Returns integer basis points (e.g., 700 -> 7.00).
    """
    ga = client.get_service("GoogleAdsService")

    query = f"""
        SELECT
          shopping_performance_view.custom_label_0,
          shopping_performance_view.custom_label_1,
          metrics.impressions
        FROM shopping_performance_view
        WHERE segments.date DURING LAST_{days_back}_DAYS
          AND shopping_performance_view.custom_label_0 = '{seller_label0}'
        """

    impressions_by_label1 = {}
    try:
        for row in ga.search(customer_id=customer_id, query=query):
            l1 = row.shopping_performance_view.custom_label_1 or ""
            imps = int(row.metrics.impressions or 0)
            impressions_by_label1[l1] = impressions_by_label1.get(l1, 0) + imps
    except GoogleAdsException as ex:
        print(f"[ERROR] GAQL failed while reading label1: {ex}")
        return None

    if not impressions_by_label1:
        return None

    # Pick label1 with highest impressions
    top_label1, _ = max(impressions_by_label1.items(), key=lambda kv: kv[1])

    # Expect numeric like "700" => 700 bps
    digits = ''.join(ch for ch in str(top_label1) if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def find_campaigns_for_seller(
    client: GoogleAdsClient,
    customer_id: str,
    seller_label0: str,
) -> List[str]:
    """Find campaign resource names that belong to this seller.

    Heuristic: the campaign name contains the seller label 0 value.
    """
    ga = client.get_service("GoogleAdsService")
    # Search campaigns that contain the seller label in the name (case-insensitive)
    # GAQL has no ILIKE; fetch names and filter locally as fallback.
    query = """
        SELECT campaign.resource_name, campaign.name
        FROM campaign
        WHERE campaign.status IN (ENABLED, PAUSED)
    """
    seller_lower = seller_label0.lower()
    campaign_rns: List[str] = []
    for row in ga.search(customer_id=customer_id, query=query):
        name = str(row.campaign.name or "")
        if seller_lower in name.lower():
            campaign_rns.append(row.campaign.resource_name)
    return campaign_rns


def update_campaign_troas(
    client: GoogleAdsClient,
    customer_id: str,
    campaign_rn: str,
    target_roas: float,
    dry_run: bool,
) -> None:
    svc = client.get_service("CampaignService")
    op = client.get_type("CampaignOperation")
    camp = op.update
    camp.resource_name = campaign_rn
    camp.maximize_conversion_value.target_roas = float(target_roas)

    from google.protobuf import field_mask_pb2  # lazy import to avoid global dependency

    op.update_mask.CopyFrom(
        field_mask_pb2.FieldMask(paths=["maximize_conversion_value.target_roas"])  # type: ignore
    )

    if dry_run:
        print(f"[DRY-RUN] Would set tROAS={target_roas:.2f} for {campaign_rn}")
        return

    svc.mutate_campaigns(customer_id=customer_id, operations=[op])
    print(f"[OK] Set tROAS={target_roas:.2f} for {campaign_rn}")


def main():
    parser = argparse.ArgumentParser(description="Sync campaign tROAS from custom label 1 for a seller (label 0)")
    parser.add_argument("--customer", required=True, help="Customer ID, e.g. 123-456-7890")
    parser.add_argument("--seller", required=True, help="Seller value (custom label 0)")
    parser.add_argument("--days-back", type=int, default=30, help="History window to determine current label 1 (default 30)")
    parser.add_argument("--target-roas-bps", type=int, default=None, help="Explicit ROAS in basis points (e.g. 700 => 7.00). If omitted, derive from current label 1")
    parser.add_argument("--dry-run", action="store_true", help="Do not persist changes; only print actions")

    args = parser.parse_args()

    client = load_client()
    customer_id = args.customer.replace("-", "")

    # Determine target ROAS bps
    roas_bps: Optional[int] = args.target_roas_bps
    if roas_bps is None:
        roas_bps = find_label1_bps_for_seller(client, customer_id, args.seller, args.days_back)
        if roas_bps is None:
            print("[ERROR] Could not determine current label 1 value for the seller.")
            sys.exit(2)

    target_roas = float(roas_bps) / 100.0
    print(f"[INFO] Target tROAS from label1 = {roas_bps} bps => {target_roas:.2f}")

    # Find campaigns for seller
    campaigns = find_campaigns_for_seller(client, customer_id, args.seller)
    if not campaigns:
        print("[WARN] No campaigns found for this seller (by name contains heuristic).")
        sys.exit(3)

    # Update each campaign
    for rn in campaigns:
        update_campaign_troas(client, customer_id, rn, target_roas, args.dry_run)

    print("[DONE] tROAS sync completed.")


if __name__ == "__main__":
    main()







