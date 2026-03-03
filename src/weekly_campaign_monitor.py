#!/usr/bin/env python3
"""
Weekly Campaign Monitor for Google Ads PMax Campaigns

This script:
1. Checks existing campaigns for performance
2. Discovers new labels that don't have campaigns yet
3. Identifies empty campaigns (no impressions/conversions)
4. Automatically creates new campaigns for new labels
5. Optionally pauses empty campaigns

Usage:
    python weekly_campaign_monitor.py --customer 1234567890 --label-index 0 --prefix "PMax Feed"
"""

import os
import sys
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import time

# Add the src directory to Python path
sys.path.append(str(Path(__file__).parent))

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

# Import functions from label_campaigns.py
from label_campaigns import (
    discover_labels, 
    _create_pmax_campaign, 
    _create_pmax_asset_group,
    add_listing_group_for_label,
    _add_campaign_criteria,
    _digits_only
)

def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Weekly Campaign Monitor for PMax and Shopping Campaigns")
    parser.add_argument("--customer", required=True, help="Target customer id (linked account)")
    parser.add_argument("--label-index", type=int, default=0, help="Which custom_label index to use (0..4)")
    parser.add_argument("--prefix", default="", help="Campaign name pattern to monitor (optional - if empty, searches all ENABLED campaigns)")
    parser.add_argument("--daily-budget", type=float, default=5.0, help="Daily budget for new campaigns")
    parser.add_argument("--target-roas", type=float, default=None, help="Optional target ROAS for new campaigns")
    parser.add_argument("--merchant-id", default="", help="Override Merchant Center ID (optional)")
    parser.add_argument("--target-languages", type=str, default="it", help="Target languages (comma-separated)")
    parser.add_argument("--target-countries", type=str, default="IT", help="Target countries (comma-separated)")
    parser.add_argument("--feed-label", type=str, default="nl", help="Feed label for shopping setting")
    parser.add_argument("--min-impressions", type=int, default=100, help="Minimum impressions to consider campaign active")
    parser.add_argument("--min-conversions", type=int, default=0, help="Minimum conversions to consider campaign active")
    parser.add_argument("--days-back", type=int, default=30, help="Number of days to look back for performance data")
    parser.add_argument("--auto-pause-empty", action="store_true", help="Automatically pause empty campaigns")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default: false)")
    parser.add_argument("--detailed-report", action="store_true", help="Generate detailed performance report")
    parser.add_argument("--export-csv", action="store_true", help="Export report to CSV file")
    parser.add_argument("--include-roas", action="store_true", help="Include ROAS and ROI analysis in report")
    parser.add_argument("--include-ctr", action="store_true", help="Include CTR and CPC analysis in report")
    parser.add_argument("--include-budget", action="store_true", help="Include budget utilization analysis in report")
    parser.add_argument("--include-volume", action="store_true", help="Include volume analysis in report")
    parser.add_argument("--include-labels", action="store_true", help="Include label performance analysis in report")
    parser.add_argument("--include-trends", action="store_true", help="Include performance trends analysis in report")
    
    return parser.parse_args()

def get_existing_campaigns(client: GoogleAdsClient, customer_id: str, prefix: str) -> Dict[str, str]:
    """Get existing campaigns with the specified prefix (or all ENABLED campaigns if prefix is empty)."""
    ga = client.get_service("GoogleAdsService")
    
    # Build query based on whether prefix is provided
    if prefix:
        query = f"""
        SELECT 
            campaign.id,
            campaign.name,
            campaign.status
        FROM campaign 
            WHERE campaign.name LIKE '%{prefix}%'
            AND campaign.advertising_channel_type IN ('PERFORMANCE_MAX', 'SHOPPING')
            AND campaign.status = 'ENABLED'
        """
    else:
        query = f"""
            SELECT 
                campaign.id,
                campaign.name,
                campaign.status
            FROM campaign 
            WHERE campaign.advertising_channel_type IN ('PERFORMANCE_MAX', 'SHOPPING')
            AND campaign.status = 'ENABLED'
        """
    
    campaigns = {}
    for row in ga.search(customer_id=customer_id, query=query):
        campaigns[row.campaign.name] = {
            'id': str(row.campaign.id),
            'status': row.campaign.status.name,
            'resource_name': f"customers/{customer_id}/campaigns/{row.campaign.id}"
        }
    
    return campaigns

def get_campaign_performance(client: GoogleAdsClient, customer_id: str, campaign_ids: List[str], days_back: int) -> Dict[str, Dict]:
    """Get comprehensive performance data for campaigns in the last N days."""
    if not campaign_ids:
        return {}
    
    ga = client.get_service("GoogleAdsService")
    
    # For multiple campaigns, we need to use IN operator instead of OR
    if len(campaign_ids) == 1:
        query = f"""
            SELECT 
                campaign.id,
                campaign.name,
                campaign.status,
                campaign_budget.amount_micros,
                metrics.impressions,
                metrics.clicks,
                metrics.conversions,
                metrics.conversions_value,
                metrics.cost_micros,
                metrics.ctr,
                metrics.average_cpc,
                metrics.cost_per_conversion,
                metrics.conversions_from_interactions_rate,
                metrics.value_per_conversion,
                metrics.bounce_rate,
                metrics.search_impression_share,
                metrics.search_rank_lost_impression_share,
                metrics.search_rank_lost_top_impression_share,
                metrics.search_top_impression_share
            FROM campaign 
            WHERE campaign.id = {campaign_ids[0]}
            AND segments.date DURING LAST_{days_back}_DAYS
        """
    else:
        # Use IN operator for multiple campaign IDs
        campaign_ids_str = ",".join(campaign_ids)
        query = f"""
            SELECT 
                campaign.id,
                campaign.name,
                campaign.status,
                campaign_budget.amount_micros,
                metrics.impressions,
                metrics.clicks,
                metrics.conversions,
                metrics.conversions_value,
                metrics.cost_micros,
                metrics.ctr,
                metrics.average_cpc,
                metrics.cost_per_conversion,
                metrics.conversions_from_interactions_rate,
                metrics.value_per_conversion,
                metrics.bounce_rate,
                metrics.search_impression_share,
                metrics.search_rank_lost_impression_share,
                metrics.search_rank_lost_top_impression_share,
                metrics.search_top_impression_share
            FROM campaign 
            WHERE campaign.id IN ({campaign_ids_str})
            AND segments.date DURING LAST_{days_back}_DAYS
        """
    
    performance = {}
    for row in ga.search(customer_id=customer_id, query=query):
        campaign_id = str(row.campaign.id)
        cost = row.metrics.cost_micros / 1_000_000
        conversions_value = row.metrics.conversions_value
        
        # Calculate ROAS
        roas = conversions_value / cost if cost > 0 else 0
        
        # Calculate ROI (ROAS - 1)
        roi = roas - 1 if roas > 0 else 0
        
        # Calculate CPA
        cpa = cost / row.metrics.conversions if row.metrics.conversions > 0 else 0
        
        # Calculate conversion rate
        conv_rate = (row.metrics.conversions / row.metrics.clicks * 100) if row.metrics.clicks > 0 else 0
        
        performance[campaign_id] = {
            'name': row.campaign.name,
            'status': row.campaign.status.name,
            'target_roas': None,  # Will be filled later with separate query
            'budget_amount_micros': row.campaign_budget.amount_micros,
            'budget_amount': row.campaign_budget.amount_micros / 1_000_000,
            'impressions': int(row.metrics.impressions),
            'clicks': int(row.metrics.clicks),
            'conversions': int(row.metrics.conversions),
            'conversions_value': conversions_value,
            'cost_micros': int(row.metrics.cost_micros),
            'cost': cost,
            'ctr': float(row.metrics.ctr) * 100 if row.metrics.ctr else 0,
            'average_cpc': float(row.metrics.average_cpc) if row.metrics.average_cpc else 0,
            'cost_per_conversion': float(row.metrics.cost_per_conversion) if row.metrics.cost_per_conversion else 0,
            'conversions_from_interactions_rate': float(row.metrics.conversions_from_interactions_rate) if row.metrics.conversions_from_interactions_rate else 0,
            'value_per_conversion': float(row.metrics.value_per_conversion) if row.metrics.value_per_conversion else 0,
            'bounce_rate': float(row.metrics.bounce_rate) if row.metrics.bounce_rate else 0,
            'search_impression_share': float(row.metrics.search_impression_share) if row.metrics.search_impression_share else 0,
            'search_rank_lost_impression_share': float(row.metrics.search_rank_lost_impression_share) if row.metrics.search_rank_lost_impression_share else 0,
            'search_rank_lost_top_impression_share': float(row.metrics.search_rank_lost_top_impression_share) if row.metrics.search_rank_lost_top_impression_share else 0,
            'search_top_impression_share': float(row.metrics.search_top_impression_share) if row.metrics.search_top_impression_share else 0,
            'roas': roas,
            'roi': roi,
            'cpa': cpa,
            'conversion_rate': conv_rate
        }
    
    return performance

def get_campaign_target_roas(client: GoogleAdsClient, customer_id: str, campaign_ids: List[str]) -> Dict[str, float]:
    """Get target ROAS for campaigns using a separate query.
    
    NOTE: This function is temporarily disabled due to Google Ads API limitations.
    The campaign.target_roas field cannot be used in SELECT clauses.
    """
    # Temporarily disabled due to API limitations
    print("  WARNING: Target ROAS query disabled due to Google Ads API limitations")
    return {}

def identify_empty_campaigns(campaigns: Dict[str, Dict], performance: Dict[str, Dict], 
                           min_impressions: int, min_conversions: int) -> List[str]:
    """Identify campaigns that are considered empty based on performance criteria."""
    empty_campaigns = []
    
    for name, campaign_info in campaigns.items():
        campaign_id = campaign_info['id']
        perf = performance.get(campaign_id, {})
        
        impressions = perf.get('impressions', 0)
        conversions = perf.get('conversions', 0)
        
        if impressions < min_impressions and conversions < min_conversions:
            empty_campaigns.append(name)
            print(f"  [EMPTY] {name}: {impressions} impressions, {conversions} conversions")
    
    return empty_campaigns

def get_campaign_labels(client: GoogleAdsClient, customer_id: str, campaign_ids: List[str], label_index: int) -> Dict[str, str]:
    """Get the label value for each campaign based on shopping performance view."""
    if not campaign_ids:
        return {}
    
    ga = client.get_service("GoogleAdsService")
    
    # Map label_index to the correct segment field
    segment_map = {
        0: "segments.product_custom_label0",
        1: "segments.product_custom_label1", 
        2: "segments.product_custom_label2",
        3: "segments.product_custom_label3",
        4: "segments.product_custom_label4"
    }
    segment_field = segment_map.get(label_index, "segments.product_custom_label0")
    
    campaign_labels = {}
    
    # Get labels from product_group_view (fallback approach)
    try:
        query = f"""
            SELECT 
                campaign.id,
                product_group_view.product_group.name
            FROM product_group_view 
            WHERE campaign.id IN ({','.join(campaign_ids)})
            AND segments.date DURING LAST_30_DAYS
            AND campaign.advertising_channel_type = 'SHOPPING'
        """
        
        for row in ga.search(customer_id=customer_id, query=query):
            campaign_id = str(row.campaign.id)
            product_group_name = row.product_group_view.product_group.name
            
            # Extract seller from product group name
            if product_group_name and " - " in product_group_name:
                parts = product_group_name.split(" - ")
                if len(parts) >= 2:
                    potential_seller = parts[0].strip()
                    if potential_seller and len(potential_seller) > 2:
                        campaign_labels[campaign_id] = potential_seller
        
        # Fill in missing campaigns with Unknown
        for campaign_id in campaign_ids:
            if campaign_id not in campaign_labels:
                campaign_labels[campaign_id] = 'Unknown'
                
    except Exception as e:
        print(f"  [WARNING] Could not get labels from shopping performance view: {e}")
        # Fallback to campaign name extraction
        for campaign_id in campaign_ids:
            try:
                query = f"""
                    SELECT 
                        campaign.id,
                        campaign.name
                    FROM campaign 
                    WHERE campaign.id = {campaign_id}
                """
                
                for row in ga.search(customer_id=customer_id, query=query):
                    campaign_name = row.campaign.name
                    # Try to extract seller name from campaign name patterns
                    if " - " in campaign_name:
                        parts = campaign_name.split(" - ")
                        if len(parts) >= 2:
                            potential_seller = parts[1].strip()
                            generic_terms = ["OVER", "UNDER", "EQUAL", "NOBENCH", "NORMAL", "CONFIG", "HIGH", "MEDIUM", "LOW", "ALL", "CATCH"]
                            if potential_seller not in generic_terms and len(potential_seller) > 2:
                                campaign_labels[campaign_id] = potential_seller
                            else:
                                campaign_labels[campaign_id] = 'Unknown'
                        else:
                            campaign_labels[campaign_id] = 'Unknown'
                    else:
                        campaign_labels[campaign_id] = 'Unknown'
                    break
            except Exception as e2:
                print(f"  [WARNING] Could not get campaign name for {campaign_id}: {e2}")
                campaign_labels[campaign_id] = 'Unknown'
    
    return campaign_labels

def get_seller_performance_data(client: GoogleAdsClient, customer_id: str, label_index: int, days_back: int) -> Dict[str, Dict]:
    """Get performance data per seller from shopping_performance_view using product_group_view."""
    ga = client.get_service("GoogleAdsService")
    
    try:
        # Try using product_group_view instead of shopping_performance_view
        query = f"""
            SELECT 
                product_group_view.resource_name,
                product_group_view.product_group.id,
                product_group_view.product_group.name,
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
            FROM product_group_view 
            WHERE segments.date DURING LAST_{days_back}_DAYS
            AND campaign.advertising_channel_type = 'SHOPPING'
        """
        
        seller_data = {}
        for row in ga.search(customer_id=customer_id, query=query):
            # Extract seller name from product group name or resource name
            product_group_name = row.product_group_view.product_group.name
            resource_name = row.product_group_view.resource_name
            
            # Try to extract seller from product group name
            # This assumes the product group name contains the seller info
            seller = "Unknown"
            if product_group_name and " - " in product_group_name:
                parts = product_group_name.split(" - ")
                if len(parts) >= 2:
                    potential_seller = parts[0].strip()
                    if potential_seller and len(potential_seller) > 2:
                        seller = potential_seller
            
            if seller not in seller_data:
                seller_data[seller] = {
                    'impressions': 0,
                    'clicks': 0,
                    'conversions': 0,
                    'conversions_value': 0,
                    'cost': 0,
                    'ctr': 0,
                    'avg_cpc': 0,
                    'cpa': 0,
                    'conversion_rate': 0,
                    'value_per_conversion': 0
                }
            
            # Aggregate the data
            seller_data[seller]['impressions'] += int(row.metrics.impressions)
            seller_data[seller]['clicks'] += int(row.metrics.clicks)
            seller_data[seller]['conversions'] += int(row.metrics.conversions)
            seller_data[seller]['conversions_value'] += float(row.metrics.conversions_value)
            seller_data[seller]['cost'] += float(row.metrics.cost_micros) / 1_000_000
            seller_data[seller]['ctr'] = float(row.metrics.ctr) * 100 if row.metrics.ctr else 0
            seller_data[seller]['avg_cpc'] = float(row.metrics.average_cpc) if row.metrics.average_cpc else 0
            seller_data[seller]['cpa'] = float(row.metrics.cost_per_conversion) if row.metrics.cost_per_conversion else 0
            seller_data[seller]['conversion_rate'] = float(row.metrics.conversions_from_interactions_rate) * 100 if row.metrics.conversions_from_interactions_rate else 0
            seller_data[seller]['value_per_conversion'] = float(row.metrics.value_per_conversion) if row.metrics.value_per_conversion else 0
        
        # Calculate derived metrics
        for seller, data in seller_data.items():
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
        
        return seller_data
        
    except Exception as e:
        print(f"  [WARNING] Could not get seller performance data from product_group_view: {e}")
        # Fallback: return empty dict
        return {}

def get_marge_per_label_2(client: GoogleAdsClient, customer_id: str, days_back: int) -> Dict[str, Dict]:
    """Get performance data grouped by custom label 2 (marge ex 15%) directly from API."""
    ga = client.get_service("GoogleAdsService")
    marge_data = {}
    
    try:
        query = f"""
            SELECT
                segments.product_custom_attribute2,
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
            WHERE segments.date DURING LAST_{days_back}_DAYS
            AND segments.product_custom_attribute2 IS NOT NULL
            """
        
        for row in ga.search(customer_id=customer_id, query=query):
            marge_value = row.segments.product_custom_attribute2 or ""
            if not marge_value:
                continue
                
            if marge_value not in marge_data:
                marge_data[marge_value] = {
                    'total_impressions': 0,
                    'total_clicks': 0,
                    'total_conversions': 0,
                    'total_cost': 0,
                    'total_conversions_value': 0,
                    'ctr': 0,
                    'avg_cpc': 0,
                    'cpa': 0,
                    'conversion_rate': 0,
                    'value_per_conversion': 0
                }
            
            # Aggregate performance data
            marge_data[marge_value]['total_impressions'] += int(row.metrics.impressions)
            marge_data[marge_value]['total_clicks'] += int(row.metrics.clicks)
            marge_data[marge_value]['total_conversions'] += int(row.metrics.conversions)
            marge_data[marge_value]['total_conversions_value'] += float(row.metrics.conversions_value)
            marge_data[marge_value]['total_cost'] += float(row.metrics.cost_micros) / 1_000_000
            marge_data[marge_value]['ctr'] = float(row.metrics.ctr) * 100 if row.metrics.ctr else 0
            marge_data[marge_value]['avg_cpc'] = float(row.metrics.average_cpc) if row.metrics.average_cpc else 0
            marge_data[marge_value]['cpa'] = float(row.metrics.cost_per_conversion) if row.metrics.cost_per_conversion else 0
            marge_data[marge_value]['conversion_rate'] = float(row.metrics.conversions_from_interactions_rate) * 100 if row.metrics.conversions_from_interactions_rate else 0
            marge_data[marge_value]['value_per_conversion'] = float(row.metrics.value_per_conversion) if row.metrics.value_per_conversion else 0
        
        # Calculate derived metrics
        for marge_value, data in marge_data.items():
            if data['total_conversions'] > 0:
                data['cpa'] = data['total_cost'] / data['total_conversions']
            if data['total_cost'] > 0:
                data['roas'] = data['total_conversions_value'] / data['total_cost']
                data['roi'] = data['roas'] - 1
            else:
                data['roas'] = 0
                data['roi'] = 0
            if data['total_clicks'] > 0:
                data['conversion_rate'] = (data['total_conversions'] / data['total_clicks']) * 100
            if data['total_impressions'] > 0:
                data['ctr'] = (data['total_clicks'] / data['total_impressions']) * 100
            if data['total_clicks'] > 0:
                data['avg_cpc'] = data['total_cost'] / data['total_clicks']
        
        return marge_data
        
    except Exception as e:
        print(f"  [WARNING] Could not get marge data from custom label 2: {e}")
        return {}

def find_new_labels(existing_labels: set, all_labels: Dict[str, Dict]) -> Dict[str, int]:
    """Find labels that don't have campaigns yet."""
    new_labels = {}
    for label, data in all_labels.items():
        if label not in existing_labels:
            new_labels[label] = data['impressions']
    
    return new_labels

def create_campaign_for_label(client: GoogleAdsClient, customer_id: str, label: str, 
                            args: argparse.Namespace, timestamp: str) -> Optional[str]:
    """Create a new campaign for a specific label."""
    try:
        # Create campaign name
        safe_label = label.replace(" ", "_")[:40]
        campaign_name = f"{args.prefix} - {safe_label} - {timestamp}"
        
        print(f"  [CREATE] Creating campaign: {campaign_name}")
        
        if args.dry_run:
            print(f"    [DRY-RUN] Would create campaign: {campaign_name}")
            return None
        
        # Create campaign
        campaign_rn = _create_pmax_campaign(
            client=client,
            customer_id=customer_id,
            campaign_name=campaign_name,
            daily_budget_micros=int(round(args.daily_budget * 1_000_000)),
            campaign_target_roas=args.target_roas,
            is_feed_only=True,
            merchant_id=args.merchant_id,
            target_languages=args.target_languages,
            target_countries=args.target_countries,
            feed_label=args.feed_label,
        )
        
        # Create asset group
        asset_group_name = f"{campaign_name} - Asset Group"
        ag_rn = _create_pmax_asset_group(
            client=client,
            customer_id=customer_id,
            campaign_rn=campaign_rn,
            asset_group_name=asset_group_name,
            label_index=args.label_index,
            label_value=label,
            is_feed_only=True,
            merchant_id=args.merchant_id,
            target_languages=args.target_languages,
            target_countries=args.target_countries,
        )
        
        # Add listing group filter
        add_listing_group_for_label(client, customer_id, ag_rn, label, args.label_index)
        
        print(f"    [SUCCESS] Created campaign: {campaign_name}")
        return campaign_rn
        
    except Exception as e:
        print(f"    [ERROR] Failed to create campaign for {label}: {e}")
        return None

def pause_empty_campaign(client: GoogleAdsClient, customer_id: str, campaign_rn: str) -> bool:
    """Pause an empty campaign."""
    try:
        campaign_svc = client.get_service("CampaignService")
        op = client.get_type("CampaignOperation")
        campaign = op.update
        campaign.resource_name = campaign_rn
        campaign.status = client.enums.CampaignStatusEnum.PAUSED
        op.update_mask.CopyFrom(client.get_type("FieldMask")(paths=["status"]))
        
        result = campaign_svc.mutate_campaigns(customer_id=customer_id, operations=[op])
        print(f"    [PAUSED] Campaign paused: {campaign_rn}")
        return True
        
    except Exception as e:
        print(f"    [ERROR] Failed to pause campaign: {e}")
        return False

def generate_performance_report(campaigns: Dict[str, Dict], performance: Dict[str, Dict], 
                              campaign_labels: Dict[str, str], days_back: int, all_labels: Dict[str, Dict] = None, 
                              seller_performance: Dict[str, Dict] = None, marge_per_label_2: Dict[str, Dict] = None) -> Dict:
    """Generate a comprehensive performance report with actionable insights."""
    
    report = {
        'summary': {
            'total_campaigns': len(campaigns),
            'active_campaigns': 0,
            'paused_campaigns': 0,
            'total_impressions': 0,
            'total_clicks': 0,
            'total_conversions': 0,
            'total_conversions_value': 0,
            'total_cost': 0,
            'avg_cpa': 0,
            'avg_roas': 0,
            'avg_roi': 0,
            'avg_ctr': 0,
            'avg_cpc': 0,
            'conversion_rate': 0,
            'total_budget': 0,
            'budget_utilization': 0
        },
        'top_performers': [],
        'underperformers': [],
        'high_roas_campaigns': [],
        'low_roas_campaigns': [],
        'high_volume_campaigns': [],
        'label_performance': {},
        'performance_trends': {},
        'recommendations': [],
        'all_labels': all_labels or {},
        'seller_performance': seller_performance or {},
        'marge_per_label_2': marge_per_label_2 or {}
    }
    
    # Calculate totals and categorize campaigns
    for name, campaign_info in campaigns.items():
        campaign_id = campaign_info['id']
        perf = performance.get(campaign_id, {})
        label = campaign_labels.get(campaign_id, 'Unknown')
        
        # Extract performance data
        impressions = perf.get('impressions', 0)
        clicks = perf.get('clicks', 0)
        conversions = perf.get('conversions', 0)
        conversions_value = perf.get('conversions_value', 0)
        cost = perf.get('cost', 0)
        budget_amount = perf.get('budget_amount', 0)
        roas = perf.get('roas', 0)
        roi = perf.get('roi', 0)
        cpa = perf.get('cpa', 0)
        ctr = perf.get('ctr', 0)
        avg_cpc = perf.get('average_cpc', 0)
        conv_rate = perf.get('conversion_rate', 0)
        
        # Update summary
        report['summary']['total_impressions'] += impressions
        report['summary']['total_clicks'] += clicks
        report['summary']['total_conversions'] += conversions
        report['summary']['total_conversions_value'] += conversions_value
        report['summary']['total_cost'] += cost
        report['summary']['total_budget'] += budget_amount
        
        # Track campaign status
        if campaign_info['status'] == 'ENABLED':
            report['summary']['active_campaigns'] += 1
        else:
            report['summary']['paused_campaigns'] += 1
        
        # Categorize performance
        campaign_data = {
            'name': name,
            'label': label,
            'status': campaign_info['status'],
            'impressions': impressions,
            'clicks': clicks,
            'conversions': conversions,
            'conversions_value': conversions_value,
            'cost': cost,
            'budget_amount': budget_amount,
            'target_roas': perf.get('target_roas'),  # May be None due to API limitations
            'roas': roas,
            'roi': roi,
            'cpa': cpa,
            'ctr': ctr,
            'avg_cpc': avg_cpc,
            'conversion_rate': conv_rate,
            'resource_name': campaign_info['resource_name']
        }
        
        # Top performers (high conversions, good conversion rate)
        if conversions >= 5 and conv_rate >= 2.0:
            report['top_performers'].append(campaign_data)
        
        # Underperformers (low impressions, no conversions)
        if impressions < 100 and conversions == 0:
            report['underperformers'].append(campaign_data)
        
        # High ROAS campaigns (ROAS > 4.0)
        if roas >= 4.0 and conversions > 0:
            report['high_roas_campaigns'].append(campaign_data)
        
        # Low ROAS campaigns (ROAS < 2.0 and cost > 0)
        if roas < 2.0 and cost > 0:
            report['low_roas_campaigns'].append(campaign_data)
        
        # High volume campaigns (high impressions)
        if impressions >= 1000:
            report['high_volume_campaigns'].append(campaign_data)
        
        # Aggregate by label
        if label not in report['label_performance']:
            report['label_performance'][label] = {
                'campaigns': 0,
                'total_impressions': 0,
                'total_clicks': 0,
                'total_conversions': 0,
                'total_conversions_value': 0,
                'total_cost': 0,
                'total_budget': 0,
                'avg_roas': 0,
                'avg_roi': 0,
                'avg_cpa': 0,
                'avg_ctr': 0,
                'avg_conversion_rate': 0
            }
        
        report['label_performance'][label]['campaigns'] += 1
        report['label_performance'][label]['total_impressions'] += impressions
        report['label_performance'][label]['total_clicks'] += clicks
        report['label_performance'][label]['total_conversions'] += conversions
        report['label_performance'][label]['total_conversions_value'] += conversions_value
        report['label_performance'][label]['total_cost'] += cost
        report['label_performance'][label]['total_budget'] += budget_amount
    
    # Calculate averages
    if report['summary']['total_conversions'] > 0:
        report['summary']['avg_cpa'] = report['summary']['total_cost'] / report['summary']['total_conversions']
    
    if report['summary']['total_impressions'] > 0:
        report['summary']['conversion_rate'] = (report['summary']['total_conversions'] / report['summary']['total_clicks']) * 100 if report['summary']['total_clicks'] > 0 else 0
        report['summary']['avg_ctr'] = (report['summary']['total_clicks'] / report['summary']['total_impressions']) * 100
    
    if report['summary']['total_cost'] > 0:
        report['summary']['avg_roas'] = report['summary']['total_conversions_value'] / report['summary']['total_cost']
        report['summary']['avg_roi'] = report['summary']['avg_roas'] - 1
    
    if report['summary']['total_clicks'] > 0:
        report['summary']['avg_cpc'] = report['summary']['total_cost'] / report['summary']['total_clicks']
    
    if report['summary']['total_budget'] > 0:
        report['summary']['budget_utilization'] = (report['summary']['total_cost'] / report['summary']['total_budget']) * 100
    
    # Calculate label averages
    for label, data in report['label_performance'].items():
        if data['total_conversions'] > 0:
            data['avg_cpa'] = data['total_cost'] / data['total_conversions']
        if data['total_cost'] > 0:
            data['avg_roas'] = data['total_conversions_value'] / data['total_cost']
            data['avg_roi'] = data['avg_roas'] - 1
        if data['total_impressions'] > 0:
            data['avg_ctr'] = (data['total_clicks'] / data['total_impressions']) * 100
            data['avg_conversion_rate'] = (data['total_conversions'] / data['total_clicks']) * 100 if data['total_clicks'] > 0 else 0
    
    # Sort campaigns by performance
    report['top_performers'].sort(key=lambda x: x['conversions'], reverse=True)
    report['underperformers'].sort(key=lambda x: x['impressions'])
    report['high_roas_campaigns'].sort(key=lambda x: x['roas'], reverse=True)
    report['low_roas_campaigns'].sort(key=lambda x: x['roas'])
    report['high_volume_campaigns'].sort(key=lambda x: x['impressions'], reverse=True)
    
    # Generate recommendations
    if report['underperformers']:
        report['recommendations'].append(f"Consider pausing {len(report['underperformers'])} underperforming campaigns")
    
    if report['low_roas_campaigns']:
        report['recommendations'].append(f"Review {len(report['low_roas_campaigns'])} campaigns with ROAS < 2.0")
    
    if report['summary']['conversion_rate'] < 1.0:
        report['recommendations'].append("Overall conversion rate is low - review targeting and landing pages")
    
    if report['summary']['avg_cpa'] > 50:  # Assuming €50 is high
        report['recommendations'].append("Average CPA is high - consider adjusting bidding strategy")
    
    if report['summary']['budget_utilization'] < 50:
        report['recommendations'].append("Low budget utilization - consider increasing bids or expanding targeting")
    
    if report['summary']['avg_roas'] < 2.0:
        report['recommendations'].append("Overall ROAS is low - review product pricing and campaign optimization")
    
    return report

def print_detailed_report(report: Dict, days_back: int, args: argparse.Namespace = None):
    """Print a detailed, formatted performance report."""
    
    print(f"\n{'='*60}")
    print(f"PERFORMANCE REPORT (Last {days_back} days)")
    print(f"{'='*60}")
    
    # Check which metrics to include
    include_roas = args.include_roas if args else True
    include_ctr = args.include_ctr if args else True
    include_budget = args.include_budget if args else True
    include_volume = args.include_volume if args else True
    include_labels = args.include_labels if args else True
    include_trends = args.include_trends if args else True
    
    # Summary Section
    print(f"\nSUMMARY:")
    print(f"  Total Campaigns: {report['summary']['total_campaigns']}")
    print(f"  Active: {report['summary']['active_campaigns']} | Paused: {report['summary']['paused_campaigns']}")
    print(f"  Total Impressions: {report['summary']['total_impressions']:,}")
    
    if include_ctr:
        print(f"  Total Clicks: {report['summary']['total_clicks']:,}")
        print(f"  Avg CTR: {report['summary']['avg_ctr']:.2f}%")
        print(f"  Avg CPC: €{report['summary']['avg_cpc']:.2f}")
    
    print(f"  Total Conversions: {report['summary']['total_conversions']:,}")
    print(f"  Conversion Rate: {report['summary']['conversion_rate']:.2f}%")
    print(f"  Avg CPA: €{report['summary']['avg_cpa']:.2f}")
    
    if include_roas:
        print(f"  Total Conversions Value: €{report['summary']['total_conversions_value']:.2f}")
        print(f"  Avg ROAS: {report['summary']['avg_roas']:.2f}")
        print(f"  Avg ROI: {report['summary']['avg_roi']:.1f}%")
    
    print(f"  Total Cost: €{report['summary']['total_cost']:.2f}")
    
    if include_budget:
        print(f"  Total Budget: €{report['summary']['total_budget']:.2f}")
        print(f"  Budget Utilization: {report['summary']['budget_utilization']:.1f}%")
    
    print(f"\n  Note: Target ROAS data unavailable due to Google Ads API limitations")
    
    # Top Performers
    if report['top_performers']:
        print(f"\nTOP PERFORMERS:")
        for i, campaign in enumerate(report['top_performers'][:5], 1):
            print(f"  {i}. {campaign['name']}")
            print(f"     Label: {campaign['label']} | Status: {campaign['status']}")
            print(f"     Impressions: {campaign['impressions']:,} | Clicks: {campaign['clicks']:,} | Conversions: {campaign['conversions']}")
            print(f"     Cost: €{campaign['cost']:.2f} | CPA: €{campaign['cpa']:.2f} | ROAS: {campaign['roas']:.2f}")
            print(f"     CTR: {campaign['ctr']:.2f}% | Conv Rate: {campaign['conversion_rate']:.2f}% | Value: €{campaign['conversions_value']:.2f}")
            if campaign.get('target_roas') is not None:
                print(f"     Target ROAS: {campaign['target_roas']:.2f}")
    
    # High ROAS Campaigns
    if report['high_roas_campaigns']:
        print(f"\nHIGH ROAS CAMPAIGNS (ROAS >= 4.0):")
        for i, campaign in enumerate(report['high_roas_campaigns'][:5], 1):
            print(f"  {i}. {campaign['name']}")
            print(f"     Label: {campaign['label']} | ROAS: {campaign['roas']:.2f} | ROI: {campaign['roi']:.1f}%")
            print(f"     Conversions: {campaign['conversions']} | Value: €{campaign['conversions_value']:.2f}")
            print(f"     Cost: €{campaign['cost']:.2f} | CPA: €{campaign['cpa']:.2f}")
            if campaign.get('target_roas') is not None:
                print(f"     Target ROAS: {campaign['target_roas']:.2f}")
    
    # Low ROAS Campaigns
    if report['low_roas_campaigns']:
        print(f"\nLOW ROAS CAMPAIGNS (ROAS < 2.0):")
        for i, campaign in enumerate(report['low_roas_campaigns'][:5], 1):
            print(f"  {i}. {campaign['name']}")
            print(f"     Label: {campaign['label']} | ROAS: {campaign['roas']:.2f} | ROI: {campaign['roi']:.1f}%")
            print(f"     Impressions: {campaign['impressions']:,} | Conversions: {campaign['conversions']}")
            print(f"     Cost: €{campaign['cost']:.2f} | CPA: €{campaign['cpa']:.2f} | Value: €{campaign['conversions_value']:.2f}")
            if campaign.get('target_roas') is not None:
                print(f"     Target ROAS: {campaign['target_roas']:.2f}")
    
    # High Volume Campaigns
    if report['high_volume_campaigns']:
        print(f"\nHIGH VOLUME CAMPAIGNS (>=1000 impressions):")
        for i, campaign in enumerate(report['high_volume_campaigns'][:5], 1):
            print(f"  {i}. {campaign['name']}")
            print(f"     Label: {campaign['label']} | Impressions: {campaign['impressions']:,}")
            print(f"     Clicks: {campaign['clicks']:,} | CTR: {campaign['ctr']:.2f}%")
            print(f"     Conversions: {campaign['conversions']} | Conv Rate: {campaign['conversion_rate']:.2f}%")
            print(f"     ROAS: {campaign['roas']:.2f} | CPA: €{campaign['cpa']:.2f} | Value: €{campaign['conversions_value']:.2f}")
            if campaign.get('target_roas') is not None:
                print(f"     Target ROAS: {campaign['target_roas']:.2f}")
    
    # Underperformers
    if report['underperformers']:
        print(f"\nUNDERPERFORMING CAMPAIGNS:")
        for i, campaign in enumerate(report['underperformers'][:5], 1):
            print(f"  {i}. {campaign['name']}")
            print(f"     Label: {campaign['label']} | Status: {campaign['status']}")
            print(f"     Impressions: {campaign['impressions']:,} | Conversions: {campaign['conversions']}")
            print(f"     Cost: €{campaign['cost']:.2f} | Budget: €{campaign['budget_amount']:.2f} | Value: €{campaign['conversions_value']:.2f}")
    
    # Seller Performance (From Custom Label X) - Always use fallback method
    if args.include_labels and report.get('all_labels'):
        print(f"\nSELLER PERFORMANCE (From Custom Label {args.label_index if args else 0}):")
        sorted_labels = sorted(report['all_labels'].items(), 
                             key=lambda x: x[1].get('total_conversions', 0), reverse=True)
        
        for label, data in sorted_labels:  # All labels
            campaigns = data.get('campaigns', 0)
            impressions = data.get('total_impressions', 0)
            clicks = data.get('total_clicks', 0)
            conversions = data.get('total_conversions', 0)
            cost = data.get('total_cost', 0)
            budget = data.get('total_budget', 0)
            value = data.get('total_conversions_value', 0)
            
            # Get custom label 1 values (marge in %)
            custom_label_1_values = data.get('custom_label_1', [])
            label_1_display = ", ".join(custom_label_1_values) if custom_label_1_values else "N/A"
            
            print(f"  {label}:")
            print(f"     Marge in %: {label_1_display}")
            print(f"     Campaigns: {campaigns} | Impressions: {impressions:,}")
            if impressions > 0:
                ctr = (clicks / impressions) * 100
                conv_rate = (conversions / clicks) * 100 if clicks > 0 else 0
                cpa = cost / conversions if conversions > 0 else 0
                roas = value / cost if cost > 0 else 0
                roi = roas - 1 if roas > 0 else 0
                
                print(f"     Clicks: {clicks:,} | CTR: {ctr:.2f}%")
                print(f"     Conversions: {conversions} | Conv Rate: {conv_rate:.2f}%")
                print(f"     Cost: €{cost:.2f} | Budget: €{budget:.2f} | Value: €{value:.2f}")
                print(f"     CPA: €{cpa:.2f} | ROAS: {roas:.2f} | ROI: {roi:.1f}%")
            else:
                print(f"     No performance data available")
    
    # Marge per Custom Label 2 (Marge ex 15%)
    if args.include_labels and report.get('marge_per_label_2'):
        print(f"\nMARGE PER CUSTOM LABEL 2 (Marge ex 15%):")
        sorted_marge = sorted(report['marge_per_label_2'].items(), 
                             key=lambda x: x[1].get('total_conversions', 0), reverse=True)
        
        for marge_value, data in sorted_marge:
            impressions = data.get('total_impressions', 0)
            clicks = data.get('total_clicks', 0)
            conversions = data.get('total_conversions', 0)
            cost = data.get('total_cost', 0)
            value = data.get('total_conversions_value', 0)
            
            print(f"  {marge_value}:")
            print(f"     Impressions: {impressions:,} | Clicks: {clicks:,} | Conversions: {conversions}")
            if impressions > 0:
                ctr = data.get('ctr', 0)
                conv_rate = data.get('conversion_rate', 0)
                cpa = data.get('cpa', 0)
                roas = data.get('roas', 0)
                roi = data.get('roi', 0)
                
                print(f"     CTR: {ctr:.2f}% | Conv Rate: {conv_rate:.2f}%")
                print(f"     Cost: €{cost:.2f} | Value: €{value:.2f}")
                print(f"     CPA: €{cpa:.2f} | ROAS: {roas:.2f} | ROI: {roi:.1f}%")
            else:
                print(f"     CTR: 0.00% | Conv Rate: 0.00%")
                print(f"     Cost: €{cost:.2f} | Value: €{value:.2f}")
                print(f"     CPA: €0.00 | ROAS: 0.00 | ROI: 0.0%")
            print()
    
    # Label Performance (Existing Campaigns Only)
    if report['label_performance']:
        print(f"\nLABEL PERFORMANCE (Existing Campaigns):")
        sorted_labels = sorted(report['label_performance'].items(), 
                             key=lambda x: x[1]['total_conversions'], reverse=True)
        
        for label, data in sorted_labels[:10]:  # Top 10 labels
            if data['total_impressions'] > 0:
                print(f"  {label}:")
                print(f"     Campaigns: {data['campaigns']} | Impressions: {data['total_impressions']:,}")
                print(f"     Clicks: {data['total_clicks']:,} | CTR: {data['avg_ctr']:.2f}%")
                print(f"     Conversions: {data['total_conversions']} | Conv Rate: {data['avg_conversion_rate']:.2f}%")
                print(f"     Cost: €{data['total_cost']:.2f} | Budget: €{data['total_budget']:.2f} | Value: €{data['total_conversions_value']:.2f}")
                print(f"     CPA: €{data['avg_cpa']:.2f} | ROAS: {data['avg_roas']:.2f} | ROI: {data['avg_roi']:.1f}%")
    
    # Recommendations
    if report['recommendations']:
        print(f"\nRECOMMENDATIONS:")
        for i, rec in enumerate(report['recommendations'], 1):
            print(f"  {i}. {rec}")
    
    print(f"\n{'='*60}")

def export_report_to_csv(report: Dict, filename: str = None):
    """Export the performance report to CSV format."""
    if not filename:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"weekly_report_{timestamp}.csv"
    
    import csv
    
    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        
        # Write summary
        writer.writerow(['SUMMARY'])
        writer.writerow(['Metric', 'Value'])
        writer.writerow(['Total Campaigns', report['summary']['total_campaigns']])
        writer.writerow(['Active Campaigns', report['summary']['active_campaigns']])
        writer.writerow(['Paused Campaigns', report['summary']['paused_campaigns']])
        writer.writerow(['Total Impressions', report['summary']['total_impressions']])
        writer.writerow(['Total Conversions', report['summary']['total_conversions']])
        writer.writerow(['Total Cost', f"€{report['summary']['total_cost']:.2f}"])
        writer.writerow(['Avg CPA', f"€{report['summary']['avg_cpa']:.2f}"])
        writer.writerow(['Conversion Rate', f"{report['summary']['conversion_rate']:.2f}%"])
        
        writer.writerow([])  # Empty row
        
        # Write top performers
        writer.writerow(['TOP PERFORMERS'])
        writer.writerow(['Name', 'Label', 'Impressions', 'Conversions', 'Cost', 'CPA', 'Conv Rate'])
        for campaign in report['top_performers']:
            writer.writerow([
                campaign['name'],
                campaign['label'],
                campaign['impressions'],
                campaign['conversions'],
                f"€{campaign['cost']:.2f}",
                f"€{campaign['cost']:.2f}",
                f"{campaign['conversion_rate']:.2f}%"
            ])
        
        writer.writerow([])  # Empty row
        
        # Write underperformers
        writer.writerow(['UNDERPERFORMING CAMPAIGNS'])
        writer.writerow(['Name', 'Label', 'Impressions', 'Conversions', 'Cost'])
        for campaign in report['underperformers']:
            writer.writerow([
                campaign['name'],
                campaign['label'],
                campaign['impressions'],
                campaign['conversions'],
                f"€{campaign['cost']:.2f}"
            ])
    
    print(f"Report exported to: {filename}")
    return filename

def main() -> None:
    """Main function for weekly campaign monitoring."""
    args = parse_args()
    
    # Load configuration
    cfg = os.getenv("GOOGLE_ADS_CONFIGURATION_FILE")
    if not cfg:
        cfg = str(Path(__file__).parent.parent / "config" / "google-ads.yaml")
    
    print(f"Config path = {cfg}")
    
    # Initialize client
    client = GoogleAdsClient.load_from_storage(cfg)
    customer_id = _digits_only(args.customer)
    
    print(f"\n[WEEKLY MONITOR] Weekly Campaign Monitor for Customer {customer_id}")
    print(f"[DATE] Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[LABEL] Label Index: {args.label_index}")
    print(f"[THRESHOLD] Performance Threshold: {args.min_impressions} impressions, {args.min_conversions} conversions")
    print(f"[DAYS] Looking back: {args.days_back} days")
    print(f"[DRY RUN] Dry Run: {args.dry_run}")
    print(f"[APPLY] Apply Changes: {args.apply}")
    
    try:
        # 1. Get existing campaigns
        print(f"\n[STEP 1] Getting existing campaigns with prefix '{args.prefix}'...")
        existing_campaigns = get_existing_campaigns(client, customer_id, args.prefix)
        print(f"  Found {len(existing_campaigns)} existing campaigns")
        
        # 2. Get performance data
        print(f"\n[STEP 2] Getting campaign performance data...")
        campaign_ids = [campaign['id'] for campaign in existing_campaigns.values()]
        performance = get_campaign_performance(client, customer_id, campaign_ids, args.days_back)
        print(f"  Got performance data for {len(performance)} campaigns")
        
        # 2.5. Get target ROAS data separately (temporarily disabled due to API limitations)
        print(f"\n[STEP 2.5] Getting target ROAS data...")
        print(f"  Note: Target ROAS temporarily disabled due to Google Ads API limitations")
        
        # Set target_roas to None for all campaigns (will be calculated from performance data)
        for campaign_id in performance:
            performance[campaign_id]['target_roas'] = None
        
        # 3. Identify empty campaigns
        print(f"\n[STEP 3] Identifying empty campaigns...")
        empty_campaigns = identify_empty_campaigns(
            existing_campaigns, performance, args.min_impressions, args.min_conversions
        )
        print(f"  Found {len(empty_campaigns)} empty campaigns")
        
        # 4. Get labels for existing campaigns
        print(f"\n[STEP 4] Getting labels for existing campaigns...")
        campaign_labels = get_campaign_labels(client, customer_id, campaign_ids, args.label_index)
        existing_labels = set(campaign_labels.values())
        print(f"  Found {len(existing_labels)} existing labels")
        
        # 4.5. Get seller performance data from shopping_performance_view
        print(f"\n[STEP 4.5] Getting seller performance data from shopping_performance_view...")
        seller_performance = get_seller_performance_data(client, customer_id, args.label_index, args.days_back)
        print(f"  Found performance data for {len(seller_performance)} sellers")
        
        # If seller_performance is empty, we'll use the fallback method in the report
        
        # 5. Discover all available labels
        print(f"\n[STEP 5] Discovering all available labels...")
        all_labels_raw = discover_labels(client, customer_id, args.label_index, include_label_1=True, include_label_2=True)
        print(f"  Found {len(all_labels_raw)} total labels")
        
        # Convert to the format expected by the report and merge with existing campaign data
        all_labels = {}
        for label, data in all_labels_raw.items():
            all_labels[label] = {
                'campaigns': 0,
                'total_impressions': data['impressions'],
                'total_clicks': data['clicks'],
                'total_conversions': data['conversions'],
                'total_cost': data['cost'],
                'total_budget': 0,
                'total_conversions_value': data['conversions_value'],
                'custom_label_1': list(data.get('custom_label_1', set())),  # Convert set to list for JSON serialization
                'custom_label_2': list(data.get('custom_label_2', set()))   # Convert set to list for JSON serialization
            }
        
        # Merge existing campaign performance data into all_labels
        for name, campaign_info in existing_campaigns.items():
            campaign_id = campaign_info['id']
            perf = performance.get(campaign_id, {})
            label = campaign_labels.get(campaign_id, 'Unknown')
            
            # Add Unknown label to all_labels if it doesn't exist
            if label == 'Unknown' and label not in all_labels:
                all_labels[label] = {
                    'campaigns': 0,
                    'total_impressions': 0,
                    'total_clicks': 0,
                    'total_conversions': 0,
                    'total_cost': 0,
                    'total_budget': 0,
                    'total_conversions_value': 0
                }
            
            if label in all_labels:
                all_labels[label]['campaigns'] += 1
                all_labels[label]['total_impressions'] += perf.get('impressions', 0)
                all_labels[label]['total_clicks'] += perf.get('clicks', 0)
                all_labels[label]['total_conversions'] += perf.get('conversions', 0)
                all_labels[label]['total_cost'] += perf.get('cost', 0)
                all_labels[label]['total_budget'] += perf.get('budget_amount', 0)
                all_labels[label]['total_conversions_value'] += perf.get('conversions_value', 0)
        
        # 6. Find new labels that need campaigns
        print(f"\n[STEP 6] Finding new labels that need campaigns...")
        new_labels = find_new_labels(existing_labels, all_labels_raw)
        print(f"  Found {len(new_labels)} new labels that need campaigns")
        
        if new_labels:
            print(f"\n[LABELS] New labels to create campaigns for:")
            for label, impressions in sorted(new_labels.items(), key=lambda x: x[1], reverse=True):
                print(f"  - {label}: {impressions} impressions")
        
        # 7. Generate detailed performance report if requested
        if args.detailed_report:
            print(f"\n[STEP 7] Generating detailed performance report...")
            
            # Calculate marge per custom label 2
            marge_per_label_2 = get_marge_per_label_2(client, customer_id, args.days_back)
            print(f"  Found {len(marge_per_label_2)} marge categories")
            
            report = generate_performance_report(existing_campaigns, performance, campaign_labels, args.days_back, all_labels, seller_performance, marge_per_label_2)
            print_detailed_report(report, args.days_back, args)
            
            # Export to CSV if requested
            if args.export_csv:
                export_report_to_csv(report)
        
        # 8. Create campaigns for new labels
        if new_labels and args.apply and not args.dry_run:
            print(f"\n[STEP 8] Creating campaigns for new labels...")
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            
            created_campaigns = []
            for label, impressions in sorted(new_labels.items(), key=lambda x: x[1], reverse=True):
                campaign_rn = create_campaign_for_label(client, customer_id, label, args, timestamp)
                if campaign_rn:
                    created_campaigns.append(campaign_rn)
                time.sleep(1)  # Small delay to avoid rate limiting
            
            print(f"  Created {len(created_campaigns)} new campaigns")
        
        # 9. Handle empty campaigns
        if empty_campaigns and args.auto_pause_empty and args.apply and not args.dry_run:
            print(f"\n[STEP 9] Handling empty campaigns...")
            paused_count = 0
            for campaign_name in empty_campaigns:
                campaign_rn = existing_campaigns[campaign_name]['resource_name']
                if pause_empty_campaign(client, customer_id, campaign_rn):
                    paused_count += 1
                time.sleep(1)  # Small delay to avoid rate limiting
            
            print(f"  Paused {len(empty_campaigns)} empty campaigns")
        
        # Summary
        print(f"\n[SUMMARY] Summary:")
        print(f"  - Existing campaigns: {len(existing_campaigns)}")
        print(f"  - Empty campaigns: {len(empty_campaigns)}")
        print(f"  - New labels found: {len(new_labels)}")
        if args.apply and not args.dry_run:
            print(f"  - Campaigns created: {len(new_labels) if new_labels else 0}")
            if args.auto_pause_empty:
                print(f"  - Campaigns paused: {len(empty_campaigns) if empty_campaigns else 0}")
        
        print(f"\n[SUCCESS] Weekly campaign monitoring completed!")
        
    except GoogleAdsException as ex:
        print(f"\n[ERROR] Google Ads API error: {ex}")
        for error in ex.failure.errors:
            print(f"  Error: {error.message}")
            if error.location:
                for field_path_element in error.location.field_path_elements:
                    print(f"    Field: {field_path_element.field_name}")
        return 1
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
