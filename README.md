# Reel Radar

Every Monday, finds the reels that did far better than their creator's usual,
across 6 niches picked for a Singapore property agent's personal brand, and
puts them on one page with a "+ Calendar" button to plan his version.

**Score** = a reel's views ÷ what that creator's reels usually have by the same age.
10× means it's on pace for ten times their normal. Only reels at 2.5× or more show,
up to 10 per niche and 2 per creator.

## Files

| File | What it does |
|---|---|
| `config.json` | Niches, hashtags, tracked accounts, his handle, budget, thresholds |
| `discover.py` | One-time: finds creators per niche and lists them for you to approve |
| `radar.py` | Weekly: scrapes reels, scores them, writes `docs/data.json` |
| `docs/index.html` | The page |
| `.github/workflows/weekly.yml` | Runs `radar.py` every Monday 9am SGT |
| `test_radar.py` | Checks the scoring maths: `python test_radar.py` |

## Setup

1. **Apify key.** Sign up at apify.com, then Settings → API & Integrations → copy the token.
2. **His handle.** Put his Instagram handle in `config.json` as `"own_account"`.
3. **Find creators** (costs up to $4.50 of Apify credit; raise the limits at the top of `discover.py` on a paid plan):
   ```
   set APIFY_TOKEN=your_token          (PowerShell: $env:APIFY_TOKEN="your_token")
   python discover.py
   ```
   Open `candidates.csv`, put `y` in the approve column for about 30 per niche
   (Singapore first, up to 1 in 5 Mandarin), then:
   ```
   python discover.py --apply candidates.csv
   ```
4. **Put it on GitHub** (public repo), then in the repo:
   - Settings → Secrets and variables → Actions → New secret `APIFY_TOKEN`
   - Settings → Pages → Deploy from branch `main`, folder `/docs`
   - Actions tab → Weekly reel run → Run workflow (first run)
5. **Calendar.** Make a Google Calendar called "Dad - Content" and share it with him.
   "+ Calendar" opens a pre-filled event; pick that calendar and a date, then save.

## Monthly upkeep

The page lists accounts to replace (quiet for 30 days, grew past the range, or gone).
Run `discover.py` again, approve replacements, delete the old ones from `config.json`.

## Costs

The page footer shows this month's Apify spend against `budget_usd_per_month`.
If a run would go over, it skips and says so on the page instead of spending more.
