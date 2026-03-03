#!/usr/bin/env python3
"""Automated Campaign Manager - Enhanced version of label_campaigns.py

This script extends the original label_campaigns.py with:
- PostgreSQL database storage for performance data
- Automated decision rules for campaign optimization
- Campaign updates based on performance
- Segmentation per seller x price bucket
- Daily/weekly automation support

Usage:
  python src/automated_campaign_manager.py --customer 5059126003 --mode daily
  python src/automated_campaign_manager.py --customer 5059126003 --mode weekly --apply
"""

import argparse
import logging
import os
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

# Add src directory to path for imports
sys.path.append(str(Path(__file__).parent))

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

# Import our new modules
from database import DatabaseManager, convert_labels_to_performance_data
from decision_engine import DecisionEngine, DecisionRules, create_decision_rules_from_config
from campaign_updater import CampaignUpdater, create_campaign_updater

# Import original functionality
from label_campaigns import (
    discover_labels, 
    _create_pmax_campaign, 
    _create_pmax_asset_group,
    add_listing_group_for_label,
    _add_campaign_criteria,
    _digits_only,
    _retry
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "google-ads.yaml"

class AutomatedCampaignManager:
    """Main class for automated campaign management."""
    
    def __init__(self, customer_id: str, config: Optional[Dict[str, Any]] = None):
        """Initialize the campaign manager."""
        self.customer_id = customer_id
        self.config = config or {}
        self.db = DatabaseManager()
        self.decision_engine = DecisionEngine(
            create_decision_rules_from_config(self.config.get('decision_rules', {}))
        )
        
        # Initialize Google Ads client
        self.client = self._init_google_ads_client()
        self.campaign_updater = create_campaign_updater(self.client)
    
    def _init_google_ads_client(self) -> GoogleAdsClient:
        """Initialize Google Ads client."""
        cfg = os.getenv("GOOGLE_ADS_CONFIGURATION_FILE")
        if not cfg:
            cfg = str(CONFIG_PATH)
        
        logger.info(f"Using Google Ads config: {cfg}")
        return GoogleAdsClient.load_from_storage(cfg)
    
    def run_daily_analysis(self, apply_changes: bool = False) -> Dict[str, Any]:
        """Run daily analysis and data collection."""
        logger.info("Starting daily analysis...")
        
        results = {
            'labels_discovered': 0,
            'data_saved': 0,
            'decisions_made': 0,
            'campaigns_updated': 0,
            'errors': []
        }
        
        try:
            # 1. Discover labels and collect performance data
            logger.info("Discovering labels and collecting performance data...")
            labels = discover_labels(
                self.client, 
                self.customer_id, 
                label_index=0,  # sellers
                include_label_1=True,  # marge in %
                include_label_2=True   # price buckets
            )
            
            results['labels_discovered'] = len(labels)
            logger.info(f"Discovered {len(labels)} labels")
            
            # 2. Convert to performance data and save to database
            logger.info("Saving performance data to database...")
            performance_data = convert_labels_to_performance_data(
                labels, 
                label_index=0,
                country=self.config.get('country', 'NL'),
                product_type=self.config.get('product_type', 'ALL')
            )
            
            if self.db.save_label_data(performance_data):
                results['data_saved'] = len(performance_data)
                logger.info(f"Saved {len(performance_data)} performance records")
            else:
                results['errors'].append("Failed to save performance data to database")
            
            # 3. Get current campaign performance
            logger.info("Getting current campaign performance...")
            current_campaigns = self.campaign_updater.get_campaign_performance(
                self.customer_id, 
                days_back=30
            )
            
            # 4. Make decisions based on performance
            logger.info("Evaluating performance and making decisions...")
            performance_df = self.db.get_weekly_trends(weeks=4)
            
            if not performance_df.empty:
                decisions = self.decision_engine.evaluate_seller_performance(
                    performance_df, 
                    current_campaigns
                )
                results['decisions_made'] = len(decisions)
                logger.info(f"Made {len(decisions)} decisions")
                
                # 5. Apply decisions if requested
                if apply_changes and decisions:
                    logger.info("Applying campaign decisions...")
                    update_results = self.campaign_updater.apply_decisions(
                        decisions, 
                        self.customer_id
                    )
                    
                    successful_updates = sum(1 for r in update_results if r.success)
                    results['campaigns_updated'] = successful_updates
                    logger.info(f"Successfully updated {successful_updates} campaigns")
                    
                    # Save decisions to database
                    for decision in decisions:
                        decision_data = {
                            'date': date.today(),
                            'campaign_id': decision.campaign_id,
                            'campaign_name': decision.campaign_name,
                            'seller': decision.seller,
                            'price_bucket': decision.price_bucket,
                            'decision': decision.decision.value,
                            'current_budget': decision.current_budget,
                            'new_budget': decision.new_budget,
                            'current_troas': decision.current_troas,
                            'new_troas': decision.new_troas,
                            'reason': decision.reason,
                            'applied': apply_changes
                        }
                        self.db.save_campaign_decision(decision_data)
                else:
                    logger.info("Dry run - no changes applied")
            
        except Exception as e:
            logger.error(f"Error in daily analysis: {e}")
            results['errors'].append(str(e))
        
        return results
    
    def run_weekly_analysis(self, apply_changes: bool = False) -> Dict[str, Any]:
        """Run weekly analysis with more comprehensive decision making."""
        logger.info("Starting weekly analysis...")
        
        results = {
            'labels_discovered': 0,
            'data_saved': 0,
            'decisions_made': 0,
            'campaigns_updated': 0,
            'new_campaigns_created': 0,
            'errors': []
        }
        
        try:
            # 1. Run daily analysis first
            daily_results = self.run_daily_analysis(apply_changes)
            results.update(daily_results)
            
            # 2. Check for new sellers that need campaigns
            logger.info("Checking for new sellers needing campaigns...")
            new_campaigns = self._create_campaigns_for_new_sellers(apply_changes)
            results['new_campaigns_created'] = new_campaigns
            
            # 3. Generate weekly report
            self._generate_weekly_report()
            
        except Exception as e:
            logger.error(f"Error in weekly analysis: {e}")
            results['errors'].append(str(e))
        
        return results
    
    def _create_campaigns_for_new_sellers(self, apply_changes: bool) -> int:
        """Create campaigns for new sellers that don't have any yet."""
        # Get all sellers from performance data
        performance_df = self.db.get_weekly_trends(weeks=4)
        if performance_df.empty:
            return 0
        
        sellers = performance_df['seller'].unique()
        created_count = 0
        
        # Get existing campaigns
        current_campaigns = self.campaign_updater.get_campaign_performance(
            self.customer_id, 
            days_back=30
        )
        
        existing_sellers = set()
        for campaign in current_campaigns.values():
            # Extract seller from campaign name (assuming format: "prefix - seller - timestamp")
            if ' - ' in campaign['name']:
                parts = campaign['name'].split(' - ')
                if len(parts) >= 2:
                    existing_sellers.add(parts[1])
        
        # Find new sellers
        new_sellers = [s for s in sellers if s not in existing_sellers]
        
        if new_sellers and apply_changes:
            logger.info(f"Creating campaigns for {len(new_sellers)} new sellers...")
            
            for seller in new_sellers:
                try:
                    # Create campaign for this seller
                    campaign_name = f"PMax Feed - {seller} - {datetime.now().strftime('%Y%m%d%H%M%S')}"
                    
                    campaign_rn = _create_pmax_campaign(
                        client=self.client,
                        customer_id=self.customer_id,
                        campaign_name=campaign_name,
                        daily_budget_micros=int(self.config.get('default_budget', 5.0) * 1_000_000),
                        campaign_target_roas=self.config.get('default_troas', 4.0),
                        is_feed_only=True,
                        merchant_id=self.config.get('merchant_id'),
                        target_languages=self.config.get('target_languages', 'nl'),
                        target_countries=self.config.get('target_countries', 'NL'),
                        feed_label=self.config.get('feed_label', 'NL')
                    )
                    
                    # Create asset group with listing group
                    asset_group_name = f"{campaign_name} - Asset Group"
                    asset_group_rn = _create_pmax_asset_group(
                        client=self.client,
                        customer_id=self.customer_id,
                        campaign_rn=campaign_rn,
                        asset_group_name=asset_group_name,
                        label_index=0,  # custom_label_0 for sellers
                        label_value=seller,
                        is_feed_only=True,
                        merchant_id=self.config.get('merchant_id'),
                        target_languages=self.config.get('target_languages', 'nl'),
                        target_countries=self.config.get('target_countries', 'NL')
                    )
                    
                    created_count += 1
                    logger.info(f"Created campaign for seller: {seller}")
                    
                    # Small delay to avoid rate limiting
                    import time
                    time.sleep(2)
                    
                except Exception as e:
                    logger.error(f"Error creating campaign for seller {seller}: {e}")
        
        return created_count
    
    def _generate_weekly_report(self):
        """Generate weekly performance report."""
        logger.info("Generating weekly report...")
        
        # Get weekly trends
        trends_df = self.db.get_weekly_trends(weeks=4)
        
        if trends_df.empty:
            logger.info("No data available for weekly report")
            return
        
        # Generate report
        report_path = PROJECT_ROOT / f"weekly_report_{date.today().strftime('%Y%m%d')}.csv"
        trends_df.to_csv(report_path, index=False)
        
        logger.info(f"Weekly report saved to: {report_path}")
        
        # Print summary
        print("\n" + "="*60)
        print("WEEKLY PERFORMANCE SUMMARY")
        print("="*60)
        
        # Top performers
        top_performers = trends_df.nlargest(10, 'total_value')
        print("\nTOP 10 PERFORMERS (by value):")
        for _, row in top_performers.iterrows():
            print(f"  {row['seller']} ({row['price_bucket']}): "
                  f"€{row['total_value']:.2f} | ROAS: {row['avg_roas']:.2f} | "
                  f"Impressions: {row['total_impressions']:,}")
        
        # Underperformers
        underperformers = trends_df[
            (trends_df['avg_roas'] < 2.0) & 
            (trends_df['total_impressions'] > 1000)
        ].nsmallest(10, 'avg_roas')
        
        if not underperformers.empty:
            print("\nUNDERPERFORMERS (ROAS < 2.0):")
            for _, row in underperformers.iterrows():
                print(f"  {row['seller']} ({row['price_bucket']}): "
                      f"ROAS: {row['avg_roas']:.2f} | "
                      f"Impressions: {row['total_impressions']:,}")
        
        print("="*60)

def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Automated Campaign Manager - Enhanced label_campaigns.py"
    )
    
    parser.add_argument("--customer", required=True, help="Target customer id (linked account)")
    parser.add_argument("--mode", choices=["daily", "weekly"], default="daily", 
                       help="Analysis mode: daily or weekly")
    parser.add_argument("--apply", action="store_true", 
                       help="Apply changes (default: dry run)")
    parser.add_argument("--config", help="Path to configuration file (JSON)")
    parser.add_argument("--merchant-id", help="Merchant Center ID")
    parser.add_argument("--default-budget", type=float, default=5.0, 
                       help="Default daily budget for new campaigns")
    parser.add_argument("--default-troas", type=float, default=4.0, 
                       help="Default target ROAS for new campaigns")
    parser.add_argument("--country", default="NL", help="Target country")
    parser.add_argument("--target-languages", default="nl", 
                       help="Target languages (comma-separated)")
    parser.add_argument("--target-countries", default="NL", 
                       help="Target countries (comma-separated)")
    parser.add_argument("--feed-label", default="NL", 
                       help="Feed label for shopping setting")
    
    return parser.parse_args()

def load_config(config_path: Optional[str]) -> Dict[str, Any]:
    """Load configuration from file."""
    if not config_path or not os.path.exists(config_path):
        return {}
    
    import json
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading config file {config_path}: {e}")
        return {}

def main():
    """Main function."""
    args = parse_args()
    
    # Load .env file
    from dotenv import load_dotenv
    load_dotenv()
    
    # Load configuration
    config = load_config(args.config)
    
    # Override config with command line arguments
    if args.merchant_id:
        config['merchant_id'] = args.merchant_id
    config['default_budget'] = args.default_budget
    config['default_troas'] = args.default_troas
    config['country'] = args.country
    config['target_languages'] = args.target_languages
    config['target_countries'] = args.target_countries
    config['feed_label'] = args.feed_label
    
    # Initialize campaign manager
    manager = AutomatedCampaignManager(args.customer, config)
    
    # Run analysis based on mode
    if args.mode == "daily":
        results = manager.run_daily_analysis(args.apply)
    else:
        results = manager.run_weekly_analysis(args.apply)
    
    # Print results
    print("\n" + "="*60)
    print("ANALYSIS RESULTS")
    print("="*60)
    print(f"Labels discovered: {results['labels_discovered']}")
    print(f"Data records saved: {results['data_saved']}")
    print(f"Decisions made: {results['decisions_made']}")
    print(f"Campaigns updated: {results['campaigns_updated']}")
    if 'new_campaigns_created' in results:
        print(f"New campaigns created: {results['new_campaigns_created']}")
    
    if results['errors']:
        print(f"\nErrors: {len(results['errors'])}")
        for error in results['errors']:
            print(f"  - {error}")
    
    print("="*60)
    
    if args.apply:
        print("Changes have been applied to Google Ads.")
    else:
        print("Dry run completed - no changes were applied.")
        print("Use --apply to apply changes.")

if __name__ == "__main__":
    main()
