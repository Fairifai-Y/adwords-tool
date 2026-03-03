"""Probe all accessible accounts and report which are queryable with current config.

Run:
  py -m src.probe_accounts
"""

from __future__ import annotations

import re
from pathlib import Path
import os
from dotenv import load_dotenv

from google.ads.googleads.client import GoogleAdsClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "google-ads.yaml"


def _digits_only(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"\D", "", value)


def main() -> None:
    load_dotenv()
    print("Config path =", os.getenv("GOOGLE_ADS_CONFIGURATION_FILE"))
    client = GoogleAdsClient.load_from_storage(str(CONFIG_PATH))

    # Read login (manager) from loaded config
    login_customer_id = getattr(client, "login_customer_id", None)
    login_customer_id = _digits_only(str(login_customer_id) if login_customer_id else None)
    if not login_customer_id:
        print("login_customer_id ontbreekt in config/google-ads.yaml")
        return

    customer_service = client.get_service("CustomerService")
    resource_names = customer_service.list_accessible_customers().resource_names
    ids = [rn.split("/")[-1] for rn in resource_names]

    print(f"Login (manager): {login_customer_id}")
    print("Probe accounts:")

    for cid in ids:
        # New client per attempt to ensure headers are set cleanly
        probe_client = GoogleAdsClient.load_from_storage(str(CONFIG_PATH))
        probe_client.login_customer_id = login_customer_id
        ga_service = probe_client.get_service("GoogleAdsService")
        query = "SELECT customer.id FROM customer LIMIT 1"
        try:
            list(ga_service.search(customer_id=cid, query=query))
            print(f"PASS  customer_id={cid}")
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            print(f"FAIL  customer_id={cid}  ->  {msg.splitlines()[0] if msg else type(exc).__name__}")


if __name__ == "__main__":
    main()





