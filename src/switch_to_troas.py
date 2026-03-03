from __future__ import annotations

import argparse
import os
from pathlib import Path

from google.ads.googleads.client import GoogleAdsClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def get_or_create_portfolio_troas(client: GoogleAdsClient, customer_id: str, target_roas: float) -> str:
    ga = client.get_service("GoogleAdsService")
    bs_svc = client.get_service("BiddingStrategyService")
    query = (
        "SELECT bidding_strategy.resource_name, bidding_strategy.type FROM bidding_strategy "
        "WHERE bidding_strategy.type = TARGET_ROAS"
    )
    try:
        for row in ga.search(customer_id=customer_id, query=query):
            return row.bidding_strategy.resource_name
    except Exception:
        pass

    op = client.get_type("BiddingStrategyOperation")
    bs = op.create
    bs.name = f"Portfolio tROAS {target_roas:.2f}"
    bs.type_ = client.enums.BiddingStrategyTypeEnum.TARGET_ROAS
    bs.target_roas.target_roas = float(target_roas)
    resp = bs_svc.mutate_bidding_strategies(customer_id=customer_id, operations=[op])
    return resp.results[0].resource_name


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--customer", required=True)
    parser.add_argument("--campaign-rn", required=True)
    parser.add_argument("--target-roas", type=float, default=5.0)
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "google-ads.yaml"))
    args = parser.parse_args()

    os.environ.setdefault("GOOGLE_ADS_CONFIGURATION_FILE", args.config)
    client = GoogleAdsClient.load_from_storage(args.config)

    strategy_rn = get_or_create_portfolio_troas(client, args.customer, args.target_roas)

    camp_svc = client.get_service("CampaignService")
    op = client.get_type("CampaignOperation")
    camp = op.update
    camp.resource_name = args.campaign_rn
    camp.bidding_strategy = strategy_rn
    op.update_mask.paths.append("bidding_strategy")

    camp_svc.mutate_campaigns(customer_id=args.customer, operations=[op])
    print(f"Switched {args.campaign_rn} to portfolio TARGET_ROAS: {strategy_rn}")


if __name__ == "__main__":
    main()









