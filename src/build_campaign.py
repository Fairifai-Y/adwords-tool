"""Build a campaign with target ROAS.

This module contains a stub function to construct a campaign payload. Replace
with real Google Ads API calls when wiring up.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class Campaign:
    name: str
    target_roas: float
    products_count: int
    meta: Dict[str, Any]


def build_campaign_with_target_roas(products: List[dict], target_roas: float) -> Campaign:
    """Create a simple in-memory campaign object from inputs.

    In production, construct and submit operations via the Google Ads API.
    """

    campaign_name = f"Auto Campaign (ROAS {target_roas:.2f})"
    return Campaign(
        name=campaign_name,
        target_roas=target_roas,
        products_count=len(products),
        meta={
            "labels": sorted({label for p in products for label in p.get("labels", [])}),
        },
    )





