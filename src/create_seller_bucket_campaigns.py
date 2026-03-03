"""Create feed-only PMax campaigns per seller (custom label 0), config type (custom label 4),
and price bucket (custom label 2).

This script discovers all seller-bucket-config combinations from shopping performance data
and creates feed-only PMax campaigns with dynamic tROAS based on seller margins.
Also creates a catch-all campaign with low priority for remaining products.

Usage:
  py src/create_seller_bucket_campaigns.py --customer 5059126003
  py src/create_seller_bucket_campaigns.py --customer 5059126003 --merchant-id 5561429284 --apply

Notes:
- Creates feed-only PMax campaigns per seller-bucket-config combination
- Uses custom label 0 for sellers, custom label 2 for price buckets, custom label 4 for config types
- tROAS is calculated dynamically from custom label 1 (margin percentages, highest impressions wins)
- Campaigns are named: "SELLER - CONFIG_TYPE - PRICE_BUCKET"
- Specific campaigns get targeted listing group filters
- Catch-all campaign gets high tROAS (7.5) and higher budget (€50)
- Requires Merchant Center ID for feed-only campaigns
"""

from __future__ import annotations

import argparse
import re
import time
import random
from pathlib import Path
from typing import Dict, List, Set, Optional

from dotenv import load_dotenv
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from google.api_core import exceptions as gax

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
                if ec.database_error == "CONCURRENT_MODIFICATION":
                    return True, "CONCURRENT_MODIFICATION"
            if hasattr(ec, "quota_error"):
                if ec.quota_error == "RESOURCE_EXHAUSTED":
                    return True, "RESOURCE_EXHAUSTED"
            if hasattr(ec, "request_error"):
                if ec.request_error == "INVALID_ARGUMENT":
                    return True, "INVALID_ARGUMENT"
            if hasattr(ec, "internal_error"):
                if ec.internal_error == "INTERNAL_ERROR":
                    return True, "INTERNAL_ERROR"
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


def _get_geo_target_constant(client: GoogleAdsClient, customer_id: str, country_code: str) -> Optional[str]:
    """Lookup geo target constant ID for a 2-letter country code using GAQL (v21)."""
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
    try:
        for row in ga.search(customer_id=customer_id, query=query):
            if row.geo_target_constant.country_code == cc and row.geo_target_constant.target_type == "Country":
                gid = str(row.geo_target_constant.id)
                print(f"  [VERIFY] {cc} -> {row.geo_target_constant.name} (ID: {gid})")
                return gid
    except Exception as e:
        print(f"    [ERROR] Could not query geo target for {cc}: {e}")
    print(f"    Warning: No country-level geo target for code {cc}")
    return None


def _get_language_constant(client: GoogleAdsClient, customer_id: str, language_code: str) -> Optional[str]:
    """Lookup language constant ID by ISO code using GAQL (v21)."""
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
    try:
        for row in ga.search(customer_id=customer_id, query=query):
            lid = str(row.language_constant.id)
            print(f"  [VERIFY] lang {code} -> {row.language_constant.name} (ID: {lid})")
            return lid
    except Exception as e:
        print(f"    [ERROR] Could not query language for '{code}': {e}")
    print(f"    Warning: Could not find language for code '{code}'")
    return None


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
        except Exception as e:
            print(f"  [ERROR] Failed to add campaign criteria: {e}")


def discover_seller_bucket_combinations(client: GoogleAdsClient, customer_id: str) -> Dict[str, Dict[str, Set[str]]]:
    """Discover all seller-bucket-config combinations from shopping performance data."""
    ga = client.get_service("GoogleAdsService")
    
    complete_query = """
        SELECT
            segments.product_custom_attribute0,
            segments.product_custom_attribute2,
            segments.product_custom_attribute4,
            metrics.impressions
        FROM shopping_performance_view
        WHERE segments.date DURING LAST_30_DAYS
        AND segments.product_custom_attribute0 IS NOT NULL
        AND segments.product_custom_attribute2 IS NOT NULL
        AND segments.product_custom_attribute4 IS NOT NULL
        """
    
    seller_only_query = """
        SELECT
            segments.product_custom_attribute0,
            metrics.impressions
        FROM shopping_performance_view
        WHERE segments.date DURING LAST_30_DAYS
        AND segments.product_custom_attribute0 IS NOT NULL
        """
    
    seller_bucket_configs = {}
    
    try:
        for row in ga.search(customer_id=customer_id, query=complete_query):
            seller = row.segments.product_custom_attribute0 or ""
            bucket = row.segments.product_custom_attribute2 or ""
            config_type = row.segments.product_custom_attribute4 or ""
            
            if not seller or not bucket or not config_type:
                continue
                
            if seller not in seller_bucket_configs:
                seller_bucket_configs[seller] = {}
            
            if bucket not in seller_bucket_configs[seller]:
                seller_bucket_configs[seller][bucket] = set()
            
            seller_bucket_configs[seller][bucket].add(config_type)
            
        for row in ga.search(customer_id=customer_id, query=seller_only_query):
            seller = row.segments.product_custom_attribute0 or ""
            if not seller:
                continue
            if seller not in seller_bucket_configs:
                seller_bucket_configs[seller] = {"catch-all": {"normal"}}
            
    except GoogleAdsException as ex:
        print(f"Google Ads API error: {ex}")
        return {}
    
    return seller_bucket_configs


def create_seller_bucket_campaigns(
    client: GoogleAdsClient,
    customer_id: str,
    seller_bucket_configs: Dict[str, Dict[str, Set[str]]],
    apply: bool = False,
    merchant_id: str = "5561429284",
    target_languages: str = None,
    target_countries: str = None,
    daily_budget: float = 25.0,
    roas_factor: float = None,
    start_enabled: bool = False,
    feed_label: str = None,
) -> Dict[str, List[str]]:
    """Create feed-only PMax campaigns per seller-bucket-config combination."""
    results = {}
    
    print("\nDiscovering seller margins for dynamic tROAS calculation...")
    seller_to_margin = _discover_seller_to_margin(client, customer_id)
    print(f"Found margins for {len(seller_to_margin)} sellers")
    
    for seller, bucket_configs in seller_bucket_configs.items():
        print(f"\nProcessing seller: {seller}")
        print(f"Price buckets: {', '.join(bucket_configs.keys())}")
        
        # Calculate dynamic wait time based on seller complexity
        total_configs = sum(len(config_types) for config_types in bucket_configs.values())
        wait_time = min(5, max(1, total_configs * 0.5))  # 0.5s per config, max 5s
        
        # Add delay between sellers to reduce concurrent modification
        if seller != list(seller_bucket_configs.keys())[0]:  # Skip delay for first seller
            print(f"    [WAIT] Waiting {wait_time:.1f}s between sellers (complexity: {total_configs} configs)...")
            time.sleep(wait_time)
        
        seller_campaigns = []
        
        for bucket, config_types in bucket_configs.items():
            print(f"\n  Creating campaigns for bucket: {bucket}")
            print(f"  Config types: {', '.join(config_types)}")
            
            if bucket == "catch-all":
                campaign_name = f"{seller} - Catch-All"
                if apply:
                    try:
                        campaign_id = _create_seller_catch_all_campaign(
                            client,
                            customer_id,
                            campaign_name,
                            seller,
                            seller_to_margin,
                            merchant_id,
                            target_languages,
                            target_countries,
                            daily_budget,
                            roas_factor,
                            start_enabled,
                            feed_label,
                        )
                        if campaign_id:
                            print(f"    [OK] Created: {campaign_name} (ID: {campaign_id})")
                            seller_campaigns.append(campaign_name)
                        else:
                            print(f"    [SKIP] Skipped: {campaign_name}")
                    except Exception as e:
                        print(f"    [FAIL] Failed: {campaign_name} - {e}")
                else:
                    margin = seller_to_margin.get(seller, "15%")
                    target_roas = _parse_percent_to_troas(margin)
                    print(f"    [DRY RUN] Would create: {campaign_name} (margin: {margin} -> tROAS: {target_roas})")
                    seller_campaigns.append(campaign_name)

            else:
                for config_type in config_types:
                    campaign_name = f"{seller} - {config_type} - {bucket}"
                    if apply:
                        try:
                            campaign_id = _create_feed_only_pmax_campaign(
                                client,
                                customer_id,
                                campaign_name,
                                seller,
                                seller_to_margin,
                                config_type,
                                bucket,
                                merchant_id,
                                target_languages,
                                target_countries,
                                daily_budget,
                                roas_factor,
                                start_enabled,
                                feed_label,
                            )
                            if campaign_id:
                                print(f"    [OK] Created: {campaign_name} (ID: {campaign_id})")
                                seller_campaigns.append(campaign_name)
                            else:
                                print(f"    [SKIP] Skipped: {campaign_name}")
                        except Exception as e:
                            print(f"    [FAIL] Failed: {campaign_name} - {e}")
                    else:
                        margin = seller_to_margin.get(seller, "15%")
                        target_roas = _parse_percent_to_troas(margin)
                        print(f"    [DRY RUN] Would create: {campaign_name} (margin: {margin} -> tROAS: {target_roas})")
                        seller_campaigns.append(campaign_name)
        
        results[seller] = seller_campaigns
    
    return results


def _discover_seller_to_margin(client: GoogleAdsClient, customer_id: str) -> Dict[str, str]:
    """Discover seller (custom_label_0) to margin percentage (custom_label_1) mapping."""
    ga = client.get_service("GoogleAdsService")
    query = """
        SELECT 
            segments.product_custom_attribute0,
            segments.product_custom_attribute1,
            metrics.impressions
        FROM shopping_performance_view
        WHERE segments.date DURING LAST_30_DAYS
        AND segments.product_custom_attribute0 IS NOT NULL
        AND segments.product_custom_attribute1 IS NOT NULL
    """
    
    agg: Dict[str, Dict[str, int]] = {}
    for row in ga.search(customer_id=customer_id, query=query):
        seller = row.segments.product_custom_attribute0 or ""
        margin = row.segments.product_custom_attribute1 or ""
        if not seller:
            continue
        agg.setdefault(seller, {})
        agg[seller][margin] = agg[seller].get(margin, 0) + int(row.metrics.impressions)
    
    result: Dict[str, str] = {}
    for seller, counter in agg.items():
        if counter:
            best_margin = max(counter.items(), key=lambda kv: kv[1])[0]
            result[seller] = best_margin
    
    return result


def _create_budget(client: GoogleAdsClient, customer_id: str, name: str, amount_micros: int) -> str:
    """Create a campaign budget."""
    svc = client.get_service("CampaignBudgetService")
    op = client.get_type("CampaignBudgetOperation")
    bud = op.create
    bud.name = name
    bud.amount_micros = amount_micros
    bud.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD
    bud.explicitly_shared = False
    rn = svc.mutate_campaign_budgets(customer_id=customer_id, operations=[op]).results[0].resource_name
    return rn


def _parse_percent_to_troas(percent_str: str) -> float:
    """Convert margin percentage string to tROAS value."""
    if not percent_str:
        return 6.5
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", percent_str)
    if not m:
        return 6.5
    try:
        pct = float(m.group(1))
        if pct <= 0:
            return 6.5
        return round(1.0 / (pct / 100.0), 2)
    except Exception:
        return 6.5



def _create_feed_only_pmax_campaign(client: GoogleAdsClient, customer_id: str, campaign_name: str, 
                                   seller: str, seller_to_margin: Dict[str, str], 
                                   config_type: str, price_bucket: str,
                                    merchant_id: str = "389429754",
                                    target_languages: str = None, target_countries: str = None,
                                    daily_budget: float = 25.0, roas_factor: float = None, start_enabled: bool = False, feed_label: str = None) -> str:
    """Create a feed-only PMax campaign with listing groups."""
    svc = client.get_service("CampaignService")
    
    # Calculate tROAS from seller margin
    margin = seller_to_margin.get(seller, "15%")
    target_roas = _parse_percent_to_troas(margin)
    
    # Apply ROAS factor as percentage (e.g., +10% or -10%)
    if roas_factor and roas_factor != 0:
        original = target_roas
        target_roas = round(target_roas * (1 + roas_factor / 100), 2)
        print(f"    Adjusted tROAS: {original} {roas_factor:+.1f}% = {target_roas}")
    
    # Create budget
    budget_rn = _create_budget(client, customer_id, f"{campaign_name} Budget", int(daily_budget * 1_000_000))
    
    # Create campaign (Performance Max - Feed Only)
    camp_op = client.get_type("CampaignOperation")
    camp = camp_op.create
    camp.name = campaign_name
    camp.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.PERFORMANCE_MAX
    camp.shopping_setting.merchant_id = merchant_id
    
    # Set feed_label for the shopping setting (replaces sales_country)
    if feed_label:
        camp.shopping_setting.feed_label = feed_label
        print(f"    Shopping Setting: feed_label={feed_label}")
    elif target_countries:
        countries = [c.strip().upper() for c in target_countries.split(',')]
        if countries:
            camp.shopping_setting.feed_label = countries[0]  # Use first country as feed_label
            print(f"    Shopping Setting: feed_label={countries[0]}")
    else:
        # Default to 'NL' if no feed_label or target_countries provided
        camp.shopping_setting.feed_label = "NL"
        print(f"    Shopping Setting: feed_label=NL (default)")
    
    # Set campaign status
    camp.status = client.enums.CampaignStatusEnum.ENABLED if start_enabled else client.enums.CampaignStatusEnum.PAUSED
    
    # EU political flag - set to false (no EU political advertising)
    try:
        camp.contains_eu_political_advertising = client.enums.EuPoliticalAdvertisingStatusEnum.DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING
    except Exception:
        try:
            # Fallback to boolean
            camp.contains_eu_political_advertising = False
        except Exception:
            pass
    
    # Set bidding strategy - MaximizeConversionValue with optional tROAS
    if target_roas is not None:
        camp.maximize_conversion_value.target_roas = float(target_roas)
    else:
        # Default to MaximizeConversionValue without tROAS (no additional settings needed)
        pass
    
    # Set campaign budget
    camp.campaign_budget = budget_rn
    
    camp_resp = _retry(lambda: svc.mutate_campaigns(customer_id=customer_id, operations=[camp_op]))
    campaign_rn = camp_resp.results[0].resource_name
    campaign_id = campaign_rn.split('/')[-1]
    
    # Wait for campaign to be ready before creating asset groups
    print(f"    [WAIT] Waiting 3 seconds for campaign to be ready...")
    time.sleep(3)
    
    # Create minimal asset group, then listing groups for feed-only PMax
    try:
        ag_rn = _retry(lambda: _create_feed_only_asset_group(
            client,
            customer_id,
            campaign_id,
            asset_group_name=f"{campaign_name} - Asset Group",
            start_enabled=start_enabled,
        ))
        # Dynamic wait time based on campaign complexity
        wait_time = 3.0  # Base wait time
        print(f"    [WAIT] Waiting {wait_time:.1f}s before creating listing groups...")
        time.sleep(wait_time)
        
        _retry(
            lambda: _create_listing_groups_for_seller_bucket(client, customer_id, campaign_id, seller, config_type, price_bucket),
            attempts=3,
            first_sleep=2.0,
            base=2.5,
            context=f"listing groups for {campaign_name}"
        )
        print(f"    [OK] Asset group and listing groups created for {campaign_name}")
    except Exception as e:
        print(f"    [WARN] Campaign created but failed to add asset group/listing groups: {e}")
        # Log specific failure for manual review
        print(f"    [MANUAL_REVIEW] Campaign {campaign_name} needs manual listing group setup")
    
    # Add campaign criteria for geo + language targeting
    if target_countries or target_languages:
        print(f"    [WAIT] Waiting 2 seconds before adding campaign criteria...")
        time.sleep(2)
        campaign_rn = f"customers/{customer_id}/campaigns/{campaign_id}"
        _retry(lambda: _add_campaign_criteria(client, customer_id, campaign_rn, target_countries, target_languages))
    
    return campaign_id


def _create_seller_catch_all_campaign(client: GoogleAdsClient, customer_id: str, campaign_name: str, 
                                     seller: str, seller_to_margin: Dict[str, str], merchant_id: str = "5561429284",
                                     target_languages: str = None, target_countries: str = None,
                                     daily_budget: float = 25.0, roas_factor: float = None, start_enabled: bool = False, feed_label: str = None) -> str:
    """Create a seller-specific catch-all campaign."""
    svc = client.get_service("CampaignService")
    
    # Calculate tROAS from seller margin
    margin = seller_to_margin.get(seller, "15%")
    target_roas = _parse_percent_to_troas(margin)
    
    # Apply ROAS factor as percentage (e.g., +10% or -10%)
    if roas_factor and roas_factor != 0:
        original = target_roas
        target_roas = round(target_roas * (1 + roas_factor / 100), 2)
        print(f"    Adjusted tROAS: {original} {roas_factor:+.1f}% = {target_roas}")
    
    # Create budget
    budget_rn = _create_budget(client, customer_id, f"{campaign_name} Budget", int(daily_budget * 1_000_000))
    
    # Create campaign (Performance Max - Feed Only)
    camp_op = client.get_type("CampaignOperation")
    camp = camp_op.create
    camp.name = campaign_name
    camp.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.PERFORMANCE_MAX
    camp.shopping_setting.merchant_id = merchant_id
    
    # Set feed_label for the shopping setting (replaces sales_country)
    if feed_label:
        camp.shopping_setting.feed_label = feed_label
        print(f"    Shopping Setting: feed_label={feed_label}")
    elif target_countries:
        countries = [c.strip().upper() for c in target_countries.split(',')]
        if countries:
            camp.shopping_setting.feed_label = countries[0]  # Use first country as feed_label
            print(f"    Shopping Setting: feed_label={countries[0]}")
    else:
        # Default to 'NL' if no feed_label or target_countries provided
        camp.shopping_setting.feed_label = "NL"
        print(f"    Shopping Setting: feed_label=NL (default)")
    
    # Set campaign status
    camp.status = client.enums.CampaignStatusEnum.ENABLED if start_enabled else client.enums.CampaignStatusEnum.PAUSED
    
    # EU political flag - set to false (no EU political advertising)
    try:
        camp.contains_eu_political_advertising = client.enums.EuPoliticalAdvertisingStatusEnum.DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING
    except Exception:
        try:
            # Fallback to boolean
            camp.contains_eu_political_advertising = False
        except Exception:
            pass
    
    # Set bidding strategy - MaximizeConversionValue with optional tROAS
    if target_roas is not None:
        camp.maximize_conversion_value.target_roas = float(target_roas)
    else:
        # Default to MaximizeConversionValue without tROAS (no additional settings needed)
        pass
    
    # Set campaign budget
    camp.campaign_budget = budget_rn
    
    camp_resp = _retry(lambda: svc.mutate_campaigns(customer_id=customer_id, operations=[camp_op]))
    campaign_rn = camp_resp.results[0].resource_name
    campaign_id = campaign_rn.split('/')[-1]
    
    # Wait for campaign to be ready before creating asset groups
    print(f"    [WAIT] Waiting 3 seconds for campaign to be ready...")
    time.sleep(3)
    
    # Create asset group and listing groups for seller catch-all
    try:
        _ = _retry(lambda: _create_feed_only_asset_group(
            client,
            customer_id,
            campaign_id,
            asset_group_name=f"{campaign_name} - Asset Group",
            start_enabled=start_enabled,
        ))
        # Dynamic wait time based on campaign complexity
        wait_time = 3.0  # Base wait time
        print(f"    [WAIT] Waiting {wait_time:.1f}s before creating listing groups...")
        time.sleep(wait_time)
        
        _retry(
            lambda: _create_listing_groups_for_seller_catch_all(client, customer_id, campaign_id, seller),
            attempts=3,
            first_sleep=2.0,
            base=2.5,
            context=f"listing groups for {campaign_name}"
        )
        print(f"    [OK] Asset group and listing groups created for {campaign_name}")
    except Exception as e:
        print(f"    [WARN] Campaign created but failed to add asset group/listing groups: {e}")
        # Log specific failure for manual review
        print(f"    [MANUAL_REVIEW] Campaign {campaign_name} needs manual listing group setup")
    
    # Add campaign criteria for geo + language targeting
    if target_countries or target_languages:
        print(f"    [WAIT] Waiting 2 seconds before adding campaign criteria...")
        time.sleep(2)
        campaign_rn = f"customers/{customer_id}/campaigns/{campaign_id}"
        _retry(lambda: _add_campaign_criteria(client, customer_id, campaign_rn, target_countries, target_languages))
    
    return campaign_id


def _create_catch_all_campaign(client: GoogleAdsClient, customer_id: str, merchant_id: str = "5561429284", 
                              target_languages: str = None, target_countries: str = None,
                              daily_budget: float = 50.0, roas_factor: float = None, start_enabled: bool = False, feed_label: str = None) -> str:
    """Create a catch-all campaign for remaining products."""
    svc = client.get_service("CampaignService")
    
    # Calculate tROAS for catch-all campaign (default high tROAS)
    target_roas = 7.5  # Default high tROAS for catch-all
    
    # Apply ROAS factor as percentage (e.g., +10% or -10%)
    if roas_factor and roas_factor != 0:
        original = target_roas
        target_roas = round(target_roas * (1 + roas_factor / 100), 2)
        print(f"    Adjusted tROAS: {original} {roas_factor:+.1f}% = {target_roas}")
    
    # Create budget
    budget_rn = _create_budget(client, customer_id, "CATCH-ALL - Low Priority Budget", int(daily_budget * 1_000_000))
    
    # Create campaign (Performance Max - Feed Only)
    camp_op = client.get_type("CampaignOperation")
    camp = camp_op.create
    camp.name = "CATCH-ALL - Low Priority"
    camp.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.PERFORMANCE_MAX
    camp.shopping_setting.merchant_id = merchant_id
    
    # Set feed_label for the shopping setting (replaces sales_country)
    if feed_label:
        camp.shopping_setting.feed_label = feed_label
        print(f"    Shopping Setting: feed_label={feed_label}")
    elif target_countries:
        countries = [c.strip().upper() for c in target_countries.split(',')]
        if countries:
            camp.shopping_setting.feed_label = countries[0]  # Use first country as feed_label
            print(f"    Shopping Setting: feed_label={countries[0]}")
    else:
        # Default to 'NL' if no feed_label or target_countries provided
        camp.shopping_setting.feed_label = "NL"
        print(f"    Shopping Setting: feed_label=NL (default)")
    
    # Set campaign status
    camp.status = client.enums.CampaignStatusEnum.ENABLED if start_enabled else client.enums.CampaignStatusEnum.PAUSED
    
    # EU political flag - set to false (no EU political advertising)
    try:
        camp.contains_eu_political_advertising = client.enums.EuPoliticalAdvertisingStatusEnum.DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING
    except Exception:
        try:
            # Fallback to boolean
            camp.contains_eu_political_advertising = False
        except Exception:
            pass
    
    # Set bidding strategy - MaximizeConversionValue with optional tROAS
    camp.bidding_strategy_type = client.enums.BiddingStrategyTypeEnum.MAXIMIZE_CONVERSION_VALUE
    if target_roas is not None:
        camp.maximize_conversion_value.target_roas = float(target_roas)
    
    # Set campaign budget
    camp.campaign_budget = budget_rn
    
    camp_resp = _retry(lambda: svc.mutate_campaigns(customer_id=customer_id, operations=[camp_op]))
    campaign_rn = camp_resp.results[0].resource_name
    campaign_id = campaign_rn.split('/')[-1]
    
    # Wait for campaign to be ready before creating asset groups
    print(f"    [WAIT] Waiting 3 seconds for campaign to be ready...")
    time.sleep(3)
    
    # Create asset group and listing groups for catch-all
    try:
        _ = _retry(lambda: _create_feed_only_asset_group(
            client,
            customer_id,
            campaign_id,
            asset_group_name="CATCH-ALL - Asset Group",
            start_enabled=start_enabled,
        ))
        # Dynamic wait time based on campaign complexity
        wait_time = 3.0  # Base wait time
        print(f"    [WAIT] Waiting {wait_time:.1f}s before creating listing groups...")
        time.sleep(wait_time)
        
        _retry(
            lambda: _create_listing_groups_for_catch_all(client, customer_id, campaign_id),
            attempts=3,
            first_sleep=2.0,
            base=2.5,
            context="listing groups for CATCH-ALL"
        )
        print(f"    [OK] Asset group and listing groups created for CATCH-ALL")
    except Exception as e:
        print(f"    [WARN] Campaign created but failed to add asset group/listing groups: {e}")
        # Log specific failure for manual review
        print(f"    [MANUAL_REVIEW] Campaign CATCH-ALL needs manual listing group setup")
    
    # Add campaign criteria for geo + language targeting
    if target_countries or target_languages:
        print(f"    [WAIT] Waiting 2 seconds before adding campaign criteria...")
        time.sleep(2)
        campaign_rn = f"customers/{customer_id}/campaigns/{campaign_id}"
        _retry(lambda: _add_campaign_criteria(client, customer_id, campaign_rn, target_countries, target_languages))
    
    return campaign_id


def _create_listing_groups_for_seller_bucket(client: GoogleAdsClient, customer_id: str, campaign_id: str, 
                                           seller: str, config_type: str, price_bucket: str):
    """Create 3-level listing groups for seller-bucket campaigns: custom_label_0 -> custom_label_4 -> custom_label_2."""
    gas = client.get_service("GoogleAdsService")
    enums = client.enums
    
    # Find asset group for this campaign
    asset_group_rn = _find_asset_group_for_campaign(client, customer_id, campaign_id)
    if not asset_group_rn:
        raise Exception("No asset group found for campaign")
    
    asset_group_id = asset_group_rn.split("/")[-1]
    path = gas.asset_group_listing_group_filter_path
    
    # Level 1: ROOT (SUBDIVISION) - no case_value
    op_root = client.get_type("MutateOperation")
    root = op_root.asset_group_listing_group_filter_operation.create
    root.resource_name = path(customer_id, asset_group_id, "-1")
    root.asset_group = asset_group_rn
    root.type_ = enums.ListingGroupFilterTypeEnum.SUBDIVISION
    root.listing_source = enums.ListingGroupFilterListingSourceEnum.SHOPPING
    
    # Level 2: SELLER (custom_label_0) - SUBDIVISION on seller value we want to drill into
    dim_seller = client.get_type("ListingGroupFilterDimension")
    dim_seller.product_custom_attribute.index = enums.ListingGroupFilterCustomAttributeIndexEnum.INDEX0
    dim_seller.product_custom_attribute.value = seller
    
    op_seller = client.get_type("MutateOperation")
    seller_node = op_seller.asset_group_listing_group_filter_operation.create
    seller_node.resource_name = path(customer_id, asset_group_id, "-2")
    seller_node.asset_group = asset_group_rn
    seller_node.parent_listing_group_filter = root.resource_name
    seller_node.type_ = enums.ListingGroupFilterTypeEnum.SUBDIVISION
    seller_node.listing_source = enums.ListingGroupFilterListingSourceEnum.SHOPPING
    seller_node.case_value = dim_seller
    
    # Level 3: CONFIG TYPE (custom_label_4) - SUBDIVISION under seller (specific value)
    dim_config = client.get_type("ListingGroupFilterDimension")
    dim_config.product_custom_attribute.index = enums.ListingGroupFilterCustomAttributeIndexEnum.INDEX4
    dim_config.product_custom_attribute.value = config_type

    op_config = client.get_type("MutateOperation")
    config_node = op_config.asset_group_listing_group_filter_operation.create
    config_node.resource_name = path(customer_id, asset_group_id, "-3")
    config_node.asset_group = asset_group_rn
    config_node.parent_listing_group_filter = seller_node.resource_name
    config_node.type_ = enums.ListingGroupFilterTypeEnum.SUBDIVISION
    config_node.listing_source = enums.ListingGroupFilterListingSourceEnum.SHOPPING
    config_node.case_value = dim_config

    # Level 4: PRICE BUCKET (custom_label_2) - INCLUDED under config subdivision
    dim_bucket = client.get_type("ListingGroupFilterDimension")
    dim_bucket.product_custom_attribute.index = enums.ListingGroupFilterCustomAttributeIndexEnum.INDEX2
    dim_bucket.product_custom_attribute.value = price_bucket
    
    op_bucket = client.get_type("MutateOperation")
    bucket_node = op_bucket.asset_group_listing_group_filter_operation.create
    bucket_node.resource_name = path(customer_id, asset_group_id, "-4")
    bucket_node.asset_group = asset_group_rn
    bucket_node.parent_listing_group_filter = config_node.resource_name
    bucket_node.type_ = enums.ListingGroupFilterTypeEnum.UNIT_INCLUDED
    bucket_node.listing_source = enums.ListingGroupFilterListingSourceEnum.SHOPPING
    bucket_node.case_value = dim_bucket
    
    # EVERYTHING ELSE nodes for each SUBDIVISION level
    # Everything else for seller level (sibling of seller_node under root)
    dim_seller_else = client.get_type("ListingGroupFilterDimension")
    dim_seller_else.product_custom_attribute.index = enums.ListingGroupFilterCustomAttributeIndexEnum.INDEX0
    dim_seller_else.product_custom_attribute._pb.SetInParent()
    
    op_seller_else = client.get_type("MutateOperation")
    seller_else = op_seller_else.asset_group_listing_group_filter_operation.create
    seller_else.resource_name = path(customer_id, asset_group_id, "-7")
    seller_else.asset_group = asset_group_rn
    seller_else.parent_listing_group_filter = root.resource_name
    seller_else.type_ = enums.ListingGroupFilterTypeEnum.UNIT_EXCLUDED
    seller_else.listing_source = enums.ListingGroupFilterListingSourceEnum.SHOPPING
    seller_else.case_value = dim_seller_else
    
    # Everything else for config level (sibling of config_node under seller_node)
    dim_config_else = client.get_type("ListingGroupFilterDimension")
    dim_config_else.product_custom_attribute.index = enums.ListingGroupFilterCustomAttributeIndexEnum.INDEX4
    dim_config_else.product_custom_attribute._pb.SetInParent()
    
    op_config_else = client.get_type("MutateOperation")
    config_else = op_config_else.asset_group_listing_group_filter_operation.create
    config_else.resource_name = path(customer_id, asset_group_id, "-5")
    config_else.asset_group = asset_group_rn
    config_else.parent_listing_group_filter = seller_node.resource_name
    config_else.type_ = enums.ListingGroupFilterTypeEnum.UNIT_EXCLUDED
    config_else.listing_source = enums.ListingGroupFilterListingSourceEnum.SHOPPING
    config_else.case_value = dim_config_else
    
    # Everything else for bucket level (sibling of bucket_node under config_node)
    dim_bucket_else = client.get_type("ListingGroupFilterDimension")
    dim_bucket_else.product_custom_attribute.index = enums.ListingGroupFilterCustomAttributeIndexEnum.INDEX2
    dim_bucket_else.product_custom_attribute._pb.SetInParent()
    
    op_bucket_else = client.get_type("MutateOperation")
    bucket_else = op_bucket_else.asset_group_listing_group_filter_operation.create
    bucket_else.resource_name = path(customer_id, asset_group_id, "-6")
    bucket_else.asset_group = asset_group_rn
    bucket_else.parent_listing_group_filter = config_node.resource_name
    bucket_else.type_ = enums.ListingGroupFilterTypeEnum.UNIT_EXCLUDED
    bucket_else.listing_source = enums.ListingGroupFilterListingSourceEnum.SHOPPING
    bucket_else.case_value = dim_bucket_else
    
    # Apply all operations
    operations = [
        op_root, op_seller, op_config, op_bucket,
        op_seller_else, op_config_else, op_bucket_else
    ]
    
    try:
        _retry(
            lambda: gas.mutate(customer_id=customer_id, mutate_operations=operations),
            attempts=3,
            first_sleep=2.0,
            base=2.5,
            context=f"listing groups for seller={seller} config={config_type} bucket={price_bucket}"
        )
        print(f"    [OK] Listing groups: custom_label_0='{seller}' -> custom_label_4='{config_type}' -> custom_label_2='{price_bucket}'")
    except Exception as e:
        print(f"    [FATAL] Listing group skipped: seller={seller} bucket={price_bucket} type={config_type} - {e}")
        raise


def _create_listing_groups_for_seller_catch_all(client: GoogleAdsClient, customer_id: str, campaign_id: str, seller: str):
    """Create listing groups for seller catch-all campaigns (only seller filter)."""
    gas = client.get_service("GoogleAdsService")
    enums = client.enums
    
    # Find asset group for this campaign
    asset_group_rn = _find_asset_group_for_campaign(client, customer_id, campaign_id)
    if not asset_group_rn:
        raise Exception("No asset group found for campaign")
    
    asset_group_id = asset_group_rn.split("/")[-1]
    path = gas.asset_group_listing_group_filter_path
    
    # ROOT (SUBDIVISION)
    op_root = client.get_type("MutateOperation")
    root = op_root.asset_group_listing_group_filter_operation.create
    root.resource_name = path(customer_id, asset_group_id, "-1")
    root.asset_group = asset_group_rn
    root.type_ = enums.ListingGroupFilterTypeEnum.SUBDIVISION
    root.listing_source = enums.ListingGroupFilterListingSourceEnum.SHOPPING
    
    # SELLER (custom_label_0) - INCLUDED
    dim_seller = client.get_type("ListingGroupFilterDimension")
    dim_seller.product_custom_attribute.index = enums.ListingGroupFilterCustomAttributeIndexEnum.INDEX0
    dim_seller.product_custom_attribute.value = seller
    
    op_seller = client.get_type("MutateOperation")
    seller_node = op_seller.asset_group_listing_group_filter_operation.create
    seller_node.resource_name = path(customer_id, asset_group_id, "-2")
    seller_node.asset_group = asset_group_rn
    seller_node.parent_listing_group_filter = root.resource_name
    seller_node.type_ = enums.ListingGroupFilterTypeEnum.UNIT_INCLUDED
    seller_node.listing_source = enums.ListingGroupFilterListingSourceEnum.SHOPPING
    seller_node.case_value = dim_seller
    
    # EVERYTHING ELSE for seller level
    dim_seller_else = client.get_type("ListingGroupFilterDimension")
    dim_seller_else.product_custom_attribute.index = enums.ListingGroupFilterCustomAttributeIndexEnum.INDEX0
    dim_seller_else.product_custom_attribute._pb.SetInParent()
    
    op_seller_else = client.get_type("MutateOperation")
    seller_else = op_seller_else.asset_group_listing_group_filter_operation.create
    seller_else.resource_name = path(customer_id, asset_group_id, "-3")
    seller_else.asset_group = asset_group_rn
    seller_else.parent_listing_group_filter = root.resource_name
    seller_else.type_ = enums.ListingGroupFilterTypeEnum.UNIT_EXCLUDED
    seller_else.listing_source = enums.ListingGroupFilterListingSourceEnum.SHOPPING
    seller_else.case_value = dim_seller_else
    
    # Apply operations
    operations = [op_root, op_seller, op_seller_else]
    try:
        _retry(
            lambda: gas.mutate(customer_id=customer_id, mutate_operations=operations),
            attempts=3,
            first_sleep=2.0,
            base=2.5,
            context=f"listing groups for seller catch-all={seller}"
        )
        print(f"    [OK] Listing groups: custom_label_0='{seller}' (catch-all)")
    except Exception as e:
        print(f"    [FATAL] Listing group skipped: seller={seller} (catch-all) - {e}")
        raise


def _create_listing_groups_for_catch_all(client: GoogleAdsClient, customer_id: str, campaign_id: str):
    """Create listing groups for catch-all campaigns (no filters, all products)."""
    gas = client.get_service("GoogleAdsService")
    enums = client.enums
    
    # Find asset group for this campaign
    asset_group_rn = _find_asset_group_for_campaign(client, customer_id, campaign_id)
    if not asset_group_rn:
        raise Exception("No asset group found for campaign")
    
    asset_group_id = asset_group_rn.split("/")[-1]
    path = gas.asset_group_listing_group_filter_path
    
    # Create a single UNIT_INCLUDED node at root to include all products (no subdivisions needed)
    op_unit = client.get_type("MutateOperation")
    unit = op_unit.asset_group_listing_group_filter_operation.create
    unit.resource_name = path(customer_id, asset_group_id, "-1")
    unit.asset_group = asset_group_rn
    unit.type_ = enums.ListingGroupFilterTypeEnum.UNIT_INCLUDED
    unit.listing_source = enums.ListingGroupFilterListingSourceEnum.SHOPPING

    try:
        _retry(
            lambda: gas.mutate(customer_id=customer_id, mutate_operations=[op_unit]),
            attempts=3,
            first_sleep=2.0,
            base=2.5,
            context="listing groups for catch-all"
        )
        print(f"    [OK] Listing groups: catch-all (all products included)")
    except Exception as e:
        print(f"    [FATAL] Listing group skipped: catch-all - {e}")
        raise


def _create_feed_only_asset_group(
    client: GoogleAdsClient,
    customer_id: str,
    campaign_id: str,
    asset_group_name: str,
    start_enabled: bool,
) -> str:
    """Create a minimal feed-only PMax Asset Group for a campaign and return its resource name."""
    ag_svc = client.get_service("AssetGroupService")
    op = client.get_type("AssetGroupOperation")
    ag = op.create
    ag.name = asset_group_name
    ag.campaign = f"customers/{customer_id}/campaigns/{campaign_id}"
    ag.status = client.enums.AssetGroupStatusEnum.ENABLED if start_enabled else client.enums.AssetGroupStatusEnum.PAUSED
    # For feed-only, do not set final_urls; they'll come from Merchant Center
    resp = _retry(lambda: ag_svc.mutate_asset_groups(customer_id=customer_id, operations=[op]))
    ag_rn = resp.results[0].resource_name
    print(f"    [OK] Asset group created: {ag_rn}")
    return ag_rn

def _find_asset_group_for_campaign(client: GoogleAdsClient, customer_id: str, campaign_id: str) -> str:
    """Find the asset group for a campaign."""
    ga_service = client.get_service("GoogleAdsService")
    campaign_rn = f"customers/{customer_id}/campaigns/{campaign_id}"
    
    query = f"""
        SELECT 
            asset_group.resource_name,
            asset_group.name,
            asset_group.status
        FROM asset_group 
        WHERE asset_group.campaign = '{campaign_rn}'
        LIMIT 1
    """
    
    for row in ga_service.search(customer_id=customer_id, query=query):
        return row.asset_group.resource_name
    
    return None


def _create_pmax_asset_group(
    client: GoogleAdsClient,
    customer_id: str,
    campaign_rn: str,
    asset_group_name: str,
) -> str:
    """Create a PMax feed-only asset group."""
    ag_svc = client.get_service("AssetGroupService")
    
    ag_op = client.get_type("AssetGroupOperation")
    ag = ag_op.create
    ag.name = asset_group_name
    ag.campaign = campaign_rn
    ag.status = client.enums.AssetGroupStatusEnum.PAUSED
    
    # For feed-only PMax, we don't set any final URLs
    # The final URLs will be automatically set from the Merchant Center feed
    print(f"  Geen final URLs ingesteld - worden automatisch ingesteld vanuit Merchant Center feed")
    
    ag_resp = _retry(lambda: ag_svc.mutate_asset_groups(customer_id=customer_id, operations=[ag_op]))
    ag_rn = ag_resp.results[0].resource_name
    print(f"  [OK] Asset group created: {ag_rn}")
    
    return ag_rn


# ... rest of your helper functions (_check_campaign_exists, _create_feed_only_pmax_campaign, etc.)
# zijn ongewijzigd behalve de dubbele try/except voor contains_eu_political_advertising die nu netter zijn.

def main():
    parser = argparse.ArgumentParser(description="Create feed-only PMax campaigns per seller-bucket combination")
    parser.add_argument("--customer", required=True, help="Customer ID")
    parser.add_argument("--apply", action="store_true", help="Actually create campaigns (default: dry run)")
    parser.add_argument("--merchant-id", default="5561429284", help="Merchant Center ID for feed-only campaigns")
    parser.add_argument("--target-languages", help="Target languages (comma-separated)")
    parser.add_argument("--target-countries", help="Target countries (comma-separated)")
    parser.add_argument("--daily-budget", type=float, default=25.0, help="Daily budget in EUR (default: 25.0)")
    parser.add_argument("--roas-factor", type=float, help="Percentage to adjust calculated ROAS (e.g., +10 for 10% increase, -10 for 10% decrease)")
    parser.add_argument("--start-enabled", action="store_true", help="Start campaigns as ENABLED instead of PAUSED")
    parser.add_argument("--feed-label", help="Feed label for shopping campaigns (e.g., 'AT', 'DE', 'NL')")
    
    args = parser.parse_args()
    
    load_dotenv()
    
    try:
        client = GoogleAdsClient.load_from_storage(str(CONFIG_PATH))
    except Exception as e:
        print(f"Failed to load Google Ads client: {e}")
        return 1
    
    customer_id = ''.join(filter(str.isdigit, str(args.customer)))
    
    print(f"Creating seller-bucket campaigns for customer: {customer_id}")
    print(f"Apply mode: {'ON' if args.apply else 'DRY RUN'}")
    
    print("\nDiscovering seller-bucket-config combinations...")
    seller_bucket_configs = discover_seller_bucket_combinations(client, customer_id)
    
    if not seller_bucket_configs:
        print("No seller-bucket-config combinations found.")
        return 1
    
    print(f"Found {len(seller_bucket_configs)} sellers with price buckets and config types:")
    for seller, bucket_configs in seller_bucket_configs.items():
        print(f"  {seller}:")
        for bucket, config_types in bucket_configs.items():
            print(f"    {bucket}: {', '.join(config_types)}")
    
    print(f"\nCreating feed-only PMax campaigns...")
    results = create_seller_bucket_campaigns(
        client,
        customer_id,
        seller_bucket_configs,
        args.apply,
        args.merchant_id,
        args.target_languages,
        args.target_countries,
        args.daily_budget,
        args.roas_factor,
        args.start_enabled,
        args.feed_label,
    )

    print(f"\nCreating catch-all campaign...")
    if args.apply:
        try:
            catch_all_id = _create_catch_all_campaign(
                client,
                customer_id,
                args.merchant_id,
                args.target_languages,
                args.target_countries,
                args.daily_budget,
                args.roas_factor,
                args.start_enabled,
                args.feed_label,
            )
            if catch_all_id:
                print(f"[OK] Catch-all campaign created (ID: {catch_all_id})")
            else:
                print(f"[SKIP] Catch-all campaign already exists")
        except Exception as e:
            print(f"[FAIL] Failed to create catch-all campaign: {e}")
    else:
        print(f"[DRY RUN] Would create: CATCH-ALL - Low Priority (tROAS: 7.5, Budget: €50)")
    
    total_campaigns = sum(len(campaigns) for campaigns in results.values())
    catch_all_count = 1
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"Total sellers processed: {len(results)}")
    print(f"Specific campaigns {'created' if args.apply else 'would be created'}: {total_campaigns}")
    print(f"Catch-all campaign {'created' if args.apply else 'would be created'}: {catch_all_count}")
    print(f"Total campaigns {'created' if args.apply else 'would be created'}: {total_campaigns + catch_all_count}")
    
    for seller, campaigns in results.items():
        print(f"\n{seller}: {len(campaigns)} campaigns")
        for campaign in campaigns:
            print(f"  - {campaign}")
    
    return 0


if __name__ == "__main__":
    exit(main())
