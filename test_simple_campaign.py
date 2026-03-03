#!/usr/bin/env python3
"""Test simple campaign creation"""

from google.ads.googleads.client import GoogleAdsClient
from dotenv import load_dotenv

load_dotenv()

# Initialize Google Ads client
client = GoogleAdsClient.load_from_storage('config/google-ads.yaml')
customer_id = '1561495323'

print('Testing simple campaign creation...')

# Create budget
campaign_budget_service = client.get_service("CampaignBudgetService")
budget_operation = client.get_type("CampaignBudgetOperation")
budget = budget_operation.create
budget.name = f"TEST-BUDGET-{int(__import__('time').time())}"
budget.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD
budget.amount_micros = 25 * 1_000_000  # €25
budget.explicitly_shared = False

try:
    budget_response = campaign_budget_service.mutate_campaign_budgets(
        customer_id=customer_id, operations=[budget_operation]
    )
    budget_resource_name = budget_response.results[0].resource_name
    print(f"✓ Budget created: {budget_resource_name}")
    
    # Create campaign
    campaign_service = client.get_service("CampaignService")
    campaign_operation = client.get_type("CampaignOperation")
    campaign = campaign_operation.create
    campaign.name = f"TEST-CAMPAIGN-{int(__import__('time').time())}"
    campaign.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.SHOPPING
    campaign.status = client.enums.CampaignStatusEnum.PAUSED
    campaign.campaign_budget = budget_resource_name
    
    # Set Shopping Setting
    campaign.shopping_setting.merchant_id = 389429754
    campaign.shopping_setting.feed_label = ""
    
    # Required field for EU political advertising
    campaign.contains_eu_political_advertising = 0
    
    # Required bidding strategy
    campaign.bidding_strategy_type = client.enums.BiddingStrategyTypeEnum.MANUAL_CPC
    
    campaign_response = campaign_service.mutate_campaigns(
        customer_id=customer_id, operations=[campaign_operation]
    )
    
    campaign_id = campaign_response.results[0].resource_name.split('/')[-1]
    print(f"✓ Campaign created! ID: {campaign_id}")
    
except Exception as e:
    print(f"✗ Failed: {e}")
