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

# ---- F2/F3 via Blacktop Data (https://ocblacktop.com/api/formula-2). Documented endpoints:
#   GET /v1/{series}/events                         -> {"upcoming":[{id,name,round,dateStart,dateEnd,location:{name,country:{name}}}], ...}
#   GET /v1/{series}/events/{eventId}/sessions      -> sessions in chronological order
#   GET /v1/{series}/events/{eventId}/sessions/{sessionId}/results  (shape documented for F1; "same shape" for all series)
#   GET /v1/{series}/standings/drivers | /standings/teams
# Only the /events example response is published; other field names are read defensively and the
# raw responses are saved to .cache/blacktop-*.json so the parser can be verified once a key exists.
# Free tier: 7,500 req/month, 60 req/min, server-side only, non-commercial. We cache 1h; ~2 runs per 3h is well within.
BT = "https://api.ocblacktop.com/v1"
def _list(x, *keys):
    if isinstance(x, list): return x
    if isinstance(x, dict):
        for k in keys + ("data", "results", "items", "standings"):
            if isinstance(x.get(k), list): return x[k]
    return []
def _g(d, *ks, default=""):
    for k in ks:
        v = d
        for part in k.split("."):
            v = v.get(part) if isinstance(v, dict) else None
        if v not in (None, ""): return v
    return default
def _name(d):
    if isinstance(d, str): return d
    if not isinstance(d, dict): return ""
    n = _g(d, "name", "fullName", "displayName")
    return n or f'{_g(d, "firstName", "givenName")} {_g(d, "lastName", "familyName")}'.strip()

def feeder(series):
    key = os.environ.get("BLACKTOP_API_KEY")
    if not key:
        return {"status": "coming_soon", "note": "Needs a free Blacktop Data API key (BLACKTOP_API_KEY). No data shown until then."}
    H = {"x-api-key": key}
    def call(path, ttl=None):
        d = get(f"{BT}/{series}{path}", H, ttl)
        (CACHE / f"blacktop-{series}-{hashlib.sha1(path.encode()).hexdigest()[:8]}.json").write_text(json.dumps({"path": path, "body": d})[:200000])
        return d
    try:
        ev = call("/events?limit=50", 3 * 3600)
        events = (_list(ev, "upcoming") + _list(ev, "past", "completed", "events")) if isinstance(ev, dict) else _list(ev)
        seen, evs = set(), []
        for e in events:
            if e.get("id") in seen: continue
            seen.add(e.get("id")); evs.append(e)
        evs.sort(key=lambda e: str(_g(e, "dateStart", "date")))
        today = dt.date.today().isoformat()
        sessions, results = [], []
        for e in evs:
            ev_name = f'{_g(e, "name")} (Round {_g(e, "round")})'; place = _g(e, "location.name", "location.city")
            past = str(_g(e, "dateEnd", "dateStart")) < today
            # Quota: past rounds never change -> cache 30 days; next 3 rounds 3h; later rounds 1 day.
            nxt = [x for x in evs if str(_g(x, "dateEnd", "dateStart")) >= today][:3]
            ttl = 30 * 86400 if past else (3 * 3600 if e in nxt else 86400)
            if True:
                for s in _list(call(f'/events/{e["id"]}/sessions', ttl), "sessions"):
                    start = _g(s, "startTime", "start", "dateStart", "date")
                    label = _g(s, "name", "type")
                    if start and not past:
                        sessions.append({"event": ev_name, "session": label, "start": str(start), "place": place})
                    if past and any(w in str(label).lower() for w in ("race", "sprint", "feature")) and s.get("id"):
                        cls = [{"pos": str(_g(r, "position", "pos")), "name": _name(_g(r, "driver", default={})) or _name(r),
                                "team": _name(_g(r, "team", "constructor", default={})), "time": str(_g(r, "time", "gap", "status")),
                                "points": str(_g(r, "points", default=0))}
                               for r in _list(call(f'/events/{e["id"]}/sessions/{s["id"]}/results', 30 * 86400), "results", "classification")]
                        if cls: results.append({"round": str(_g(e, "round")), "event": f'{_g(e, "name")} – {label}', "date": str(_g(s, "startTime", "date", default=_g(e, "dateEnd")))[:10], "place": place, "classification": cls})
        st = lambda rows, team: [{"pos": str(_g(r, "position", "pos")), "name": _name(_g(r, "team", default={})) if team else (_name(_g(r, "driver", default={})) or _name(r)),
                                  "team": "" if team else _name(_g(r, "team", default={})), "points": str(_g(r, "points", default=0)), "wins": str(_g(r, "wins", default=""))} for r in rows]
        drivers = st(_list(call("/standings/drivers", 3 * 3600), "drivers"), False)
        teams = st(_list(call("/standings/teams", 3 * 3600), "teams"), True)
        if not (drivers or sessions or results):
            return {"status": "coming_soon", "note": "Blacktop responded but the format wasn't recognised; parser needs updating."}
        results.sort(key=lambda r: r["date"], reverse=True)
        return {"status": "ok", "source": "Blacktop Data (ocblacktop.com)", "season": str(dt.date.today().year), "round": results[0]["round"] if results else "",
                "drivers": drivers, "teams": teams, "sessions": sorted(sessions, key=lambda s: s["start"]), "results": results}
    except Exception as e:
        print(f"WARN {series}: {e}")
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
