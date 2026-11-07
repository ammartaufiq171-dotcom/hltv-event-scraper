# hltv-event-scraper

Pull every completed match and every player stat line from an HLTV event page —
results, per-map scoreboards, series totals, and the event-level rating table —
into flat CSVs and one JSON bundle.

Built and validated against **IEM Beijing 2026** (event 8245): 26 matches,
65 maps, 80 players, 16 teams.

```
data/results.csv                26 matches: date, stage, teams, score, maps
data/player_stats_tournament.csv 80 players: HLTV rating 3.0 table
data/player_stats_derived.csv    totals from map data: K, D, +/-, ADR, KAST, headshots
data/player_stats_per_match.csv  one row per player per series (incl. K (hs))
data/player_stats_per_map.csv    one row per player per map (650 for IEM Beijing)
data/team_stats.csv              16 teams: maps, K-D diff, K/D, rating
data/schedule_upcoming.csv       unplayed fixtures
data/event.json                  everything above bundled
data/summary.md                  readable report: top players, all results
```

### Headshot columns

Both player tables (`per_match`, `per_map`) and the derived totals carry the
detailed-stats fields, joined per player per team:

| Column | HLTV column | Example |
|---|---|---|
| `headshots` | `K (hs)` | `44 (18)` → 18 |
| `hs_pct` | derived | 18 / 44 → 40.9 |
| `ekills_hs` | `eK (hs)` | `"43 (18)"` |
| `assists`, `flash_assists` | `A (f)` | `5 (0)` |
| `traded_deaths` | `D (t)` | `36 (8)` → 8 |
| `multi_kills` | `MKs` | 9 |
| `clutches` | `1vsX` | 2 |
| `op_kd` | `Op.K-D` | `6 : 4` |

## Why a real browser

HLTV sits behind Cloudflare. A headless browser gets stuck on the challenge
page; a **visible** Chrome with a persistent profile normally passes on its own,
and if a checkbox appears you click it once. The scraper then attaches to that
same browser over the DevTools protocol, so every `fetch()` carries the
clearance cookie and every page renders exactly as a human would see it.

## Quick start

```bash
pip install -r requirements.txt

# 1. open a visible Chrome on the debugging port (leave it open)
./scripts/open_chrome.sh 9222              # macOS / Linux / git-bash
# powershell -ExecutionPolicy Bypass -File .\scripts\open_chrome.ps1

# 2. load the event once so Cloudflare clears
#    (or just let the scraper navigate; click any checkbox that appears)

# 3. scrape, build, report, verify
python -m hltv all --event 8245 --out ./data
```

Partial runs:

```bash
python -m hltv scrape --event 8245 --out ./data      # raw only
python -m hltv scrape --event 8245 --limit 3         # smoke test
python -m hltv scrape --event 8245 --no-details      # skip headshot pages
python -m hltv details --out ./data                  # only the detailed-stats pages
python -m hltv build  --out ./data                   # raw -> CSVs
python -m hltv report --out ./data                   # summary.md + derived
python -m hltv verify --out ./data                   # self-check, exit 1 on failure
```

`scrape_matches` appends to `data/raw_matches.jsonl` and skips what it already
has, so an interrupted run resumes where it stopped.

## How it works

| Step | Endpoint | Extracted |
|---|---|---|
| event meta | `/events/<id>` → `/events/<id>/<slug>` | name, dates, prize, team count |
| results | `/results?event=<id>` | `.result-con` rows: teams, score, bo, match link, unix time |
| upcoming | `/events/<id>/matches` | unplayed fixtures: teams or TBD, stage label, start time, bo |
| brackets | event page (live DOM) | `.slotted-bracket` trees — best effort, see note 2 |
| team stats | `/stats/teams?event=<id>` | maps, K-D diff, K/D, rating |
| player stats | `/stats/players?event=<id>` | rating 3.0, net kills/24, eco + round swing |
| match detail | `/matches/<id>/<slug>` | series totals, per-map tables, stage line |
| detailed stats | `/stats/matches/<id>/<slug>` and `/stats/matches/mapstatsid/<id>/<slug>` | K (hs), eK (hs), A (f), D (t), MKs, 1vsX, opening K-D, per series and per map |

Stage for each result comes from the match page itself
(`.veto-box .preformatted-text` reads `Best of 3 (LAN) * Group A upper bracket
quarter-final`), with a bracket join as fallback.

Four things worth knowing if you fork this:

1. **The event page needs its slug.** `/events/8245` renders a shell with a
   generic title and no brackets; the canonical `/events/8245/iem-beijing-2026`
   is resolved from the links on that shell.
2. **Brackets are client-rendered and lazy.** The fetches return no bracket
   markup, and the placeholders on the live page often stay empty, so treat
   bracket output as best effort — per-match stage is the reliable source.
3. **Per-map blocks are keyed by map stats id.** Each `.mapholder` links to
   `/stats/matches/mapstatsid/<id>/...`; the matching block is
   `#<id>-content`. IDs start with a digit, so `querySelector('#123-content')`
   throws — use `getElementById`.
4. **Never parse the map score out of squashed text.** `.mapholder` innerText
   reads `NukeHEROIC13STATS (9:3; 4:1)B84`, and teams like `B8`, `G2`, `9z`
   glue onto the score. Read `.results-team-score` instead.
5. **The detailed-stats page has its own match id.** Headshots live at
   `/stats/matches/<statsMatchId>/<slug>`, which is unrelated to the match page
   id (`/matches/2399995` → `/stats/matches/132722`). Resolve it from the
   "Detailed stats" link on the match page; never build it by hand. The per-map
   versions reuse the `mapstatsid` you already capture from each `.mapholder`.
   Columns there are read by header label (`K (hs)`, `A (f)`, `D (t)`), so a
   reordered table cannot silently shift numbers into the wrong field.

## Verification

`python -m hltv verify` checks the built CSVs, not the scraper's intentions:

- every result got a stage label from the bracket join
- map winners reconstruct each series score exactly (0 mismatches on IEM Beijing)
- no unplayed map leaked a score
- each player's match-total kills equal the sum of their map kills
- ratings parse as `N.NN`
- per-map headshots add up to the series headshot figure
- headshots never exceed kills

## Caveats

- Schema follows HLTV's Nov 2026 redesign (Rating 3.0). If they change markup,
  the selectors in `hltv/js.py` are the only place to fix.
- Times in `results.csv` are converted to US Eastern; edit `TZ` in
  `hltv/build.py` for another zone.
- Dates/times are the site's absolute timestamps, so a late match can land on
  the previous local day.
- Default delay is 1.5 s between requests. Keep it — this is a hobby project
  hammering someone else's server, not an API.
- Not affiliated with HLTV. Scrape public pages at a polite rate, for personal
  or research use, and check HLTV's terms before republishing data.

## License

MIT — see `LICENSE`.
