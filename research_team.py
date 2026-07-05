"""
Research team stage.

Instead of one trend-scan call, this runs three independent researcher
agents, each briefed to look at the opportunity from a different angle, then
a fourth "lead" agent reviews all three findings and picks the strongest one
(or explains why it's blending/adjusting them). This catches the case where
a single research pass latches onto a weak or overly narrow idea - three
independent takes plus a review step is a real (if partial) safeguard
against that, not a guarantee.

Falls back to the caller's fallback niche rotation if the whole team fails
to produce anything (e.g. all three researcher calls error out).
"""

import json
import re

import requests

RESEARCHER_ANGLES = [
    "seasonal and calendar-driven opportunities (upcoming holidays, back-to-school, "
    "graduation, gifting seasons) in the next 4-8 weeks",
    "rising evergreen niches - hobbies, professions, or identity groups with strong, "
    "steady gift-buying behavior that may be currently underserved",
    "broad cultural/lifestyle mood shifts (e.g. what people are talking about wanting "
    "more of in their daily life - rest, humor, productivity, comfort) that translate "
    "into wearable or giftable slogans",
]

RESEARCHER_SYSTEM = """You are one researcher on a print-on-demand product research team, assigned this \
specific angle: {angle}

Use web search to investigate this angle and propose ONE concrete niche opportunity. Output ONLY valid \
JSON (no markdown fences, no commentary) with this exact shape:

{{"niche": "a specific, narrow niche phrase (not a full sentence)", "product_type": "one of: {product_types}", \
"reasoning": "one sentence on why this fits your assigned angle right now", "avoid_terms": ["any brand names, \
characters, or trademarked terms that came up in research that should NOT be used in a design"]}}

Keep the niche narrow and concrete. Never suggest a niche built around a specific real brand, celebrity, \
sports team, or copyrighted character. The "product_type" value must be exactly one of the options listed."""

LEAD_SYSTEM = """You are the lead researcher on a print-on-demand product team, reviewing proposals from \
three researchers who each investigated a different angle. Pick the single strongest proposal, or combine \
the best elements into a sharper version of one of them. Output ONLY valid JSON (no markdown fences, no \
commentary) with this exact shape:

{"niche": "the chosen/refined niche phrase", "product_type": "the chosen product type (must match one of \
the proposals)", "reasoning": "one sentence on why this beat the other two proposals", "avoid_terms": \
["combined avoid_terms from all proposals that are still relevant"], "team_notes": "one sentence noting \
what the other two researchers proposed, for the record"}"""


def _call_claude(api_key, system, user_msg, use_search=True, max_tokens=1000):
    body = {
        "model": "claude-sonnet-4-6",
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user_msg}],
    }
    if use_search:
        body["tools"] = [{"type": "web_search_20250305", "name": "web_search"}]
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=body,
        timeout=90,
    )
    resp.raise_for_status()
    data = resp.json()
    text_block = next((b["text"] for b in data["content"] if b.get("type") == "text"), None)
    if not text_block:
        return None
    cleaned = re.sub(r"^```json|^```|```$", "", text_block.strip(), flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        return None
    return json.loads(match.group(0))


def run_research_team(api_key, product_types, recent_niches=None):
    recent_niches = recent_niches or []
    product_types_str = ", ".join(product_types)
    avoid_clause = f" Avoid repeating these recent niches: {', '.join(recent_niches)}." if recent_niches else ""

    proposals = []
    for angle in RESEARCHER_ANGLES:
        try:
            system = RESEARCHER_SYSTEM.format(angle=angle, product_types=product_types_str)
            user_msg = f"Investigate your assigned angle and propose one niche opportunity.{avoid_clause}"
            result = _call_claude(api_key, system, user_msg)
            if result and result.get("niche") and result.get("product_type") in product_types:
                proposals.append(result)
        except Exception as e:
            print(f"Researcher failed on angle '{angle[:40]}...': {e}")

    if not proposals:
        print("All researchers failed - falling back.")
        return None

    if len(proposals) == 1:
        proposals[0]["team_notes"] = "Only one researcher succeeded; used by default."
        return proposals[0]

    try:
        lead_user_msg = "Here are the researcher proposals:\n" + json.dumps(proposals, indent=2)
        final = _call_claude(api_key, LEAD_SYSTEM, lead_user_msg, use_search=False, max_tokens=600)
        if final and final.get("niche") and final.get("product_type") in product_types:
            return final
    except Exception as e:
        print(f"Lead reviewer failed, using first proposal instead: {e}")

    return proposals[0]
