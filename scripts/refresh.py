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

def get(url, headers=None):
    f = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".json")
    if f.exists() and time.time() - f.stat().st_mtime < TTL:
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
    return {"status": "ok", "source": "Jolpica (api.jolpi.ca)", "season": ds["season"], "round": ds["round"],
            "drivers": drivers, "teams": teams, "sessions": sessions}

def feeder(series):
    key = os.environ.get("BLACKTOP_API_KEY")
    if not key:
        return {"status": "coming_soon", "note": "Needs a free Blacktop Data API key (BLACKTOP_API_KEY). No data shown until then."}
    # NOTE: endpoint paths beyond /v1/formula2/events must be verified against Blacktop docs once a key exists.
    base = f"https://api.ocblacktop.com/v1/{series}"
    try:
        events = get(base + "/events", {"x-api-key": key})
        return {"status": "raw", "source": "Blacktop Data", "events": events}
    except Exception as e:
        return {"status": "coming_soon", "note": f"Blacktop request failed: {e}"}

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
