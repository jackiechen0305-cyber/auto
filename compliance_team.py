"""
Compliance & pricing stage.

Two roles that gate the pipeline before anything is created:

1. Compliance reviewer - an independent agent that reviews the final chosen
   concept with fresh eyes, specifically hunting for trademark risk,
   accidental similarity to known slogans/lyrics, and anything not
   family-friendly. This runs ON TOP of the hardcoded blocklist, not
   instead of it. If the reviewer flags the concept, the run stops and the
   reason is logged. (Important honesty note: an AI reviewer is a useful
   extra filter but is NOT a legal trademark clearance - for designs you
   plan to scale, a real trademark search is still the responsible step.)

2. Pricing agent - reads the actual per-unit cost of the chosen variants
   from Printify's catalog data and sets a retail price with a sensible
   margin, instead of using one hardcoded price for every product type
   (a mug and a hoodie should not both cost $19.99).
"""

import json
import re

import requests

PRINTIFY_BASE = "https://api.printify.com/v1"

COMPLIANCE_SYSTEM = """You are a compliance reviewer for a print-on-demand shop. You'll be given a \
product concept (slogan, title, description, tags). Review it with fresh, skeptical eyes for:

1. Trademark/IP risk: does the slogan resemble a known brand slogan, song lyric, movie line, book \
quote, or catchphrase strongly associated with a specific franchise, celebrity, or company?
2. Appropriateness: is anything not family-friendly, or could it read as offensive to a group?
3. Claims: does the description make any factual claim that could be false or misleading?

Be strict - when in doubt, flag it. Output ONLY valid JSON (no markdown fences, no commentary):

{"approved": true or false, "concerns": ["specific concern 1", "..."] , "reasoning": "one sentence summary"}

If approved is false, concerns must explain exactly what to avoid so a rewrite can fix it."""


def _call_claude(api_key, system, user_msg, max_tokens=400):
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user_msg}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    text_block = next((b["text"] for b in data["content"] if b.get("type") == "text"), "{}")
    cleaned = re.sub(r"^```json|^```|```$", "", text_block.strip(), flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    return json.loads(match.group(0)) if match else {}


def compliance_review(api_key, concept):
    """Returns (approved: bool, details: dict)."""
    try:
        result = _call_claude(
            api_key, COMPLIANCE_SYSTEM,
            json.dumps({k: concept.get(k) for k in ("slogan", "product_title", "description", "tags")}),
        )
        return bool(result.get("approved")), result
    except Exception as e:
        # If the reviewer itself fails, fail CLOSED (don't approve by accident).
        return False, {"approved": False, "concerns": [f"compliance reviewer errored: {e}"],
                       "reasoning": "reviewer unavailable - failing closed"}


def compute_price_cents(printify_token, blueprint_id, print_provider_id, variant_ids,
                        margin_multiplier=2.2, min_margin_cents=700):
    """
    Reads real variant costs from Printify and returns a retail price in cents:
    the highest variant cost * margin_multiplier, but never less than
    cost + min_margin_cents, rounded to end in 99.
    Returns None if costs can't be read (caller should fall back to config price).
    """
    try:
        r = requests.get(
            f"{PRINTIFY_BASE}/catalog/blueprints/{blueprint_id}/print_providers/{print_provider_id}/variants.json",
            headers={"Authorization": f"Bearer {printify_token}"},
            timeout=30,
        )
        r.raise_for_status()
        variants = r.json().get("variants", [])
        wanted = [v for v in variants if v["id"] in [int(x) for x in variant_ids]]
        costs = [v.get("cost") for v in wanted if v.get("cost")]
        if not costs:
            return None
        max_cost = max(costs)  # cents
        price = max(int(max_cost * margin_multiplier), max_cost + min_margin_cents)
        # round up to nearest x.99
        price = ((price // 100) + 1) * 100 - 1
        return price
    except Exception as e:
        print(f"Pricing agent could not read variant costs: {e}")
        return None
