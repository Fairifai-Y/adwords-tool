"""Weekly automation runner to:

1. Create Standard Shopping campaigns (label_0 + label_4 + label_2)
2. Create PMax ALL Labels campaigns
3. Adjust portfolio tROAS (Standard Shopping)
4. Adjust PMax campaign tROAS (direct on campaigns)

All per domain/merchant combination defined in a JSON config file.

Usage (local / cron / PythonAnywhere scheduled task):

    python src/weekly_automation_runner.py --config config/weekly_automation.json

The config file defines, per account, which steps moeten draaien en met welke
parameters (prefix, budget, ROAS percentage, enz.).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class StandardConfig:
    enabled: bool
    customer_id: str
    merchant_id: str
    prefix: str = "GS"
    daily_budget: float = 5.0
    feed_label: str = "nl"
    target_countries: str = "NL"
    target_languages: str = "nl"
    roas_factor: float = 0.0
    start_enabled: bool = False


@dataclass
class PMaxConfig:
    enabled: bool
    customer_id: str
    merchant_id: str
    prefix: str = "PMax ALL"
    label_index: int = 0
    daily_budget: float = 5.0
    feed_label: str = "nl"
    target_countries: str = "NL"
    target_languages: str = "nl"
    roas_factor: float = 0.0
    pmax_type: str = "feed-only"  # or "normal"
    start_enabled: bool = False


@dataclass
class PortfolioRoasConfig:
    enabled: bool
    customer_id: str
    reset: bool = False
    percentage: float = 0.0  # e.g. -25 for -25%


@dataclass
class PMaxRoasConfig:
    enabled: bool
    customer_id: str
    prefix: Optional[str] = None  # filter on campaign prefix, e.g. "PMax ALL"
    reset: bool = False
    percentage: float = 0.0


@dataclass
class WeeklyJob:
    name: str  # free description, e.g. "SDEAL_BE"
    standard: Optional[StandardConfig] = None
    pmax: Optional[PMaxConfig] = None
    portfolio_roas: Optional[PortfolioRoasConfig] = None
    pmax_roas: Optional[PMaxRoasConfig] = None


def _load_config(path: Path) -> List[WeeklyJob]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    jobs: List[WeeklyJob] = []

    for item in raw:
        name = item.get("name", "UNNAMED")

        std_cfg = None
        std = item.get("standard")
        if std and std.get("enabled", False):
            std_cfg = StandardConfig(
                enabled=True,
                customer_id=std["customer_id"],
                merchant_id=std["merchant_id"],
                prefix=std.get("prefix", "GS"),
                daily_budget=float(std.get("daily_budget", 5.0)),
                feed_label=std.get("feed_label", "nl"),
                target_countries=std.get("target_countries", "NL"),
                target_languages=std.get("target_languages", "nl"),
                roas_factor=float(std.get("roas_factor", 0.0)),
                start_enabled=bool(std.get("start_enabled", False)),
            )

        pmax_cfg = None
        pm = item.get("pmax")
        if pm and pm.get("enabled", False):
            pmax_cfg = PMaxConfig(
                enabled=True,
                customer_id=pm["customer_id"],
                merchant_id=pm["merchant_id"],
                prefix=pm.get("prefix", "PMax ALL"),
                label_index=int(pm.get("label_index", 0)),
                daily_budget=float(pm.get("daily_budget", 5.0)),
                feed_label=pm.get("feed_label", "nl"),
                target_countries=pm.get("target_countries", "NL"),
                target_languages=pm.get("target_languages", "nl"),
                roas_factor=float(pm.get("roas_factor", 0.0)),
                pmax_type=pm.get("pmax_type", "feed-only"),
                start_enabled=bool(pm.get("start_enabled", False)),
            )

        port_cfg = None
        pr = item.get("portfolio_roas")
        if pr and pr.get("enabled", False):
            port_cfg = PortfolioRoasConfig(
                enabled=True,
                customer_id=pr["customer_id"],
                reset=bool(pr.get("reset", False)),
                percentage=float(pr.get("percentage", 0.0)),
            )

        pmax_roas_cfg = None
        pmr = item.get("pmax_roas")
        if pmr and pmr.get("enabled", False):
            pmax_roas_cfg = PMaxRoasConfig(
                enabled=True,
                customer_id=pmr["customer_id"],
                prefix=pmr.get("prefix") or None,
                reset=bool(pmr.get("reset", False)),
                percentage=float(pmr.get("percentage", 0.0)),
            )

        jobs.append(
            WeeklyJob(
                name=name,
                standard=std_cfg,
                pmax=pmax_cfg,
                portfolio_roas=port_cfg,
                pmax_roas=pmax_roas_cfg,
            )
        )

    return jobs


def _run(cmd: list[str], cwd: Path) -> int:
    print(f"\n[RUN] {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    print(f"[EXIT] {result.returncode}")
    if result.stdout:
        print("[STDOUT]")
        print(result.stdout)
    if result.stderr:
        print("[STDERR]")
        print(result.stderr)
    return result.returncode


def run_standard(job: WeeklyJob, cfg: StandardConfig, python_exe: str) -> None:
    print(f"\n==== Standard Shopping creation for job '{job.name}' ====")
    cmd = [
        python_exe,
        "src/create_product_type_campaigns.py",
        "--customer",
        cfg.customer_id,
        "--prefix",
        cfg.prefix,
        "--daily-budget",
        str(cfg.daily_budget),
        "--apply",
        "true",
        "--feed-label",
        cfg.feed_label,
        "--target-countries",
        cfg.target_countries,
        "--target-languages",
        cfg.target_languages,
    ]

    # Merchant ID is required for Shopping campaigns (shopping_setting.merchant_id)
    if cfg.merchant_id:
        cmd.extend(["--merchant-id", cfg.merchant_id])

    if cfg.roas_factor:
        cmd.extend(["--roas-factor", str(cfg.roas_factor)])
    if cfg.start_enabled:
        cmd.append("--start-enabled")

    _run(cmd, PROJECT_ROOT)


def run_pmax(job: WeeklyJob, cfg: PMaxConfig, python_exe: str) -> None:
    print(f"\n==== PMax ALL Labels creation for job '{job.name}' ====")
    cmd = [
        python_exe,
        "src/label_campaigns.py",
        "--customer",
        cfg.customer_id,
        "--label-index",
        str(cfg.label_index),
        "--prefix",
        cfg.prefix,
        "--daily-budget",
        str(cfg.daily_budget),
        "--pmax-type",
        cfg.pmax_type,
        "--feed-label",
        cfg.feed_label,
        "--target-countries",
        cfg.target_countries,
        "--target-languages",
        cfg.target_languages,
        "--apply",
        "true",
    ]

    # We rely on label_campaigns' eigen logica voor tROAS (target_roas / roas_factor)
    if cfg.roas_factor:
        cmd.extend(["--roas-factor", str(cfg.roas_factor)])

    _run(cmd, PROJECT_ROOT)


def run_portfolio_roas(job: WeeklyJob, cfg: PortfolioRoasConfig, python_exe: str) -> None:
    print(f"\n==== Portfolio ROAS adjustment for job '{job.name}' ====")
    cmd = [
        python_exe,
        "src/adjust_portfolio_roas.py",
        "--customer",
        cfg.customer_id,
    ]

    if cfg.reset:
        cmd.append("--reset")
    # percentage mag 0 zijn in combinatie met reset, dus alleen toevoegen als niet None
    if cfg.percentage:
        cmd.extend(["--percentage", str(cfg.percentage)])

    cmd.append("--apply")
    _run(cmd, PROJECT_ROOT)


def run_pmax_roas(job: WeeklyJob, cfg: PMaxRoasConfig, python_exe: str) -> None:
    print(f"\n==== PMax ROAS adjustment for job '{job.name}' ====")
    cmd = [
        python_exe,
        "src/adjust_pmax_roas.py",
        "--customer",
        cfg.customer_id,
    ]

    if cfg.prefix:
        cmd.extend(["--prefix", cfg.prefix])
    if cfg.reset:
        cmd.append("--reset")
    if cfg.percentage:
        cmd.extend(["--percentage", str(cfg.percentage)])

    cmd.append("--apply")
    _run(cmd, PROJECT_ROOT)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Weekly automation runner for campaign creation + ROAS adjustments"
    )
    parser.add_argument(
        "--config",
        default=str(PROJECT_ROOT / "config" / "weekly_automation.json"),
        help="Path to weekly automation config JSON",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"[ERROR] Config file not found: {config_path}")
        sys.exit(1)

    jobs = _load_config(config_path)
    if not jobs:
        print(f"[ERROR] No jobs defined in {config_path}")
        sys.exit(1)

    python_exe = sys.executable or "python"
    print(f"Using Python executable: {python_exe}")
    print(f"Loaded {len(jobs)} job(s) from {config_path}")

    for job in jobs:
        print(f"\n================= JOB: {job.name} =================")
        # 1) Campagne creatie
        if job.standard:
            run_standard(job, job.standard, python_exe)
        if job.pmax:
            run_pmax(job, job.pmax, python_exe)

        # 2) ROAS adjustments
        if job.portfolio_roas:
            run_portfolio_roas(job, job.portfolio_roas, python_exe)
        if job.pmax_roas:
            run_pmax_roas(job, job.pmax_roas, python_exe)

    print("\nAlle jobs voltooid.")


if __name__ == "__main__":
    main()

