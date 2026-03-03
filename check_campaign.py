#!/usr/bin/env python3
"""
Check and update campaign feed_label settings
"""
from google.ads.googleads.client import GoogleAdsClient
from google.protobuf import field_mask_pb2
from pathlib import Path
import os

# Load config
PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "config" / "google-ads.yaml"

# Set environment variable for config
os.environ["GOOGLE_ADS_CONFIGURATION_FILE"] = str(CONFIG_PATH)

def check_campaign_settings():
    """Check current campaign shopping settings"""
    client = GoogleAdsClient.load_from_storage(str(CONFIG_PATH))
    customer_id = "5059126003"
    
    ga = client.get_service("GoogleAdsService")
    query = """
        SELECT 
            campaign.resource_name,
            campaign.name,
            campaign.shopping_setting.merchant_id,
            campaign.shopping_setting.feed_label
        FROM campaign
        WHERE campaign.name LIKE '%PMax Feed%'
        ORDER BY campaign.id DESC
        LIMIT 5
    """
    
    print("🔍 Checking campaign settings...")
    campaigns_found = False
    for row in ga.search(customer_id=customer_id, query=query):
        campaigns_found = True
        print(f"\nCampaign: {row.campaign.name}")
        print(f"Resource Name: {row.campaign.resource_name}")
        print(f"Merchant ID: {row.campaign.shopping_setting.merchant_id}")
        print(f"Feed Label: '{row.campaign.shopping_setting.feed_label}'")
        
        if not row.campaign.shopping_setting.feed_label:
            print("❌ Feed label is leeg - dit veroorzaakt het probleem!")
            return row.campaign.resource_name
        else:
            print("✅ Feed label is ingesteld")
    
    if not campaigns_found:
        print("❌ Geen PMax Feed campagnes gevonden")
        return None
    
    return None

def update_campaign_feed_label(campaign_rn):
    """Update campaign with correct feed_label"""
    client = GoogleAdsClient.load_from_storage(str(CONFIG_PATH))
    customer_id = "5059126003"
    
    print("🔧 Updating campaign feed_label...")
    
    # Create update operation
    op = client.get_type("CampaignOperation")
    camp = op.update
    camp.resource_name = campaign_rn
    camp.shopping_setting.feed_label = "NL"  # Set to your Merchant Center feed label
    
    # Set update mask
    op.update_mask.CopyFrom(field_mask_pb2.FieldMask(paths=["shopping_setting.feed_label"]))
    
    # Execute update
    try:
        client.get_service("CampaignService").mutate_campaigns(
            customer_id=customer_id, 
            operations=[op]
        )
        print("✅ Campaign feed_label succesvol bijgewerkt naar 'NL'")
        return True
    except Exception as e:
        print(f"❌ Fout bij bijwerken: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Campaign Feed Label Checker & Updater")
    print("=" * 50)
    
    # Check current settings
    campaign_to_update = check_campaign_settings()
    
    if campaign_to_update:
        print("\n" + "=" * 50)
        response = input("Wil je de feed_label bijwerken naar 'NL'? (y/n): ")
        if response.lower() == 'y':
            update_campaign_feed_label(campaign_to_update)
        else:
            print("❌ Geen wijzigingen doorgevoerd")
    else:
        print("✅ Alle campagnes zijn al correct geconfigureerd")
