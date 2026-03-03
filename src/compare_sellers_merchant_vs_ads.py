"""
Vergelijk sellers uit Merchant API (custom label 0 in feed) met sellers uit Google Ads
(shopping_performance_view, laatste 30 dagen) voor een gegeven Merchant-account en Ads-klant.

Sellers = custom label 0 (Merchant: productAttributes.customLabel0, Ads: segments.product_custom_attribute0).

Bij veel producten (bijv. 1.2M): gebruik --max-products voor een snelle steekproef, of --sellers-cache
om de lijst eenmalig op te slaan en daarna direct te laden.

Run:
  py -m src.compare_sellers_merchant_vs_ads --merchant-id 389412329 --customer 747-204-9709
  py -m src.compare_sellers_merchant_vs_ads --merchant-id 389412329 --customer 747-204-9709 --max-products 50000
  py -m src.compare_sellers_merchant_vs_ads --merchant-id 389412329 --customer 747-204-9709 --sellers-cache sellers_389412329.txt
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Optional, Set

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTENT_API_CONFIG = PROJECT_ROOT / "config" / "content-api.yaml"
GOOGLE_ADS_CONFIG = PROJECT_ROOT / "config" / "google-ads.yaml"
CONFIG_PATH = PROJECT_ROOT / "config" / "google-ads.yaml"
MERCHANT_API_SCOPE = "https://www.googleapis.com/auth/content"
MERCHANT_API_PRODUCTS = "https://merchantapi.googleapis.com/products/v1"


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


# Max pageSize voor Merchant API products.list (doc: max 1000)
MERCHANT_PAGE_SIZE = 1000


def get_sellers_from_merchant_api(
    merchant_account_id: str,
    max_products: Optional[int] = None,
    sellers_cache_path: Optional[Path] = None,
) -> Set[str]:
    """
    Haal unieke customLabel0 (sellers) op uit Merchant API.
    - max_products: stop na N producten (steekproef; None = alles).
    - sellers_cache_path: laad uit bestand als het bestaat (eerste regel = merchant_id);
      anders fetch en sla op.
    """
    if sellers_cache_path and sellers_cache_path.exists():
        try:
            lines = sellers_cache_path.read_text(encoding="utf-8").strip().splitlines()
            if lines and lines[0].startswith("merchant_id="):
                cached_id = lines[0].split("=", 1)[1].strip()
                if cached_id == merchant_account_id:
                    sellers = set(s.strip() for s in lines[1:] if s.strip())
                    print(f"  Sellers geladen uit cache: {sellers_cache_path} ({len(sellers)} sellers)")
                    return sellers
        except Exception as e:
            print(f"  Cache lezen mislukt: {e}, opnieuw ophalen via API")

    client_id = _read_yaml_string_value(CONTENT_API_CONFIG, "client_id")
    client_secret = _read_yaml_string_value(CONTENT_API_CONFIG, "client_secret")
    refresh_token = _read_yaml_string_value(CONTENT_API_CONFIG, "refresh_token")
    if not all([client_id, client_secret, refresh_token]):
        raise RuntimeError("config/content-api.yaml ontbreekt of is incompleet (client_id, client_secret, refresh_token)")

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google.auth.transport.requests import AuthorizedSession

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=[MERCHANT_API_SCOPE],
    )
    creds.refresh(Request())
    session = AuthorizedSession(creds)

    sellers: Set[str] = set()
    url = f"{MERCHANT_API_PRODUCTS}/accounts/{merchant_account_id}/products"
    page_token: Optional[str] = None
    total_products = 0
    page_num = 0

    while True:
        page_num += 1
        params = {"pageSize": MERCHANT_PAGE_SIZE}
        if page_token:
            params["pageToken"] = page_token
        r = session.get(url, params=params)
        if not r.ok:
            raise RuntimeError(f"Merchant API products list failed: {r.status_code} {r.text[:500]}")
        data = r.json()
        products = data.get("products") or []
        for p in products:
            total_products += 1
            attrs = p.get("productAttributes") or {}
            cl0 = attrs.get("customLabel0") or ""
            if cl0 and isinstance(cl0, str):
                sellers.add(cl0.strip())
            if max_products is not None and total_products >= max_products:
                break
        if page_num == 1 or page_num % 20 == 0 or not data.get("nextPageToken"):
            print(f"  Pagina {page_num}: {total_products} producten, {len(sellers)} unieke sellers")
        if max_products is not None and total_products >= max_products:
            print(f"  Gestopt bij --max-products={max_products} (steekproef)")
            break
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    print(f"  Totaal producten verwerkt: {total_products}")

    if sellers_cache_path and sellers:
        try:
            text = f"merchant_id={merchant_account_id}\n" + "\n".join(sorted(sellers))
            sellers_cache_path.write_text(text, encoding="utf-8")
            print(f"  Sellers opgeslagen in cache: {sellers_cache_path}")
        except Exception as e:
            print(f"  Cache schrijven mislukt: {e}")

    return sellers


def get_sellers_from_google_ads(customer_id: str) -> Set[str]:
    """Haal alle unieke product_custom_attribute0 (sellers) op uit shopping_performance_view (laatste 30 dagen)."""
    from dotenv import load_dotenv
    from google.ads.googleads.client import GoogleAdsClient
    from google.ads.googleads.errors import GoogleAdsException

    load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
    import os
    cfg = os.environ.get("GOOGLE_ADS_CONFIGURATION_FILE") or str(CONFIG_PATH)
    client = GoogleAdsClient.load_from_storage(cfg)
    ga = client.get_service("GoogleAdsService")

    customer_id_clean = "".join(filter(str.isdigit, customer_id))
    query = """
        SELECT segments.product_custom_attribute0
        FROM shopping_performance_view
        WHERE segments.date DURING LAST_30_DAYS
        AND segments.product_custom_attribute0 IS NOT NULL
    """
    sellers: Set[str] = set()
    try:
        for row in ga.search(customer_id=customer_id_clean, query=query):
            seller = row.segments.product_custom_attribute0 or ""
            if seller:
                sellers.add(seller)
    except GoogleAdsException as ex:
        raise RuntimeError(f"Google Ads query failed: {ex}") from ex
    return sellers


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Vergelijk sellers uit Merchant API (custom label 0) met Google Ads (shopping performance)"
    )
    parser.add_argument("--merchant-id", required=True, help="Merchant Center account ID (bijv. 389412329)")
    parser.add_argument("--customer", required=True, help="Google Ads customer ID (bijv. 747-204-9709)")
    parser.add_argument(
        "--max-products",
        type=int,
        default=None,
        help="Max aantal producten om te verwerken (steekproef; default = alles). Bijv. 50000 voor snelle check.",
    )
    parser.add_argument(
        "--sellers-cache",
        type=str,
        default=None,
        help="Bestand om sellers in op te slaan/te laden. Eerste run: ophalen en opslaan. Volgende runs: direct laden (geen API-calls).",
    )
    args = parser.parse_args()

    merchant_id = args.merchant_id.strip()
    customer_id = args.customer.strip()
    cache_path = Path(args.sellers_cache).resolve() if args.sellers_cache else None

    print("Merchant API: sellers ophalen uit producten (custom label 0)...")
    if args.max_products:
        print(f"  Beperkt tot {args.max_products} producten (steekproef)")
    if cache_path:
        print(f"  Cache: {cache_path}")
    try:
        merchant_sellers = get_sellers_from_merchant_api(
            merchant_id,
            max_products=args.max_products,
            sellers_cache_path=cache_path,
        )
    except Exception as e:
        print(f"Fout Merchant API: {e}")
        return
    print(f"  Unieke sellers (Merchant API): {len(merchant_sellers)}")

    print("Google Ads: sellers ophalen uit shopping_performance_view (laatste 30 dagen)...")
    try:
        ads_sellers = get_sellers_from_google_ads(customer_id)
    except Exception as e:
        print(f"Fout Google Ads: {e}")
        return
    print(f"  Unieke sellers (Google Ads): {len(ads_sellers)}")

    # Vergelijk case-insensitief (Merchant vaak Hoofdletters, Ads vaak lowercase)
    def norm(s: str) -> str:
        return s.strip().lower()

    merchant_by_norm: dict[str, str] = {norm(s): s for s in merchant_sellers}
    ads_by_norm: dict[str, str] = {norm(s): s for s in ads_sellers}
    merchant_norm = set(merchant_by_norm)
    ads_norm = set(ads_by_norm)

    only_merchant_norm = merchant_norm - ads_norm
    only_ads_norm = ads_norm - merchant_norm
    in_both_norm = merchant_norm & ads_norm

    only_merchant = [merchant_by_norm[k] for k in only_merchant_norm]
    only_ads = [ads_by_norm[k] for k in only_ads_norm]

    print()
    print("=" * 60)
    print("VERGELIJKING (case-insensitief)")
    print("=" * 60)
    print(f"  Alleen in Merchant API (feed):     {len(only_merchant)}")
    print(f"  Alleen in Google Ads (traffic):   {len(only_ads)}")
    print(f"  In beide:                        {len(in_both_norm)}")
    print()
    if only_merchant:
        print("Sellers alleen in Merchant (geen traffic laatste 30d):")
        for s in sorted(only_merchant, key=str.lower)[:30]:
            print(f"  - {s}")
        if len(only_merchant) > 30:
            print(f"  ... en {len(only_merchant) - 30} meer")
    print()
    if only_ads:
        print("Sellers alleen in Google Ads (niet in feed / andere naam?):")
        for s in sorted(only_ads, key=str.lower)[:30]:
            print(f"  - {s}")
        if len(only_ads) > 30:
            print(f"  ... en {len(only_ads) - 30} meer")


if __name__ == "__main__":
    main()
