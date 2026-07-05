# Auto POD Agent

An autonomous pipeline: on a schedule, a research team finds a timely niche
and product type, a catalog team independently verifies real Printify
options for it, Claude writes an original slogan and listing copy, and the
product gets created (optionally published) on your Printify-connected
store. No manual clicking, and no manual catalog ID lookup, once it's set up.

## The team structure

**Research team** (`research_team.py`) - three independent researcher
agents each investigate a different angle (seasonal/calendar moments,
evergreen niches, cultural mood shifts), then a lead reviewer picks the
strongest proposal or sharpens one of them. This is a real cross-check, not
a single guess - though it's still a safeguard, not a guarantee of a good
pick every time.

**Catalog team** (`catalog_team.py`) - takes the chosen product category
(e.g. "mug") and fetches Printify's actual current catalog live. Two
independent checker agents each pick a blueprint, then a print provider,
then a set of variants, from the real options. If they agree, that's the
pick. If they disagree at any step, a tiebreaker agent decides, and the
disagreement gets recorded in `history.json` so you can see it happened.

This means **no manual ID lookup is required anymore** - the old
`product_types` config with hardcoded blueprint/provider/variant IDs is
gone. You only need to tell it which general categories to consider.

## What you need

- A [Printify](https://printify.com) account with a shop connected (Etsy or Shopify)
- A Printify Personal Access Token (Account -> Connections)
- A GitHub account
- An Anthropic API key

## Setup

### 1. Get your shop_id
Use the included **"Look up Printify catalog IDs"** GitHub Action (Actions
tab -> run it with command=`shops`) - this is now the *only* manual lookup
step left, since it identifies which of your shops to publish to.

### 2. Fill in product_config.json
```json
{
  "shop_id": "your_real_shop_id",
  "price_cents": 1999,
  "publish": false,
  "allowed_product_categories": ["t-shirt", "mug", "hoodie", "tote bag"]
}
```
`allowed_product_categories` are just keywords - the catalog team searches
Printify's real catalog for blueprints matching these at runtime. Add or
remove categories freely; no IDs needed. Delete the `_instructions` key.

### 3. Add secrets
**Settings -> Secrets and variables -> Actions**: `ANTHROPIC_API_KEY` and
`PRINTIFY_API_TOKEN`.

### 4. Test it
**Actions -> Auto POD agent -> Run workflow**. Check `history.json`
afterward - it now logs which researchers proposed what, which one won,
and whether the catalog checkers agreed or needed a tiebreaker.

## Worth knowing before you turn on `publish` mode

- Start with `"publish": false` and actually read a handful of runs' worth
  of output and `history.json` entries first.
- More agents checking each other reduces the chance of a bad pick, but
  doesn't eliminate it - occasional review is still worth doing, especially
  early on.
- This uses noticeably more API calls per run than the single-agent version
  (roughly 4 calls for research, up to ~8 for the catalog team with
  tiebreaks). Cost is still small in absolute terms (a handful of cents per
  run at most) but worth knowing if you scale up run frequency a lot.
- Slogans are instructed to be original wording, but for a real store it's
  still worth a quick trademark gut-check on anything you plan to scale.

## Customizing

- **Categories**: edit `allowed_product_categories` in `product_config.json`.
- **Research angles**: edit `RESEARCHER_ANGLES` in `research_team.py`.
- **Schedule**: edit the `cron` line in `.github/workflows/auto-pod.yml`.
- **Design look**: `design_renderer.py` controls font size, wrapping, layout.
- **Slogan tone/rules**: `SYSTEM_PROMPT` in `generate_and_list.py`.
