"""Generate a Google Ads API refresh token using values from config/google-ads.yaml.

Usage:
  python -m src.generate_refresh_token

Requires: google-auth-oauthlib
  pip install --user google-auth-oauthlib
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from google_auth_oauthlib.flow import InstalledAppFlow


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "google-ads.yaml"
SCOPE = ["https://www.googleapis.com/auth/adwords"]


def _read_yaml_string_value(path: Path, key: str) -> Optional[str]:
    """Very small YAML key:value reader for simple string values.

    This avoids adding a full YAML dependency. It supports lines like:
      key: "value"
      key: 'value'
      key: value
    and ignores comments/blank lines.
    """

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
    client_id = _read_yaml_string_value(CONFIG_PATH, "client_id")
    client_secret = _read_yaml_string_value(CONFIG_PATH, "client_secret")

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

    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPE)
    # Opens a browser window for you to authenticate and authorize.
    creds = flow.run_local_server(host="localhost", port=0, prompt="consent")

    refresh_token = getattr(creds, "refresh_token", None)
    if not refresh_token:
        raise SystemExit(
            "Geen refresh_token ontvangen. Zorg dat je toestemming gaf en de juiste account gebruikte."
        )

    print("\nCopy/paste deze waarde in config/google-ads.yaml bij refresh_token:\n")
    print(refresh_token)


if __name__ == "__main__":
    main()























