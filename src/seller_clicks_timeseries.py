"""Per-seller (via campagnenaam) klik-analyse per dag over de afgelopen N dagen.

Gebruik (voorbeeld):

    py src/seller_clicks_timeseries.py --customer 5059126003 --campaign-name "EchtVeelVoorWeinig" --days 90 --export-csv

Dit script:
- Vraagt de Google Ads API op met een GAQL-query met segments.date
- Filtert op campagnenaam (substring match, case-sensitive zoals in de UI)
- Aggegreert kliks, impressies, kosten en conversies per DAG over alle matching campagnes

Later kunnen we de filterlogica eenvoudig aanpassen naar seller ID (bijv. via label of naam-pattern).
"""

from __future__ import annotations

import argparse
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
from google.ads.googleads.client import GoogleAdsClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "google-ads.yaml"
REPORTS_DIR = PROJECT_ROOT / "reports"


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")


@dataclass
class DailyMetrics:
    date: str
    impressions: int = 0
    clicks: int = 0
    conversions: float = 0.0
    conversions_value: float = 0.0
    cost: float = 0.0  # account currency


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Kliks per dag over de afgelopen N dagen voor campagnes die een bepaalde naam bevatten."
    )
    parser.add_argument(
        "--customer",
        required=True,
        help="Target customer id (linked account)",
    )
    parser.add_argument(
        "--campaign-name",
        required=True,
        help="Substring van de campagnenaam om op te filteren, bijv. 'EchtVeelVoorWeinig'",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Aantal dagen terug te kijken (default 90)",
    )
    parser.add_argument(
        "--export-csv",
        action="store_true",
        help="Exporteer resultaat naar CSV-bestand onder 'reports/'",
    )
    parser.add_argument(
        "--config",
        default="",
        help="Optioneel pad naar google-ads.yaml (default: config/google-ads.yaml)",
    )
    return parser.parse_args()


def build_where_clause(
    campaign_name_substring: str,
    days: int,
    seller_id: Optional[str] = None,
) -> str:
    """Bouwt de WHERE-clause voor de GAQL-query.

    Let op: in plaats van `DURING LAST_N_DAYS` (wat niet voor alle N is toegestaan),
    gebruiken we hier een expliciete datumrange met BETWEEN.

    Nu filteren we op campagnenaam; later kan hier een alternatief pad voor seller_id in.
    """
    # Escapen van enkele quotes voor GAQL
    escaped_name = campaign_name_substring.replace("'", "\\'")

    # Bereken datumrange: vandaag t/m (vandaag - (days-1))
    if days <= 0:
        days = 1
    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)

    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    where_parts: List[str] = [
        f"segments.date BETWEEN '{start_str}' AND '{end_str}'",
        "campaign.advertising_channel_type IN ('PERFORMANCE_MAX', 'SHOPPING')",
        "campaign.status != 'REMOVED'",
        f"campaign.name LIKE '%{escaped_name}%'",
    ]

    # Placeholder voor toekomstig gebruik van seller_id
    if seller_id:
        # Bijv. als seller_id later in custom label of naam komt:
        # where_parts.append(f"segments.product_custom_attribute0 = '{seller_id}'")
        pass

    return " AND ".join(where_parts)


def fetch_daily_metrics(
    client: GoogleAdsClient,
    customer_id: str,
    campaign_name_substring: str,
    days: int,
) -> Dict[str, DailyMetrics]:
    ga = client.get_service("GoogleAdsService")

    where_clause = build_where_clause(
        campaign_name_substring=campaign_name_substring,
        days=days,
    )

    query = f"""
        SELECT
          segments.date,
          campaign.id,
          campaign.name,
          metrics.impressions,
          metrics.clicks,
          metrics.conversions,
          metrics.conversions_value,
          metrics.cost_micros
        FROM campaign
        WHERE {where_clause}
        ORDER BY segments.date ASC, campaign.id
    """

    daily: Dict[str, DailyMetrics] = {}

    for row in ga.search(customer_id=customer_id, query=query):
        date_str = str(row.segments.date)
        if date_str not in daily:
            daily[date_str] = DailyMetrics(date=date_str)

        dm = daily[date_str]
        dm.impressions += int(row.metrics.impressions)
        dm.clicks += int(row.metrics.clicks)
        dm.conversions += float(row.metrics.conversions)
        dm.conversions_value += float(row.metrics.conversions_value)
        dm.cost += float(row.metrics.cost_micros) / 1_000_000

    return dict(sorted(daily.items(), key=lambda kv: kv[0]))


def print_table(daily: Dict[str, DailyMetrics], campaign_name_substring: str, days: int) -> None:
    print("")
    print("=" * 72)
    print(f"Kliks per dag (laatste {days} dagen) voor campagnenaam bevat: '{campaign_name_substring}'")
    print("=" * 72)
    print(f"{'Datum':<12} {'Impr':>10} {'Clicks':>10} {'Conv':>8} {'Value':>10} {'Cost':>10}")
    print("-" * 72)

    total_impr = total_clicks = 0
    total_conv = total_value = total_cost = 0.0

    for date_str, dm in daily.items():
        total_impr += dm.impressions
        total_clicks += dm.clicks
        total_conv += dm.conversions
        total_value += dm.conversions_value
        total_cost += dm.cost

        print(
            f"{date_str:<12} "
            f"{dm.impressions:>10,d} "
            f"{dm.clicks:>10,d} "
            f"{dm.conversions:>8.0f} "
            f"{dm.conversions_value:>10.2f} "
            f"{dm.cost:>10.2f}"
        )

    if daily:
        print("-" * 72)
        print(
            f"{'TOTAAL':<12} "
            f"{total_impr:>10,d} "
            f"{total_clicks:>10,d} "
            f"{total_conv:>8.0f} "
            f"{total_value:>10.2f} "
            f"{total_cost:>10.2f}"
        )
    else:
        print("Geen data gevonden voor deze filter / periode.")


def export_to_csv(daily: Dict[str, DailyMetrics], campaign_name_substring: str) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", campaign_name_substring).strip("_")[:40]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = REPORTS_DIR / f"seller_clicks_{safe_name}_{timestamp}.csv"

    import csv

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "impressions", "clicks", "conversions", "conversions_value", "cost"])
        for date_str, dm in daily.items():
            writer.writerow(
                [
                    date_str,
                    dm.impressions,
                    dm.clicks,
                    dm.conversions,
                    f"{dm.conversions_value:.2f}",
                    f"{dm.cost:.2f}",
                ]
            )

    print(f"\nCSV-export geschreven naar: {out_path}")
    return out_path


def main() -> int:
    load_dotenv()
    args = parse_args()

    customer_id = _digits_only(args.customer)

    cfg = os.getenv("GOOGLE_ADS_CONFIGURATION_FILE") or str(DEFAULT_CONFIG_PATH)
    print(f"Config path = {cfg}")

    client = GoogleAdsClient.load_from_storage(cfg)

    print(
        f"\n[SELLER CLICKS] Klik-analyse voor customer {customer_id}, "
        f"campagnenaam bevat '{args.campaign_name}', laatste {args.days} dagen"
    )

    try:
        daily = fetch_daily_metrics(
            client=client,
            customer_id=customer_id,
            campaign_name_substring=args.campaign_name,
            days=args.days,
        )
        print_table(daily, args.campaign_name, args.days)

        if args.export_csv:
            export_to_csv(daily, args.campaign_name)

        print("\n[SUCCESS] Analyse voltooid.")
        return 0
    except Exception as e:
        print(f"\n[ERROR] Fout tijdens ophalen van data: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

