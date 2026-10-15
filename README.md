# Feeder Ladder (working name) – unofficial, non-commercial open-wheel fan site
- `python3 scripts/refresh.py` → writes site/data/series.json, site/data/news.json, site/cal/*.ics (cached in .cache, 1h TTL, 0.5s spacing, 429 backoff)
- Set `BLACKTOP_API_KEY` to enable F2/F3 (free key at ocblacktop.com; verify endpoint paths first).
- News: edit content/news.json (own-words summaries + source link, type News|Rumor).
- Preview: `cd site && python3 -m http.server 8765`
- Deploy: publish the `site/` folder (Cloudflare Pages or GitHub Pages). Workflow: .github/workflows/refresh.yml
