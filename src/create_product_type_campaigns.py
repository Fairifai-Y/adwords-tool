"""Create Standard Shopping campaigns based on custom_label_0 + custom_label_4 + custom_label_2.

This script creates Standard Shopping campaigns for each combination of:
- custom_label_0 (seller)
- custom_label_4 (config type)
- custom_label_2 (price bucket / product type)

It derives tROAS from custom_label_1 (dominant value by impressions) per seller and applies
TARGET_ROAS bidding with campaign priority = 1. It then creates one ad group with a
three-level Product Partition tree: label_0 -> label_4 -> label_2.

Usage:
  py src/create_product_type_campaigns.py --customer 5059126003 --apply false
"""

from __future__ import annotations

import argparse
import re
import time
import random
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Set
from pathlib import Path
import os
from dotenv import load_dotenv

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from google.api_core import exceptions as gax
from datetime import datetime, timezone
from google.protobuf import field_mask_pb2


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "google-ads.yaml"
def _get_or_create_portfolio_troas(
    client: GoogleAdsClient,
    customer_id: str,
    target_roas: float,
    seller_name: Optional[str] = None,
) -> str:
    """Get or create a per-seller portfolio TARGET_ROAS and return its resource name.

    If seller_name is provided, we search/create a strategy named:
      tROAS {target_roas:.2f} - {seller_name}
    otherwise fall back to a generic name.
    """
    bs_svc = client.get_service("BiddingStrategyService")
    ga_svc = client.get_service("GoogleAdsService")
    enums = client.enums

    # Build desired name
    safe_seller = (seller_name or "").strip()
    # Sanitize seller for name safety
    if safe_seller:
        safe_seller = re.sub(r"[^\w\s\-]", "", safe_seller)[:60].strip()
    desired_name = f"tROAS {target_roas:.2f} - {safe_seller}" if safe_seller else f"tROAS {target_roas:.2f}"

    # Try to find an existing TARGET_ROAS with this exact name
    query = (
        "SELECT bidding_strategy.resource_name, bidding_strategy.name, "
        "bidding_strategy.type FROM bidding_strategy "
        f"WHERE bidding_strategy.type = TARGET_ROAS AND bidding_strategy.name = '{desired_name}'"
    )
    try:
        for row in ga_svc.search(customer_id=customer_id, query=query):
            return row.bidding_strategy.resource_name
    except Exception:
        pass

    # Create a new one
    op = client.get_type("BiddingStrategyOperation")
    bs = op.create
    bs.name = desired_name
    bs.type_ = enums.BiddingStrategyTypeEnum.TARGET_ROAS
    bs.target_roas.target_roas = float(target_roas)
    resp = bs_svc.mutate_bidding_strategies(customer_id=customer_id, operations=[op])
    return resp.results[0].resource_name


def _ensure_troas_active(client: GoogleAdsClient, customer_id: str, campaign_rn: str, retries: int = 5) -> None:
    """Wait until the campaign reflects a TARGET_ROAS portfolio strategy before mutating listing groups."""
    ga = client.get_service("GoogleAdsService")
    query = (
        "SELECT campaign.resource_name, campaign.bidding_strategy, campaign.bidding_strategy_type "
        "FROM campaign WHERE campaign.resource_name = '" + campaign_rn + "'"
    )
    for i in range(retries):
        try:
            rows = list(ga.search(customer_id=customer_id, query=query))
            if rows:
                row = rows[0]
                bst = row.campaign.bidding_strategy
                bst_type = row.campaign.bidding_strategy_type
                # Portfolio attached OR inline type is TARGET_ROAS
                if bst or getattr(bst_type, "name", "") == "TARGET_ROAS":
                    return
        except Exception:
            pass
        time.sleep(2.0 + i)


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
            # af en toe interne of tijdelijke fouten
            if hasattr(ec, "internal_error") and ec.internal_error.name == "INTERNAL_ERROR":
                return True, "INTERNAL_ERROR"
            if hasattr(ec, "quota_error") and ec.quota_error.name == "RESOURCE_EXHAUSTED":
                return True, "RESOURCE_EXHAUSTED"
    return False, ""


def _retry(fn, attempts=6, base=1.6, first_sleep=1.0):
    """Retry function with exponential backoff.

    Fixed initial delays for listing group stability:
      - 1st retry = 2s
      - 2nd retry = 5s
      - 3rd retry = 15s
    Then continue with exponential backoff.
    """
    fixed_delays = [2.0, 5.0, 15.0]
    delay = first_sleep
    for i in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:
            ok, reason = _should_retry(e)
            if not ok or i == attempts:
                raise
            if i <= len(fixed_delays):
                sleep_s = fixed_delays[i - 1]
            else:
                sleep_s = delay * (1.0 + random.random() * 0.25)
            print(f"  Retry wegens {reason} in {sleep_s:.1f}s (poging {i}/{attempts})")
            time.sleep(sleep_s)
            delay *= base


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value)


def _label_field(index: int) -> str:
    if index not in {0, 1, 2, 3, 4}:
        raise ValueError("label-index must be 0..4")
    return f"segments.product_custom_attribute{index}"


@dataclass
class CampaignPlan:
    name: str
    label_0_value: str
    label_4_value: str
    label_2_value: str
    daily_budget_micros: int
    target_roas: Optional[float] = None


def get_existing_campaigns(client: GoogleAdsClient, customer_id: str, prefix: str) -> Set[str]:
    """Get set of existing campaign names with the specified prefix."""
    ga = client.get_service("GoogleAdsService")
    
    # Escape prefix for GAQL query
    safe_prefix = prefix.replace("'", "\\'").replace("\\", "\\\\")
    
    query = f"""
        SELECT campaign.name
        FROM campaign
        WHERE campaign.name LIKE '{safe_prefix}%'
        AND campaign.advertising_channel_type = 'SHOPPING'
    """
    
    existing_names = set()
    try:
        for row in ga.search(customer_id=customer_id, query=query):
            existing_names.add(row.campaign.name)
    except Exception as e:
        print(f"[WARN] Kon bestaande campagnes niet ophalen: {e}")
    
    return existing_names


def get_existing_sellers_with_campaigns(client: GoogleAdsClient, customer_id: str, prefix: str) -> Set[str]:
    """Get set of sellers (label_0) that already have campaigns with the specified prefix."""
    ga = client.get_service("GoogleAdsService")
    
    # Escape prefix for GAQL query
    safe_prefix = prefix.replace("'", "\\'").replace("\\", "\\\\")
    
    query = f"""
        SELECT campaign.name
        FROM campaign
        WHERE campaign.name LIKE '{safe_prefix}%'
        AND campaign.advertising_channel_type = 'SHOPPING'
    """
    
    existing_sellers = set()
    try:
        for row in ga.search(customer_id=customer_id, query=query):
            # Extract seller name from campaign name: "Std Shopping - seller - config - bucket"
            # Format: "{prefix} - {label_0} - {label_4} - {label_2}"
            parts = row.campaign.name.split(' - ')
            if len(parts) >= 2:
                # Second part should be the seller (label_0)
                seller = parts[1].strip()
                if seller:
                    existing_sellers.add(seller)
    except Exception as e:
        print(f"[WARN] Kon bestaande sellers niet ophalen: {e}")
    
    return existing_sellers


def discover_label_combinations(client: GoogleAdsClient, customer_id: str) -> Dict[Tuple[str, str, str], int]:
    """Discover combinations of custom_label_0 + custom_label_4 + custom_label_2 from last 30 days.
    Only combinations with traffic in the last 30 days are returned.
    """
    ga = client.get_service("GoogleAdsService")
    query = (
        "SELECT segments.product_custom_attribute0, "
        "segments.product_custom_attribute4, "
        "segments.product_custom_attribute2, metrics.impressions "
        "FROM shopping_performance_view "
        "WHERE segments.date DURING LAST_30_DAYS "
        "AND segments.product_custom_attribute0 IS NOT NULL "
        "AND segments.product_custom_attribute4 IS NOT NULL "
        "AND segments.product_custom_attribute2 IS NOT NULL"
    )
    
    combinations: Dict[Tuple[str, str, str], int] = {}
    for row in ga.search(customer_id=customer_id, query=query):
        label_0 = getattr(row.segments, "product_custom_attribute0") or ""
        label_4 = getattr(row.segments, "product_custom_attribute4") or ""
        label_2 = getattr(row.segments, "product_custom_attribute2") or ""
        impressions = row.metrics.impressions
        
        if label_0 and label_4 and label_2:
            key = (label_0, label_4, label_2)
            combinations[key] = combinations.get(key, 0) + impressions
    
    return combinations


def get_troas_for_label_0(client: GoogleAdsClient, customer_id: str, label_0: str) -> Optional[float]:
    """Get the tROAS value for a specific custom_label_0 from custom_label_1."""
    ga = client.get_service("GoogleAdsService")
    
    # Escape GAQL string literal (single quotes and backslashes)
    def _escape_gaql(value: str) -> str:
        if value is None:
            return ""
        # GAQL uses single-quoted string literals; escape embedded quotes and backslashes
        return value.replace("\\", "\\\\").replace("'", "\\'")

    safe_label_0 = _escape_gaql(label_0)
    query = (
        "SELECT segments.product_custom_attribute0, segments.product_custom_attribute1, metrics.impressions "
        "FROM shopping_performance_view "
        "WHERE segments.date DURING LAST_30_DAYS "
        f"AND segments.product_custom_attribute0 = '{safe_label_0}' "
        "AND segments.product_custom_attribute1 IS NOT NULL"
    )
    
    label_1_values = {}
    for row in ga.search(customer_id=customer_id, query=query):
        label_1 = getattr(row.segments, "product_custom_attribute1") or ""
        impressions = row.metrics.impressions
        if label_1:
            label_1_values[label_1] = label_1_values.get(label_1, 0) + impressions
    
    if not label_1_values:
        return None
    
    # Find the dominant label_1 value (highest impressions)
    dominant_label_1 = max(label_1_values.items(), key=lambda x: x[1])[0]
    
    print(f"    Dominant custom_label_1 voor '{label_0}': '{dominant_label_1}'")
    
    # Parse tROAS from label_1 (assuming format like "17.5%" or "15%")
    try:
        # Remove % and convert to float
        clean_value = dominant_label_1.replace('%', '').strip()
        percentage = float(clean_value)
        if percentage <= 0:
            print(f"    -> Percentage moet > 0 zijn, kreeg: {percentage}")
            return None
        
        # Convert percentage to tROAS: 17.5% = 0.175 -> tROAS = 1/0.175 = 5.71
        troas = 1.0 / (percentage / 100.0)
        troas = round(troas, 2)  # Round to 2 decimal places
        print(f"    -> Afgeleide tROAS: {percentage}% -> {troas}")
        return troas
    except ValueError:
        print(f"    -> Kon tROAS niet afleiden uit '{dominant_label_1}'")
        return None


def build_campaign_plans(
    combinations: Dict[Tuple[str, str, str], int],
    prefix: str = "Std Shopping",
    daily_budget: float = 5.0,
    default_target_roas: Optional[float] = None,
    roas_factor: float = 0.0,
    client: Optional[GoogleAdsClient] = None,
    customer_id: Optional[str] = None,
) -> List[CampaignPlan]:
    """Build campaign plans for each label combination."""
    plans = []
    budget_micros = int(daily_budget * 1_000_000)
    
    for (label_0, label_4, label_2), impressions in sorted(combinations.items(), key=lambda x: x[1], reverse=True):
        # Get tROAS for this label_0 if client is provided
        target_roas = default_target_roas
        if client and customer_id and default_target_roas is None:
            target_roas = get_troas_for_label_0(client, customer_id, label_0)
        
        # Apply ROAS factor if specified (as percentage)
        if target_roas is not None and roas_factor != 0:
            original_roas = target_roas
            target_roas = round(target_roas * (1 + roas_factor / 100), 2)
            print(f"    ROAS aangepast: {original_roas} {roas_factor:+.1f}% = {target_roas}")
        
        # Create campaign name
        safe_label_0 = re.sub(r'[^\w\s-]', '', label_0).strip()
        safe_label_4 = re.sub(r'[^\w\s-]', '', label_4).strip()
        safe_label_2 = re.sub(r'[^\w\s-]', '', label_2).strip()
        campaign_name = f"{prefix} - {safe_label_0} - {safe_label_4} - {safe_label_2}"
        
        plan = CampaignPlan(
            name=campaign_name,
            label_0_value=label_0,
            label_4_value=label_4,
            label_2_value=label_2,
            daily_budget_micros=budget_micros,
            target_roas=target_roas
        )
        plans.append(plan)
    
    return plans


def _create_standard_shopping_campaign(
    client: GoogleAdsClient,
    customer_id: str,
    campaign_name: str,
    daily_budget_micros: int,
    merchant_id: Optional[str],
    target_countries: Optional[str],
    target_languages: Optional[str],
    target_roas: Optional[float],
    start_enabled: bool,
    priority: int = 1,
) -> str:
    """Create a Standard Shopping campaign with TARGET_ROAS and priority."""
    budget_svc = client.get_service("CampaignBudgetService")
    camp_svc = client.get_service("CampaignService")

    # Budget
    budget_op = client.get_type("CampaignBudgetOperation")
    budget = budget_op.create
    budget.name = f"{campaign_name} - Budget"
    budget.amount_micros = daily_budget_micros
    budget.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD
    budget.explicitly_shared = False
    budget_resp = _retry(lambda: budget_svc.mutate_campaign_budgets(customer_id=customer_id, operations=[budget_op]))
    budget_rn = budget_resp.results[0].resource_name

    # Campaign
    camp_op = client.get_type("CampaignOperation")
    camp = camp_op.create
    camp.name = campaign_name
    camp.status = client.enums.CampaignStatusEnum.ENABLED if start_enabled else client.enums.CampaignStatusEnum.PAUSED
    camp.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.SHOPPING
    camp.campaign_budget = budget_rn

    # Shopping setting
    if merchant_id:
        camp.shopping_setting.merchant_id = int(merchant_id)
    # For Standard Shopping, set sales_country from first target country
    try:
        first_cc = (target_countries or "").split(',')[0].strip().upper() if target_countries else ""
        if first_cc:
            camp.shopping_setting.sales_country = first_cc
    except Exception:
        pass
    camp.shopping_setting.campaign_priority = int(priority)

    # Phase 1: start with Manual CPC so listing groups can include leaf bids
    try:
        camp.bidding_strategy_type = client.enums.BiddingStrategyTypeEnum.MANUAL_CPC
        camp.manual_cpc = client.get_type("ManualCpc")
    except Exception:
        pass

    # EU political
    try:
        camp.contains_eu_political_advertising = client.enums.EuPoliticalAdvertisingStatusEnum.DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING
    except Exception:
        pass

    camp_resp = _retry(lambda: camp_svc.mutate_campaigns(customer_id=customer_id, operations=[camp_op]))
    campaign_rn = camp_resp.results[0].resource_name

    # Stel expliciet locatie-targeting (landen) in via CampaignCriterion, zodat UI niet "All countries" toont.
    try:
        ga = client.get_service("GoogleAdsService")
        ccodes = [c.strip().upper() for c in (target_countries or "").split(',') if c.strip()]
        if ccodes:
            cc_filter = ",".join([f"'{c}'" for c in ccodes])
            g_query = (
                "SELECT geo_target_constant.resource_name, geo_target_constant.country_code, "
                "geo_target_constant.target_type, geo_target_constant.status "
                "FROM geo_target_constant "
                f"WHERE geo_target_constant.country_code IN ({cc_filter}) "
                "AND geo_target_constant.target_type = 'Country' "
                "AND geo_target_constant.status = 'ENABLED'"
            )
            geo_rns = [row.geo_target_constant.resource_name for row in ga.search(customer_id=customer_id, query=g_query)]
            if geo_rns:
                crit_ops = []
                campcrit_svc = client.get_service("CampaignCriterionService")
                for geo_rn in geo_rns:
                    op = client.get_type("CampaignCriterionOperation")
                    crit = op.create
                    crit.campaign = campaign_rn
                    crit.location.geo_target_constant = geo_rn
                    crit.negative = False
                    crit_ops.append(op)
                _retry(lambda: campcrit_svc.mutate_campaign_criteria(customer_id=customer_id, operations=crit_ops))
    except Exception as e:
        print(f"[WARN] Kon locatie-targeting niet toepassen: {e}")

    time.sleep(1.0)
    return campaign_rn


def _create_ad_group(client: GoogleAdsClient, customer_id: str, campaign_rn: str, name: str, start_enabled: bool) -> str:
    """Create a Shopping Ad Group."""
    ag_svc = client.get_service("AdGroupService")
    op = client.get_type("AdGroupOperation")
    ag = op.create
    ag.name = name
    ag.campaign = campaign_rn
    ag.status = client.enums.AdGroupStatusEnum.ENABLED if start_enabled else client.enums.AdGroupStatusEnum.PAUSED
    ag.type_ = client.enums.AdGroupTypeEnum.SHOPPING_PRODUCT_ADS
    # Set a default ad group bid for phase-1 Manual CPC
    try:
        ag.cpc_bid_micros = 200000
    except Exception:
        pass
    resp = _retry(lambda: ag_svc.mutate_ad_groups(customer_id=customer_id, operations=[op]))
    return resp.results[0].resource_name


def _create_product_ad(
    client: GoogleAdsClient,
    customer_id: str,
    ad_group_rn: str,
    start_enabled: bool,
) -> None:
    """Create a Shopping product ad (required for Shopping ad groups)."""
    ad_svc = client.get_service("AdGroupAdService")
    op = client.get_type("AdGroupAdOperation")
    aga = op.create
    aga.ad_group = ad_group_rn
    aga.status = client.enums.AdGroupAdStatusEnum.ENABLED if start_enabled else client.enums.AdGroupAdStatusEnum.PAUSED
    aga.ad.shopping_product_ad = client.get_type("ShoppingProductAdInfo")
    _retry(lambda: ad_svc.mutate_ad_group_ads(customer_id=customer_id, operations=[op]))


def _add_product_partitions_for_triplet(
    client: GoogleAdsClient,
    customer_id: str,
    ad_group_rn: str,
    label_0_value: str,
    label_4_value: str,
    label_2_value: str,
    manual_cpc: bool,
) -> None:
    """Create 3-level product partition tree following PMax pattern.
    
    Structure:
      ROOT (SUBDIVISION)
       ├─ label_0=VALUE (SUBDIVISION) 
       │   ├─ label_4=VALUE (SUBDIVISION)
       │   │   ├─ label_2=VALUE (UNIT INCLUDED)
       │   │   └─ OTHERS (UNIT EXCLUDED)
       │   └─ OTHERS (UNIT EXCLUDED)
       └─ OTHERS (UNIT EXCLUDED)
    """
    agc_svc = client.get_service("AdGroupCriterionService")
    enums = client.enums

    ops = []

    # Helpers
    agc = client.get_service("AdGroupCriterionService")
    ad_group_id = ad_group_rn.split("/")[-1]
    def path(temp_id: int) -> str:
        return agc.ad_group_criterion_path(customer_id, ad_group_id, str(temp_id))

    # Temp IDs
    root_id = -1
    l0_id = -2
    l4_id = -3
    leaf_id = -4
    others_root_id = -5
    others_l0_id = -6
    others_l4_id = -7

    # 1) ROOT SUBDIVISION
    op_root = client.get_type("AdGroupCriterionOperation")
    n_root = op_root.create
    n_root.resource_name = path(root_id)
    n_root.ad_group = ad_group_rn
    n_root.status = enums.AdGroupCriterionStatusEnum.ENABLED
    n_root.listing_group.type_ = enums.ListingGroupTypeEnum.SUBDIVISION
    ops.append(op_root)

    # 2) ROOT OTHERS (UNIT, negative)
    op_root_other = client.get_type("AdGroupCriterionOperation")
    n_root_other = op_root_other.create
    n_root_other.resource_name = path(others_root_id)
    n_root_other.ad_group = ad_group_rn
    n_root_other.status = enums.AdGroupCriterionStatusEnum.ENABLED
    n_root_other.listing_group.type_ = enums.ListingGroupTypeEnum.UNIT
    n_root_other.listing_group.parent_ad_group_criterion = n_root.resource_name
    n_root_other.negative = True
    # others: set case_value with index only (no value)
    n_root_other.listing_group.case_value.product_custom_attribute.index = enums.ProductCustomAttributeIndexEnum.INDEX0
    n_root_other.listing_group.case_value.product_custom_attribute._pb.SetInParent()
    # no bid on others
    ops.append(op_root_other)

    # 3) Level 1 SUBDIVISION (custom_label_0)
    op_l0 = client.get_type("AdGroupCriterionOperation")
    n_l0 = op_l0.create
    n_l0.resource_name = path(l0_id)
    n_l0.ad_group = ad_group_rn
    n_l0.status = enums.AdGroupCriterionStatusEnum.ENABLED
    n_l0.listing_group.type_ = enums.ListingGroupTypeEnum.SUBDIVISION
    n_l0.listing_group.parent_ad_group_criterion = n_root.resource_name
    n_l0.listing_group.case_value.product_custom_attribute.index = enums.ProductCustomAttributeIndexEnum.INDEX0
    n_l0.listing_group.case_value.product_custom_attribute.value = label_0_value
    ops.append(op_l0)

    # 4) Level 1 OTHERS (UNIT, negative)
    op_l0_other = client.get_type("AdGroupCriterionOperation")
    n_l0_other = op_l0_other.create
    n_l0_other.resource_name = path(others_l0_id)
    n_l0_other.ad_group = ad_group_rn
    n_l0_other.status = enums.AdGroupCriterionStatusEnum.ENABLED
    n_l0_other.listing_group.type_ = enums.ListingGroupTypeEnum.UNIT
    n_l0_other.listing_group.parent_ad_group_criterion = n_l0.resource_name
    n_l0_other.negative = True
    # others: set case_value with index only (no value)
    n_l0_other.listing_group.case_value.product_custom_attribute.index = enums.ProductCustomAttributeIndexEnum.INDEX4
    n_l0_other.listing_group.case_value.product_custom_attribute._pb.SetInParent()
    # no bid on others
    ops.append(op_l0_other)

    # 5) Level 2 SUBDIVISION (custom_label_4)
    op_l4 = client.get_type("AdGroupCriterionOperation")
    n_l4 = op_l4.create
    n_l4.resource_name = path(l4_id)
    n_l4.ad_group = ad_group_rn
    n_l4.status = enums.AdGroupCriterionStatusEnum.ENABLED
    n_l4.listing_group.type_ = enums.ListingGroupTypeEnum.SUBDIVISION
    n_l4.listing_group.parent_ad_group_criterion = n_l0.resource_name
    n_l4.listing_group.case_value.product_custom_attribute.index = enums.ProductCustomAttributeIndexEnum.INDEX4
    n_l4.listing_group.case_value.product_custom_attribute.value = label_4_value
    ops.append(op_l4)

    # 6) Level 2 OTHERS (UNIT, negative)
    op_l4_other = client.get_type("AdGroupCriterionOperation")
    n_l4_other = op_l4_other.create
    n_l4_other.resource_name = path(others_l4_id)
    n_l4_other.ad_group = ad_group_rn
    n_l4_other.status = enums.AdGroupCriterionStatusEnum.ENABLED
    n_l4_other.listing_group.type_ = enums.ListingGroupTypeEnum.UNIT
    n_l4_other.listing_group.parent_ad_group_criterion = n_l4.resource_name
    n_l4_other.negative = True
    # others: set case_value with index only (no value)
    n_l4_other.listing_group.case_value.product_custom_attribute.index = enums.ProductCustomAttributeIndexEnum.INDEX2
    n_l4_other.listing_group.case_value.product_custom_attribute._pb.SetInParent()
    # no bid on others
    ops.append(op_l4_other)

    # 7) Level 3 LEAF (UNIT_INCLUDED custom_label_2)
    op_leaf = client.get_type("AdGroupCriterionOperation")
    n_leaf = op_leaf.create
    n_leaf.resource_name = path(leaf_id)
    n_leaf.ad_group = ad_group_rn
    n_leaf.status = enums.AdGroupCriterionStatusEnum.ENABLED
    n_leaf.listing_group.type_ = enums.ListingGroupTypeEnum.UNIT
    n_leaf.listing_group.parent_ad_group_criterion = n_l4.resource_name
    n_leaf.listing_group.case_value.product_custom_attribute.index = enums.ProductCustomAttributeIndexEnum.INDEX2
    n_leaf.listing_group.case_value.product_custom_attribute.value = label_2_value
    # Explicit leaf bid for phase-1 Manual CPC
    n_leaf.cpc_bid_micros = 200000
    ops.append(op_leaf)

    _retry(lambda: agc_svc.mutate_ad_group_criteria(customer_id=customer_id, operations=ops))


def parse_args():
    """Parse command line arguments."""
    p = argparse.ArgumentParser(description="Create Standard Shopping campaigns for label_0 + label_4 + label_2 combinations")
    p.add_argument("--customer", required=True, help="Customer ID")
    p.add_argument("--login", help="Login customer ID (optional)")
    p.add_argument("--prefix", default="Std Shopping", help="Campaign name prefix")
    p.add_argument("--daily-budget", type=float, default=5.0, help="Daily budget in EUR")
    p.add_argument("--target-roas", type=float, help="Override tROAS (otherwise derived from custom_label_1)")
    p.add_argument("--roas-factor", type=float, default=0.0, help="Percentage to adjust calculated ROAS (e.g., +10 for 10% increase, -10 for 10% decrease)")
    # Backward/UI compatibility: accept underscore version as alias
    p.add_argument("--roas_factor", dest="roas_factor", type=float, help=argparse.SUPPRESS)
    p.add_argument("--merchant-id", default="", help="Override Merchant Center ID (optional)")
    p.add_argument("--start-enabled", action="store_true", 
                   help="Start campaigns and asset groups as ENABLED instead of PAUSED")
    p.add_argument("--target-languages", type=str, default="nl", 
                   help="Comma-separated list of target languages (e.g., 'nl,en,de' or 'nl')")
    p.add_argument("--target-countries", type=str, default="NL", 
                   help="Comma-separated list of target countries (e.g., 'NL,BE,DE' or 'NL')")
    p.add_argument("--feed-label", type=str, default="", 
                   help="Feed label for shopping setting (e.g., 'dk', 'nl', 'de')")
    p.add_argument("--apply", type=str, default="false", help="Apply mutations (true/false)")
    p.add_argument("--min-impressions", type=int, default=100, 
                   help="Minimum impressions threshold for combinations")
    p.add_argument("--max-campaigns", type=int, default=0,
                   help="Maximum number of campaigns to list/apply (0 = no cap)")
    p.add_argument("--skip-existing", action="store_true", default=True,
                   help="Skip campaigns that already exist (default: True, more efficient)")
    p.add_argument("--no-skip-existing", dest="skip_existing", action="store_false",
                   help="Create all campaigns even if they already exist (may cause errors)")
    p.add_argument("--new-sellers-only", action="store_true",
                   help="Only create campaigns for sellers that don't have any campaigns yet")
    return p.parse_args()


def main() -> None:
    """Main function."""
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

    # Discover label combinations
    print("Ontdekken van label_0 + label_4 + label_2 combinaties (laatste 30 dagen)...")
    combinations = discover_label_combinations(client, customer_id=customer_id)
    
    if not combinations:
        print("Geen label combinaties gevonden in de laatste 30 dagen. Er is geen traffic met label_0 + label_4 + label_2.")
        return

    # Filter by minimum impressions
    filtered_combinations = {
        (label_0, label_4, label_2): impressions
        for (label_0, label_4, label_2), impressions in combinations.items()
        if impressions >= args.min_impressions
    }
    
    if not filtered_combinations:
        print(f"Geen combinaties gevonden met minimaal {args.min_impressions} impressies.")
        return

    # Bepaal selectie op basis van cap (verkleint ook tROAS-berekeningen)
    cap_for_selection = max(0, int(getattr(args, "max_campaigns", 0) or 0))
    if cap_for_selection > 0:
        top_items = sorted(filtered_combinations.items(), key=lambda x: x[1], reverse=True)[:cap_for_selection]
        selected_combinations = dict(top_items)
    else:
        selected_combinations = filtered_combinations

    print(f"\nGeselecteerd {len(selected_combinations)} combinaties voor planning (van {len(filtered_combinations)} gevonden, min {args.min_impressions} impressies):")
    for (label_0, label_4, label_2), impressions in sorted(selected_combinations.items(), key=lambda x: x[1], reverse=True):
        print(f"  {label_0!r} + {label_4!r} + {label_2!r}: {impressions} impressies")

    # Build campaign plans
    plans = build_campaign_plans(
        selected_combinations,
        prefix=args.prefix,
        daily_budget=args.daily_budget,
        default_target_roas=args.target_roas,
        roas_factor=args.roas_factor,
        client=client,
        customer_id=customer_id,
    )

    # Apply temporary cap if requested
    plans_to_use = plans
    if getattr(args, "max_campaigns", 0):
        cap = max(0, int(args.max_campaigns))
        if cap > 0 and len(plans) > cap:
            plans_to_use = plans[:cap]

    # Filter out existing campaigns and/or filter by new sellers only
    if args.skip_existing or getattr(args, "new_sellers_only", False):
        print(f"\nControleren op bestaande campagnes...")
        existing_campaigns = get_existing_campaigns(client, customer_id, args.prefix)
        print(f"  Gevonden {len(existing_campaigns)} bestaande campagne(s) met prefix '{args.prefix}'")
        
        existing_sellers = set()
        if getattr(args, "new_sellers_only", False):
            existing_sellers = get_existing_sellers_with_campaigns(client, customer_id, args.prefix)
            print(f"  Gevonden {len(existing_sellers)} seller(s) die al campagnes hebben")
        
        original_count = len(plans_to_use)
        filtered_plans = []
        skipped_by_name = 0
        skipped_by_seller = 0
        
        for plan in plans_to_use:
            # Skip if campaign name already exists
            if args.skip_existing and plan.name in existing_campaigns:
                skipped_by_name += 1
                continue
            
            # Skip if seller already has campaigns (new-sellers-only mode)
            if getattr(args, "new_sellers_only", False) and plan.label_0_value in existing_sellers:
                skipped_by_seller += 1
                continue
            
            filtered_plans.append(plan)
        
        plans_to_use = filtered_plans
        
        if skipped_by_name > 0 or skipped_by_seller > 0:
            print(f"\n  Gefilterd: {original_count} -> {len(plans_to_use)} campagnes")
            if skipped_by_name > 0:
                print(f"    Overgeslagen (bestaan al): {skipped_by_name}")
            if skipped_by_seller > 0:
                print(f"    Overgeslagen (seller heeft al campagnes): {skipped_by_seller}")
            print(f"    Te maken: {len(plans_to_use)}")

    print(f"\nCampaign-plannen ({len(plans_to_use)} campagnes, totaal ontdekt: {len(plans)}):")
    for plan in plans_to_use:
        roas = f", tROAS={plan.target_roas}" if plan.target_roas else ""
        print(f"- {plan.name}  (label_0='{plan.label_0_value}', label_4='{plan.label_4_value}', label_2='{plan.label_2_value}'{roas})")
        
        # Show ROAS calculation details if ROAS factor was applied
        if args.roas_factor != 0 and plan.target_roas is not None:
            # Calculate original ROAS from adjusted ROAS
            original_roas = round(plan.target_roas / (1 + args.roas_factor / 100), 2)
            print(f"    -> ROAS: {original_roas} {args.roas_factor:+.1f}% = {plan.target_roas}")

    if str(args.apply).lower() in {"1", "true", "yes"}:
        print(f"\nApply=true -> {len(plans_to_use)} campagnes worden aangemaakt (van totaal {len(plans)} gevonden)...")
        merchant_id = _digits_only(args.merchant_id) if args.merchant_id else None
        
        created_campaigns = []
        for i, plan in enumerate(plans_to_use, 1):
            print(f"\n[{i}/{len(plans_to_use)}] Aanmaken campagne: {plan.name}")
            
            try:
                # Create Standard Shopping campaign
                campaign_rn = _create_standard_shopping_campaign(
                    client=client,
                    customer_id=customer_id,
                    campaign_name=plan.name,
                    daily_budget_micros=plan.daily_budget_micros,
                    merchant_id=merchant_id,
                    target_countries=args.target_countries,
                    target_languages=args.target_languages,
                    target_roas=plan.target_roas,
                    start_enabled=args.start_enabled,
                    priority=1,
                )

                # Create Ad Group and product partitions
                ad_group_rn = _create_ad_group(
                    client=client,
                    customer_id=customer_id,
                    campaign_rn=campaign_rn,
                    name=f"Ad Group - {plan.label_0_value} - {plan.label_4_value}",
                    start_enabled=args.start_enabled,
                )

                # Create a product ad in the ad group (required)
                _create_product_ad(
                    client=client,
                    customer_id=customer_id,
                    ad_group_rn=ad_group_rn,
                    start_enabled=args.start_enabled,
                )

                _add_product_partitions_for_triplet(
                    client=client,
                    customer_id=customer_id,
                    ad_group_rn=ad_group_rn,
                    label_0_value=plan.label_0_value,
                    label_4_value=plan.label_4_value,
                    label_2_value=plan.label_2_value,
                    manual_cpc=True,
                )

                # Phase 2: switch to per-seller portfolio TARGET_ROAS
                try:
                    strategy_rn = _get_or_create_portfolio_troas(
                        client,
                        customer_id,
                        plan.target_roas or 5.0,
                        seller_name=plan.label_0_value,
                    )
                    camp_svc = client.get_service("CampaignService")
                    op = client.get_type("CampaignOperation")
                    camp = op.update
                    camp.resource_name = campaign_rn
                    camp.bidding_strategy = strategy_rn
                    fm = field_mask_pb2.FieldMask(paths=["bidding_strategy"])
                    op.update_mask.CopyFrom(fm)
                    _retry(lambda: camp_svc.mutate_campaigns(customer_id=customer_id, operations=[op]))
                except Exception as e:
                    print(f"  [WARN] Kon niet naar portfolio tROAS switchen: {e}")
                
                created_campaigns.append({
                    'name': plan.name,
                    'campaign_rn': campaign_rn,
                    'ad_group_rn': ad_group_rn,
                    'label_0': plan.label_0_value,
                    'label_4': plan.label_4_value,
                    'label_2': plan.label_2_value,
                    'target_roas': plan.target_roas
                })
                
                print(f"  [OK] Campagne aangemaakt: {campaign_rn}")
                print(f"  [OK] Ad Group aangemaakt: {ad_group_rn}")
                
            except Exception as e:
                print(f"  [ERROR] Fout bij aanmaken campagne: {e}")
                continue
        
        print(f"\n[OK] Klaar! {len(created_campaigns)} van {len(plans_to_use)} campagnes succesvol aangemaakt.")
        
        if created_campaigns:
            print("\nAangemaakte campagnes:")
            for campaign in created_campaigns:
                print(f"  - {campaign['name']}")
                print(f"    Campaign: {campaign['campaign_rn']}")
                print(f"    Ad Group: {campaign['ad_group_rn']}")
                print(f"    Labels: {campaign['label_0']} + {campaign['label_4']} + {campaign['label_2']}")
                if campaign['target_roas']:
                    print(f"    tROAS: {campaign['target_roas']}")
                print()
    else:
        print("\nApply=false -> Dry run voltooid. Gebruik --apply true om campagnes aan te maken.")


if __name__ == "__main__":
    main()

