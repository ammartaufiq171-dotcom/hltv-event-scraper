"""Turn raw scrape output into flat CSVs plus one JSON bundle."""
from __future__ import annotations

import csv
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
MINUS = {"\u2212": "-", "\u2013": "-", "\u2014": "-", "\u00a0": " "}


def clean(v):
    if v is None or not isinstance(v, str):
        return v if v is not None else ""
    for a, b in MINUS.items():
        v = v.replace(a, b)
    return v.strip()


def is_score(v) -> bool:
    return bool(v) and bool(re.fullmatch(r"\d{1,2}", str(v).strip()))


def split_kd(s):
    m = re.match(r"^(\d+)\s*-\s*(\d+)$", clean(s))
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def split_pair(v):
    """'44 (18)' -> (44, 18). Used for K (hs), A (f), D (t)."""
    m = re.match(r"^\s*(\d+)\s*(?:\((\d+)\))?\s*$", clean(v) or "")
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2) or 0)


def _detail_index(tables):
    """{(team, nick): row} from a detailed-stats page's tables."""
    idx = {}
    for t in tables or []:
        team = clean(t.get("team"))
        for p in t.get("players", []):
            idx[(team, clean(p.get("nick")))] = p
    return idx


def _hs_fields(row):
    """Headshot / flash / traded numbers for one player.

    Only supplementary columns are returned: kills/deaths already come from the
    scoreboard's K-D, so returning them here would collide with those keys.
    """
    if not row:
        return {"headshots": "", "hs_pct": "", "ekills_hs": "", "assists": "",
                "flash_assists": "", "traded_deaths": "", "multi_kills": "",
                "clutches": "", "op_kd": ""}
    k, hs = split_pair(row.get("killsHs"))
    a, fa = split_pair(row.get("assistsFlash"))
    _, td = split_pair(row.get("deathsTraded"))
    ek, ehs = split_pair(row.get("ekillsHs"))
    return {
        "headshots": hs if hs is not None else "",
        "hs_pct": round(100.0 * hs / k, 1) if (k and hs is not None) else "",
        "ekills_hs": f"{ek} ({ehs})" if ek is not None else "",
        "assists": a if a is not None else "",
        "flash_assists": fa if fa is not None else "",
        "traded_deaths": td if td is not None else "",
        "multi_kills": clean(row.get("multiKills")),
        "clutches": clean(row.get("clutches")),
        "op_kd": clean(row.get("opKd")),
    }


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def stage_lookup(brackets, results):
    """Label each result with bracket / tier / round taken from the bracket tree.

    Matches are joined on the unordered team pair plus their scores, since the
    bracket cells carry no match links.
    """
    idx = defaultdict(list)
    for b in brackets:
        teams = [t for t in b.get("teams", []) if t.get("name")]
        if len(teams) != 2 or any(t.get("result") is None for t in teams):
            continue
        key = (tuple(sorted(t["name"] for t in teams)),
               tuple(sorted((t["name"], str(t["result"])) for t in teams)))
        idx[key].append(" / ".join(x for x in [b.get("bracket"), b.get("tier"), b.get("round")] if x))

    out, used = {}, Counter()
    for r in results:
        key = (tuple(sorted([r["team1"], r["team2"]])),
               tuple(sorted([(r["team1"], str(clean(r["s1"]))), (r["team2"], str(clean(r["s2"])))])))
        cands = idx.get(key) or []
        if cands:
            out[r["url"]] = cands[min(used[key], len(cands) - 1)]
            used[key] += 1
        else:
            out[r["url"]] = ""
    return out


def _rows_to_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def build(out: str) -> dict:
    read = lambda n: json.load(open(os.path.join(out, n), encoding="utf-8"))
    results = read("raw_results.json")
    brackets = read("raw_brackets.json")
    teams = read("raw_teams.json")
    players = read("raw_players.json")
    meta = json.load(open(os.path.join(out, "raw_event.json"), encoding="utf-8")) if \
        os.path.exists(os.path.join(out, "raw_event.json")) else {}
    matches = load_jsonl(os.path.join(out, "raw_matches.jsonl"))
    details = {r["matchId"]: r for r in load_jsonl(os.path.join(out, "raw_details.jsonl"))}
    upcoming_raw = []
    up_path = os.path.join(out, "raw_upcoming.json")
    if os.path.exists(up_path):
        upcoming_raw = json.load(open(up_path, encoding="utf-8"))
    by_url = {m["url"]: m for m in matches}
    stages = stage_lookup(brackets, results)

    # Refuse to build from an empty event-level scrape: writing nothing would
    # leave the previous run's CSVs in place and look like success.
    if not players:
        raise SystemExit("event player table is empty (likely a Cloudflare challenge) "
                         "— re-run: python -m hltv scrape --event <id>")
    if not teams:
        raise SystemExit("event team table is empty (likely a Cloudflare challenge) "
                         "— re-run: python -m hltv scrape --event <id>")

    # ---- results.csv
    res_rows = []
    for r in sorted(results, key=lambda x: int(x["unix"] or 0)):
        det = by_url.get(r["url"])
        maps = [f'{m["map"]} {m["s1"]}-{m["s2"]}' for m in (det or {}).get("maps", [])
                if is_score(m.get("s1")) and is_score(m.get("s2"))]
        dt = datetime.fromtimestamp(int(r["unix"]) / 1000, TZ)
        winner = r["team2"] if clean(r.get("s2cls")) == "score-won" else r["team1"]
        # Per-match stage from the match page wins; bracket join is the fallback.
        stage = ((det or {}).get("stage") or stages.get(r["url"], "")).strip()
        stage = re.split(r"\.\s", stage)[0].strip().rstrip(".")  # drop "Winner advances ..." notes
        res_rows.append({
            "date_local": dt.strftime("%Y-%m-%d"),
            "time_local": dt.strftime("%H:%M"),
            "datetime_iso": dt.isoformat(),
            "stage": stage,
            "team1": r["team1"], "score1": clean(r["s1"]),
            "score2": clean(r["s2"]), "team2": r["team2"],
            "winner": winner,
            "format": (r.get("bo") or "").upper(),
            "maps": "; ".join(maps),
            "match_id": (r["url"] or "").split("/matches/")[-1].split("/")[0],
            "url": "https://www.hltv.org" + r["url"],
        })
    _rows_to_csv(os.path.join(out, "results.csv"), res_rows)

    # ---- schedule_upcoming.csv: fixtures from the event Matches tab,
    #      falling back to unplayed bracket slots when brackets rendered.
    sched = []
    for u in upcoming_raw:
        stage = (u.get("stage") or "").strip()
        slug = (u.get("url") or "").rsplit("/", 1)[-1]
        if not stage:  # TBD rows have no .match-stage element
            if "3rd-place" in slug:
                stage = "3rd Place Decider"
            elif "grand-final" in slug:
                stage = "Grand Final"
        when = ""
        if u.get("unix"):
            try:
                when = datetime.fromtimestamp(int(u["unix"]) / 1000, TZ).strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                when = u.get("time") or ""
        sched.append({
            "stage": stage, "team1": u.get("team1") or "TBD", "team2": u.get("team2") or "TBD",
            "datetime_local": when, "format": (u.get("bo") or "").upper(),
            "url": ("https://www.hltv.org" + u["url"]) if u.get("url") else "",
        })
    if not sched:
        for b in brackets:
            bt = [t for t in b.get("teams", []) if t.get("name")]
            if any(t.get("result") for t in bt):
                continue
            sched.append({
                "stage": " / ".join(x for x in [b.get("bracket"), b.get("tier"), b.get("round")] if x),
                "team1": bt[0]["name"] if bt else "TBD",
                "team2": bt[1]["name"] if len(bt) > 1 else "TBD",
                "datetime_local": f'{b.get("day") or ""} {b.get("time") or ""}'.strip(),
                "format": b.get("bo") or "", "url": "",
            })
    _rows_to_csv(os.path.join(out, "schedule_upcoming.csv"), sched)

    # ---- event-level stat tables
    tp = [{"player": p["nick"], "team": p["team"], "maps": clean(p["maps"]),
           "rounds": clean(p["rounds"]), "net_kills_per24": clean(p["netKills24"]),
           "eco_swing_pct": clean(p["ecoSwing"]), "round_swing_pct": clean(p["rndSwing"]),
           "rating_3_0": clean(p["rating"])} for p in players]
    _rows_to_csv(os.path.join(out, "player_stats_tournament.csv"), tp)

    _rows_to_csv(os.path.join(out, "team_stats.csv"),
                 [{"team": t["team"], "maps": clean(t["maps"]), "kdiff": clean(t["kdiff"]),
                   "kd": clean(t["kd"]), "rating_3_0": clean(t["rating"])} for t in teams])

    # ---- per-match and per-map player rows
    per_match, per_map = [], []
    for r in sorted(results, key=lambda x: int(x["unix"] or 0)):
        det = by_url.get(r["url"])
        if not det:
            continue
        dt = datetime.fromtimestamp(int(r["unix"]) / 1000, TZ).strftime("%Y-%m-%d %H:%M")
        stage = stages.get(r["url"], "")
        names = [t["team"] for t in det["totals"] if t and t.get("team")]
        drec = details.get(det["matchId"], {})
        series_idx = _detail_index(drec.get("series"))

        for t in det["totals"]:
            if not t or not t.get("team"):
                continue
            opp = next((n for n in names if n != t["team"]), "")
            for p in t["players"]:
                k, d = split_kd(p.get("kd"))
                ek, ed = split_kd(p.get("ekd"))
                per_match.append({
                    "match_id": det["matchId"], "datetime_local": dt, "stage": stage,
                    "team": t["team"], "opponent": opp,
                    "player": p.get("nick"), "full_name": clean(p.get("full")),
                    "country": clean(p.get("flag")),
                    "kills": k if k is not None else "", "deaths": d if d is not None else "",
                    "ekills_adj": ek if ek is not None else "", "edeaths_adj": ed if ed is not None else "",
                    "swing_pct": clean(p.get("swing")),
                    "adr": clean(p.get("adr")), "eadr": clean(p.get("eadr")),
                    "kast_pct": clean(p.get("kast")), "ekast_pct": clean(p.get("ekast")),
                    "rating_3_0": clean(p.get("rating")),
                    **_hs_fields(series_idx.get((t["team"], clean(p.get("nick"))))),
                })

        for m in det["maps"]:
            map_detail = (drec.get("maps") or {}).get(str(m.get("statsId")))
            map_idx = _detail_index(map_detail)
            for t in m["tables"]:
                if not t or not t.get("team"):
                    continue
                first = (t["team"] or "") == (m.get("t1") or "")
                ts, os_ = (m.get("s1"), m.get("s2")) if first else (m.get("s2"), m.get("s1"))
                for p in t["players"]:
                    k, d = split_kd(p.get("kd"))
                    per_map.append({
                        "match_id": det["matchId"], "map": m["map"],
                        "map_stats_id": m.get("statsId"),
                        "team_score": ts if is_score(ts) else "",
                        "opp_score": os_ if is_score(os_) else "",
                        "half_scores": clean(m.get("halfScores")),
                        "team": t["team"], "player": p.get("nick"),
                        "kills": k if k is not None else "", "deaths": d if d is not None else "",
                        "swing_pct": clean(p.get("swing")), "adr": clean(p.get("adr")),
                        "kast_pct": clean(p.get("kast")), "rating_3_0": clean(p.get("rating")),
                        **_hs_fields(map_idx.get((t["team"], clean(p.get("nick"))))),
                    })

    _rows_to_csv(os.path.join(out, "player_stats_per_match.csv"), per_match)
    _rows_to_csv(os.path.join(out, "player_stats_per_map.csv"), per_map)

    # ---- bundled JSON
    bundle = {
        "event": {
            "id": meta.get("eventId"), "name": meta.get("hub"), "url": meta.get("url"),
            "headerCells": meta.get("headerCells"),
            "scraped_at": datetime.now(TZ).isoformat(),
            "source": "https://www.hltv.org",
        },
        "results": res_rows, "upcoming": sched, "teams": teams, "players": tp,
        "brackets": brackets, "per_match": per_match, "per_map": per_map,
    }
    path = os.path.join(out, "event.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False, indent=1)

    counts = {"results": len(res_rows), "upcoming": len(sched), "teams": len(teams),
              "players": len(tp), "per_match": len(per_match), "per_map": len(per_map)}
    print("built:", ", ".join(f"{k}={v}" for k, v in counts.items()))
    return counts
