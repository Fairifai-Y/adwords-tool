"""Quick connectivity test for Google Ads API using env-configured YAML.

Run:
  py -m pip install --user google-ads python-dotenv
  py -m src.test_connection
"""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

def main() -> None:
    # Doelaccount (zonder streepjes in GAQL-call)
    customer_id = "5059126003"

    # 1) Projectroot (= map boven /src) en .env laden
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(dotenv_path=project_root / ".env")

    # 2) Configpad bepalen (env of fallback naar /config/google-ads.yaml)
    cfg = os.getenv("GOOGLE_ADS_CONFIGURATION_FILE")
    if not cfg:
        cfg = str(project_root / "config" / "google-ads.yaml")

    print("Config path =", cfg)

    # 3) Client expliciet laden vanaf dit pad
    client = GoogleAdsClient.load_from_storage(cfg)
    print("Effective login_customer_id =", getattr(client, "login_customer_id", None))

    # 4) Simpele GAQL-rooktest
    ga_service = client.get_service("GoogleAdsService")
    query = (
        "SELECT customer.id, customer.descriptive_name, customer.currency_code, "
        "customer.time_zone FROM customer LIMIT 1"
    )

    try:
        response = ga_service.search(customer_id=customer_id, query=query)
        print("Connectie geslaagd. Voorbeeldresultaat:")
        for row in response:
            cust = row.customer
            print(
                {
                    "id": cust.id,
                    "name": cust.descriptive_name,
                    "currency": cust.currency_code,
                    "time_zone": cust.time_zone,
                }
            )
            break
    except GoogleAdsException as exc:
        print("❌ Google Ads API error:", exc.error.code().name)
        for e in exc.failure.errors:
            print("-", e.error_code, e.message)
    except FileNotFoundError:
        print("❌ Kon het YAML-bestand niet vinden op pad:", cfg)
    except Exception as exc:
        print("❌ Onverwachte fout:", str(exc))

if __name__ == "__main__":
    main()