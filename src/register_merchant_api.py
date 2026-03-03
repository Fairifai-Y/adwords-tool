"""Eenmalige registratie: koppel je GCP-project aan je Merchant Center-account.

De Merchant API vereist dat je GCP-project (vaulted-bazaar-468506-i4) eenmalig
wordt geregistreerd bij het Merchant Center-account. Daarna werken de API-calls.

De ingelogde gebruiker (refresh token) moet Admin zijn op het Merchant Center-account.

Run (vervang met jouw merchant-id en e-mail):
  py -m src.register_merchant_api --merchant-id 389429754 --developer-email jouw@email.com

Na succes: wacht ca. 5 minuten en run: py -m src.test_content_api
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTENT_API_CONFIG = PROJECT_ROOT / "config" / "content-api.yaml"
MERCHANT_API_SCOPE = "https://www.googleapis.com/auth/content"


def _read_yaml_string_value(path: Path, key: str) -> Optional[str]:
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
    parser = argparse.ArgumentParser(
        description="Registreer GCP-project bij Merchant Center (eenmalig)"
    )
    parser.add_argument("--merchant-id", required=True, help="Merchant Center account ID (bijv. 389429754)")
    parser.add_argument(
        "--developer-email",
        required=True,
        help="E-mail van de developer/contact (moet bij een Google-account horen, Admin op Merchant Center)",
    )
    args = parser.parse_args()

    client_id = _read_yaml_string_value(CONTENT_API_CONFIG, "client_id")
    client_secret = _read_yaml_string_value(CONTENT_API_CONFIG, "client_secret")
    refresh_token = _read_yaml_string_value(CONTENT_API_CONFIG, "refresh_token")

    if not all([client_id, client_secret, refresh_token]):
        print("[X] Vul config/content-api.yaml in (client_id, client_secret, refresh_token).")
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
    creds.refresh(Request())
    session = AuthorizedSession(creds)

    account_id = args.merchant_id.strip()
    email = args.developer_email.strip()
    url = (
        f"https://merchantapi.googleapis.com/accounts/v1/accounts/{account_id}/developerRegistration:registerGcp"
    )
    body = {"developerEmail": email}

    print("Registreer GCP-project bij Merchant Center account", account_id)
    print("Developer e-mail:", email)
    print()

    r = session.post(url, json=body)
    print("Status:", r.status_code)
    if r.ok:
        data = r.json()
        print("[OK] GCP-project is geregistreerd.")
        print("     Wacht ca. 5 minuten en run: py -m src.test_content_api")
        if data.get("gcpIds"):
            print("     GCP IDs:", data["gcpIds"])
    else:
        print("Body:", r.text[:800])
        if r.status_code == 403:
            print()
            print("-> Zorg dat de ingelogde gebruiker Admin is op het Merchant Center-account.")


if __name__ == "__main__":
    main()
