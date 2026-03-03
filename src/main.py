"""Orchestrates fetching products and building a campaign.

Run: python -m src.main --target-roas 4.0
"""

from __future__ import annotations

import argparse
from typing import List

from .fetch_products import fetch_products_with_labels
from .build_campaign import build_campaign_with_target_roas
from .utils import ensure_config_exists, parse_target_roas


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Google Ads campaign from products")
    parser.add_argument(
        "--target-roas",
        dest="target_roas",
        type=str,
        required=False,
        default="4.0",
        help="Desired target ROAS (e.g., 4.0)",
    )
    return parser.parse_args()


def main() -> None:
    ensure_config_exists()
    args = parse_args()
    target_roas = parse_target_roas(args.target_roas)

    products = fetch_products_with_labels()
    campaign = build_campaign_with_target_roas(products, target_roas)

    print("Campaign ready:")
    print({
        "name": campaign.name,
        "target_roas": campaign.target_roas,
        "products_count": campaign.products_count,
        "labels": campaign.meta.get("labels", []),
    })


if __name__ == "__main__":
    main()





