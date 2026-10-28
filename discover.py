"""One-time setup: find creators for each niche through hashtags, keep those in the follower range.

  APIFY_TOKEN=... python discover.py           search, then write candidates.csv to review
  python discover.py --apply candidates.csv    add rows you marked approve=y to config.json
"""
import csv
import json
import re
import sys
from collections import Counter

from radar import ROOT, apify, load

PER_HASHTAG = 20      # reels pulled per hashtag (30 on a paid plan)
TOP_OWNERS = 60       # most-seen creators per niche whose follower count gets checked (80 on a paid plan)
SPEND_LIMIT = 4.5     # USD, whole search; fits Apify's free $5 a month (10 on a paid plan)
SG_HINT = re.compile(r"singapore|\bsg\b|🇸🇬|新加坡", re.I)
CHINESE = re.compile(r"[一-鿿]")
FIELDS = ["approve", "niche", "handle", "followers", "region", "lang", "seen_in_posts", "bio"]


def search(cfg):
    taken = {a["handle"].lower() for a in cfg["accounts"]}
    left, rows = SPEND_LIMIT, []
    for n in cfg["niches"]:
        seen, via_sg = Counter(), set()
        for region, tags in n["hashtags"].items():
            payload = {"hashtags": tags, "resultsLimit": PER_HASHTAG, "resultsType": "reels"}
            items, usd = apify(cfg["actors"]["hashtags"], payload, left)
            left -= max(usd, len(items) * cfg["apify_price_per_1000"] / 1000)
            for it in items:
                owner = (it.get("ownerUsername") or "").lower()
                if owner and owner not in taken:
                    seen[owner] += 1
                    if region == "sg":
                        via_sg.add(owner)
        owners = [o for o, _ in seen.most_common(TOP_OWNERS)]
        profiles, usd = apify(cfg["actors"]["profiles"], {"usernames": owners}, left) if owners else ([], 0)
        left -= max(usd, len(profiles) * cfg["apify_price_per_1000"] / 1000)
        for p in profiles:
            handle = (p.get("username") or "").lower()
            about = f"{p.get('fullName') or ''} {p.get('biography') or ''}".replace("\n", " ")
            region = "sg" if handle in via_sg or SG_HINT.search(about) else "global"
            low, high = cfg["followers"][region]
            followers = p.get("followersCount") or 0
            if p.get("private") or not low <= followers <= high:
                continue
            rows.append({
                "approve": "", "niche": n["id"], "handle": handle, "followers": followers, "region": region,
                "lang": "zh" if CHINESE.search(about) else "en", "seen_in_posts": seen[handle], "bio": about[:160],
            })
        print(f"{n['name']}: {sum(r['niche'] == n['id'] for r in rows)} candidates, ${SPEND_LIMIT - left:.2f} spent so far")
        if left <= 0:
            print("Spend limit reached, stopping early.")
            break
    order = {n["id"]: i for i, n in enumerate(cfg["niches"])}
    rows.sort(key=lambda r: (order[r["niche"]], r["region"] != "sg", -r["seen_in_posts"]))
    with open(ROOT / "candidates.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote candidates.csv ({len(rows)} rows). Put y in the approve column for the ones to track.")


def apply(cfg, path):
    have = {a["handle"].lower() for a in cfg["accounts"]}
    with open(path, encoding="utf-8-sig") as f:
        picked = [r for r in csv.DictReader(f) if r["approve"].strip().lower() in ("y", "yes", "1")]
    for r in picked:
        if r["handle"].lower() not in have:
            cfg["accounts"].append({k: r[k] for k in ("handle", "niche", "region", "lang")})
            have.add(r["handle"].lower())
    (ROOT / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", "utf-8")
    counts = Counter(a["niche"] for a in cfg["accounts"])
    print("Now tracking:", ", ".join(f"{k} {v}" for k, v in counts.items()))


if __name__ == "__main__":
    config = load(ROOT / "config.json", None)
    if len(sys.argv) == 3 and sys.argv[1] == "--apply":
        apply(config, sys.argv[2])
    else:
        search(config)
