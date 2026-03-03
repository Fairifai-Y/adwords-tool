"""Check OAuth token scopes and account access.

Run:
  py -m src.check_oauth
"""

from __future__ import annotations

from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import json


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "google-ads.yaml"


def _read_yaml_string_value(path: Path, key: str) -> str | None:
    """Read simple YAML key: value pairs."""
    import re
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
    refresh_token = _read_yaml_string_value(CONFIG_PATH, "refresh_token")

    if not all([client_id, client_secret, refresh_token]):
        print("client_id, client_secret of refresh_token ontbreekt in config/google-ads.yaml")
        return

    # Create credentials object
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/adwords"]
    )

    try:
        # Refresh to get current token and check scopes
        creds.refresh(Request())
        print("OAuth token info:")
        print(f"  Scopes: {creds.scopes}")
        print(f"  Expired: {creds.expired}")
        print(f"  Valid: {creds.valid}")
        
        # Try to get user info
        from google.auth.transport.requests import AuthorizedSession
        session = AuthorizedSession(creds)
        user_info = session.get("https://www.googleapis.com/oauth2/v2/userinfo").json()
        print(f"  User: {user_info.get('email', 'Unknown')}")
        
    except Exception as exc:
        print(f"Fout bij OAuth check: {exc}")


if __name__ == "__main__":
    main()
