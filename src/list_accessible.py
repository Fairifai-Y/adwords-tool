"""List all accessible customer IDs for the current OAuth credentials.

Run:
  py -m src.list_accessible
"""

from __future__ import annotations

from google.ads.googleads.client import GoogleAdsClient
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "google-ads.yaml"


def main() -> None:
    if not CONFIG_PATH.exists():
        print(f"Config niet gevonden op {CONFIG_PATH}")
        sys.exit(1)
    client = GoogleAdsClient.load_from_storage(str(CONFIG_PATH))
    customer_service = client.get_service("CustomerService")
    resource_names = customer_service.list_accessible_customers().resource_names
    if not resource_names:
        print("Geen toegankelijke klanten gevonden voor deze credentials.")
        return
    print("Toegankelijke customer resource names:")
    for rn in resource_names:
        # rn looks like customers/1234567890
        print(rn)


if __name__ == "__main__":
    main()


