"""Fetch products and labels from your source of truth.

This is a placeholder implementation that returns a static structure. Replace
with real logic to fetch from your CMS, database, or product feed.
"""

from __future__ import annotations

from typing import Dict, List, TypedDict


class Product(TypedDict):
    id: str
    title: str
    price: float
    labels: List[str]


def fetch_products_with_labels() -> List[Product]:
    """Return a list of products including labels.

    Replace this stub with actual data retrieval (e.g., API/DB call).
    """

    products: List[Product] = [
        {"id": "SKU-001", "title": "Example Product A", "price": 19.99, "labels": ["bestseller", "summer"]},
        {"id": "SKU-002", "title": "Example Product B", "price": 49.0, "labels": ["new", "accessories"]},
    ]
    return products





