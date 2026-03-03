#!/usr/bin/env python3
"""Setup database credentials interactively."""

import os
import sys
from pathlib import Path

def setup_database_credentials():
    """Setup database credentials interactively."""
    print("🗄️  Database Credentials Setup")
    print("=" * 40)
    
    print("\nVul je database credentials in:")
    
    # Get database credentials
    host = input("Database host (bijv. localhost): ").strip() or "localhost"
    port = input("Database port (bijv. 5432): ").strip() or "5432"
    database = input("Database naam: ").strip()
    username = input("Gebruikersnaam: ").strip()
    password = input("Wachtwoord: ").strip()
    
    if not all([database, username, password]):
        print("❌ Database naam, gebruikersnaam en wachtwoord zijn verplicht!")
        return False
    
    # Set environment variables
    os.environ['DB_HOST'] = host
    os.environ['DB_PORT'] = port
    os.environ['DB_NAME'] = database
    os.environ['DB_USER'] = username
    os.environ['DB_PASSWORD'] = password
    
    print(f"\n✅ Environment variables ingesteld:")
    print(f"   DB_HOST={host}")
    print(f"   DB_PORT={port}")
    print(f"   DB_NAME={database}")
    print(f"   DB_USER={username}")
    print(f"   DB_PASSWORD={'*' * len(password)}")
    
    return True

def test_connection():
    """Test database connection."""
    print("\n🔍 Testing database connection...")
    
    try:
        # Add src directory to path
        sys.path.append(str(Path(__file__).parent / "src"))
        from database import DatabaseManager
        
        db = DatabaseManager()
        print("✅ Database connection successful!")
        print("✅ Database tables created/verified!")
        return True
        
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False

def main():
    """Main function."""
    if setup_database_credentials():
        if test_connection():
            print("\n🎉 Database setup completed successfully!")
            print("\n📚 Next steps:")
            print("1. Run: python src/automated_campaign_manager.py --customer YOUR_ID --mode daily")
            print("2. Check the AUTOMATION_README.md for full instructions")
        else:
            print("\n❌ Database connection failed. Please check your credentials.")
    else:
        print("\n❌ Setup failed. Please try again.")

if __name__ == "__main__":
    main()











