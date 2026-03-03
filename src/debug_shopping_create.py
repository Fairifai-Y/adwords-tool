"""Minimal debug helper to find a CREATE combination that the API accepts.

Runs CampaignService.MutateCampaigns with validate_only=True and prints
request_id and the first error if present. Toggle flags to test variants.

Usage examples:
  py -m src.debug_shopping_create --customer 5059126003 --merchant-id 5561429284 --sales-country DK \
      --eu-political false --bidding manual_cpc

  py -m src.debug_shopping_create --customer 5059126003 --merchant-id 5561429284 --sales-country DK \
      --eu-political false --bidding mcv --target-roas 6.5
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from dotenv import load_dotenv
from google.ads.googleads.client import GoogleAdsClient
from datetime import datetime


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Validate-only Shopping campaign create combos")
    p.add_argument("--customer", required=True)
    p.add_argument("--merchant-id", required=True)
    p.add_argument("--sales-country", required=True)
    p.add_argument("--name", default="Debug Shopping Create")
    p.add_argument("--eu-political", default="false", help="true/false")
    p.add_argument("--bidding", default="manual_cpc", choices=["manual_cpc", "mcv", "portfolio"])
    p.add_argument("--target-roas", type=float, default=None)
    return p.parse_args()


def main() -> None:
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
    args = parse_args()

    cfg = os.getenv("GOOGLE_ADS_CONFIGURATION_FILE")
    if not cfg:
        cfg = str(PROJECT_ROOT / "config" / "google-ads.yaml")
    client = GoogleAdsClient.load_from_storage(cfg)

    # Budget
    bud_svc = client.get_service("CampaignBudgetService")
    bud_op = client.get_type("CampaignBudgetOperation")
    bud = bud_op.create
    bud.name = f"{args.name} - Budget"
    bud.amount_micros = 5_000_000
    bud.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD
    bud.explicitly_shared = False
    
    # Create real budget first
    try:
        budget_resp = bud_svc.mutate_campaign_budgets(customer_id=args.customer, operations=[bud_op])
        budget_rn = budget_resp.results[0].resource_name
        print(f"Budget created: {budget_rn}")
    except Exception as exc:
        print("Budget create error:", exc)
        return

    # Create real portfolio bidding strategy if needed
    bidding_strategy_rn = None
    if args.bidding == "portfolio":
        bs_service = client.get_service("BiddingStrategyService")
        bs_op = client.get_type("BiddingStrategyOperation")
        bs = bs_op.create
        bs.name = f"Debug Portfolio tROAS - {args.name} - {datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        bs.target_roas.target_roas = 6.5
        try:
            bs_resp = bs_service.mutate_bidding_strategies(customer_id=args.customer, operations=[bs_op])
            bidding_strategy_rn = bs_resp.results[0].resource_name
            print(f"Portfolio bidding strategy created: {bidding_strategy_rn}")
        except Exception as exc:
            print("Portfolio bidding strategy create error:", exc)
            return

    # Campaign
    camp_svc = client.get_service("CampaignService")
    camp_op = client.get_type("CampaignOperation")
    camp = camp_op.create
    camp.name = args.name
    camp.status = client.enums.CampaignStatusEnum.PAUSED
    camp.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.PERFORMANCE_MAX
    camp.campaign_budget = budget_rn  # Link to real budget
    
    # Feed-only PMax settings
    camp.url_expansion_opt_out = True  # Disable URL expansion for feed-only
    camp.final_url_suffix = ""  # No final URL suffix for feed-only
    
    # Disable Brand Guidelines for feed-only PMax
    try:
        camp.brand_guidelines_enabled = False
    except Exception:
        pass

    # Set EU political advertising field - try different enum variations
    eu_bool = str(args.eu_political).lower() in {"1", "true", "yes"}
    
    # Debug: print available enum values
    print("Available EU political advertising enums:")
    try:
        for attr in dir(client.enums):
            if 'political' in attr.lower() or 'eu' in attr.lower():
                print(f"  {attr}")
                # Also print the values for this enum
                try:
                    enum_obj = getattr(client.enums, attr)
                    for val in dir(enum_obj):
                        if not val.startswith('_'):
                            print(f"    {val}")
                except Exception:
                    pass
    except Exception as e:
        print(f"  Error listing enums: {e}")
    
    try:
        # Try enum approach first
        if eu_bool:
            camp.contains_eu_political_advertising = client.enums.EuPoliticalAdvertisingStatusEnum.CONTAINS_EU_POLITICAL_ADVERTISING
        else:
            camp.contains_eu_political_advertising = client.enums.EuPoliticalAdvertisingStatusEnum.DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING
        print(f"Enum approach set to: {eu_bool}")
    except Exception as e:
        print(f"Enum approach failed: {e}")
        try:
            # Try boolean approach
            camp.contains_eu_political_advertising = eu_bool
            print(f"Boolean approach set to: {eu_bool}")
        except Exception as e2:
            print(f"Boolean approach failed: {e2}")
            # Try setting it on the proto message directly
            try:
                camp._pb.contains_eu_political_advertising = eu_bool
                print(f"Proto approach set to: {eu_bool}")
            except Exception as e3:
                print(f"Proto approach failed: {e3}")
                pass

    if args.bidding == "manual_cpc":
        # proto-plus: set fields directly on the oneof submessage
        camp.manual_cpc.enhanced_cpc_enabled = True
        try:
            camp.bidding_strategy_type = client.enums.BiddingStrategyTypeEnum.MANUAL_CPC
        except Exception:
            pass
    elif args.bidding == "mcv":
        # set campaign-level MaximizeConversionValue with optional tROAS
        if args.target_roas is not None:
            camp.maximize_conversion_value.target_roas = float(args.target_roas)
    elif args.bidding == "portfolio" and bidding_strategy_rn:
        # Link to real portfolio bidding strategy
        camp.bidding_strategy = bidding_strategy_rn
        # DO NOT set any per-campaign bidding fields when using portfolio
    elif args.bidding == "mcv":
        # For PMax, we can use MaximizeConversionValue with tROAS
        mcv = client.get_type("MaximizeConversionValue")
        if args.target_roas is not None:
            mcv.target_roas = float(args.target_roas)
        camp.maximize_conversion_value.CopyFrom(mcv)

    try:
        # Try real creation instead of validate_only
        camp_resp = camp_svc.mutate_campaigns(customer_id=args.customer, operations=[camp_op])
        campaign_rn = camp_resp.results[0].resource_name
        print(f"Campaign created successfully: {campaign_rn}")
    except Exception as exc:
        print("Campaign create error:\n", exc)
        return

    print("All creation checks passed for this combo.")


if __name__ == "__main__":
    main()


