"""
Catalog team stage.

Removes the manual "look up IDs and hardcode them" step. Given a product
type (e.g. "mug"), this fetches Printify's real current catalog, then has
two independent checker agents each pick a blueprint/provider/variant set
from the real fetched options. If they agree, that's the pick. If they
disagree, a third tiebreaker agent decides between the two, and the
disagreement gets logged so you can see it happened.

This is a real safeguard against a single bad pick, not a guarantee -
still worth glancing at history.json occasionally.
"""

import json
import re

import requests

PRINTIFY_BASE = "https://api.printify.com/v1"

CHECKER_SYSTEM = """You are a catalog checker for a print-on-demand shop. You'll be given a product \
category and a list of real available blueprints (product options) from Printify's catalog. Pick the \
single best-fitting, most standard/popular option for a small shop selling this category (prefer well- \
known basics over obscure/niche variants, e.g. a standard crewneck tee over a fringe specialty cut, \
unless the category specifically calls for something unusual). Output ONLY valid JSON (no markdown \
fences, no commentary):

{"blueprint_id": <id from the list>, "reasoning": "one short sentence why"}"""

PROVIDER_CHECKER_SYSTEM = """You are a catalog checker for a print-on-demand shop. You'll be given a \
list of real print providers available for a chosen product. Pick the one with the best balance of \
being widely available and reasonably fast, avoiding providers whose name suggests a narrow specialty \
unrelated to general retail. Output ONLY valid JSON (no markdown fences, no commentary):

{"print_provider_id": <id from the list>, "reasoning": "one short sentence why"}"""

VARIANT_CHECKER_SYSTEM = """You are a catalog checker for a print-on-demand shop. You'll be given a real \
list of variants (size/color combinations) for a product. Pick a sensible small starter set - for \
apparel, typically S/M/L/XL in one popular neutral color (e.g. black or white); for non-apparel (mugs, \
totes, etc), pick the single standard/default variant unless multiple colors are clearly core to the \
product. Output ONLY valid JSON (no markdown fences, no commentary):

{"variant_ids": [<ids from the list>], "reasoning": "one short sentence why"}"""

TIEBREAKER_SYSTEM = """Two catalog checkers disagreed on a print-on-demand catalog pick. Review both \
proposals and the original options, then decide the better one. Output ONLY valid JSON (no markdown \
fences, no commentary):

{"chosen": "a" or "b", "reasoning": "one short sentence why"}"""


def _printify_get(token, path):
    r = requests.get(f"{PRINTIFY_BASE}{path}", headers={"Authorization": f"Bearer {token}"}, timeout=30)
    r.raise_for_status()
    return r.json()


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


def _two_checkers_agree(api_key, system, user_msg, key, valid_ids):
    """Runs the same checker prompt twice independently, compares results, tiebreaks if needed."""
    picks = []
    for _ in range(2):
        try:
            result = _call_claude(api_key, system, user_msg)
            value = result.get(key)
            if isinstance(value, list):
                if value and all(v in valid_ids for v in value):
                    picks.append(result)
            elif value in valid_ids:
                picks.append(result)
        except Exception as e:
            print(f"Checker call failed: {e}")

    if not picks:
        return None, "no_valid_picks"
    if len(picks) == 1:
        return picks[0], "only_one_succeeded"

    a, b = picks[0], picks[1]
    if a.get(key) == b.get(key):
        return a, "agreed"

    # disagreement - tiebreak
    try:
        tie_msg = f"Option A: {json.dumps(a)}\nOption B: {json.dumps(b)}\nOriginal options: {user_msg}"
        tie_result = _call_claude(api_key, TIEBREAKER_SYSTEM, tie_msg, max_tokens=200)
        chosen = a if tie_result.get("chosen") == "a" else b
        return chosen, f"disagreed_tiebroken (a={a.get(key)}, b={b.get(key)})"
    except Exception as e:
        print(f"Tiebreaker failed, defaulting to first checker: {e}")
        return a, f"disagreed_tiebreak_failed (a={a.get(key)}, b={b.get(key)})"


def verify_catalog_choice(api_key, printify_token, product_type):
    """Returns (config_dict, notes_dict) or (None, notes_dict) if nothing usable was found."""
    notes = {}

    blueprints = _printify_get(printify_token, "/catalog/blueprints.json")
    matches = [bp for bp in blueprints if product_type.lower() in bp["title"].lower()]
    if not matches:
        # broaden: try matching on individual significant words in the product type
        words = [w for w in product_type.lower().split() if len(w) > 3]
        matches = [bp for bp in blueprints if any(w in bp["title"].lower() for w in words)]
    if not matches:
        return None, {"error": f"no blueprints matched product_type '{product_type}'"}

    valid_bp_ids = [bp["id"] for bp in matches]
    bp_summary = json.dumps([{"id": bp["id"], "title": bp["title"]} for bp in matches[:25]])
    bp_pick, bp_note = _two_checkers_agree(
        api_key, CHECKER_SYSTEM, f"Category: {product_type}\nAvailable blueprints: {bp_summary}",
        "blueprint_id", valid_bp_ids,
    )
    notes["blueprint"] = bp_note
    if not bp_pick:
        return None, notes
    blueprint_id = bp_pick["blueprint_id"]

    providers = _printify_get(printify_token, f"/catalog/blueprints/{blueprint_id}/print_providers.json")
    if not providers:
        return None, {**notes, "error": f"no print providers for blueprint {blueprint_id}"}
    valid_provider_ids = [p["id"] for p in providers]
    provider_summary = json.dumps([{"id": p["id"], "title": p["title"]} for p in providers])
    provider_pick, provider_note = _two_checkers_agree(
        api_key, PROVIDER_CHECKER_SYSTEM, f"Available print providers: {provider_summary}",
        "print_provider_id", valid_provider_ids,
    )
    notes["print_provider"] = provider_note
    if not provider_pick:
        return None, notes
    print_provider_id = provider_pick["print_provider_id"]

    variant_data = _printify_get(
        printify_token, f"/catalog/blueprints/{blueprint_id}/print_providers/{print_provider_id}/variants.json"
    )
    variants = variant_data.get("variants", [])
    if not variants:
        return None, {**notes, "error": f"no variants for blueprint {blueprint_id}/provider {print_provider_id}"}
    valid_variant_ids = [v["id"] for v in variants]
    variant_summary = json.dumps([{"id": v["id"], "title": v["title"]} for v in variants[:40]])
    variant_pick, variant_note = _two_checkers_agree(
        api_key, VARIANT_CHECKER_SYSTEM, f"Available variants: {variant_summary}",
        "variant_ids", valid_variant_ids,
    )
    notes["variants"] = variant_note
    if not variant_pick:
        return None, notes

    config = {
        "blueprint_id": blueprint_id,
        "print_provider_id": print_provider_id,
        "variant_ids": variant_pick["variant_ids"],
    }
    return config, notes
