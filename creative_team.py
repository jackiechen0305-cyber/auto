"""
Creative team stage.

Instead of one copywriter producing one slogan, three copywriters with
different briefs each produce a candidate concept, then a creative director
reviews them side by side and picks (or refines) the winner. This raises
the floor on quality - a weak or generic slogan has to beat two rivals to
ship, rather than shipping just because it was the only one generated.
"""

import json
import re

import requests

COPYWRITER_STYLES = [
    "witty and punchy - the kind of line that makes someone smirk in public",
    "warm and heartfelt - something a person would gift to someone they love",
    "bold and identity-proud - a statement the wearer uses to signal who they are",
]

COPYWRITER_SYSTEM = """You are one copywriter on a print-on-demand creative team. Your assigned style: \
{style}

Given a niche, write ONE original concept in your style. Output ONLY valid JSON (no markdown fences, \
no commentary) with this exact shape:

{{"slogan": "a short punchy original slogan, under 6 words, no copyrighted phrases or song lyrics", \
"product_title": "SEO-friendly product listing title", "description": "a 2-3 sentence product description", \
"tags": ["tag1", "tag2"], "text_color": "#111111", "bg_color": null}}

Rules:
- The slogan must be entirely original wording - never quote or closely paraphrase a known song lyric, \
movie line, book quote, or existing trademarked slogan.
- Do not reference real brand names, celebrities, sports teams, or copyrighted characters.
- Keep it appropriate for a general audience.
- text_color should be a hex readable on most garment colors (default to solid dark or white)."""

DIRECTOR_SYSTEM = """You are the creative director reviewing three copywriter concepts for the same \
print-on-demand niche. Judge them on: originality, how instantly the target buyer would 'get it', and \
how well it works as large text on a product. Pick the strongest, or refine the best one slightly \
(keeping its spirit). Output ONLY valid JSON (no markdown fences, no commentary) with this exact shape:

{"slogan": "...", "product_title": "...", "description": "...", "tags": ["..."], "text_color": "#111111", \
"bg_color": null, "director_notes": "one sentence on why this won"}"""


def _call_claude(api_key, system, user_msg, max_tokens=500):
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


def run_creative_team(api_key, niche_text, avoid_terms=None, recent_slogans=None):
    user_msg = f"Niche: {niche_text}"
    if avoid_terms:
        user_msg += f"\nDo not use or reference these terms in any way: {', '.join(avoid_terms)}"
    if recent_slogans:
        user_msg += f"\nDon't repeat these recent slogans, be genuinely different: {', '.join(recent_slogans)}"

    candidates = []
    for style in COPYWRITER_STYLES:
        try:
            system = COPYWRITER_SYSTEM.format(style=style)
            concept = _call_claude(api_key, system, user_msg)
            if concept.get("slogan"):
                candidates.append(concept)
        except Exception as e:
            print(f"Copywriter failed ({style[:30]}...): {e}")

    if not candidates:
        return None

    if len(candidates) == 1:
        candidates[0]["director_notes"] = "Only one copywriter succeeded; used by default."
        return candidates[0]

    try:
        director_msg = f"Niche: {niche_text}\nCandidates:\n{json.dumps(candidates, indent=2)}"
        final = _call_claude(api_key, DIRECTOR_SYSTEM, director_msg, max_tokens=600)
        if final.get("slogan"):
            return final
    except Exception as e:
        print(f"Creative director failed, using first candidate: {e}")

    return candidates[0]
