"""Self-checks that catch the usual scrape regressions.

Runs entirely on the built CSVs:
  1. every result has a stage label from the bracket join
  2. map winners reconstruct each series score exactly
  3. no unplayed map leaked a score
  4. match-level kills equal the sum of that player's map kills
  5. ratings look like N.NN
Exit code is non-zero when something is off, so it works in CI.
"""
from __future__ import annotations

import csv
import os
import re
import sys
from collections import defaultdict


def rd(out, name):
    path = os.path.join(out, name)
    return list(csv.DictReader(open(path, encoding="utf-8-sig"))) if os.path.exists(path) else []


def run(out: str) -> int:
    res = rd(out, "results.csv")
    per_match = rd(out, "player_stats_per_match.csv")
    per_map = rd(out, "player_stats_per_map.csv")
    tp = rd(out, "player_stats_tournament.csv")
    failures = []

    print(f"rows    : results={len(res)} per_match={len(per_match)} "
          f"per_map={len(per_map)} players={len(tp)}")

    # 1. stage labels
    unlabeled = [r["match_id"] for r in res if not r["stage"]]
    print(f"1 stages: {len(res) - len(unlabeled)}/{len(res)} labelled")
    if unlabeled:
        failures.append(f"{len(unlabeled)} results without a stage label: {unlabeled[:5]}")

    # 2. series scores reconstruct
    maps_by_match = defaultdict(lambda: defaultdict(dict))
    for r in per_map:
        if r["team_score"]:
            maps_by_match[r["match_id"]][r["map"]][r["team"]] = int(r["team_score"])

    bad_series = []
    for r in res:
        w1 = w2 = 0
        for _, teams in maps_by_match.get(r["match_id"], {}).items():
            if len(teams) != 2:
                continue
            (a, sa), (b, sb) = teams.items()
            winner = a if sa > sb else (b if sb > sa else None)
            if winner == r["team1"]:
                w1 += 1
            elif winner == r["team2"]:
                w2 += 1
        if (w1, w2) != (int(r["score1"]), int(r["score2"])):
            bad_series.append((r["match_id"], f"{r['team1']} {r['score1']}-{r['score2']} {r['team2']}",
                               f"reconstructed {w1}-{w2}"))
    print(f"2 series: {len(res) - len(bad_series)}/{len(res)} scores reconstructed from map winners")
    if bad_series:
        failures.append(f"series score mismatch: {bad_series[:5]}")

    # 3. unplayed maps
    scored = [r for r in per_map if r["team_score"]]
    print(f"3 maps  : {len(scored)} player-map rows carry a score")
    if len(per_map) != len(scored):
        failures.append(f"{len(per_map) - len(scored)} map rows have no score")

    # 4. kill totals agree between levels
    mk = defaultdict(int)
    for r in per_match:
        mk[(r["match_id"], r["player"])] += int(r["kills"] or 0)
    mk2 = defaultdict(int)
    for r in per_map:
        mk2[(r["match_id"], r["player"])] += int(r["kills"] or 0)
    diffs = [k for k in mk if mk[k] != mk2.get(k, 0)]
    print(f"4 kills : {len(mk) - len(diffs)}/{len(mk)} player-match totals equal their map sums")
    if diffs:
        failures.append(f"kill totals disagree for {len(diffs)} player-matches")

    # 5. rating shape
    odd = [p["player"] for p in tp if p["rating_3_0"] and not re.fullmatch(r"\d\.\d\d", p["rating_3_0"])]
    print(f"5 rating: {len(tp) - len(odd)}/{len(tp)} parsed cleanly")
    if odd:
        failures.append(f"unparseable ratings: {odd[:5]}")

    if failures:
        print("\nFAIL")
        for f in failures:
            print("  -", f)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else "./data"))
