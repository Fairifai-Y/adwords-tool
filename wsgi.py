#!/usr/bin/env python3
"""
WSGI entry point for production deployment
"""

import os
import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

# Set environment variables
os.environ["GOOGLE_ADS_CONFIGURATION_FILE"] = str(project_root / "config" / "google-ads.yaml")

# Import the Flask app
from simple_web import app

if __name__ == "__main__":
    app.run()

