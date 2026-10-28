"""Checks for the scoring maths. Run: python test_radar.py"""
from radar import DEFAULT_CURVE, ad_heavy, baseline, curve_at, est_final, learn_curve, not_a_format, select

T0 = "2026-10-01T00:00:00+00:00"


def reel(code, owner, posted, snaps):
    return {"code": code, "owner": owner, "posted": posted, "snaps": snaps}


def test_curve():
    assert curve_at(1, DEFAULT_CURVE) == 0.45
    assert abs(curve_at(4, DEFAULT_CURVE) - 0.75) < 1e-9  # halfway between day 3 and 5
    assert curve_at(99, DEFAULT_CURVE) == 1.0


def test_age_adjusted_score():
    # Creator's reels all end around 3,000 views (checked at day 30).
    old = [reel(f"o{i}", "a", T0, [["2026-10-31T00:00:00+00:00", 3000]]) for i in range(5)]
    base = baseline(old, DEFAULT_CURVE)
    assert base == 3000
    # A 1-day-old reel with 13,500 views is on pace for 30,000: 10x.
    assert round(est_final(13500, 1, DEFAULT_CURVE) / base, 1) == 10.0
    # Too little history: no baseline.
    assert baseline(old[:2], DEFAULT_CURVE) is None
    # The reel being scored doesn't count toward its own baseline.
    assert baseline(old[:3], DEFAULT_CURVE, exclude="o0") is None


def test_select_caps():
    cards = [{"niche": "n", "owner": "a", "score": s} for s in (9, 8, 7)]
    cards += [{"niche": "n", "owner": "b", "score": 6}, {"niche": "n", "owner": "c", "score": 2}]
    out = select(cards, min_score=2.5, per_niche=10, per_creator=2)["n"]
    assert [(c["owner"], c["score"]) for c in out] == [("a", 9), ("a", 8), ("b", 6)]
    assert len(select(cards, 2.5, 1, 2)["n"]) == 1


def test_learn_curve():
    pts, learned = learn_curve({})
    assert not learned and pts[1] == (1, 0.45)
    # 40 reels that each had 60% of their final views at day 1.
    reels = {
        str(i): reel(str(i), "a", T0, [["2026-10-02T00:00:00+00:00", 600], ["2026-10-31T00:00:00+00:00", 1000]])
        for i in range(40)
    }
    pts, learned = learn_curve(reels)
    assert learned and abs(pts[1][1] - 0.6) < 1e-9
    assert all(b[1] >= a[1] for a, b in zip(pts, pts[1:]))  # never goes down


def test_not_a_format():
    # The six reels the 2026-10-28 trial picked, all uncopyable.
    cases = {
        "Tried the Food Bar @7elevensg ... Here's the deal: From now til": "Ad",
        "CMLink SIM-only Plan ... October Promo • 50% off 6 months": "Ad",
        "🚨 𝐓-𝐑𝐄𝐗 𝐒𝐏𝐎𝐓𝐓𝐄𝐃! 𝐖𝐢𝐧 𝐅𝐑𝐄𝐄 𝐃𝐢𝐧𝐨 𝐏𝐥𝐮𝐬𝐡𝐢𝐞𝐬": "Ad",
        "Take a walk through Sembawang Estate's Halloween decorations": "Event or news",
        "Sit-n-Read node at City Square Mall. Read more details at our link in profile": "Event or news",
        "THE DAY WE FOUND OUT! 🥹🍼🧸": "Life moment",
        "From 23 to 25 October the walk is in malls": "Event or news",
    }
    for caption, why in cases.items():
        assert not_a_format({"caption": caption}) == why, caption
    # Normal agent content, prices included, stays in.
    for caption in ("3 mistakes HDB sellers make. #3 cost my client $40k", "Sold! 4-room in Punggol for $680,000", ""):
        assert not_a_format({"caption": caption}) is None, caption
    assert not_a_format({"caption": "", "paid": True}) == "Ad"


def test_ad_heavy():
    reels = {f"a{i}": {"owner": "a", "caption": "promo" if i < 3 else "tips"} for i in range(5)}
    reels |= {f"b{i}": {"owner": "b", "caption": "promo" if i < 2 else "tips"} for i in range(5)}
    reels |= {f"c{i}": {"owner": "c", "caption": "promo"} for i in range(4)}  # too few to judge
    assert ad_heavy(reels) == {"a": (3, 5)}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("all checks passed")
