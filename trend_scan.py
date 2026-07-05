"""
Trend scan stage.

Uses Claude with the web_search tool to check what's actually trending in
print-on-demand / gift niches right now, instead of blindly cycling through
a fixed list. Falls back to niches.json if the search comes back empty or
the API call fails for any reason, so the pipeline never just stops.
"""

import json
import re

import requests

SYSTEM_PROMPT = """You are a product-research analyst for a print-on-demand shop (t-shirts, mugs, etc, \
sold on Etsy/Shopify). Use web search to check what's currently trending in gift and apparel niches - \
seasonal moments, rising search terms, popular gift occasions in the next few weeks. Then output ONLY \
valid JSON (no markdown fences, no commentary) with this exact shape:

{"niche": "a specific, narrow niche phrase (not a full sentence)", "reasoning": "one sentence on why this \
is timely right now", "avoid_terms": ["any brand names, characters, or trademarked terms that came up in \
research that should NOT be used in a design"]}

Keep the niche narrow and concrete (e.g. "retired teacher humor" not "teachers"). Never suggest a niche \
built around a specific real brand, celebrity, sports team, or copyrighted character."""


def get_trending_niche(api_key, recent_niches=None):
    recent_niches = recent_niches or []
    user_msg = "Find one good print-on-demand niche opportunity for right now."
    if recent_niches:
        user_msg += f" Avoid repeating these recent niches: {', '.join(recent_niches)}."

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 1000,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_msg}],
                "tools": [{"type": "web_search_20250305", "name": "web_search"}],
            },
            timeout=90,
        )
        resp.raise_for_status()
        data = resp.json()
        text_block = next((b["text"] for b in data["content"] if b.get("type") == "text"), None)
        if not text_block:
            return None
        cleaned = re.sub(r"^```json|^```|```$", "", text_block.strip(), flags=re.MULTILINE).strip()
        # the model may include search commentary before the JSON - grab the last {...} block
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            return None
        return json.loads(match.group(0))
    except Exception as e:
        print(f"Trend scan failed, will fall back to niches.json: {e}")
        return None
