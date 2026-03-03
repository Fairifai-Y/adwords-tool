#!/usr/bin/env python3
"""Quick start script for automated campaign management.

This script helps you set up and test the automated campaign management system.
"""

import os
import sys
import subprocess
from pathlib import Path

def check_dependencies():
    """Check if all required dependencies are installed."""
    print("🔍 Checking dependencies...")
    
    required_packages = [
        'psycopg2-binary',
        'pandas',
        'google-ads',
        'python-dotenv'
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
            print(f"  ✅ {package}")
        except ImportError:
            print(f"  ❌ {package}")
            missing_packages.append(package)
    
    if missing_packages:
        print(f"\n📦 Installing missing packages: {', '.join(missing_packages)}")
        subprocess.check_call([sys.executable, '-m', 'pip', 'install'] + missing_packages)
        print("✅ Dependencies installed!")
    else:
        print("✅ All dependencies are installed!")

def check_database_connection():
    """Check database connection."""
    print("\n🗄️  Checking database connection...")
    
    try:
        from src.database import DatabaseManager
        db = DatabaseManager()
        print("✅ Database connection successful!")
        return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        print("\n💡 To fix this:")
        print("1. Install PostgreSQL")
        print("2. Create database: CREATE DATABASE adwords_automation;")
        print("3. Set environment variables:")
        print("   export DATABASE_URL='postgresql://user:password@localhost:5432/adwords_automation'")
        return False

def check_google_ads_connection():
    """Check Google Ads API connection."""
    print("\n🔗 Checking Google Ads API connection...")
    
    try:
        from google.ads.googleads.client import GoogleAdsClient
        config_path = Path("config/google-ads.yaml")
        if not config_path.exists():
            print("❌ Google Ads config file not found!")
            print("💡 Make sure config/google-ads.yaml exists")
            return False
        
        client = GoogleAdsClient.load_from_storage(str(config_path))
        print("✅ Google Ads API connection successful!")
        return True
    except Exception as e:
        print(f"❌ Google Ads API connection failed: {e}")
        print("💡 Check your config/google-ads.yaml file")
        return False

def run_test_analysis(customer_id):
    """Run a test analysis."""
    print(f"\n🧪 Running test analysis for customer {customer_id}...")
    
    try:
        from src.automated_campaign_manager import AutomatedCampaignManager
        
        # Run daily analysis in dry-run mode
        manager = AutomatedCampaignManager(customer_id)
        results = manager.run_daily_analysis(apply_changes=False)
        
        print("✅ Test analysis completed!")
        print(f"📊 Results:")
        print(f"  - Labels discovered: {results['labels_discovered']}")
        print(f"  - Data records saved: {results['data_saved']}")
        print(f"  - Decisions made: {results['decisions_made']}")
        
        if results['errors']:
            print(f"  - Errors: {len(results['errors'])}")
            for error in results['errors']:
                print(f"    - {error}")
        
        return True
    except Exception as e:
        print(f"❌ Test analysis failed: {e}")
        return False

def main():
    """Main function."""
    print("🚀 Automated Campaign Management - Quick Start")
    print("=" * 50)
    
    # Check dependencies
    check_dependencies()
    
    # Check database connection
    db_ok = check_database_connection()
    
    # Check Google Ads connection
    ads_ok = check_google_ads_connection()
    
    if not db_ok or not ads_ok:
        print("\n❌ Setup incomplete. Please fix the issues above and run again.")
        return
    
    # Get customer ID
    customer_id = input("\n📝 Enter your Google Ads customer ID: ").strip()
    if not customer_id:
        print("❌ Customer ID is required!")
        return
    
    # Run test analysis
    if run_test_analysis(customer_id):
        print("\n🎉 Setup completed successfully!")
        print("\n📚 Next steps:")
        print("1. Review the configuration in config/automation_config.json")
        print("2. Run daily analysis: python src/automated_campaign_manager.py --customer YOUR_ID --mode daily")
        print("3. Run with changes: python src/automated_campaign_manager.py --customer YOUR_ID --mode daily --apply")
        print("4. Set up automation with cron or Task Scheduler")
        print("5. Read AUTOMATION_README.md for detailed instructions")
    else:
        print("\n❌ Setup failed. Please check the errors above.")

if __name__ == "__main__":
    main()











