"""
Autonomous POD agent.

What it does, in order:
1. Runs a trend scan (trend_scan.py) using Claude + live web search to find
   a timely niche opportunity. Falls back to rotating through niches.json
   if the scan fails or the API call errors out.
2. Asks Claude for an original slogan + product title/description/tags for
   that niche, explicitly avoiding any risky terms the trend scan flagged.
3. Runs the slogan past a lightweight safety check (built-in blocklist +
   flagged terms) before doing anything with it.
4. Renders the slogan into a print-ready PNG design (design_renderer.py)
5. Uploads the design to Printify and creates a product from it using the
   blueprint/provider/variants in product_config.json
6. Publishes it to your connected shop if "publish": true in the config
   (otherwise it's created but left unpublished so you can review it first)
7. Logs everything to history.json so you have a record and so future runs
   avoid repeating the same niche or slogan.

Required environment variables (set as GitHub Actions secrets):
  ANTHROPIC_API_KEY
  PRINTIFY_API_TOKEN

Config: product_config.json (fill this in using list_catalog.py first)
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
from trend_scan import get_trending_niche

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

SYSTEM_PROMPT = """You write original, family-friendly slogans for print-on-demand products (t-shirts, \
mugs, etc). Given a niche, output ONLY valid JSON (no markdown fences, no commentary) with this exact shape:

{"slogan": "a short punchy original slogan, under 6 words, no copyrighted phrases or song lyrics", \
"product_title": "SEO-friendly product listing title", "description": "a 2-3 sentence product description", \
"tags": ["tag1", "tag2"], "text_color": "#111111", "bg_color": null}

Rules:
- The slogan must be entirely original wording - never quote or closely paraphrase a known song lyric, \
movie line, book quote, or existing trademarked slogan.
- Do not reference real brand names, celebrities, sports teams, or copyrighted characters.
- Keep it appropriate for a general audience.
- text_color should be a hex string readable on most garment colors (dark colors work best on light \
shirts and vice versa - default to a single solid dark or white color).
"""


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


def generate_concept(niche_text, avoid_terms=None, recent_slogans=None):
    user_msg = f"Niche: {niche_text}"
    if avoid_terms:
        user_msg += f"\nDo not use or reference these terms in any way: {', '.join(avoid_terms)}"
    if recent_slogans:
        user_msg += f"\nDon't repeat these recent slogans, make it genuinely different: {', '.join(recent_slogans)}"

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 500,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_msg}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    text_block = next((b["text"] for b in data["content"] if b["type"] == "text"), "{}")
    cleaned = re.sub(r"^```json|^```|```$", "", text_block.strip(), flags=re.MULTILINE).strip()
    return json.loads(cleaned)


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


def create_product(config, concept, image_id):
    shop_id = config["shop_id"]
    payload = {
        "title": concept["product_title"],
        "description": concept["description"],
        "blueprint_id": int(config["blueprint_id"]),
        "print_provider_id": int(config["print_provider_id"]),
        "variants": [
            {"id": int(vid), "price": config["price_cents"], "is_enabled": True}
            for vid in config["variant_ids"]
        ],
        "print_areas": [
            {
                "variant_ids": [int(vid) for vid in config["variant_ids"]],
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
    if "PUT_" in json.dumps(config):
        print("product_config.json still has placeholder values. Run list_catalog.py and fill it in first.")
        sys.exit(1)

    history = load_json(HISTORY_PATH, default=[])
    recent_niches = [h["niche"] for h in history[-10:]]
    recent_slogans = [h["slogan"] for h in history[-10:] if h.get("slogan")]

    avoid_terms = []
    trend = get_trending_niche(ANTHROPIC_API_KEY, recent_niches=recent_niches)
    if trend and trend.get("niche"):
        niche_text = trend["niche"]
        avoid_terms = trend.get("avoid_terms", [])
        source = "trend scan"
        print(f"Trend scan picked: {niche_text}  ({trend.get('reasoning', '')})")
    else:
        niches = load_json(NICHES_PATH, default=[])
        niche_entry = pick_niche(niches)
        niche_text = niche_entry["niche"]
        source = "fallback rotation"
        print(f"Using fallback niche rotation: {niche_text}")
        niche_entry["used"] = True
        save_json(NICHES_PATH, niches)

    concept = generate_concept(niche_text, avoid_terms=avoid_terms, recent_slogans=recent_slogans)
    print(f"Slogan: {concept['slogan']}")

    problems = safety_check(concept, extra_blocked_terms=avoid_terms)
    if problems:
        print(f"Safety check flagged terms {problems} - skipping this run without creating a product.")
        history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "niche": niche_text, "source": source, "slogan": concept.get("slogan"),
            "status": "blocked_by_safety_check", "flagged_terms": problems,
        })
        save_json(HISTORY_PATH, history)
        sys.exit(1)

    design_path = ROOT / "design_output.png"
    render_design(
        concept["slogan"],
        design_path,
        text_color=concept.get("text_color", "#111111"),
        bg_color=concept.get("bg_color"),
    )

    image_id = upload_design(design_path, f"{niche_text[:30].replace(' ', '_')}.png")
    product = create_product(config, concept, image_id)
    print(f"Created product id={product['id']}")

    published = False
    if config.get("publish"):
        publish_product(config["shop_id"], product["id"])
        published = True
        print("Published to connected shop.")
    else:
        print("Created as unpublished draft (set \"publish\": true in product_config.json to auto-publish).")

    history.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "niche": niche_text,
        "source": source,
        "slogan": concept.get("slogan"),
        "product_id": product.get("id"),
        "published": published,
        "status": "created",
    })
    save_json(HISTORY_PATH, history)


if __name__ == "__main__":
    main()
