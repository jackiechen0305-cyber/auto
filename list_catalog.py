"""
Run this ONCE, manually, before turning on the automation.

Printify's catalog of products (blueprints), print providers, and variants
changes over time and varies by account/region, so rather than guessing IDs
that might be wrong, this fetches the real current options from your account
so you can fill in product_config.json correctly.

Usage:
    export PRINTIFY_API_TOKEN=your_token
    python list_catalog.py shops          # lists your connected shops -> get shop_id
    python list_catalog.py blueprints     # lists product types -> get blueprint_id
    python list_catalog.py providers 5    # lists print providers for blueprint 5
    python list_catalog.py variants 5 39  # lists variants for blueprint 5 + provider 39
"""

import os
import sys

import requests

TOKEN = os.environ.get("PRINTIFY_API_TOKEN")
BASE = "https://api.printify.com/v1"


def _get(path):
    r = requests.get(f"{BASE}{path}", headers={"Authorization": f"Bearer {TOKEN}"}, timeout=30)
    r.raise_for_status()
    return r.json()


def main():
    if not TOKEN:
        print("Set PRINTIFY_API_TOKEN first.")
        sys.exit(1)

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "shops":
        for shop in _get("/shops.json"):
            print(f"shop_id={shop['id']}  title={shop['title']}  channel={shop['sales_channel']}")

    elif cmd == "blueprints":
        for bp in _get("/catalog/blueprints.json"):
            print(f"blueprint_id={bp['id']}  title={bp['title']}")

    elif cmd == "providers":
        blueprint_id = sys.argv[2]
        for p in _get(f"/catalog/blueprints/{blueprint_id}/print_providers.json"):
            print(f"print_provider_id={p['id']}  title={p['title']}")

    elif cmd == "variants":
        blueprint_id, provider_id = sys.argv[2], sys.argv[3]
        data = _get(f"/catalog/blueprints/{blueprint_id}/print_providers/{provider_id}/variants.json")
        for v in data.get("variants", []):
            print(f"variant_id={v['id']}  title={v['title']}")

    else:
        print(__doc__)


if __name__ == "__main__":
    main()
