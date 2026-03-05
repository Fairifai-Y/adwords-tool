"""Per-account seller ROAS overzicht.

Toont per "seller" (bijv. custom_label_0 / product_custom_attribute0) de
omzet (conversions_value), kosten en ROAS (omzet / kosten) over de laatste N dagen.

Gebruik (voorbeeld):

    py src/account_seller_roas.py --customer 505-912-6003 --days 30

"""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Dict

from dotenv import load_dotenv
from google.ads.googleads.client import GoogleAdsClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "google-ads.yaml"


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")


@dataclass
class SellerMetrics:
    name: str
    revenue: float = 0.0
    cost: float = 0.0

    @property
    def roas(self) -> float:
        if self.cost <= 0:
            return 0.0
        return self.revenue / self.cost


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Per-account seller ROAS overzicht (omzet, kosten, ROAS) voor de laatste N dagen."
    )
    p.add_argument("--customer", required=True, help="Target customer id (linked account)")
    p.add_argument(
        "--days",
        type=int,
        default=30,
        help="Aantal dagen terug te kijken (default 30)",
    )
    p.add_argument(
        "--config",
        default="",
        help="Optioneel pad naar google-ads.yaml (default: config/google-ads.yaml)",
    )
    return p.parse_args()


def _date_range_clause(days: int) -> str:
    if days <= 0:
        days = 1
    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    return f"segments.date BETWEEN '{start_str}' AND '{end_str}'"


def fetch_seller_roas(
    client: GoogleAdsClient,
    customer_id: str,
    days: int,
) -> Dict[str, SellerMetrics]:
    """Haalt omzet, kosten en ROAS op per seller (custom_label_0)."""
    ga = client.get_service("GoogleAdsService")

    where_date = _date_range_clause(days)

    # We gebruiken shopping_performance_view zodat we op product_custom_attribute0 (seller) kunnen groeperen
    query = f"""
        SELECT
          segments.product_custom_attribute0,
          metrics.conversions_value,
          metrics.cost_micros
        FROM shopping_performance_view
        WHERE {where_date}
          AND segments.product_custom_attribute0 IS NOT NULL
    """

    sellers: Dict[str, SellerMetrics] = {}

    for row in ga.search(customer_id=customer_id, query=query):
        name = getattr(row.segments, "product_custom_attribute0", None) or ""
        if not name:
            continue

        m = sellers.get(name)
        if not m:
            m = SellerMetrics(name=name)
            sellers[name] = m

        m.revenue += float(row.metrics.conversions_value)
        m.cost += float(row.metrics.cost_micros) / 1_000_000

    return sellers


def print_table(sellers: Dict[str, SellerMetrics], days: int, customer_id: str) -> None:
    print("")
    print("=" * 80)
    print(
        f"Seller ROAS overzicht (laatste {days} dagen) voor customer {customer_id} "
        f"(gebaseerd op custom_label_0 / product_custom_attribute0)"
    )
    print("=" * 80)
    print(f"{'Seller':<40} {'Omzet':>12} {'Kosten':>12} {'ROAS':>8}")
    print("-" * 80)

    total_revenue = 0.0
    total_cost = 0.0

    # Sorteer op omzet desc
    for name, m in sorted(sellers.items(), key=lambda kv: kv[1].revenue, reverse=True):
        total_revenue += m.revenue
        total_cost += m.cost
        print(
            f"{name[:38]:<40} "
            f"{m.revenue:>12.2f} "
            f"{m.cost:>12.2f} "
            f"{m.roas:>8.2f}"
        )

    if sellers:
        print("-" * 80)
        total_roas = (total_revenue / total_cost) if total_cost > 0 else 0.0
        print(
            f"{'TOTAAL':<40} "
            f"{total_revenue:>12.2f} "
            f"{total_cost:>12.2f} "
            f"{total_roas:>8.2f}"
        )
    else:
        print("Geen data gevonden voor deze periode / account.")


def main() -> int:
    load_dotenv()
    args = parse_args()

    customer_id = _digits_only(args.customer)

    cfg = os.getenv("GOOGLE_ADS_CONFIGURATION_FILE") or str(DEFAULT_CONFIG_PATH)
    print(f"Config path = {cfg}")

    client = GoogleAdsClient.load_from_storage(cfg)

    try:
        sellers = fetch_seller_roas(client=client, customer_id=customer_id, days=args.days)
        print_table(sellers, args.days, customer_id)
        print("\n[SUCCESS] Seller ROAS overzicht voltooid.")
        return 0
    except Exception as e:
        print(f"\n[ERROR] Fout tijdens ophalen van seller ROAS data: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

