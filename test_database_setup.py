#!/usr/bin/env python3
"""Test database setup and create tables."""

import os
import sys
from pathlib import Path

# Add src directory to path
sys.path.append(str(Path(__file__).parent / "src"))

def test_database_connection():
    """Test database connection and create tables."""
    print("🔍 Testing database connection...")
    
    try:
        from database import DatabaseManager
        
        # Try to create database manager (this will create tables if they don't exist)
        db = DatabaseManager()
        print("✅ Database connection successful!")
        print("✅ Database tables created/verified!")
        
        return True
        
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        print("\n💡 Make sure to set your database credentials in environment variables:")
        print("   export DB_HOST=localhost")
        print("   export DB_PORT=5432")
        print("   export DB_NAME=adwords_automation")
        print("   export DB_USER=postgres")
        print("   export DB_PASSWORD=your_password")
        print("\n   Or set DATABASE_URL:")
        print("   export DATABASE_URL='postgresql://user:password@host:port/database'")
        
        return False

def main():
    """Main function."""
    print("🗄️  Database Setup Test")
    print("=" * 30)
    
    if test_database_connection():
        print("\n🎉 Database setup completed successfully!")
        print("\n📚 Next steps:")
        print("1. Run: python src/automated_campaign_manager.py --customer YOUR_ID --mode daily")
        print("2. Check the AUTOMATION_README.md for full instructions")
    else:
        print("\n❌ Database setup failed. Please check your credentials and try again.")

if __name__ == "__main__":
    main()











