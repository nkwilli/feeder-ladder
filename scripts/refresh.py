#!/usr/bin/env python3
"""Data refresh for Feeder Ladder. Writes JSON + .ics into site/.
- F1: Jolpica (Ergast-compatible) API. Limits: ~4 req/s burst, 500 req/hr -> we make ~3 requests, cached 1h, 0.5s spacing.
- F2/F3: Blacktop Data API (free tier needs an API key: env BLACKTOP_API_KEY). Without a key we write a 'coming soon' status, never fake data.
"""
import json, os, time, hashlib, urllib.request, datetime as dt, pathlib, shutil
ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE, CACHE = ROOT / "site", ROOT / ".cache"
CACHE.mkdir(exist_ok=True); (SITE / "data").mkdir(parents=True, exist_ok=True); (SITE / "cal").mkdir(exist_ok=True)
TTL = int(os.environ.get("CACHE_TTL", 3600)); UA = "FeederLadderFanSite/0.1 (non-commercial)"
_last = [0.0]

def get(url, headers=None, ttl=None):
    f = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".json")
    if f.exists() and time.time() - f.stat().st_mtime < (ttl or TTL):
        return json.loads(f.read_text())
    wait = 0.5 - (time.time() - _last[0])
    if wait > 0: time.sleep(wait)
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.load(r); break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 3: time.sleep(2 ** attempt * 5); continue
            if f.exists(): return json.loads(f.read_text())  # stale cache fallback
            raise
    _last[0] = time.time(); f.write_text(json.dumps(data)); return data

def f1():
    B = "https://api.jolpi.ca/ergast/f1/current"
    ds = get(B + "/driverStandings.json")["MRData"]["StandingsTable"]["StandingsLists"][0]
    cs = get(B + "/constructorStandings.json")["MRData"]["StandingsTable"]["StandingsLists"][0]
    races = get(B + "/races.json?limit=100")["MRData"]["RaceTable"]["Races"]
    drivers = [{"pos": d["position"], "name": f'{d["Driver"]["givenName"]} {d["Driver"]["familyName"]}',
                "team": d["Constructors"][-1]["name"] if d["Constructors"] else "", "points": d["points"], "wins": d["wins"]}
               for d in ds["DriverStandings"]]
    teams = [{"pos": c["position"], "name": c["Constructor"]["name"], "points": c["points"], "wins": c["wins"]} for c in cs["ConstructorStandings"]]
    names = {"FirstPractice": "Practice 1", "SecondPractice": "Practice 2", "ThirdPractice": "Practice 3",
             "SprintQualifying": "Sprint Qualifying", "SprintShootout": "Sprint Qualifying", "Sprint": "Sprint", "Qualifying": "Qualifying"}
    sessions = []
    for r in races:
        ev = f'{r["raceName"]} (Round {r["round"]})'
        for k, label in names.items():
            if k in r and "time" in r[k]:
                sessions.append({"event": ev, "session": label, "start": f'{r[k]["date"]}T{r[k]["time"]}', "place": r["Circuit"]["Location"]["locality"]})
        sessions.append({"event": ev, "session": "Race", "start": f'{r["date"]}T{r.get("time","12:00:00Z")}', "place": r["Circuit"]["Location"]["locality"]})
    sessions.sort(key=lambda s: s["start"])
    results = f1_results(races)
    return {"results": results, "status": "ok", "source": "Jolpica (api.jolpi.ca)", "season": ds["season"], "round": ds["round"],
            "drivers": drivers, "teams": teams, "sessions": sessions}

def f1_results(races):
    """Past race classifications from Jolpica, paginated (100 rows/page)."""
    rows, off = [], 0
    while True:
        m = get(f"https://api.jolpi.ca/ergast/f1/current/results.json?limit=100&offset={off}")["MRData"]
        rows += m["RaceTable"]["Races"]; off += 100
        if off >= int(m["total"]): break
    by = {}
    for r in rows:  # pages can split one race across two pages
        by.setdefault(r["round"], {"round": r["round"], "event": r["raceName"], "date": r["date"],
                                   "place": r["Circuit"]["Location"]["locality"], "classification": []})["classification"] += [
            {"pos": x["positionText"], "name": f'{x["Driver"]["givenName"]} {x["Driver"]["familyName"]}', "team": x["Constructor"]["name"],
             "time": (x.get("Time") or {}).get("time") if x["status"] == "Finished" else x["status"], "points": x["points"]} for x in r["Results"]]
    out = sorted(by.values(), key=lambda r: int(r["round"]), reverse=True)
    for r in out: r["classification"].sort(key=lambda x: int(x["pos"]) if x["pos"].isdigit() else 999)
    return out

# ---- F2/F3 via Orange Cat Blacktop (https://ocblacktop.com/api/formula-2), header x-api-key.
# Verified with a real key (2026-10-14):
#   GET /v1/{series}/events?limit=50 -> {"data":[{id,name,dateStart,dateEnd,status,location:{name,city,country},
#        schedule:[{id,name,type(practice|qualifying|sprint|race),startTime,status}]}], "meta":{page,limit,total,totalPages}}
#        (newest first, so page 1 covers the current season)
#   GET /v1/{series}/events/{eventId}/sessions/{sessionId}/results -> [{position,displayTime,laps,status,points,driver:{firstName,lastName},team:{name}}]
#   GET /v1/{series}/standings/drivers -> [{position,points,firstName,lastName,teams:[]}] ; /standings/teams -> [{position,points,name}]
# Free tier: 7,500 req/month, 60/min, server-side only, non-commercial.
# Budget per run: 3 calls/series (events + 2 standings, cached 3h) -> ~1,500/month for F2+F3 at 8 runs/day.
# Results of finished sessions never change -> cached 30 days (one-off ~25 calls per series per season).
BT = "https://api.ocblacktop.com/v1"
def _num(x):
    try: return f"{float(x):g}"
    except (TypeError, ValueError): return str(x or "")

def feeder(series):
    key = os.environ.get("BLACKTOP_API_KEY")
    if not key:
        return {"status": "coming_soon", "note": "Needs a free Blacktop Data API key (BLACKTOP_API_KEY). No data shown until then."}
    H = {"x-api-key": key}
    call = lambda path, ttl: get(f"{BT}/{series}{path}", H, ttl)
    try:
        evs = call("/events?limit=50", 3 * 3600)["data"]
        season = max(e["dateStart"][:4] for e in evs)
        cur = sorted([e for e in evs if e["dateStart"].startswith(season)], key=lambda e: e["dateStart"])
        sessions, results, team_of = [], [], {}
        for rnd, e in enumerate(cur, 1):
            place = (e.get("location") or {}).get("name") or e["name"]
            ev_name = f'{e["name"]} (Round {rnd})'
            for sx in sorted(e.get("schedule") or [], key=lambda x: x.get("startTime") or ""):
                if sx.get("status") != "completed":
                    if sx.get("startTime"):
                        sessions.append({"event": ev_name, "session": sx["name"], "start": sx["startTime"].replace(".000Z", "Z"), "place": place})
                elif sx.get("type") in ("sprint", "race"):
                    rows = call(f'/events/{e["id"]}/sessions/{sx["id"]}/results', 30 * 86400)
                    cls = []
                    for r in rows if isinstance(rows, list) else []:
                        d, t = r.get("driver") or {}, (r.get("team") or {}).get("name", "")
                        nm = f'{d.get("firstName","")} {d.get("lastName","")}'.strip()
                        team_of[nm] = t
                        cls.append({"pos": str(r.get("position") or r.get("status") or "-"), "name": nm, "team": t,
                                    "time": r.get("displayTime") or r.get("status") or "", "points": _num(r.get("points"))})
                    cls.sort(key=lambda x: int(x["pos"]) if x["pos"].isdigit() else 999)
                    if cls: results.append({"round": str(rnd), "event": f'{e["name"]} – {sx["name"]}', "date": (sx.get("startTime") or e["dateEnd"])[:10],
                                            "place": place, "classification": cls})
        drivers = [{"pos": str(r["position"]), "name": f'{r.get("firstName","")} {r.get("lastName","")}'.strip(), "points": _num(r.get("points")), "wins": ""}
                   for r in call("/standings/drivers", 3 * 3600)]
        for d in drivers: d["team"] = team_of.get(d["name"], "")
        teams = [{"pos": str(r["position"]), "name": r["name"], "points": _num(r.get("points")), "wins": ""} for r in call("/standings/teams", 3 * 3600)]
        for d in drivers: d["wins"] = str(sum(1 for r in results if r["classification"] and r["classification"][0]["name"] == d["name"]))
        for t in teams: t["wins"] = str(sum(1 for r in results if r["classification"] and r["classification"][0]["team"] == t["name"]))
        results.sort(key=lambda r: r["date"], reverse=True)
        done = sum(1 for e in cur if e.get("status") == "completed")
        return {"status": "ok", "source": "Blacktop Data (ocblacktop.com)", "season": season, "round": str(done),
                "drivers": drivers, "teams": teams, "sessions": sessions, "results": results}
    except Exception as e:
        print(f"WARN {series}: {type(e).__name__}")
        return {"status": "coming_soon", "note": "Blacktop request failed; showing no data rather than stale or guessed data."}

def ics(name, sessions):
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    L = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//Feeder Ladder//{name}//EN", f"X-WR-CALNAME:{name} (Feeder Ladder, unofficial)", "CALSCALE:GREGORIAN"]
    for s in sessions:
        st = dt.datetime.fromisoformat(s["start"].replace("Z", "+00:00"))
        dur = 2 if s["session"] == "Race" else 1
        uid = hashlib.sha1((name + s["event"] + s["session"]).encode()).hexdigest()
        L += ["BEGIN:VEVENT", f"UID:{uid}@feederladder", f"DTSTAMP:{now}", f"DTSTART:{st:%Y%m%dT%H%M%SZ}",
              f"DTEND:{st + dt.timedelta(hours=dur):%Y%m%dT%H%M%SZ}", f"SUMMARY:{name}: {s['event']} - {s['session']}",
              f"LOCATION:{s['place']}", "END:VEVENT"]
    return "\r\n".join(L + ["END:VCALENDAR"]) + "\r\n"

if __name__ == "__main__":
    out = {"updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "f1": f1(), "f2": feeder("formula2"), "f3": feeder("formula3")}
    (SITE / "data" / "series.json").write_text(json.dumps(out, indent=1))
    (SITE / "cal" / "f1.ics").write_text(ics("F1", out["f1"]["sessions"]))
    for s in ("f2", "f3"):
        p = SITE / "cal" / f"{s}.ics"
        if out[s].get("sessions"): p.write_text(ics(s.upper(), out[s]["sessions"]))
        elif p.exists(): p.unlink()
    shutil.copy(ROOT / "content" / "news.json", SITE / "data" / "news.json")
    print("ok", out["updated"], "F1 round", out["f1"]["round"], "| F2:", out["f2"]["status"], "| F3:", out["f3"]["status"])
