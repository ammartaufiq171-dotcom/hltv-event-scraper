"""Scraping orchestration: event-level pages, then every completed match."""
from __future__ import annotations

import json
import os
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


def scrape(event_id: int | str, out: str, port: int = 9222, delay: float = 1.5,
           limit: int | None = None) -> None:
    with CDP(port=port) as c:
        scrape_event(c, event_id, out, delay=delay)
        scrape_matches(c, out, delay=delay, limit=limit)
