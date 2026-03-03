"""Genereer een refresh token alleen voor de Content API for Shopping.

Gebruikt dezelfde client_id en client_secret als in config/google-ads.yaml
(alleen lezen, er wordt niets gewijzigd). De nieuwe token is alleen voor
Content API en hoort in config/content-api.yaml - zo blijft google-ads.yaml
ongewijzigd voor Google Ads.

Stappen:
  1. Maak config/content-api.yaml (kopie van content-api.yaml.example)
  2. Zet daarin client_id en client_secret (zelfde als google-ads.yaml)
  3. Run: py -m src.generate_content_api_refresh_token
  4. Plak de getoonde refresh_token in config/content-api.yaml bij refresh_token

Requires: google-auth-oauthlib
  pip install google-auth-oauthlib
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from google_auth_oauthlib.flow import InstalledAppFlow

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Lees alleen van google-ads (client_id/secret); schrijf nooit
GOOGLE_ADS_CONFIG = PROJECT_ROOT / "config" / "google-ads.yaml"
CONTENT_API_SCOPE = ["https://www.googleapis.com/auth/content"]


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
    client_id = _read_yaml_string_value(GOOGLE_ADS_CONFIG, "client_id")
    client_secret = _read_yaml_string_value(GOOGLE_ADS_CONFIG, "client_secret")

    if not client_id or not client_secret:
        raise SystemExit(
            "client_id of client_secret niet gevonden in config/google-ads.yaml"
        )

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, scopes=CONTENT_API_SCOPE)
    creds = flow.run_local_server(host="localhost", port=0, prompt="consent")

    refresh_token = getattr(creds, "refresh_token", None)
    if not refresh_token:
        raise SystemExit(
            "Geen refresh_token ontvangen. Zorg dat je toestemming gaf voor Merchant Center / Content."
        )

    print("")
    print("Plak deze waarde in config/content-api.yaml bij refresh_token:")
    print("")
    print(refresh_token)
    print("")
    print("(config/google-ads.yaml is niet gewijzigd)")


if __name__ == "__main__":
    main()
