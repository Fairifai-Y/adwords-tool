#!/usr/bin/env python3
"""Test pmax_feed_only.py functions"""

from google.ads.googleads.client import GoogleAdsClient
from dotenv import load_dotenv
import sys
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent / 'src'))

from pmax_feed_only import _create_pmax_campaign, _create_budget
import time

load_dotenv()

# Initialize Google Ads client
client = GoogleAdsClient.load_from_storage('config/google-ads.yaml')
customer_id = '1561495323'

print('Testing pmax_feed_only.py functions...')

try:
    # Create budget
    budget_rn = _create_budget(client, customer_id, f'TEST-BUDGET-{int(time.time())}', 25 * 1_000_000)
    print(f'✓ Budget created: {budget_rn}')
    
    # Create campaign
    campaign_rn = _create_pmax_campaign(client, customer_id, f'TEST-CAMPAIGN-{int(time.time())}', budget_rn, 389429754, 'NL', False, 6.5)
    print(f'✓ Campaign created! ID: {campaign_rn.split("/")[-1]}')
    
except Exception as e:
    print(f'✗ Failed: {e}')











