"""JavaScript extractors for HLTV pages.

Each extractor runs inside the already-authenticated page (so the Cloudflare
cookie is present) and returns plain JSON. HTML is fetched same-origin and
parsed with DOMParser, which is far faster than driving page navigation.

Selectors mirror HLTV's current markup (Nov 2026 redesign):

  .result-con              one row on /results
  .result-score span       score, classed score-won / score-lost
  .slotted-bracket*        event overview brackets (client-rendered: live DOM only)
  table.player-ratings-table   /stats/teams, /stats/players
  #all-content             match page, series-total stats
  #<mapstatsid>-content    match page, per-map stats (id read from .mapholder link)
  table.totalstats         per-team stat table (5 players + header row)
  td.kd/.adr/.kast/.rating stat cells; traditional-data vs eco-adjusted-data
"""

# ---------------------------------------------------------------- event meta

JS_RESOLVE_EVENT = r"""
(eventId) => {
  const prefix = '/events/' + eventId + '/';
  const hrefs = Array.from(document.querySelectorAll('a[href*="' + prefix + '"]'))
    .map(a => a.getAttribute('href'))
    .filter(h => h && h.split('/').filter(Boolean).length >= 3);
  return hrefs.length ? hrefs[0] : null;
}
"""

JS_EVENT_META = r"""
() => {
  const hub = document.querySelector('.event-hub-top');
  const hdr = document.querySelector('.event-header-component');
  const cells = hdr ? Array.from(hdr.querySelectorAll(':scope > * > *')).map(e => e.innerText.trim()) : [];
  return {
    hub: hub ? hub.innerText.replace(/\s+/g, ' ').trim() : null,
    title: document.title,
    headerText: hdr ? hdr.innerText.replace(/\s+/g, ' ').trim() : null,
    headerCells: cells.filter(Boolean).slice(0, 12)
  };
}
"""

# ------------------------------------------------------------------- results

JS_RESULTS = r"""
async (url) => {
  const res = await fetch(url, {credentials: 'include'});
  const html = await res.text();
  if (!res.ok || /Just a moment/i.test(html.slice(0, 3000))) {
    return { blocked: true, status: res.status };
  }
  const doc = new DOMParser().parseFromString(html, 'text/html');
  return Array.from(doc.querySelectorAll('.result-con')).map(rc => {
    const a = rc.querySelector('a[href*="/matches/"]');
    const spans = Array.from(rc.querySelectorAll('.result-score span'));
    const t1 = rc.querySelector('.line-align.team1 .team');
    const t2 = rc.querySelector('.line-align.team2 .team');
    return {
      url: a ? a.getAttribute('href') : null,
      unix: rc.getAttribute('data-zonedgrouping-entry-unix'),
      team1: t1 ? t1.innerText.trim() : null,
      team2: t2 ? t2.innerText.trim() : null,
      s1: spans[0] ? spans[0].innerText.trim() : null,
      s1cls: spans[0] ? spans[0].className : null,
      s2: spans[1] ? spans[1].innerText.trim() : null,
      s2cls: spans[1] ? spans[1].className : null,
      bo: rc.querySelector('.map-text') ? rc.querySelector('.map-text').innerText.trim() : null,
      stars: rc.querySelectorAll('.stars .star').length
    };
  });
}
"""

# ------------------------------------------------------------------ brackets
# Must run against the live document: the bracket trees are rendered client-side.

JS_BRACKETS = r"""
() => {
  const out = [];
  for (const ph of document.querySelectorAll('.slotted-bracket-placeholder')) {
    const bh = ph.querySelector('.slotted-bracket-header');
    const bname = bh ? bh.innerText.trim() : null;
    for (const tier of ph.querySelectorAll('.slotted-bracket-tier')) {
      const tn = tier.querySelector('.bracket-tier-header');
      const tierName = tn ? tn.innerText.trim() : null;
      for (const round of tier.querySelectorAll('.round')) {
        const rn = round.querySelector('.round-header');
        const roundName = rn ? rn.innerText.trim() : null;
        for (const slot of round.querySelectorAll('.slot-wrapper')) {
          const m = slot.querySelector('.match');
          if (!m) continue;
          const hdr = slot.querySelector('.header');
          const teams = Array.from(m.querySelectorAll('.team')).map(t => ({
            name: t.querySelector('.team-name') ? t.querySelector('.team-name').innerText.trim() : null,
            result: t.querySelector('.result') ? t.querySelector('.result').innerText.trim() : null,
            winner: t.classList.contains('winner'),
            tbd: t.classList.contains('team-tbd')
          }));
          out.push({
            bracket: bname, tier: tierName, round: roundName, teams: teams,
            time: hdr && hdr.querySelector('.time-time') ? hdr.querySelector('.time-time').innerText.trim() : null,
            day: hdr && hdr.querySelector('.time-day-of-week') ? hdr.querySelector('.time-day-of-week').innerText.trim() : null,
            bo: hdr && hdr.querySelector('.best-of-x') ? hdr.querySelector('.best-of-x').innerText.trim() : null
          });
        }
      }
    }
  }
  return out;
}
"""

# --------------------------------------------------------------- team stats

JS_TEAMS = r"""
async (url) => {
  const res = await fetch(url, {credentials: 'include'});
  const html = await res.text();
  if (!res.ok || /Just a moment/i.test(html.slice(0, 3000))) {
    return { blocked: true, status: res.status };
  }
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const t = doc.querySelector('table.player-ratings-table');
  if (!t) return [];
  const rows = Array.from(t.querySelectorAll('tbody tr'))
    .filter(tr => tr.querySelectorAll('td').length >= 5);
  return rows.map(tr => {
    const tds = Array.from(tr.querySelectorAll('td'));
    const link = tr.querySelector('a[href*="/team/"]');
    return {
      team: tds[0] ? tds[0].innerText.trim() : null,
      teamId: link ? (link.getAttribute('href').match(/\/team\/(\d+)/) || [])[1] : null,
      maps: tds[1] ? tds[1].innerText.trim() : null,
      kdiff: tds[2] ? tds[2].innerText.trim() : null,
      kd: tds[3] ? tds[3].innerText.trim() : null,
      rating: tds[4] ? tds[4].innerText.trim() : null
    };
  });
}
"""

# ------------------------------------------------------------- player stats

JS_PLAYERS = r"""
async (url) => {
  const res = await fetch(url, {credentials: 'include'});
  const html = await res.text();
  if (!res.ok || /Just a moment/i.test(html.slice(0, 3000))) {
    return { blocked: true, status: res.status };
  }
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const t = doc.querySelector('table.player-ratings-table');
  if (!t) return [];
  const rows = Array.from(t.querySelectorAll('tbody tr'))
    .filter(tr => tr.querySelector('td.playerCol'));
  return rows.map(tr => {
    const tds = Array.from(tr.querySelectorAll('td'));
    const link = tr.querySelector('a[href*="/player/"]');
    const nickEl = tr.querySelector('.player-nick');
    return {
      nick: nickEl ? nickEl.innerText.trim() : (tds[0] ? tds[0].innerText.trim() : null),
      playerId: link ? (link.getAttribute('href').match(/\/player\/(\d+)/) || [])[1] : null,
      team: tds[1] ? tds[1].innerText.trim() : null,
      maps: tds[2] ? tds[2].innerText.trim() : null,
      rounds: tds[3] ? tds[3].innerText.trim() : null,
      netKills24: tds[4] ? tds[4].innerText.trim() : null,
      ecoSwing: tds[5] ? tds[5].innerText.trim() : null,
      rndSwing: tds[6] ? tds[6].innerText.trim() : null,
      rating: tds[7] ? tds[7].innerText.trim() : null
    };
  });
}
"""

# ------------------------------------------------------------- match detail
# Returns series totals (#all-content) plus one entry per map with its own
# per-team tables. Scores come from .results-team-score, never from squashed
# innerText: team names ending in digits (B8, G2, 9z) otherwise corrupt parsing.

JS_MATCH = r"""
async (url) => {
  const res = await fetch(url, {credentials: 'include'});
  const html = await res.text();
  if (!res.ok || /Just a moment/i.test(html.slice(0, 3000))) {
    return { blocked: true, status: res.status };
  }
  const doc = new DOMParser().parseFromString(html, 'text/html');

  const txt = (tr, sel) => {
    const e = tr.querySelector(sel);
    return e ? e.innerText.trim() : null;
  };

  const parseTable = (t) => {
    if (!t) return null;
    const teamA = t.querySelector('a.teamName') || t.querySelector('a.team');
    const rows = Array.from(t.querySelectorAll('tbody tr'))
      .filter(tr => !tr.classList.contains('header-row'));
    return {
      team: teamA ? teamA.innerText.trim() : null,
      players: rows.map(tr => {
        const cell = tr.querySelector('td.players');
        const nickEl = cell ? cell.querySelector('.player-nick') : null;
        const fullEl = cell ? cell.querySelector('.gtSmartphone-only') : null;
        const a = cell ? cell.querySelector('a[href*="/player/"]') : null;
        const flag = cell ? cell.querySelector('img.flag') : null;
        return {
          nick: nickEl ? nickEl.innerText.trim() : (cell ? cell.innerText.trim() : null),
          full: fullEl ? fullEl.innerText.trim() : null,
          url: a ? a.getAttribute('href') : null,
          flag: flag ? flag.getAttribute('alt') : null,
          kd: txt(tr, 'td.kd.traditional-data'),
          ekd: txt(tr, 'td.kd.eco-adjusted-data'),
          swing: txt(tr, 'td.roundSwing'),
          adr: txt(tr, 'td.adr.traditional-data'),
          eadr: txt(tr, 'td.adr.eco-adjusted-data'),
          kast: txt(tr, 'td.kast.traditional-data'),
          ekast: txt(tr, 'td.kast.eco-adjusted-data'),
          rating: txt(tr, 'td.rating')
        };
      })
    };
  };

  // "Detailed stats" link: /stats/matches/<statsMatchId>/<slug>
  const detLink = doc.querySelector('a[href*="/stats/matches/"]:not([href*="mapstatsid"])');
  const detailsPath = detLink ? detLink.getAttribute('href') : null;

  const allBlock = doc.querySelector('#all-content');
  const totals = allBlock
    ? Array.from(allBlock.querySelectorAll('table.totalstats')).map(parseTable)
    : [];

  // Stage lives in the veto box: "Best of 3 (LAN) * Group A upper bracket quarter-final"
  const veto = doc.querySelector('.veto-box .preformatted-text') || doc.querySelector('.veto-box');
  let stage = null;
  if (veto) {
    const t = veto.innerText.replace(/\s+/g, ' ').trim();
    const i = t.indexOf('*');
    stage = i >= 0 ? t.slice(i + 1).trim() : null;
  }

  const maps = Array.from(doc.querySelectorAll('.mapholder')).map(h => {
    const mn = h.querySelector('.mapname');
    const link = h.querySelector('a[href*="mapstatsid"]');
    const href = link ? link.getAttribute('href') : null;
    const mid = href ? (href.match(/mapstatsid\/(\d+)/) || [])[1] : null;
    const pick = (sel, cls) => {
      const e = h.querySelector(sel + ' .' + cls);
      return e ? e.innerText.trim() : null;
    };
    const s1 = pick('.results-left', 'results-team-score');
    const s2 = pick('.results-right', 'results-team-score');
    const t1 = pick('.results-left', 'results-teamname');
    const t2 = pick('.results-right', 'results-teamname');

    const half = h.querySelector('.results-center-half-score');
    const block = mid ? doc.getElementById(mid + '-content') : null;
    return {
      map: mn ? mn.innerText.trim() : null,
      statsId: mid,
      statsPath: href,
      halfScores: half ? half.innerText.replace(/\s+/g, ' ').trim() : null,
      s1: s1, s2: s2, t1: t1, t2: t2,
      tables: block ? Array.from(block.querySelectorAll('table.totalstats')).map(parseTable) : []
    };
  });

  return { url, title: doc.title, stage, detailsPath, totals, maps };
}
"""

# ------------------------------------------------------------ detailed stats
# /stats/matches/<id>/<slug> (series) and /stats/matches/mapstatsid/<id>/<slug>
# (single map) share one table shape. Columns are resolved from the header text
# so a reordered column cannot silently shift the numbers into the wrong field.
# "K (hs)"      -> 44 (18)  kills with headshots
# "A (f)"       -> 5 (0)    assists with flash assists
# "D (t)"       -> 36 (8)   deaths with traded deaths
# "Op.K-D"      -> 6 : 4    opening kills : opening deaths

JS_DETAIL = r"""
async (path) => {
  const res = await fetch(path, {credentials: 'include'});
  const html = await res.text();
  if (!res.ok || /Just a moment/i.test(html.slice(0, 3000))) {
    return { blocked: true, status: res.status };
  }
  const doc = new DOMParser().parseFromString(html, 'text/html');

  const parse = (t) => {
    const heads = Array.from(t.querySelectorAll('thead td, thead th'))
      .map(x => x.innerText.replace(/\s+/g, ' ').trim());
    const idx = {};
    heads.forEach((h, i) => { if (!(h in idx)) idx[h] = i; });
    const get = (tds, label) => {
      const i = idx[label];
      return (i !== undefined && tds[i]) ? tds[i].innerText.replace(/\s+/g, ' ').trim() : null;
    };
    return {
      team: heads[0] || null,
      players: Array.from(t.querySelectorAll('tbody tr')).map(tr => {
        const tds = Array.from(tr.querySelectorAll('td'));
        return {
          nick: tds[0] ? tds[0].innerText.trim() : null,
          opKd: get(tds, 'Op.K-D'),
          opEkd: get(tds, 'Op.eK-eD'),
          multiKills: get(tds, 'MKs'),
          kast: get(tds, 'KAST'),
          ekast: get(tds, 'eKAST'),
          clutches: get(tds, '1vsX'),
          killsHs: get(tds, 'K (hs)'),
          ekillsHs: get(tds, 'eK (hs)'),
          assistsFlash: get(tds, 'A (f)'),
          deathsTraded: get(tds, 'D (t)'),
          edeathsTraded: get(tds, 'eD (t)'),
          adr: get(tds, 'ADR'),
          eadr: get(tds, 'eADR'),
          swing: get(tds, 'Swing'),
          rating: get(tds, 'Rating3.0')
        };
      })
    };
  };

  return { path, tables: Array.from(doc.querySelectorAll('table.totalstats')).map(parse) };
}
"""

# --------------------------------------------------------------- upcoming
# The event's Matches tab lists not-yet-played fixtures with their stage.
# JS_UPCOMING_LIVE reads the same rows from the already-loaded tab, for when
# that path is challenged to fetch() but renders fine when navigated to.

JS_UPCOMING = r"""
async (url) => {
  const res = await fetch(url, {credentials: 'include'});
  const html = await res.text();
  if (!res.ok || /Just a moment/i.test(html.slice(0, 3000))) {
    return { blocked: true, status: res.status };
  }
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const rows = Array.from(doc.querySelectorAll('.match-bottom')).map(row => {
    const a = row.querySelector('a[href*="/matches/"]');
    const t = row.querySelector('.match-time');
    const meta = row.querySelector('.match-meta');
    const st = row.querySelector('.match-stage');
    const names = Array.from(row.querySelectorAll('.match-teamname')).map(e => e.innerText.trim());
    return {
      url: a ? a.getAttribute('href') : null,
      unix: t ? t.getAttribute('data-unix') : null,
      time: t ? t.innerText.trim() : null,
      bo: meta ? meta.innerText.trim() : null,
      team1: names[0] || null,
      team2: names[1] || null,
      stage: st ? st.innerText.replace(/\s+/g, ' ').trim() : null,
      stageClass: st ? String(st.className) : null
    };
  });

  // Some fixtures render no stage text (3rd place decider shows only a
  // "match-pre-playoff" class). Ask the match page, whose veto box always
  // spells it out: "Best of 3 (LAN) * 3rd place decider match".
  for (const r of rows) {
    if (r.stage || !r.url) continue;
    if (r.stageClass && /grand-final/.test(r.stageClass)) { r.stage = 'Grand Final'; continue; }
    try {
      const h = await (await fetch(r.url, {credentials: 'include'})).text();
      const d = new DOMParser().parseFromString(h, 'text/html');
      const v = d.querySelector('.veto-box .preformatted-text') || d.querySelector('.veto-box');
      if (!v) continue;
      const t = v.innerText.replace(/\s+/g, ' ').trim();
      const i = t.indexOf('*');
      r.stage = i >= 0 ? t.slice(i + 1).trim() : null;
    } catch (e) { /* leave stage empty */ }
  }
  return rows;
}
"""

# Live-DOM fallback for the fixtures list (see scrape.scrape_event).
JS_UPCOMING_LIVE = r"""
() => {
  const doc = document;
  const rows = Array.from(doc.querySelectorAll('.match-bottom')).map(row => {
    const a = row.querySelector('a[href*="/matches/"]');
    const t = row.querySelector('.match-time');
    const meta = row.querySelector('.match-meta');
    const st = row.querySelector('.match-stage');
    const names = Array.from(row.querySelectorAll('.match-teamname')).map(e => e.innerText.trim());
    return {
      url: a ? a.getAttribute('href') : null,
      unix: t ? t.getAttribute('data-unix') : null,
      time: t ? t.innerText.trim() : null,
      bo: meta ? meta.innerText.trim() : null,
      team1: names[0] || null,
      team2: names[1] || null,
      stage: st ? st.innerText.replace(/\s+/g, ' ').trim() : null,
      stageClass: st ? String(st.className) : null
    };
  });
  return rows;
}
"""
