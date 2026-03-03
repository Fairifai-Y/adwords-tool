"""Test verbinding met de Merchant API (merchantapi.googleapis.com).

Leest credentials uit config/content-api.yaml. Gebruikt de Merchant API,
niet de oude Content API for Shopping (shoppingcontent).

Run:
  py -m src.test_content_api
  py -m src.test_content_api --merchant-id 389429754
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTENT_API_CONFIG = PROJECT_ROOT / "config" / "content-api.yaml"
GOOGLE_ADS_CONFIG = PROJECT_ROOT / "config" / "google-ads.yaml"

# Zelfde OAuth scope voor Merchant API
MERCHANT_API_SCOPE = "https://www.googleapis.com/auth/content"
MERCHANT_API_ACCOUNTS = "https://merchantapi.googleapis.com/accounts/v1/accounts"
MERCHANT_API_PRODUCTS = "https://merchantapi.googleapis.com/products/v1"


def _read_yaml_string_value(path: Path, key: str) -> Optional[str]:
    """Read simple YAML key: value pairs."""
    if not path.exists():
        return None
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*:\s*(?:['\"])?([^'\"\n#]+)")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = pattern.match(line)
        if match:
            return match.group(1).strip()
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Test Content API verbinding")
    parser.add_argument("--merchant-id", type=str, default="", help="Merchant Center ID (optioneel, voor products.list)")
    args = parser.parse_args()

    # Gebruik content-api.yaml als die bestaat en een refresh_token heeft
    if CONTENT_API_CONFIG.exists():
        client_id = _read_yaml_string_value(CONTENT_API_CONFIG, "client_id")
        client_secret = _read_yaml_string_value(CONTENT_API_CONFIG, "client_secret")
        refresh_token = _read_yaml_string_value(CONTENT_API_CONFIG, "refresh_token")
        config_name = "config/content-api.yaml"
    else:
        client_id = _read_yaml_string_value(GOOGLE_ADS_CONFIG, "client_id")
        client_secret = _read_yaml_string_value(GOOGLE_ADS_CONFIG, "client_secret")
        refresh_token = _read_yaml_string_value(GOOGLE_ADS_CONFIG, "refresh_token")
        config_name = "config/google-ads.yaml"

    if not all([client_id, client_secret, refresh_token]):
        print("[X] client_id, client_secret of refresh_token ontbreekt.")
        if not CONTENT_API_CONFIG.exists():
            print("   Maak config/content-api.yaml (zie content-api.yaml.example) en run:")
            print("   py -m src.generate_content_api_refresh_token")
        else:
            print("   Vul refresh_token in config/content-api.yaml (run generate_content_api_refresh_token).")
        return

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google.auth.transport.requests import AuthorizedSession

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=[MERCHANT_API_SCOPE],
    )

    print("Credentials uit", config_name, "geladen.")
    print("API: Merchant API (merchantapi.googleapis.com)")
    print("Scope:", MERCHANT_API_SCOPE)
    print()

    try:
        creds.refresh(Request())
        print("[OK] Access token opgehaald (refresh geslaagd).")
        print("   Token (eerste 20 tekens):", (creds.token or "")[:20] + "...")
        print()
    except Exception as e:
        print("[X] Refresh mislukt.")
        print("   Fout:", e)
        if config_name == "config/google-ads.yaml":
            print()
            print("   Gebruik een aparte Content API config: maak config/content-api.yaml")
            print("   en run: py -m src.generate_content_api_refresh_token")
        return

    session = AuthorizedSession(creds)

    # Merchant API: lijst accounts (geen account-id nodig)
    try:
        r = session.get(MERCHANT_API_ACCOUNTS, params={"pageSize": 10})
        print("GET accounts (Merchant API):")
        print("   Status:", r.status_code)
        if r.ok:
            data = r.json()
            accounts = data.get("accounts") or []
            print("   [OK] Merchant API verbinding werkt.")
            if accounts:
                print("   Accounts:", [a.get("name") or a.get("accountNumber") for a in accounts])
            else:
                print("   Geen accounts in response (of lege lijst).")
        else:
            print("   Body:", r.text[:500])
            if r.status_code == 401 and "not registered" in r.text:
                print("   -> 401: GCP-project nog niet gekoppeld aan Merchant Center.")
                print("   Run eenmalig: py -m src.register_merchant_api --merchant-id <id> --developer-email <email>")
            elif r.status_code == 403:
                print("   -> 403: Zet Merchant API aan in Google Cloud Console voor dit project.")
    except Exception as e:
        print("   Fout:", e)

    print()

    if args.merchant_id:
        account_id = args.merchant_id.strip()
        products_url = f"{MERCHANT_API_PRODUCTS}/accounts/{account_id}/products"
        try:
            r2 = session.get(products_url, params={"pageSize": 1})
            print(f"GET products (account {account_id}, pageSize=1):")
            print("   Status:", r2.status_code)
            if r2.ok:
                data = r2.json()
                products = data.get("products") or []
                print("   [OK] Products endpoint OK. Aantal in deze pagina:", len(products))
                if products:
                    p = products[0]
                    print("   Eerste product name:", p.get("name", "?"))
            else:
                print("   Body:", r2.text[:400])
                if r2.status_code == 401 and "not registered" in r2.text:
                    print("   -> Run eenmalig: py -m src.register_merchant_api --merchant-id", account_id, "--developer-email <jouw@email>")
        except Exception as e:
            print("   Fout:", e)
    else:
        print("Tip: geef --merchant-id <id> om products te listen.")


if __name__ == "__main__":
    main()
