from apis import seo

GOOD_DESC = (
    "Why does time slow down near a black hole? In this video we explore black holes, "
    "gravitational time dilation and what Einstein got right. " * 3
    + "\n\n0:00 Intro\n1:10 The event horizon\n3:20 Time dilation\n\n"
    "Subscribe for more and comment your theory below!\n#BlackHoles #Physics #Space"
)
GOOD_TAGS = ["black holes", "time dilation", "physics", "space", "einstein",
             "general relativity", "event horizon", "science", "astronomy"]


def test_good_metadata_scores_high():
    r = seo.score("Why Time Stops at the Edge of a Black Hole", GOOD_DESC, GOOD_TAGS, "black hole")
    assert r["score"] >= 85
    assert r["grade"] == "A"


def test_bad_metadata_scores_low_with_tips():
    r = seo.score("VIDEO", "", [], "black hole")
    assert r["score"] < 50
    failing = [c for c in r["checks"] if not c["ok"]]
    assert failing and all(c["tip"] for c in failing)


def test_weights_add_up_to_100():
    r = seo.score("x", "y", [], "")
    assert sum(c["weight"] for c in r["checks"]) == 100


def test_shorts_do_not_need_chapters():
    no_chapters = GOOD_DESC.replace("0:00 Intro", "Intro")
    title = "Title here about black holes"
    longform = {c["label"]: c["ok"] for c in seo.score(title, no_chapters, GOOD_TAGS, "black hole")["checks"]}
    shorts = {c["label"]: c["ok"] for c in seo.score(title, no_chapters, GOOD_TAGS, "black hole", is_shorts=True)["checks"]}
    assert longform["Chapters"] is False
    assert shorts["Chapters"] is True


def test_all_caps_title_flagged():
    checks = {c["label"]: c["ok"] for c in seo.score("THIS IS ALL CAPS SHOUTING", "", [], "")["checks"]}
    assert checks["Not shouting"] is False
