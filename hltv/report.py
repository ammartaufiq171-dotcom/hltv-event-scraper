"""Derived player totals and a human-readable summary.md."""
from __future__ import annotations

import csv
import os
from collections import defaultdict
from datetime import datetime


def rd(out: str, name: str):
    path = os.path.join(out, name)
    if not os.path.exists(path):
        return []
    return list(csv.DictReader(open(path, encoding="utf-8-sig")))


def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def build_report(out: str) -> None:
    res = rd(out, "results.csv")
    per_map = rd(out, "player_stats_per_map.csv")
    per_match = rd(out, "player_stats_per_match.csv")
    tp = rd(out, "player_stats_tournament.csv")
    teams = rd(out, "team_stats.csv")
    sched = rd(out, "schedule_upcoming.csv")

    # totals rebuilt from map rows (K/D sums, averaged ADR/KAST)
    agg = defaultdict(lambda: {"team": "", "maps": 0, "k": 0, "d": 0, "hs": 0, "adr": [], "kast": []})
    for r in per_map:
        if not r["team_score"]:
            continue
        a = agg[(r["player"], r["team"])]
        a["team"] = r["team"]
        a["maps"] += 1
        a["k"] += int(r["kills"] or 0)
        a["d"] += int(r["deaths"] or 0)
        if r.get("headshots"):
            a["hs"] += int(r["headshots"])
        if r["adr"]:
            a["adr"].append(float(r["adr"]))
        if r["kast_pct"]:
            a["kast"].append(float(r["kast_pct"].replace("%", "")))

    rating = {(p["player"], p["team"]): p["rating_3_0"] for p in tp}
    rounds = {(p["player"], p["team"]): p["rounds"] for p in tp}

    derived = []
    for (pl, tm), a in agg.items():
        k, d = a["k"], a["d"]
        derived.append({
            "player": pl, "team": tm, "maps": a["maps"], "rounds": rounds.get((pl, tm), ""),
            "kills": k, "deaths": d, "kd_diff": k - d,
            "kd_ratio": round(k / d, 2) if d else "",
            "headshots": a["hs"],
            "hs_pct": round(100.0 * a["hs"] / k, 1) if k else "",
            "adr_avg": round(sum(a["adr"]) / len(a["adr"]), 1) if a["adr"] else "",
            "kast_avg": round(sum(a["kast"]) / len(a["kast"]), 1) if a["kast"] else "",
            "rating_3_0": rating.get((pl, tm), ""),
        })
    derived.sort(key=lambda x: -float(x["rating_3_0"] or 0))
    write_csv(os.path.join(out, "player_stats_derived.csv"), derived)

    maps_with_stats = len({r["map_stats_id"] for r in per_map if r["team_score"]})

    L = []
    L.append("# Event results & player stats\n")
    L.append(f"Scraped {datetime.now().strftime('%Y-%m-%d %H:%M')} from HLTV (public pages).\n")
    L.append("| | |\n|---|---|")
    L.append(f"| Completed matches | {len(res)} |")
    L.append(f"| Maps with stats | {maps_with_stats} |")
    L.append(f"| Teams | {len(teams)} |")
    L.append(f"| Players | {len(tp)} |")

    L.append("\n## Top 15 players by Rating 3.0\n")
    L.append("| # | Player | Team | Maps | Rating | K–D | +/− | ADR | HS% |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for i, p in enumerate(derived[:15], 1):
        L.append(f'| {i} | {p["player"]} | {p["team"]} | {p["maps"]} | **{p["rating_3_0"]}** | '
                 f'{p["kills"]}–{p["deaths"]} | {p["kd_diff"]:+d} | {p["adr_avg"]} | {p["hs_pct"]} |')

    L.append("\n## Team stats\n")
    L.append("| # | Team | Maps | K–D diff | K/D | Rating |")
    L.append("|---|---|---|---|---|---|")
    for i, t in enumerate(teams, 1):
        L.append(f'| {i} | {t["team"]} | {t["maps"]} | {t["kdiff"]} | {t["kd"]} | {t["rating_3_0"]} |')

    if sched:
        L.append("\n## Upcoming\n")
        L.append("| Stage | Match | When | Format |\n|---|---|---|---|")
        for s in sched:
            L.append(f'| {s["stage"]} | {s["team1"]} vs {s["team2"]} | {s.get("datetime_local", "")} | {s["format"]} |')

    L.append(f"\n## All completed results ({len(res)})\n")
    cur = None
    for r in res:
        if r["stage"] != cur:
            cur = r["stage"]
            L.append(f"\n**{cur}**\n")
            L.append("| Date | Match | Score | Maps |\n|---|---|---|---|")
        L.append(f'| {r["date_local"]} {r["time_local"]} | {r["team1"]} vs {r["team2"]} | '
                 f'**{r["score1"]}–{r["score2"]}** | {r["maps"]} |')

    open(os.path.join(out, "summary.md"), "w", encoding="utf-8").write("\n".join(L))
    print(f"report  : summary.md + player_stats_derived.csv ({len(derived)} players, "
          f"{len(per_match)} match rows, {len(per_map)} map rows)")
