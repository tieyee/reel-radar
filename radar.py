"""Weekly run: scrape reels, score each against its creator's usual views at the same age, write docs/data.json.

Usage: APIFY_TOKEN=... python radar.py
"""
import datetime as dt
import json
import os
import statistics
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
DATA, DOCS = ROOT / "data", ROOT / "docs"
API = "https://api.apify.com/v2"

# Share of a reel's final views it usually has by day N. A starting guess;
# learn_curve() swaps in real numbers once enough reels have been re-checked.
DEFAULT_CURVE = [(0, 0.0), (1, 0.45), (2, 0.6), (3, 0.7), (5, 0.8), (7, 0.87), (14, 0.95), (30, 1.0)]
CURVE_DAYS = [1, 2, 3, 5, 7, 10]


def load(path, default):
    try:
        return json.loads(Path(path).read_text("utf-8"))
    except FileNotFoundError:
        return default


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), "utf-8")


def parse_time(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def age_days(posted, at):
    return (parse_time(at) - parse_time(posted)).total_seconds() / 86400


# ---------- scoring ----------

def curve_at(age, pts):
    if age >= pts[-1][0]:
        return pts[-1][1]
    for (a0, f0), (a1, f1) in zip(pts, pts[1:]):
        if a0 <= age <= a1:
            return f0 + (f1 - f0) * (age - a0) / (a1 - a0)
    return pts[0][1]


def est_final(views, age, pts):
    """Views this reel will likely end with, given views so far at this age."""
    return views / max(curve_at(age, pts), 0.05)


def latest(r):
    """(age in days at last check, views at last check)."""
    at, views = r["snaps"][-1]
    return age_days(r["posted"], at), views


def baseline(owner_reels, pts, exclude=None, n=20):
    """Creator's usual final views: median over their last n reels (not counting this one)."""
    ests = []
    for r in owner_reels:
        if r["code"] == exclude:
            continue
        age, views = latest(r)
        if age >= 1 and views:
            ests.append(est_final(views, age, pts))
        if len(ests) == n:
            break
    return statistics.median(ests) if len(ests) >= 3 else None


def learn_curve(reels, min_samples=30):
    """Build the growth curve from reels checked more than once.

    ponytail: treats the last check at day 14+ as near-final and borrows the default
    curve's tail for that last bit; good enough while the tail is flat.
    """
    buckets = {d: [] for d in CURVE_DAYS}
    for r in reels.values():
        snaps = [(age_days(r["posted"], t), v) for t, v in r["snaps"] if v]
        late = [(a, v) for a, v in snaps if a >= 14]
        if not late:
            continue
        final = late[-1][1] / curve_at(late[-1][0], DEFAULT_CURVE)
        for a, v in snaps:
            if 0.5 <= a < 12:
                buckets[min(CURVE_DAYS, key=lambda d: abs(d - a))].append(v / final)
    pts, last, learned = [(0, 0.0)], 0.0, False
    for d in CURVE_DAYS:
        if len(buckets[d]) >= min_samples:
            f, learned = statistics.median(buckets[d]), True
        else:
            f = curve_at(d, DEFAULT_CURVE)
        last = min(max(f, last), 1.0)  # a curve never goes down
        pts.append((d, last))
    pts += [(14, max(last, 0.95)), (30, 1.0)]
    return pts, learned


def select(cards, min_score, per_niche, per_creator):
    """Top reels per niche: at or above min_score, at most per_creator from one creator."""
    out = {}
    for c in sorted(cards, key=lambda c: -c["score"]):
        if c["score"] < min_score:
            continue
        picked = out.setdefault(c["niche"], [])
        if len(picked) >= per_niche or sum(p["owner"] == c["owner"] for p in picked) >= per_creator:
            continue
        picked.append(c)
    return out


# ---------- Apify ----------

def api(path, body=None):
    req = urllib.request.Request(
        f"{API}{path}",
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {os.environ['APIFY_TOKEN']}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def apify_credit_left():
    """USD the Apify plan still allows this billing cycle."""
    d = api("/users/me/limits")["data"]
    return (d["limits"].get("maxMonthlyUsageUsd") or float("inf")) - (d["current"].get("monthlyUsageUsd") or 0)


def apify(actor, payload, max_usd):
    """Run an Apify actor and return (items, usd charged). Never spends more than max_usd."""
    q = urllib.parse.urlencode({"maxTotalChargeUsd": f"{max(max_usd, 0):.2f}"})
    run = api(f"/acts/{actor.replace('/', '~')}/runs?{q}", payload)["data"]
    deadline = time.time() + 3600
    while run["status"] in ("READY", "RUNNING") and time.time() < deadline:
        time.sleep(20)
        run = api(f"/actor-runs/{run['id']}")["data"]
    if run["status"] != "SUCCEEDED":
        print(f"warning: {actor} ended {run['status']}, keeping partial results")
    items = api(f"/datasets/{run['defaultDatasetId']}/items?clean=true")
    return items, float(run.get("usageTotalUsd") or 0)


def views_of(it):
    for k in ("videoPlayCount", "playCount", "videoViewCount", "viewCount"):
        if it.get(k):
            return int(it[k])
    return None


def audio_of(it):
    m = it.get("musicInfo") or {}
    if m.get("uses_original_audio") or not m.get("song_name"):
        return "Original audio"
    return f"{m['song_name']} by {m.get('artist_name') or 'unknown'}"


def ingest(reels, items, niche_of, at):
    for it in items:
        code, owner = it.get("shortCode") or it.get("code"), (it.get("ownerUsername") or "").lower()
        views, posted = views_of(it), it.get("timestamp")
        if not (code and owner in niche_of and views is not None and posted):
            continue
        r = reels.setdefault(code, {"code": code, "snaps": []})
        r.update(
            owner=owner,
            niche=niche_of[owner],
            posted=parse_time(posted).isoformat(),
            url=it.get("url") or f"https://www.instagram.com/reel/{code}/",
            caption=(it.get("caption") or "")[:400],
            audio=audio_of(it),
            thumb_src=it.get("displayUrl"),
        )
        r["snaps"] = [s for s in r["snaps"] if s[0] != at] + [[at, views]]


def fetch_thumb(code, src):
    dest = DOCS / "thumbs" / f"{code}.jpg"
    dest.parent.mkdir(parents=True, exist_ok=True)  # git drops the empty folder
    if not dest.exists() and src:
        try:
            req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                dest.write_bytes(resp.read())
        except OSError as e:
            print(f"warning: thumbnail {code} failed: {e}")
    return f"thumbs/{code}.jpg" if dest.exists() else None


# ---------- weekly run ----------

def main():
    cfg = load(ROOT / "config.json", None)
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    at, month = now.isoformat(), now.strftime("%Y-%m")
    reels, state = load(DATA / "reels.json", {}), load(DATA / "state.json", {})
    spend = state.get("spend") if state.get("spend", {}).get("month") == month else {"month": month, "usd": 0.0}
    cap, price = cfg["budget_usd_per_month"], cfg["apify_price_per_1000"] / 1000
    page = load(DOCS / "data.json", {})

    def publish(status):
        page.update(status=status, spend={**spend, "cap": cap}, checked=at)
        state["spend"] = spend
        save(DOCS / "data.json", page)
        save(DATA / "state.json", state)
        print(status)

    accounts = {a["handle"].lower().lstrip("@"): a for a in cfg["accounts"]}
    own = cfg["own_account"].lower().lstrip("@")
    niche_of = {h: a["niche"] for h, a in accounts.items()}
    if own:
        niche_of[own] = "own"
    if not accounts:
        return publish("No creators picked yet. Run discover.py to find them.")

    # Scrape: more reels the first time we see an account, to learn its usual views.
    known = {r["owner"] for r in reels.values()}
    limit = {h: cfg["reels_weekly_fetch"] if h in known else cfg["reels_first_fetch"] for h in niche_of}
    estimate = sum(limit.values()) * price
    credit, spent_before = apify_credit_left(), spend["usd"]

    def room():  # USD this run may still spend: the lower of our budget and Apify's credit
        return min(cap - spend["usd"], credit - (spend["usd"] - spent_before))

    if estimate > room():
        why = (f"${cap - spend['usd']:.2f} of this month's ${cap} budget is left" if cap - spend["usd"] < credit
               else f"the Apify plan has ${credit:.2f} of credit left this cycle. Upgrade it at apify.com/pricing")
        return publish(f"Skipped this week. The run would cost about ${estimate:.2f}, and {why}.")
    for n in sorted(set(limit.values())):
        handles = [h for h in limit if limit[h] == n]
        items, usd = apify(cfg["actors"]["reels"], {"username": handles, "resultsLimit": n}, room())
        spend["usd"] = round(spend["usd"] + max(usd, len(items) * price), 2)
        ingest(reels, items, niche_of, at)

    # Forget reels older than 120 days.
    reels = {c: r for c, r in reels.items() if age_days(r["posted"], at) <= 120}

    # Once a month: flag creators who went quiet or grew past the range.
    health = state.get("health", {})
    if health.get("month") != month and len(accounts) * price <= room():
        profiles, usd = apify(cfg["actors"]["profiles"], {"usernames": list(accounts)}, room())
        spend["usd"] = round(spend["usd"] + max(usd, len(profiles) * price), 2)
        followers = {(p.get("username") or "").lower(): p.get("followersCount") for p in profiles}
        flags = []
        for h, a in accounts.items():
            top = cfg["followers"][a.get("region", "global")][1]
            last = max((r["posted"] for r in reels.values() if r["owner"] == h), default=None)
            f = followers.get(h)
            if f is None:
                reason = "Profile not found. It may be renamed, private or deleted."
            elif f > top:
                reason = f"Grew to {f:,} followers, past the {top:,} limit."
            elif last is None or age_days(last, at) > 30:
                reason = "No reels in the last 30 days."
            else:
                continue
            flags.append({"handle": h, "niche": a["niche"], "reason": reason})
        health = {"month": month, "flags": flags}

    # Score.
    pts, learned = learn_curve(reels)
    by_owner = {}
    for r in sorted(reels.values(), key=lambda r: r["posted"], reverse=True):
        by_owner.setdefault(r["owner"], []).append(r)
    shown_before = set(state.get("shown", []))
    cards, own_cards = [], []
    for r in reels.values():
        if r["snaps"][-1][0] != at:  # not re-checked this run, views are stale
            continue
        age, views = latest(r)
        base = baseline(by_owner[r["owner"]], pts, exclude=r["code"])
        score = round(est_final(views, age, pts) / base, 1) if base and age >= 1 else None
        card = {
            "code": r["code"], "url": r["url"], "owner": r["owner"], "niche": r["niche"],
            "score": score, "age_days": round(age, 1), "views": views,
            "caption": r["caption"], "audio": r["audio"], "posted": r["posted"],
            "lang": accounts.get(r["owner"], {}).get("lang", "en"),
            "early": age < cfg["early_days"], "seen": r["code"] in shown_before,
        }
        if r["niche"] == "own":
            if age <= 30:
                own_cards.append(card)
        elif score is not None and age <= cfg["max_age_days"]:
            cards.append(card)

    picked = select(cards, cfg["min_score"], cfg["per_niche"], cfg["per_creator"])
    own_cards = sorted(own_cards, key=lambda c: c["posted"], reverse=True)[:10]
    shown = [c for lst in picked.values() for c in lst] + own_cards
    for c in shown:
        c["thumb"] = fetch_thumb(c["code"], reels[c["code"]].get("thumb_src"))
    keep = {f"{c['code']}.jpg" for c in shown}
    for f in (DOCS / "thumbs").glob("*.jpg"):
        if f.name not in keep:
            f.unlink()

    page.clear()
    page.update(
        generated=at,
        curve_learned=learned,
        own={"handle": own, "reels": own_cards} if own else None,
        niches=[{**{k: n[k] for k in ("id", "name", "color")}, "reels": picked.get(n["id"], [])} for n in cfg["niches"]],
        health=health.get("flags", []),
    )
    state.update(health=health, shown=[c["code"] for c in shown])
    save(DATA / "reels.json", reels)
    total = sum(len(v) for v in picked.values())
    publish(f"Found {total} standout reels across {len(picked)} niches.")


if __name__ == "__main__":
    main()
