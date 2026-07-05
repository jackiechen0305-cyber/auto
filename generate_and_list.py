"""
Autonomous POD agent - structured like a small company.

Departments, in pipeline order:
1. RESEARCH TEAM (research_team.py) - three researchers investigate
   different angles, a lead reviewer picks the strongest niche + category.
2. CATALOG TEAM (catalog_team.py) - two independent checkers verify real
   Printify blueprint/provider/variant options live, with a tiebreaker.
3. CREATIVE TEAM (creative_team.py) - three copywriters with different
   styles each pitch a concept; a creative director picks the winner.
4. COMPLIANCE (compliance_team.py) - an independent reviewer checks the
   winning concept for trademark/IP risk and appropriateness, on top of a
   hardcoded blocklist. If rejected, the creative team gets ONE retry with
   the reviewer's concerns; if the retry also fails review, the run stops
   and logs why. The reviewer failing-closed means an error never
   accidentally approves anything.
5. PRICING (compliance_team.py) - reads real per-unit costs from Printify
   and sets a margin-based retail price per product, instead of one
   hardcoded price for everything.
6. PRODUCTION - renders the design, uploads it, creates the product, and
   publishes if "publish": true.
7. RECORDS - everything each team decided (including disagreements and
   rejections) is logged to history.json for audit.

Required environment variables (set as GitHub Actions secrets):
  ANTHROPIC_API_KEY
  PRINTIFY_API_TOKEN

Config: product_config.json (shop_id, fallback price_cents, publish,
allowed_product_categories, optional margin_multiplier)
"""

import base64
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

from design_renderer import render_design
from research_team import run_research_team
from catalog_team import verify_catalog_choice
from creative_team import run_creative_team
from compliance_team import compliance_review, compute_price_cents

ROOT = Path(__file__).parent
NICHES_PATH = ROOT / "niches.json"
CONFIG_PATH = ROOT / "product_config.json"
HISTORY_PATH = ROOT / "history.json"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
PRINTIFY_API_TOKEN = os.environ.get("PRINTIFY_API_TOKEN")
PRINTIFY_BASE = "https://api.printify.com/v1"

# Lightweight, always-on safety net on top of the model's own instructions.
# Not exhaustive - a real store should still spot-check output - but catches
# the most obvious cases automatically so a bad one can't slip straight to
# a published listing unattended.
BUILTIN_BLOCKLIST = [
    "nike", "adidas", "disney", "marvel", "star wars", "pokemon", "harry potter",
    "taylor swift", "nba", "nfl", "mlb", "nhl",
]


def load_json(path, default=None):
    if not path.exists():
        return default if default is not None else {}
    with open(path, "r") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def pick_niche(niches):
    for n in niches:
        if not n.get("used"):
            return n
    for n in niches:
        n["used"] = False
    return niches[0]


def safety_check(concept, extra_blocked_terms=None):
    """Returns a list of problems found, empty list means it passed."""
    blocked = [t.lower() for t in BUILTIN_BLOCKLIST] + [t.lower() for t in (extra_blocked_terms or [])]
    haystack = " ".join([
        concept.get("slogan", ""), concept.get("product_title", ""), concept.get("description", "")
    ]).lower()
    return [term for term in blocked if term in haystack]


def upload_design(png_path, file_name):
    with open(png_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    resp = requests.post(
        f"{PRINTIFY_BASE}/uploads/images.json",
        headers={"Authorization": f"Bearer {PRINTIFY_API_TOKEN}"},
        json={"file_name": file_name, "contents": b64},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def create_product(config, product_type_config, concept, image_id, price_cents):
    shop_id = config["shop_id"]
    payload = {
        "title": concept["product_title"],
        "description": concept["description"],
        "blueprint_id": int(product_type_config["blueprint_id"]),
        "print_provider_id": int(product_type_config["print_provider_id"]),
        "variants": [
            {"id": int(vid), "price": price_cents, "is_enabled": True}
            for vid in product_type_config["variant_ids"]
        ],
        "print_areas": [
            {
                "variant_ids": [int(vid) for vid in product_type_config["variant_ids"]],
                "placeholders": [
                    {
                        "position": "front",
                        "images": [
                            {"id": image_id, "x": 0.5, "y": 0.5, "scale": 1, "angle": 0}
                        ],
                    }
                ],
            }
        ],
    }
    resp = requests.post(
        f"{PRINTIFY_BASE}/shops/{shop_id}/products.json",
        headers={"Authorization": f"Bearer {PRINTIFY_API_TOKEN}"},
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def publish_product(shop_id, product_id):
    resp = requests.post(
        f"{PRINTIFY_BASE}/shops/{shop_id}/products/{product_id}/publish.json",
        headers={"Authorization": f"Bearer {PRINTIFY_API_TOKEN}"},
        json={
            "title": True, "description": True, "images": True,
            "variants": True, "tags": True, "keyFeatures": True, "shipping_template": True,
        },
        timeout=60,
    )
    resp.raise_for_status()


def main():
    if not ANTHROPIC_API_KEY or not PRINTIFY_API_TOKEN:
        print("ERROR: ANTHROPIC_API_KEY and PRINTIFY_API_TOKEN must both be set.", file=sys.stderr)
        sys.exit(1)

    config = load_json(CONFIG_PATH)
    if "PUT_" in json.dumps(config) or not config.get("allowed_product_categories"):
        print("product_config.json still has placeholder values, or has no allowed_product_categories "
              "configured. Fill those in first (see README).")
        sys.exit(1)

    allowed_categories = config["allowed_product_categories"]
    history = load_json(HISTORY_PATH, default=[])
    recent_niches = [h["niche"] for h in history[-10:] if h.get("niche")]
    recent_slogans = [h["slogan"] for h in history[-10:] if h.get("slogan")]
    run_record = {"timestamp": datetime.now(timezone.utc).isoformat()}

    # ---- 1. RESEARCH TEAM ----
    avoid_terms = []
    team_result = run_research_team(ANTHROPIC_API_KEY, allowed_categories, recent_niches=recent_niches)
    if team_result and team_result.get("niche"):
        niche_text = team_result["niche"]
        chosen_category = team_result["product_type"]
        avoid_terms = team_result.get("avoid_terms", [])
        run_record["source"] = "research team"
        run_record["team_notes"] = team_result.get("team_notes", "")
        print(f"[Research] {niche_text} -> {chosen_category}  ({team_result.get('reasoning', '')})")
    else:
        niches = load_json(NICHES_PATH, default=[])
        niche_entry = pick_niche(niches)
        niche_text = niche_entry["niche"]
        chosen_category = allowed_categories[0]
        run_record["source"] = "fallback rotation"
        print(f"[Research] team failed - fallback: {niche_text} -> {chosen_category}")
        niche_entry["used"] = True
        save_json(NICHES_PATH, niches)
    run_record["niche"] = niche_text
    run_record["product_type"] = chosen_category

    # ---- 2. CATALOG TEAM ----
    catalog_config, catalog_notes = verify_catalog_choice(ANTHROPIC_API_KEY, PRINTIFY_API_TOKEN, chosen_category)
    run_record["catalog_notes"] = catalog_notes
    print(f"[Catalog] {catalog_notes}")
    if not catalog_config:
        run_record["status"] = "catalog_team_failed"
        history.append(run_record)
        save_json(HISTORY_PATH, history)
        print(f"[Catalog] no usable product found for '{chosen_category}' - stopping this run.")
        sys.exit(1)
    run_record["catalog_pick"] = catalog_config

    # ---- 3. CREATIVE TEAM + 4. COMPLIANCE (with one retry) ----
    concept = None
    compliance_details = None
    extra_avoid = list(avoid_terms)
    for attempt in (1, 2):
        candidate = run_creative_team(
            ANTHROPIC_API_KEY, niche_text, avoid_terms=extra_avoid, recent_slogans=recent_slogans
        )
        if not candidate:
            break
        print(f"[Creative] attempt {attempt}: \"{candidate['slogan']}\"  ({candidate.get('director_notes', '')})")

        blocklist_hits = safety_check(candidate, extra_blocked_terms=avoid_terms)
        approved, review = compliance_review(ANTHROPIC_API_KEY, candidate)
        print(f"[Compliance] approved={approved and not blocklist_hits}  "
              f"blocklist_hits={blocklist_hits}  reviewer: {review.get('reasoning', '')}")

        if approved and not blocklist_hits:
            concept = candidate
            compliance_details = review
            break

        # feed the concerns back for one retry
        extra_avoid = list(set(extra_avoid + blocklist_hits + review.get("concerns", [])))

    if not concept:
        run_record["status"] = "blocked_by_compliance"
        run_record["compliance"] = compliance_details or {"reasoning": "creative team produced nothing usable"}
        history.append(run_record)
        save_json(HISTORY_PATH, history)
        print("[Compliance] concept rejected twice - stopping this run without creating a product.")
        sys.exit(1)
    run_record["slogan"] = concept["slogan"]
    run_record["compliance"] = compliance_details

    # ---- 5. PRICING ----
    price_cents = compute_price_cents(
        PRINTIFY_API_TOKEN,
        catalog_config["blueprint_id"],
        catalog_config["print_provider_id"],
        catalog_config["variant_ids"],
        margin_multiplier=config.get("margin_multiplier", 2.2),
    )
    if price_cents is None:
        price_cents = config.get("price_cents", 1999)
        run_record["pricing"] = {"source": "config fallback", "price_cents": price_cents}
        print(f"[Pricing] could not read costs - falling back to config price {price_cents}c")
    else:
        run_record["pricing"] = {"source": "cost-based", "price_cents": price_cents}
        print(f"[Pricing] cost-based retail price: {price_cents}c")

    # ---- 6. PRODUCTION ----
    design_path = ROOT / "design_output.png"
    render_design(
        concept["slogan"],
        design_path,
        text_color=concept.get("text_color", "#111111"),
        bg_color=concept.get("bg_color"),
    )
    image_id = upload_design(design_path, f"{niche_text[:30].replace(' ', '_')}.png")
    product = create_product(config, catalog_config, concept, image_id, price_cents)
    print(f"[Production] created {chosen_category} product id={product['id']}")

    published = False
    if config.get("publish"):
        publish_product(config["shop_id"], product["id"])
        published = True
        print("[Production] published to connected shop.")
    else:
        print("[Production] created as unpublished draft (set \"publish\": true to auto-publish).")

    # ---- 7. RECORDS ----
    run_record["product_id"] = product.get("id")
    run_record["published"] = published
    run_record["status"] = "created"
    history.append(run_record)
    save_json(HISTORY_PATH, history)


if __name__ == "__main__":
    main()
