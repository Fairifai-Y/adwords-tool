#!/usr/bin/env python3
"""
Performance Rules Engine for Google Ads Campaigns

This script applies performance-based rules to Google Ads campaigns:
- Pause low-performing campaigns
- Increase budget for high-performing campaigns  
- Adjust tROAS based on performance
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta

# Add the src directory to the path so we can import other modules
sys.path.append(str(Path(__file__).parent))

try:
    from google.ads.googleads.client import GoogleAdsClient
    from google.ads.googleads.errors import GoogleAdsException
    from google.protobuf import field_mask_pb2
except ImportError as e:
    print(f"Error importing Google Ads libraries: {e}")
    print("Please install google-ads library: pip install google-ads")
    sys.exit(1)

class PerformanceRulesEngine:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        # Remove any non-digit characters from customer ID
        self.customer_id = ''.join(filter(str.isdigit, str(config['customer_id'])))
        self.prefix = config['prefix']
        self.performance_period = config['performance_period']
        self.rules = config['rules']
        self.auto_apply = config['auto_apply']
        self.detailed_report = config['detailed_report']
        
        # Initialize Google Ads client
        try:
            self.client = GoogleAdsClient.load_from_storage("config/google-ads.yaml")
        except Exception as e:
            print(f"Error loading Google Ads client: {e}")
            sys.exit(1)
    
    def get_campaign_performance(self) -> List[Dict[str, Any]]:
        """Get performance data for campaigns matching the prefix"""
        query = f"""
        SELECT 
            campaign.id,
            campaign.name,
            campaign.status,
            campaign_budget.amount_micros,
            campaign_budget.delivery_method,
            campaign.maximize_conversion_value.target_roas,
            campaign.bidding_strategy_type,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions,
            metrics.conversions_value,
            campaign_budget.id
        FROM campaign 
        WHERE campaign.name LIKE '{self.prefix}%'
        AND segments.date >= '{self._get_start_date()}'
        AND segments.date <= '{self._get_end_date()}'
        """
        
        try:
            ga_service = self.client.get_service("GoogleAdsService")
            response = ga_service.search(customer_id=self.customer_id, query=query)
            
            campaigns = {}
            for row in response:
                campaign_id = row.campaign.id
                if campaign_id not in campaigns:
                    campaigns[campaign_id] = {
                        'id': campaign_id,
                        'name': row.campaign.name,
                        'status': row.campaign.status.name,
                        'budget_amount_micros': row.campaign_budget.amount_micros,
                        'budget_delivery_method': row.campaign_budget.delivery_method.name,
                        'target_roas': row.campaign.maximize_conversion_value.target_roas if row.campaign.maximize_conversion_value else None,
                        'bidding_strategy_type': row.campaign.bidding_strategy_type.name,
                        'budget_id': row.campaign_budget.id,
                        'impressions': 0,
                        'clicks': 0,
                        'cost_micros': 0,
                        'conversions': 0,
                        'conversions_value': 0
                    }
                
                # Aggregate metrics
                campaigns[campaign_id]['impressions'] += row.metrics.impressions
                campaigns[campaign_id]['clicks'] += row.metrics.clicks
                campaigns[campaign_id]['cost_micros'] += row.metrics.cost_micros
                campaigns[campaign_id]['conversions'] += row.metrics.conversions
                campaigns[campaign_id]['conversions_value'] += row.metrics.conversions_value
            
            # Calculate ROAS for each campaign
            for campaign in campaigns.values():
                if campaign['cost_micros'] > 0:
                    campaign['roas'] = campaign['conversions_value'] / (campaign['cost_micros'] / 1_000_000)
                else:
                    campaign['roas'] = 0.0
                
                campaign['cost'] = campaign['cost_micros'] / 1_000_000
                campaign['budget_amount'] = campaign['budget_amount_micros'] / 1_000_000
            
            # Get target_roas for TARGET_ROAS campaigns
            self._get_target_roas_for_campaigns(campaigns)
            
            return list(campaigns.values())
            
        except GoogleAdsException as ex:
            print(f"Google Ads API error: {ex}")
            print("Exiting due to Google Ads API error")
            sys.exit(1)
    
    def _get_target_roas_for_campaigns(self, campaigns: Dict[str, Dict[str, Any]]):
        """Get target_roas for TARGET_ROAS campaigns via separate query"""
        try:
            ga = self.client.get_service("GoogleAdsService")
            
            # Get campaign IDs that need target_roas
            campaign_ids = [str(campaign['id']) for campaign in campaigns.values() 
                          if campaign.get('bidding_strategy_type') == 'TARGET_ROAS' and not campaign.get('target_roas')]
            
            if not campaign_ids:
                return
            
            # Query target_roas for TARGET_ROAS campaigns
            query = f"""
                SELECT
                    campaign.id,
                    campaign.target_roas
                FROM campaign
                WHERE campaign.id IN ({','.join(campaign_ids)})
                AND campaign.bidding_strategy_type = 'TARGET_ROAS'
            """
            
            for row in ga.search(customer_id=self.customer_id, query=query):
                campaign_id = str(row.campaign.id)
                if campaign_id in campaigns:
                    campaigns[campaign_id]['target_roas'] = row.campaign.target_roas
                    
        except Exception as e:
            print(f"Warning: Could not get target_roas for TARGET_ROAS campaigns: {e}")
    
    def _get_start_date(self) -> str:
        """Get start date for performance period"""
        start_date = datetime.now() - timedelta(days=self.performance_period)
        return start_date.strftime('%Y-%m-%d')
    
    def _get_end_date(self) -> str:
        """Get end date for performance period"""
        return datetime.now().strftime('%Y-%m-%d')
    
    def apply_rules(self, campaigns: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Apply performance rules to campaigns"""
        results = {
            'paused_campaigns': [],
            'budget_increased_campaigns': [],
            'troas_adjusted_campaigns': [],
            'errors': []
        }
        
        for campaign in campaigns:
            try:
                # Rule 1: Pause low-performing campaigns
                if self.rules.get('pause_low_performing', {}).get('enabled', False):
                    if self._should_pause_campaign(campaign):
                        if self.auto_apply:
                            self._pause_campaign(campaign['id'])
                        results['paused_campaigns'].append({
                            'id': campaign['id'],
                            'name': campaign['name'],
                            'roas': campaign['roas'],
                            'impressions': campaign['impressions'],
                            'reason': 'Low performance'
                        })
                
                # Rule 2: Increase budget for high-performing campaigns
                if self.rules.get('increase_budget', {}).get('enabled', False):
                    if self._should_increase_budget(campaign):
                        if self.auto_apply:
                            self._increase_budget(campaign)
                        results['budget_increased_campaigns'].append({
                            'id': campaign['id'],
                            'name': campaign['name'],
                            'roas': campaign['roas'],
                            'current_budget': campaign['budget_amount'],
                            'new_budget': campaign['budget_amount'] * (1 + self.rules['increase_budget']['budget_increase_percent'] / 100)
                        })
                
                # Rule 3: Adjust tROAS based on performance
                if self.rules.get('adjust_troas', {}).get('enabled', False):
                    if self._should_adjust_troas(campaign):
                        if self.auto_apply:
                            self._adjust_troas(campaign)
                        results['troas_adjusted_campaigns'].append({
                            'id': campaign['id'],
                            'name': campaign['name'],
                            'roas': campaign['roas'],
                            'current_troas': campaign.get('target_roas', 0) or 0,
                            'new_troas': self._calculate_new_troas(campaign)
                        })
                        
            except Exception as e:
                results['errors'].append({
                    'campaign_id': campaign['id'],
                    'campaign_name': campaign['name'],
                    'error': str(e)
                })
        
        return results
    
    def _should_pause_campaign(self, campaign: Dict[str, Any]) -> bool:
        """Check if campaign should be paused based on rules"""
        rule = self.rules.get('pause_low_performing', {})
        min_roas = rule.get('min_roas', 2.0)
        min_impressions = rule.get('min_impressions', 100)
        
        return (campaign['roas'] < min_roas and 
                campaign['impressions'] >= min_impressions and
                campaign['status'] == 'ENABLED')
    
    def _should_increase_budget(self, campaign: Dict[str, Any]) -> bool:
        """Check if campaign budget should be increased based on rules"""
        rule = self.rules.get('increase_budget', {})
        min_roas = rule.get('min_roas', 4.0)
        
        return (campaign['roas'] >= min_roas and 
                campaign['status'] == 'ENABLED')
    
    def _should_adjust_troas(self, campaign: Dict[str, Any]) -> bool:
        """Check if campaign tROAS should be adjusted based on rules"""
        rule = self.rules.get('adjust_troas', {})
        high_roas_threshold = 5.0
        low_roas_threshold = 3.0
        
        return (campaign['roas'] > high_roas_threshold or 
                campaign['roas'] < low_roas_threshold) and campaign['status'] == 'ENABLED'
    
    def _calculate_new_troas(self, campaign: Dict[str, Any]) -> float:
        """Calculate new tROAS based on current performance"""
        rule = self.rules.get('adjust_troas', {})
        current_troas = campaign['target_roas'] or 0.0
        
        if campaign['roas'] > 5.0:
            return current_troas + rule.get('troas_increase', 0.5)
        elif campaign['roas'] < 3.0:
            return max(0.1, current_troas - rule.get('troas_decrease', 0.5))
        
        return current_troas
    
    def _pause_campaign(self, campaign_id: int):
        """Pause a campaign"""
        campaign_service = self.client.get_service("CampaignService")
        
        campaign_operation = self.client.get_type("CampaignOperation")
        campaign = campaign_operation.update
        campaign.resource_name = f"customers/{self.customer_id}/campaigns/{campaign_id}"
        campaign.status = self.client.enums.CampaignStatusEnum.PAUSED
        
        campaign_operation.update_mask.CopyFrom(
            field_mask_pb2.FieldMask(paths=["status"])
        )
        
        campaign_service.mutate_campaigns(customer_id=self.customer_id, operations=[campaign_operation])
    
    def _increase_budget(self, campaign: Dict[str, Any]):
        """Increase campaign budget"""
        budget_service = self.client.get_service("CampaignBudgetService")
        
        increase_percent = self.rules['increase_budget']['budget_increase_percent']
        new_amount = campaign['budget_amount'] * (1 + increase_percent / 100)
        
        budget_operation = self.client.get_type("CampaignBudgetOperation")
        budget = budget_operation.update
        budget.resource_name = f"customers/{self.customer_id}/campaignBudgets/{campaign['budget_id']}"
        budget.amount_micros = int(new_amount * 1_000_000)
        
        budget_operation.update_mask.CopyFrom(
            field_mask_pb2.FieldMask(paths=["amount_micros"])
        )
        
        budget_service.mutate_campaign_budgets(customer_id=self.customer_id, operations=[budget_operation])
    
    def _adjust_troas(self, campaign: Dict[str, Any]):
        """Adjust campaign tROAS"""
        campaign_service = self.client.get_service("CampaignService")
        
        new_troas = self._calculate_new_troas(campaign)
        
        campaign_operation = self.client.get_type("CampaignOperation")
        campaign_obj = campaign_operation.update
        campaign_obj.resource_name = f"customers/{self.customer_id}/campaigns/{campaign['id']}"
        campaign_obj.maximize_conversion_value.target_roas = new_troas
        
        campaign_operation.update_mask.CopyFrom(
            field_mask_pb2.FieldMask(paths=["maximize_conversion_value.target_roas"])
        )
        
        campaign_service.mutate_campaigns(customer_id=self.customer_id, operations=[campaign_operation])
    
    def generate_report(self, campaigns: List[Dict[str, Any]], results: Dict[str, Any]) -> str:
        """Generate a detailed report of the performance rules application"""
        report = []
        report.append("=" * 80)
        report.append("PERFORMANCE RULES REPORT")
        report.append("=" * 80)
        report.append(f"Customer ID: {self.customer_id}")
        report.append(f"Campaign Prefix: {self.prefix}")
        report.append(f"Performance Period: {self.performance_period} days")
        report.append(f"Auto Apply: {self.auto_apply}")
        report.append(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")
        
        # Campaign performance summary
        report.append("CAMPAIGN PERFORMANCE SUMMARY")
        report.append("-" * 40)
        for campaign in campaigns:
            report.append(f"Campaign: {campaign['name']}")
            report.append(f"  ID: {campaign['id']}")
            report.append(f"  Status: {campaign['status']}")
            report.append(f"  ROAS: {campaign['roas']:.2f}")
            report.append(f"  Impressions: {campaign['impressions']:,}")
            report.append(f"  Clicks: {campaign['clicks']:,}")
            report.append(f"  Cost: €{campaign['cost']:.2f}")
            report.append(f"  Budget: €{campaign['budget_amount']:.2f}")
            report.append(f"  Target ROAS: {campaign['target_roas'] or 'Not set'}")
            report.append(f"  Bidding Strategy: {campaign['bidding_strategy_type']}")
            report.append("")
        
        # Rules applied
        report.append("RULES APPLIED")
        report.append("-" * 40)
        
        if results['paused_campaigns']:
            report.append(f"Paused {len(results['paused_campaigns'])} low-performing campaigns:")
            for campaign in results['paused_campaigns']:
                report.append(f"  - {campaign['name']} (ROAS: {campaign['roas']:.2f})")
        else:
            report.append("No campaigns were paused.")
        
        if results['budget_increased_campaigns']:
            report.append(f"Increased budget for {len(results['budget_increased_campaigns'])} high-performing campaigns:")
            for campaign in results['budget_increased_campaigns']:
                report.append(f"  - {campaign['name']} (ROAS: {campaign['roas']:.2f})")
        else:
            report.append("No campaign budgets were increased.")
        
        if results['troas_adjusted_campaigns']:
            report.append(f"Adjusted tROAS for {len(results['troas_adjusted_campaigns'])} campaigns:")
            for campaign in results['troas_adjusted_campaigns']:
                report.append(f"  - {campaign['name']} (ROAS: {campaign['roas']:.2f})")
        else:
            report.append("No campaign tROAS were adjusted.")
        
        if results['errors']:
            report.append(f"Errors encountered: {len(results['errors'])}")
            for error in results['errors']:
                report.append(f"  - {error['campaign_name']}: {error['error']}")
        
        report.append("")
        report.append("=" * 80)
        
        return "\n".join(report)
    
    def run(self):
        """Main execution method"""
        print(f"Starting performance rules engine for customer {self.customer_id}")
        print(f"Campaign prefix: {self.prefix}")
        print(f"Performance period: {self.performance_period} days")
        print(f"Auto apply: {self.auto_apply}")
        print("")
        
        # Get campaign performance data
        print("Fetching campaign performance data...")
        campaigns = self.get_campaign_performance()
        
        if not campaigns:
            print("No campaigns found matching the criteria.")
            return
        
        print(f"Found {len(campaigns)} campaigns to analyze")
        print("")
        
        # Apply rules
        print("Applying performance rules...")
        results = self.apply_rules(campaigns)
        
        # Generate detailed logging
        self._log_detailed_results(campaigns, results)
        
        # Generate report
        if self.detailed_report:
            report = self.generate_report(campaigns, results)
            print(report)
        else:
            # Simple summary
            print(f"Rules applied successfully:")
            print(f"  - Paused campaigns: {len(results['paused_campaigns'])}")
            print(f"  - Budget increases: {len(results['budget_increased_campaigns'])}")
            print(f"  - tROAS adjustments: {len(results['troas_adjusted_campaigns'])}")
            print(f"  - Errors: {len(results['errors'])}")
        
        if not self.auto_apply:
            print("\nNote: This was a dry run. No changes were actually applied.")
            print("Set auto_apply=True to apply changes.")
    
    def _log_detailed_results(self, campaigns: List[Dict[str, Any]], results: Dict[str, Any]):
        """Log detailed results of performance rules application."""
        print("\n" + "="*80)
        print("DETAILED PERFORMANCE RULES ANALYSIS")
        print("="*80)
        
        # Show campaign performance summary
        enabled_campaigns = [c for c in campaigns if c['status'] == 'ENABLED']
        print(f"\nCAMPAIGN PERFORMANCE SUMMARY:")
        print(f"  Total campaigns analyzed: {len(campaigns)}")
        print(f"  Enabled campaigns: {len(enabled_campaigns)}")
        print(f"  Removed/Paused campaigns: {len(campaigns) - len(enabled_campaigns)}")
        
        if enabled_campaigns:
            # Calculate performance metrics
            total_impressions = sum(c['impressions'] for c in enabled_campaigns)
            total_clicks = sum(c['clicks'] for c in enabled_campaigns)
            total_cost = sum(c['cost'] for c in enabled_campaigns)
            total_conversions = sum(c['conversions'] for c in enabled_campaigns)
            total_value = sum(c['conversions_value'] for c in enabled_campaigns)
            
            avg_roas = total_value / total_cost if total_cost > 0 else 0
            avg_ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0
            avg_cpa = total_cost / total_conversions if total_conversions > 0 else 0
            
            print(f"  Total impressions: {total_impressions:,}")
            print(f"  Total clicks: {total_clicks:,}")
            print(f"  Total cost: €{total_cost:.2f}")
            print(f"  Total conversions: {total_conversions}")
            print(f"  Total value: €{total_value:.2f}")
            print(f"  Average ROAS: {avg_roas:.2f}")
            print(f"  Average CTR: {avg_ctr:.2f}%")
            print(f"  Average CPA: €{avg_cpa:.2f}")
        
        # Show specific rule applications
        print(f"\nRULE APPLICATIONS:")
        
        if results['paused_campaigns']:
            print(f"\n  PAUSE LOW-PERFORMING CAMPAIGNS ({len(results['paused_campaigns'])} campaigns):")
            for campaign in results['paused_campaigns']:
                print(f"    - {campaign['name']}")
                print(f"      - Current ROAS: {campaign['roas']:.2f}")
                print(f"      - Impressions: {campaign['impressions']:,}")
                print(f"      - Reason: {campaign['reason']}")
        else:
            print(f"\n  PAUSE LOW-PERFORMING CAMPAIGNS: 0 campaigns")
            print(f"      No campaigns met the criteria for pausing")
        
        if results['budget_increased_campaigns']:
            print(f"\n  INCREASE BUDGET ({len(results['budget_increased_campaigns'])} campaigns):")
            for campaign in results['budget_increased_campaigns']:
                print(f"    - {campaign['name']}")
                print(f"      - Current ROAS: {campaign['roas']:.2f}")
                print(f"      - Current budget: €{campaign['current_budget']:.2f}")
                print(f"      - New budget: €{campaign['new_budget']:.2f}")
                print(f"      - Increase: +{((campaign['new_budget'] / campaign['current_budget'] - 1) * 100):.1f}%")
        else:
            print(f"\n  INCREASE BUDGET: 0 campaigns")
            print(f"      No campaigns met the criteria for budget increase")
        
        if results['troas_adjusted_campaigns']:
            print(f"\n  ADJUST tROAS ({len(results['troas_adjusted_campaigns'])} campaigns):")
            for campaign in results['troas_adjusted_campaigns']:
                print(f"    - {campaign['name']}")
                print(f"      - Current ROAS: {campaign['roas']:.2f}")
                current_troas = campaign.get('current_troas', 0) or 0
                new_troas = campaign.get('new_troas', 0) or 0
                troas_display = f"{current_troas:.2f}" if current_troas > 0 else "Not set"
                print(f"      - Current tROAS: {troas_display}")
                print(f"      - New tROAS: {new_troas:.2f}")
                if current_troas and new_troas:
                    change = new_troas - current_troas
                    change_pct = (change / current_troas * 100) if current_troas > 0 else 0
                    print(f"      - Change: {change:+.2f} ({change_pct:+.1f}%)")
                else:
                    print(f"      - Change: N/A (no current tROAS)")
        else:
            print(f"\n  ADJUST tROAS: 0 campaigns")
            print(f"      No campaigns met the criteria for tROAS adjustment")
        
        if results['errors']:
            print(f"\n  ERRORS ({len(results['errors'])} errors):")
            for error in results['errors']:
                print(f"    - {error['campaign_name']}: {error['error']}")
        else:
            print(f"\n  ERRORS: 0 errors")
        
        # Show rule criteria
        print(f"\nRULE CRITERIA:")
        pause_rule = self.rules.get('pause_low_performing', {})
        if pause_rule.get('enabled', False):
            print(f"  - Pause campaigns with ROAS < {pause_rule.get('min_roas', 2.0)} and impressions >= {pause_rule.get('min_impressions', 100)}")
        
        budget_rule = self.rules.get('increase_budget', {})
        if budget_rule.get('enabled', False):
            print(f"  - Increase budget for campaigns with ROAS >= {budget_rule.get('min_roas', 4.0)} by {budget_rule.get('budget_increase_percent', 20)}%")
        
        troas_rule = self.rules.get('adjust_troas', {})
        if troas_rule.get('enabled', False):
            print(f"  - Adjust tROAS for campaigns with ROAS > 5.0 or ROAS < 3.0")
            print(f"    - Increase by {troas_rule.get('troas_increase', 0.5)} for high ROAS")
            print(f"    - Decrease by {troas_rule.get('troas_decrease', 0.5)} for low ROAS")
        
        print("="*80)

def main():
    parser = argparse.ArgumentParser(description='Apply performance rules to Google Ads campaigns')
    parser.add_argument('--config', required=True, help='Path to configuration JSON file')
    
    args = parser.parse_args()
    
    # Load .env file
    from dotenv import load_dotenv
    load_dotenv()
    
    # Load configuration
    try:
        with open(args.config, 'r') as f:
            config = json.load(f)
    except Exception as e:
        print(f"Error loading configuration: {e}")
        sys.exit(1)
    
    # Validate required fields
    required_fields = ['customer_id', 'prefix', 'performance_period', 'rules']
    for field in required_fields:
        if field not in config:
            print(f"Missing required field: {field}")
            sys.exit(1)
    
    # Run the performance rules engine
    try:
        engine = PerformanceRulesEngine(config)
        engine.run()
    except Exception as e:
        print(f"Error running performance rules engine: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
