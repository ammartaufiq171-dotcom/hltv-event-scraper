"""Scraping orchestration: event-level pages, then every completed match."""
from __future__ import annotations

import json
import os
import re
import time

from . import js
from .cdp import CDP

BASE = "https://www.hltv.org"


def event_path(event_id: int | str) -> str:
    return f"/events/{event_id}"


def _write(out: str, name: str, data) -> str:
    path = os.path.join(out, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return path


def _call(c: CDP, code: str, *args, retries: int = 3, pause: float = 3.0):
    last = None
    for attempt in range(retries):
        try:
            arglist = ", ".join(json.dumps(a) for a in args)
            return c.js(f"({code})({arglist})")
        except Exception as exc:  # transient page/JS errors are common
            last = exc
            time.sleep(pause)
    raise RuntimeError(f"extractor failed after {retries} attempts: {last}")


def _wait_js(c: CDP, expr: str, timeout: float = 20.0, interval: float = 0.5) -> bool:
    """Poll a boolean JS expression until true (brackets render lazily)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if c.js(expr, await_promise=False):
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def scrape_event(c: CDP, event_id: int | str, out: str, delay: float = 1.5) -> dict:
    """Results list, brackets, and the event-level team/player stat tables."""
    os.makedirs(out, exist_ok=True)

    # /events/<id> is a shell page: resolve the canonical /events/<id>/<slug>
    # from the links it renders, otherwise brackets and meta come back empty.
    c.goto(BASE + event_path(event_id))
    href = _call(c, js.JS_RESOLVE_EVENT, str(event_id))
    if href:
        canonical = href if href.startswith("http") else BASE + href
        if canonical.rstrip("/") != c.url().rstrip("/"):
            c.goto(canonical)

    if "just a moment" in (c.title() or "").lower():
        raise SystemExit(
            "Stuck on the Cloudflare challenge. Bring the Chrome window to the "
            "front, click the checkbox once, then re-run."
        )

    meta = _call(c, js.JS_EVENT_META)
    meta["eventId"] = str(event_id)
    meta["url"] = c.url()

    results = _call(c, js.JS_RESULTS, f"/results?event={event_id}")
    time.sleep(delay)
    _wait_js(c, "document.querySelectorAll('.slotted-bracket-placeholder').length > 0", 8)
    brackets = _call(c, js.JS_BRACKETS)
    time.sleep(delay)
    upcoming = _call(c, js.JS_UPCOMING, f"/events/{event_id}/matches")
    time.sleep(delay)
    teams = _call(c, js.JS_TEAMS, f"/stats/teams?event={event_id}")
    time.sleep(delay)
    players = _call(c, js.JS_PLAYERS, f"/stats/players?event={event_id}")

    _write(out, "raw_event.json", meta)
    _write(out, "raw_results.json", results)
    _write(out, "raw_brackets.json", brackets)
    _write(out, "raw_upcoming.json", upcoming)
    _write(out, "raw_teams.json", teams)
    _write(out, "raw_players.json", players)

    print(f"event      : {meta.get('hub') or meta.get('title')}")
    print(f"results    : {len(results)} matches")
    print(f"brackets   : {len(brackets)} slots (best effort)")
    print(f"upcoming   : {len(upcoming)} fixtures")
    print(f"teams      : {len(teams)} | players: {len(players)}")
    return {"results": results, "brackets": brackets, "upcoming": upcoming,
            "teams": teams, "players": players}


def scrape_matches(c: CDP, out: str, delay: float = 1.5, limit: int | None = None) -> int:
    """Per-match scoreboards (series totals + every map). Appends to JSONL so
    an interrupted run resumes where it stopped."""
    results_path = os.path.join(out, "raw_results.json")
    if not os.path.exists(results_path):
        raise SystemExit("run the event scrape first: raw_results.json missing")
    results = json.load(open(results_path, encoding="utf-8"))

    jsonl = os.path.join(out, "raw_matches.jsonl")
    done = set()
    if os.path.exists(jsonl):
        for line in open(jsonl, encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    done.add(json.loads(line)["url"])
                except Exception:
                    pass

    todo = [r for r in results if r.get("url") and r["url"] not in done]
    if limit:
        todo = todo[:limit]
    print(f"matches    : {len(results)} total, {len(done)} cached, {len(todo)} to scrape")

    for i, row in enumerate(todo, 1):
        data = _call(c, js.JS_MATCH, row["url"])
        data["matchId"] = (row["url"].split("/matches/")[1] or "").split("/")[0]
        with open(jsonl, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
        maps = [(m["map"], m["s1"], m["s2"]) for m in data["maps"]]
        print(f"  [{i}/{len(todo)}] {data['matchId']} {len(data['maps'])} maps {maps}")
        time.sleep(delay)
    return len(todo)


def scrape_details(c: CDP, out: str, delay: float = 1.5, limit: int | None = None) -> int:
    """Headshots and the rest of the detailed-stats table.

    One page per series (/stats/matches/<id>/...) plus one per map
    (/stats/matches/mapstatsid/<id>/...). Written to raw_details.jsonl so a
    re-run only fetches what is missing.
    """
    matches_path = os.path.join(out, "raw_matches.jsonl")
    if not os.path.exists(matches_path):
        raise SystemExit("run the match scrape first: raw_matches.jsonl missing")
    matches = [json.loads(l) for l in open(matches_path, encoding="utf-8") if l.strip()]
    # keep the newest record per match id
    matches = list({m["matchId"]: m for m in matches}.values())

    jsonl = os.path.join(out, "raw_details.jsonl")
    done = set()
    if os.path.exists(jsonl):
        for line in open(jsonl, encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    done.add(json.loads(line)["matchId"])
                except Exception:
                    pass

    todo = [m for m in matches if m["matchId"] not in done]
    if limit:
        todo = todo[:limit]
    print(f"details    : {len(matches)} matches, {len(done)} cached, {len(todo)} to scrape")

    for i, m in enumerate(todo, 1):
        rec = {"matchId": m["matchId"], "series": [], "maps": {}}
        if m.get("detailsPath"):
            rec["series"] = _call(c, js.JS_DETAIL, m["detailsPath"])["tables"]
            time.sleep(delay)
        for mp in m.get("maps", []):
            path = mp.get("statsPath")
            if not path or not is_scored(mp):
                continue
            key = mp.get("statsId") or mp.get("map")
            rec["maps"][key] = _call(c, js.JS_DETAIL, path)["tables"]
            time.sleep(delay)

        with open(jsonl, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        hs = sum(_num_second(p.get("killsHs")) for t in rec["series"] for p in t["players"])
        print(f"  [{i}/{len(todo)}] {m['matchId']} series={len(rec['series'])} "
              f"maps={len(rec['maps'])} headshots={hs}")
    return len(todo)


def is_scored(mp: dict) -> bool:
    s1, s2 = str(mp.get("s1") or "").strip(), str(mp.get("s2") or "").strip()
    return bool(s1.isdigit() and s2.isdigit())


def _num_second(v) -> int:
    """'44 (18)' -> 18 ; '5' -> 0"""
    if not v:
        return 0
    m = re.search(r"\((\d+)\)", str(v))
    return int(m.group(1)) if m else 0


def scrape(event_id: int | str, out: str, port: int = 9222, delay: float = 1.5,
           limit: int | None = None, details: bool = True) -> None:
    with CDP(port=port) as c:
        scrape_event(c, event_id, out, delay=delay)
        scrape_matches(c, out, delay=delay, limit=limit)
        if details:
            scrape_details(c, out, delay=delay, limit=limit)
