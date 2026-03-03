"""Create feed-only Performance Max campaigns per label.

Dry-run by default; pass --apply true to execute mutations.

Usage examples:
  py -m src.pmax_feed_only --customer 5059126003 --merchant-id 5561429284 --sales-country DK --label-index 0 --apply false
  py -m src.pmax_feed_only --customer 5059126003 --merchant-id 5561429284 --sales-country DK --label-index 0 --eu-political false --apply true
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import Dict, Optional

from dotenv import load_dotenv
from google.ads.googleads.client import GoogleAdsClient
from google.protobuf import field_mask_pb2


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _digits_only(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return re.sub(r"\D", "", value)


def _discover_labels(client: GoogleAdsClient, customer_id: str, label_index: int) -> Dict[str, int]:
    field = f"segments.product_custom_attribute{label_index}"
    ga = client.get_service("GoogleAdsService")
    query = f"""
        SELECT
          {field},
          metrics.impressions
        FROM shopping_performance_view
        WHERE segments.date DURING LAST_30_DAYS
        AND {field} IS NOT NULL
    """
    counts: Dict[str, int] = {}
    for row in ga.search(customer_id=customer_id, query=query):
        label = getattr(row.segments, f"product_custom_attribute{label_index}") or ""
        if not label:
            continue
        counts[label] = counts.get(label, 0) + int(row.metrics.impressions)
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _discover_label0_to_label1_percent(client: GoogleAdsClient, customer_id: str) -> Dict[str, str]:
    ga = client.get_service("GoogleAdsService")
    query = (
        "SELECT segments.product_custom_attribute0, "
        "segments.product_custom_attribute1, metrics.impressions "
        "FROM shopping_performance_view "
        "WHERE segments.date DURING LAST_30_DAYS "
        "AND segments.product_custom_attribute0 IS NOT NULL"
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
        if counter:
            best_c1 = max(counter.items(), key=lambda kv: kv[1])[0]
            result[c0] = best_c1
    return result


def _parse_percent_to_troas(percent_str: str) -> Optional[float]:
    if not percent_str:
        return None
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", percent_str)
    if not m:
        return None
    try:
        pct = float(m.group(1))
        if pct <= 0:
            return None
        return round(1.0 / (pct / 100.0), 2)
    except Exception:
        return None


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Create/attach feed-only PMax campaigns per label")
    p.add_argument("--customer", required=True, help="Target customer id")
    p.add_argument("--merchant-id", required=True, help="Merchant Center account id")
    p.add_argument("--sales-country", default="DK", help="Sales country code (e.g., NL, DK, BE)")
    p.add_argument("--label-index", type=int, default=0, help="Which custom_label index (0..4)")
    p.add_argument("--prefix", default="PMax Label", help="Campaign name prefix")
    p.add_argument("--daily-budget", type=float, default=5.0, help="Daily budget in account currency")
    p.add_argument("--eu-political", type=str, default="false", help="Set contains_eu_political_advertising (true/false)")
    p.add_argument("--target-roas", type=float, default=None, help="Optional tROAS for all campaigns")
    p.add_argument("--attach", type=str, default="false", help="Attach to existing campaigns with given prefix (true/false)")
    p.add_argument("--global-target-roas", type=float, default=None, help="Create/use ONE portfolio tROAS for all campaigns (e.g., 6.5)")
    p.add_argument("--apply", type=str, default="false", help="Apply mutations (true/false)")
    return p.parse_args()


def _create_budget(client: GoogleAdsClient, customer_id: str, name: str, amount_micros: int) -> str:
    svc = client.get_service("CampaignBudgetService")
    op = client.get_type("CampaignBudgetOperation")
    bud = op.create
    bud.name = name
    bud.amount_micros = amount_micros
    bud.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD
    bud.explicitly_shared = False
    rn = svc.mutate_campaign_budgets(customer_id=customer_id, operations=[op]).results[0].resource_name
    return rn


def _create_pmax_campaign(
    client: GoogleAdsClient,
    customer_id: str,
    name: str,
    budget_rn: str,
    merchant_id: int,
    sales_country: str,
    eu_political: bool,
    target_roas: Optional[float],
) -> str:
    svc = client.get_service("CampaignService")
    op = client.get_type("CampaignOperation")
    camp = op.create
    camp.name = name
    camp.status = client.enums.CampaignStatusEnum.PAUSED
    camp.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.PERFORMANCE_MAX
    # Feed-only: disable URL expansion
    try:
        camp.url_expansion_opt_out = True
    except Exception:
        pass
    camp.campaign_budget = budget_rn
    # Retail PMax uses ShoppingSetting
    try:
        camp.shopping_setting.merchant_id = int(merchant_id)
        camp.shopping_setting.sales_country = sales_country
    except Exception:
        pass
    # EU political flag
    try:
        camp.contains_eu_political_advertising = eu_political
    except Exception:
        pass
    try:
        getattr(camp, "_pb").contains_eu_political_advertising = eu_political
    except Exception:
        pass
    # Bidding on create: campaign-level MCV with optional tROAS; if not set, leave for portfolio attach
    if target_roas is not None:
        try:
            mcv = client.get_type("MaximizeConversionValue")
            mcv.target_roas = float(target_roas)
            camp.maximize_conversion_value.CopyFrom(mcv)
        except Exception:
            try:
                camp.bidding_strategy_type = client.enums.BiddingStrategyTypeEnum.MAXIMIZE_CONVERSION_VALUE
            except Exception:
                pass
    rn = svc.mutate_campaigns(customer_id=customer_id, operations=[op]).results[0].resource_name
    return rn


def _create_asset_group(client: GoogleAdsClient, customer_id: str, campaign_rn: str, name: str) -> str:
    svc = client.get_service("AssetGroupService")
    op = client.get_type("AssetGroupOperation")
    ag = op.create
    ag.name = name
    ag.campaign = campaign_rn
    ag.status = client.enums.AssetGroupStatusEnum.PAUSED
    rn = svc.mutate_asset_groups(customer_id=customer_id, operations=[op]).results[0].resource_name
    return rn


def _ensure_global_portfolio_troas(client: GoogleAdsClient, customer_id: str, roas: float) -> str:
    svc = client.get_service("BiddingStrategyService")
    op = client.get_type("BiddingStrategyOperation")
    bs = op.create
    bs.name = f"Global tROAS {roas:.2f}"
    bs.target_roas.target_roas = float(roas)
    return svc.mutate_bidding_strategies(customer_id=customer_id, operations=[op]).results[0].resource_name


def _set_campaign_portfolio(client: GoogleAdsClient, customer_id: str, campaign_rn: str, strategy_rn: str) -> None:
    svc = client.get_service("CampaignService")
    op = client.get_type("CampaignOperation")
    c = op.update
    c.resource_name = campaign_rn
    c.bidding_strategy = strategy_rn
    op.update_mask.CopyFrom(field_mask_pb2.FieldMask(paths=["bidding_strategy"]))
    svc.mutate_campaigns(customer_id=customer_id, operations=[op])


def _find_campaigns_by_prefix(client: GoogleAdsClient, customer_id: str, prefix: str) -> Dict[str, str]:
    ga = client.get_service("GoogleAdsService")
    q = (
        "SELECT campaign.resource_name, campaign.id, campaign.name "
        "FROM campaign WHERE campaign.advertising_channel_type = PERFORMANCE_MAX"
    )
    results: Dict[str, str] = {}
    for row in ga.search(customer_id=customer_id, query=q):
        name = row.campaign.name or ""
        if name.startswith(prefix):
            results[name] = row.campaign.resource_name
    return results


def _attach_listing_group_filter(
    client: GoogleAdsClient,
    customer_id: str,
    asset_group_rn: str,
    label_index: int,
    label_value: str,
) -> None:
    svc = client.get_service("AssetGroupListingGroupFilterService")

    # Root subdivision
    root_op = client.get_type("AssetGroupListingGroupFilterOperation")
    root = root_op.create
    root.asset_group = asset_group_rn
    root.type_ = client.enums.ListingGroupFilterTypeEnum.SUBDIVISION
    root.vertical = client.enums.ListingGroupFilterVerticalEnum.SHOPPING
    root_rn = svc.mutate_asset_group_listing_group_filters(
        customer_id=customer_id, operations=[root_op]
    ).results[0].resource_name

    # Include unit for custom_labelX = label_value
    unit_op = client.get_type("AssetGroupListingGroupFilterOperation")
    unit = unit_op.create
    unit.asset_group = asset_group_rn
    unit.type_ = client.enums.ListingGroupFilterTypeEnum.UNIT
    unit.vertical = client.enums.ListingGroupFilterVerticalEnum.SHOPPING
    unit.parent_listing_group_filter = root_rn
    dim = unit.case_value
    custom_attr = dim.product_custom_attribute
    idx_enum = client.enums.ProductCustomAttributeIndexEnum
    index_map = {
        0: idx_enum.CUSTOM_ATTRIBUTE_0,
        1: idx_enum.CUSTOM_ATTRIBUTE_1,
        2: idx_enum.CUSTOM_ATTRIBUTE_2,
        3: idx_enum.CUSTOM_ATTRIBUTE_3,
        4: idx_enum.CUSTOM_ATTRIBUTE_4,
    }
    custom_attr.index = index_map[label_index]
    custom_attr.value = label_value
    svc.mutate_asset_group_listing_group_filters(customer_id=customer_id, operations=[unit_op])

    # Exclude rest
    excl_op = client.get_type("AssetGroupListingGroupFilterOperation")
    excl = excl_op.create
    excl.asset_group = asset_group_rn
    excl.type_ = client.enums.ListingGroupFilterTypeEnum.UNIT
    excl.vertical = client.enums.ListingGroupFilterVerticalEnum.SHOPPING
    excl.parent_listing_group_filter = root_rn
    excl.negative = True
    svc.mutate_asset_group_listing_group_filters(customer_id=customer_id, operations=[excl_op])


def main() -> None:
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
    args = _parse_args()
    customer_id = _digits_only(args.customer) or ""
    merchant_id = int(_digits_only(args.merchant_id) or 0)
    if not customer_id or not merchant_id:
        raise SystemExit("Ongeldige customer of merchant id")

    cfg = os.getenv("GOOGLE_ADS_CONFIGURATION_FILE")
    if not cfg:
        cfg = str(PROJECT_ROOT / "config" / "google-ads.yaml")
    print("Config path =", cfg)

    client = GoogleAdsClient.load_from_storage(cfg)

    labels = _discover_labels(client, customer_id, args.label_index)
    if not labels:
        print("Geen labels gevonden.")
        return

    print("Gevonden labels (impressies):")
    for label, impr in labels.items():
        print(f"  {label!r}: {impr} impressions")

    # Derive per-campaign tROAS from dominant custom_label_1 when not forced via --target-roas
    c0_to_troas: Dict[str, float] = {}
    if args.target_roas is None:
        c0_to_c1 = _discover_label0_to_label1_percent(client, customer_id)
        for c0, c1 in c0_to_c1.items():
            troas = _parse_percent_to_troas(c1)
            if troas:
                c0_to_troas[c0] = troas

    print("\nPlannen (PMax feed-only):")
    for label in labels.keys():
        troas = args.target_roas if args.target_roas is not None else c0_to_troas.get(label)
        extra = "" if troas is None else f", tROAS={troas}"
        print(f"- {args.prefix} - {label}{extra}")

    if str(args.apply).lower() not in {"1", "true", "yes"}:
        print("\nDry-run. Geen wijzigingen toegepast.")
        return

    eu_bool = str(args.eu_political).lower() in {"1", "true", "yes"}
    # Attach mode: find existing campaigns and configure asset group + filter
    if str(args.attach).lower() in {"1", "true", "yes"}:
        existing = _find_campaigns_by_prefix(client, customer_id, args.prefix)
        if not existing:
            print("Geen bestaande PMax campagnes gevonden met prefix.")
            return
        for label, _ in labels.items():
            safe = re.sub(r"[^A-Za-z0-9 _-]+", " ", label).strip()[:40]
            name = f"{args.prefix} - {safe}" if args.prefix else safe
            camp_rn = existing.get(name)
            if not camp_rn:
                print(f"Campagne niet gevonden voor label '{label}' met naam '{name}', overslaan.")
                continue
            try:
                ag_rn = _create_asset_group(client, customer_id, camp_rn, f"{name} - Asset Group")
                _attach_listing_group_filter(
                    client,
                    customer_id,
                    asset_group_rn=ag_rn,
                    label_index=args.label_index,
                    label_value=label,
                )
                print(f"Geconfigureerd: {name}")
            except Exception as exc:
                print(f"Fout bij configureren '{name}': {exc}")
        return

    # Create new campaigns per label
    # Create new campaigns per label
    global_strategy_rn: Optional[str] = None
    if args.global_target_roas is not None:
        try:
            global_strategy_rn = _ensure_global_portfolio_troas(client, customer_id, args.global_target_roas)
            print("Global portfolio tROAS aangemaakt:", global_strategy_rn)
        except Exception as exc:
            print("Kon global portfolio tROAS niet aanmaken:", str(exc))
            global_strategy_rn = None

    for label, _ in labels.items():
        safe = re.sub(r"[^A-Za-z0-9 _-]+", " ", label).strip()[:40]
        name = f"{args.prefix} - {safe}" if args.prefix else safe
        troas = args.target_roas if args.target_roas is not None else c0_to_troas.get(label)
        try:
            budget_rn = _create_budget(
                client,
                customer_id,
                name=f"{name} - Budget",
                amount_micros=int(round(args.daily_budget * 1_000_000)),
            )
            camp_rn = _create_pmax_campaign(
                client,
                customer_id,
                name=name,
                budget_rn=budget_rn,
                merchant_id=merchant_id,
                sales_country=args.sales_country,
                eu_political=eu_bool,
                target_roas=troas,
            )
            # If a global portfolio exists and no per-campaign tROAS is set on create, attach it
            if global_strategy_rn and args.target_roas is None:
                try:
                    _set_campaign_portfolio(client, customer_id, camp_rn, global_strategy_rn)
                except Exception:
                    pass

            ag_rn = _create_asset_group(client, customer_id, camp_rn, f"{name} - Asset Group")
            _attach_listing_group_filter(
                client,
                customer_id,
                asset_group_rn=ag_rn,
                label_index=args.label_index,
                label_value=label,
            )
            print(f"Aangemaakt: {name}")
        except Exception as exc:
            print(f"Fout bij aanmaken '{name}': {exc}")


if __name__ == "__main__":
    main()


