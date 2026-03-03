"""Generate a visual HTML report of discovered feed labels and campaign plans.

Usage:
  py src/label_campaigns_report.py --customer 5059126003 --label-index 0 --open true

This runs a read-only discovery (via ShoppingPerformanceView) for the given
customer and produces an HTML file under reports/ with a table and bars.
"""

from __future__ import annotations

import argparse
import html
import os
import re
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv
from google.ads.googleads.client import GoogleAdsClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "google-ads.yaml"
REPORTS_DIR = PROJECT_ROOT / "reports"


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value)


def _label_field(index: int) -> str:
    if index not in {0, 1, 2, 3, 4}:
        raise ValueError("label-index must be 0..4 (maps to product_custom_attributeX)")
    return f"segments.product_custom_attribute{index}"


def discover_labels(client: GoogleAdsClient, customer_id: str, label_index: int) -> Dict[str, int]:
    field = _label_field(label_index)
    ga = client.get_service("GoogleAdsService")
    query = f"""
        SELECT
          {field},
          metrics.impressions
        FROM shopping_performance_view
        WHERE segments.date DURING LAST_30_DAYS
        AND {field} IS NOT NULL
        """
    counts: Dict[str, int] = {}
    for row in ga.search(customer_id=customer_id, query=query):
        label = getattr(row.segments, f"product_custom_attribute{label_index}") or ""
        if not label:
            continue
        counts[label] = counts.get(label, 0) + int(row.metrics.impressions)
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def build_plans(labels_to_impr: Dict[str, int], prefix: str, daily_budget: float, target_roas: float | None) -> List[dict]:
    plans: List[dict] = []
    for label, _ in labels_to_impr.items():
        safe_label = re.sub(r"[^A-Za-z0-9 _-]+", " ", label).strip()[:40]
        name = f"{prefix} - {safe_label}" if prefix else safe_label
        plans.append(
            {
                "label": label,
                "name": name,
                "daily_budget_micros": int(round(daily_budget * 1_000_000)),
                "bidding": "MAXIMIZE_CONVERSION_VALUE",
                "target_roas": target_roas,
            }
        )
    return plans


def _fmt_currency_micros(value: int) -> str:
    return f"{value/1_000_000:.2f}"


def _html_bars(labels_to_impr: Dict[str, int]) -> str:
    if not labels_to_impr:
        return ""
    max_impr = max(labels_to_impr.values()) or 1
    rows = []
    for label, impr in labels_to_impr.items():
        width = max(6, int((impr / max_impr) * 100))
        rows.append(
            f"<div class='bar-row'><div class='bar' style='width:{width}%' title='{impr:,} impressions'></div><span class='bar-label'>{html.escape(label)}</span><span class='bar-value'>{impr:,}</span></div>"
        )
    return "\n".join(rows)


def render_html(customer_id: str, label_index: int, labels_to_impr: Dict[str, int], plans: List[dict]) -> str:
    bars = _html_bars(labels_to_impr)
    rows = []
    for p in plans:
        roas = "" if p["target_roas"] is None else f"{p['target_roas']:.2f}"
        rows.append(
            "<tr>"
            f"<td>{html.escape(p['label'])}</td>"
            f"<td>{labels_to_impr.get(p['label'], 0):,}</td>"
            f"<td>{html.escape(p['name'])}</td>"
            f"<td>{_fmt_currency_micros(p['daily_budget_micros'])}</td>"
            f"<td>{p['bidding']}</td>"
            f"<td>{roas}</td>"
            "</tr>"
        )
    table_rows = "\n".join(rows)
    return f"""
<!doctype html>
<html lang='nl'>
  <head>
    <meta charset='utf-8' />
    <title>Label → Campaign plannen (customer {customer_id})</title>
    <style>
      body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 24px; }}
      h1 {{ margin: 0 0 4px 0; }}
      .muted {{ color: #666; margin-bottom: 24px; }}
      .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-bottom: 24px; }}
      .panel {{ border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; }}
      .bar-row {{ display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 8px; margin: 8px 0; }}
      .bar {{ height: 10px; background: linear-gradient(90deg, #60a5fa, #2563eb); border-radius: 4px; }}
      .bar-label {{ margin-left: 8px; font-size: 12px; color: #111827; }}
      .bar-value {{ font-variant-numeric: tabular-nums; color: #374151; font-size: 12px; }}
      table {{ width: 100%; border-collapse: collapse; }}
      th, td {{ border-bottom: 1px solid #e5e7eb; padding: 10px 8px; text-align: left; }}
      th {{ background: #f9fafb; position: sticky; top: 0; }}
      .small {{ font-size: 12px; color: #6b7280; }}
      footer {{ margin-top: 24px; color: #6b7280; font-size: 12px; }}
    </style>
  </head>
  <body>
    <h1>Label → Campaign plannen</h1>
    <div class='muted'>Customer {customer_id} · custom_label{label_index} · laatste 45 dagen</div>

    <div class='grid'>
      <div class='panel'>
        <h3>Labels (impressies)</h3>
        {bars}
      </div>
      <div class='panel'>
        <h3>Voorstel per label</h3>
        <table>
          <thead>
            <tr><th>Label</th><th>Impr</th><th>Campagne-naam</th><th>Dagbudget</th><th>Bidding</th><th>tROAS</th></tr>
          </thead>
          <tbody>
            {table_rows}
          </tbody>
        </table>
        <div class='small'>Dagbudget in accountvaluta. tROAS optioneel.</div>
      </div>
    </div>

    <footer>Dry-run rapport. Mutations zijn uitgeschakeld.</footer>
  </body>
</html>
"""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Visual report for label-based campaign plans")
    p.add_argument("--customer", required=True, help="Target customer id (linked account)")
    p.add_argument("--label-index", type=int, default=0, help="Which custom_label index (0..4)")
    p.add_argument("--login", default="", help="Force login customer id (MCC) header")
    p.add_argument("--prefix", default="PMax Label", help="Campaign name prefix")
    p.add_argument("--daily-budget", type=float, default=5.0, help="Daily budget in account currency")
    p.add_argument("--target-roas", type=float, default=None, help="Optional tROAS")
    p.add_argument("--out", default=str(REPORTS_DIR / "label_campaign_plans.html"), help="Output HTML path")
    p.add_argument("--open", default="true", help="Open in browser (true/false)")
    return p.parse_args()


def main() -> None:
    load_dotenv()
    print("Config path =", os.getenv("GOOGLE_ADS_CONFIGURATION_FILE"))
    args = parse_args()
    customer_id = _digits_only(args.customer)
    client = GoogleAdsClient.load_from_storage(str(CONFIG_PATH))
    # Force login header from config to avoid USER_PERMISSION_DENIED
    try:
        # 0) CLI wins
        cli_login = _digits_only(args.login) if args.login else ""
        # 1) ENV next
        env_login = os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
        login_id = _digits_only(env_login) if env_login else ""
        if cli_login:
            login_id = cli_login
        # 2) Fallback to config file
        if not login_id:
            text = CONFIG_PATH.read_text(encoding="utf-8")
            m = re.search(r"^\s*login_customer_id\s*:\s*(?:['\"])?([^'\"\n#]+)", text, re.M)
            if m:
                login_id = _digits_only(m.group(1))
        if login_id:
            client.login_customer_id = login_id
    except Exception:
        pass

    labels = discover_labels(client, customer_id=customer_id, label_index=args.label_index)
    if not labels:
        print("Geen labels gevonden in ShoppingPerformanceView. Mogelijk geen recente traffic of labels leeg.")
        return

    plans = build_plans(labels, prefix=args.prefix, daily_budget=args.daily_budget, target_roas=args.target_roas)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    html_text = render_html(customer_id, args.label_index, labels, plans)
    out_path = Path(args.out)
    out_path.write_text(html_text, encoding="utf-8")
    print(f"Rapport geschreven naar: {out_path}")

    if str(args.open).lower() in {"1", "true", "yes"}:
        try:
            import webbrowser

            webbrowser.open(out_path.as_uri())
        except Exception:
            pass


if __name__ == "__main__":
    main()


