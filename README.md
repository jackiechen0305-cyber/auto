# Auto POD Agent

An autonomous pipeline: on a schedule, it researches a timely niche, has
Claude write an original slogan and listing copy, renders that slogan into
a print-ready design, and creates (optionally publishes) a product on your
Printify-connected store. No manual clicking once it's set up.

## What's new: a real trend-scan stage

Earlier versions of this just cycled through a fixed list of niches. Now the
first thing each run does is ask Claude to search the web for what's
actually timely right now (seasonal moments, rising gift/apparel searches)
and pick a niche based on that — `trend_scan.py`. If that search fails for
any reason (rate limit, network hiccup), it automatically falls back to the
static rotation in `niches.json` so a run never just stops.

## Other reliability additions

- **`history.json`** logs every run — niche, slogan, whether it came from
  the trend scan or the fallback list, the resulting product ID, and
  whether it was published. This also feeds back into future runs so it
  won't repeat a niche or slogan it just used.
- **A built-in safety check** (`safety_check` in `generate_and_list.py`)
  scans the generated slogan/title/description against a blocklist of
  common brand names/franchises before anything gets created. If it's
  flagged, the run stops and logs it instead of creating a product. This is
  a backstop, not a guarantee — still worth glancing at `history.json`
  occasionally.

## Honest scope, read this first

- **Designs are typography-only.** This generates clean, original slogan-on-
  garment designs — it does not generate illustrations, characters, or
  graphics. A real share of POD sales are exactly this kind of text-based
  product, but if you pictured illustrated designs, that needs a separate
  image-generation step this repo doesn't include.
- **You should review before going fully live.** `product_config.json` has a
  `"publish": false` flag by default — products get created in Printify but
  stay unpublished until you flip that to `true`. Look at a few first.
- **Slogans are original, not copies.** The prompt explicitly tells Claude
  not to reuse song lyrics, movie lines, or existing trademarked slogans —
  but it's still worth a skim before publishing, since novelty/trademark
  issues in the merch space are a real risk (e.g. a slogan that's "original"
  wording can still collide with someone's registered trademark by
  coincidence — a quick trademark search on anything you plan to scale is a
  good habit).

## What you need

- A [Printify](https://printify.com) account, free to create
- A shop connected to Printify (Etsy or Shopify are the common choices —
  connect this from Printify's dashboard under **My New Store**)
- A Printify **Personal Access Token**: Printify dashboard → **My Account →
  Connections → Generate new token**
- A free [GitHub](https://github.com) account
- An [Anthropic API key](https://console.anthropic.com)

## Setup

### 1. Find your real Printify IDs
Printify's catalog and your shop ID are account-specific, so run the
included helper locally first (needs Python + `pip install requests`):

```
export PRINTIFY_API_TOKEN=your_token
python list_catalog.py shops
python list_catalog.py blueprints
python list_catalog.py providers <blueprint_id>
python list_catalog.py variants <blueprint_id> <print_provider_id>
```

Pick a blueprint (e.g. a basic t-shirt), a provider that ships to where your
customers are, and the variant IDs (sizes/colors) you want to sell. Fill
those into `product_config.json`, along with your `shop_id` and a
`price_cents` (e.g. `1999` for $19.99). Remove the `_instructions` key when
done.

### 2. Create a GitHub repo
Upload everything in this folder, keeping the `.github/workflows/` structure
intact, including your filled-in `product_config.json`.

### 3. Add secrets
**Settings → Secrets and variables → Actions** in your repo:

| Secret | Value |
|---|---|
| `ANTHROPIC_API_KEY` | your Claude API key |
| `PRINTIFY_API_TOKEN` | your Printify personal access token |

### 4. Turn it on
**Actions** tab → enable workflows → **Run workflow** to test it manually,
or just wait for the schedule (default: Mondays and Thursdays, 10am UTC).

## Customizing

- **Niches**: edit `niches.json` — add, remove, or reword as many as you like.
- **Schedule**: edit the `cron` line in `.github/workflows/auto-pod.yml`.
- **Design look**: `design_renderer.py` controls font size, wrapping, and
  layout if you want a different visual style.
- **Slogan tone/rules**: `SYSTEM_PROMPT` in `generate_and_list.py`.
- **Auto-publish**: set `"publish": true` in `product_config.json` once
  you've reviewed enough output to trust it.

## Natural next step
Pair this with the `auto-content-agent` blog pipeline and cross-promote —
a blog post about a niche can link to the matching product, and vice versa.
