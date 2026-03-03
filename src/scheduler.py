#!/usr/bin/env python3
"""Scheduler for automated campaign management.

This script runs the automated campaign manager on a schedule.
Can be run as a cron job or Windows Task Scheduler task.
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Add src directory to path
sys.path.append(str(Path(__file__).parent))

from automated_campaign_manager import AutomatedCampaignManager, load_config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('automation.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def run_daily_automation(customer_id: str, config_path: Optional[str] = None):
    """Run daily automation."""
    logger.info("Starting daily automation...")
    
    try:
        config = load_config(config_path)
        manager = AutomatedCampaignManager(customer_id, config)
        
        results = manager.run_daily_analysis(apply_changes=True)
        
        logger.info(f"Daily automation completed: {results}")
        return True
        
    except Exception as e:
        logger.error(f"Daily automation failed: {e}")
        return False

def run_weekly_automation(customer_id: str, config_path: Optional[str] = None):
    """Run weekly automation."""
    logger.info("Starting weekly automation...")
    
    try:
        config = load_config(config_path)
        manager = AutomatedCampaignManager(customer_id, config)
        
        results = manager.run_weekly_analysis(apply_changes=True)
        
        logger.info(f"Weekly automation completed: {results}")
        return True
        
    except Exception as e:
        logger.error(f"Weekly automation failed: {e}")
        return False

def main():
    """Main function for scheduler."""
    parser = argparse.ArgumentParser(description="Campaign automation scheduler")
    parser.add_argument("--customer", required=True, help="Customer ID")
    parser.add_argument("--mode", choices=["daily", "weekly"], required=True, 
                       help="Automation mode")
    parser.add_argument("--config", help="Path to configuration file")
    
    args = parser.parse_args()
    
    if args.mode == "daily":
        success = run_daily_automation(args.customer, args.config)
    else:
        success = run_weekly_automation(args.customer, args.config)
    
    if success:
        logger.info("Automation completed successfully")
        sys.exit(0)
    else:
        logger.error("Automation failed")
        sys.exit(1)

if __name__ == "__main__":
    main()











