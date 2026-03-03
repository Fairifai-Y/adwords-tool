"""Utility helpers for configuration, logging, and common routines."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"


def load_text_file(relative_path: str) -> str:
    """Load a text file from the project root using a relative path.

    This avoids adding external dependencies (e.g., YAML parsers) at this stage.
    """

    file_path = PROJECT_ROOT / relative_path
    return file_path.read_text(encoding="utf-8")


def ensure_config_exists() -> None:
    """Ensure the required config file exists; warn for optional ones.

    Required:
      - config/google-ads.yaml

    Optional (not blocking):
      - config/credentials.json (kan verborgen zijn of elders beheerd worden)
    """

    required = [CONFIG_DIR / "google-ads.yaml"]
    missing_required = [str(p.relative_to(PROJECT_ROOT)) for p in required if not p.exists()]
    if missing_required:
        raise FileNotFoundError(
            "Missing required config file: " + ", ".join(missing_required)
        )

    optional_credentials = CONFIG_DIR / "credentials.json"
    if not optional_credentials.exists():
        # Niet blokkerend: laat een vriendelijke waarschuwing zien.
        print(
            "Waarschuwing: 'config/credentials.json' niet gevonden. Als dit bestand verborgen is of je "
            "een alternatieve authenticatiemethode gebruikt, kun je dit negeren."
        )


def parse_target_roas(value: str | float | int) -> float:
    """Parse target ROAS input into a float.

    Accepts strings like "4.0" or numbers. Raises ValueError if invalid or <= 0.
    """

    try:
        roas = float(value)
    except Exception as exc:  # noqa: BLE001 - narrow conversion errors are fine here
        raise ValueError("Target ROAS must be a number") from exc
    if roas <= 0:
        raise ValueError("Target ROAS must be greater than 0")
    return roas


def project_path(*parts: str) -> Path:
    """Build a path from the project root."""

    return PROJECT_ROOT.joinpath(*parts)



