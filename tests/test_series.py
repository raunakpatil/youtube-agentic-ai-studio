import json

import config
from agents import researcher, scriptwriter
from studio import library


def _save_library_item(root, meta, research):
    folder = root / meta["id"]
    folder.mkdir()
    (folder / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (folder / "research.json").write_text(json.dumps(research), encoding="utf-8")


def test_series_context_tracks_next_episode_and_saved_coverage(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "LIB_DIR", str(tmp_path))
    monkeypatch.setattr(config, "YOUTUBE_API_KEY", "", raising=False)
    monkeypatch.setattr(config, "YOUTUBE_CHANNEL_ID", "", raising=False)
    _save_library_item(tmp_path, {
        "id": "first", "title": "How black holes form", "topic": "Black hole formation",
        "series_name": "Black holes", "series_episode": 1,
        "created_at": "2026-01-01T10:00:00", "yt_url": None,
    }, {"key_points": ["A star collapses", "The event horizon forms"]})
    _save_library_item(tmp_path, {
        "id": "second", "title": "Inside the event horizon", "topic": "Event horizon",
        "series_name": "Black holes", "series_episode": 2,
        "series_connection": "Now that we know how one forms, we look at its boundary.",
        "next_episode_hint": "Explain how black holes bend light.",
        "created_at": "2026-01-02T10:00:00", "yt_url": "https://youtu.be/abcdefghijk",
    }, {"key_points": ["Nothing escapes past the boundary", "The horizon is not a solid surface"]})

    context = library.series_context("Black holes")

    assert context["next_episode"] == 3
    assert context["previous_episode_title"] == "Inside the event horizon"
    assert context["previous_next_step"] == "Explain how black holes bend light."
    latest = next(video for video in context["recent_videos"] if video["title"] == "Inside the event horizon")
    assert latest["published"] is True
    assert latest["key_points"] == ["Nothing escapes past the boundary", "The horizon is not a solid surface"]


def test_series_context_uses_recent_youtube_uploads_when_configured(monkeypatch):
    from apis import youtube_stats

    monkeypatch.setattr(library, "list_library", lambda: [{
        "id": "yaas", "title": "Already in YAAS", "created_at": "2026-01-01T00:00:00",
        "topic": "Already in YAAS", "yt_url": "https://youtu.be/abcdefghijk",
    }])
    monkeypatch.setattr(youtube_stats, "configured", lambda: True)
    monkeypatch.setattr(youtube_stats, "channel_stats", lambda: {"recent": [
        {"id": "abcdefghijk", "title": "Already in YAAS", "published": "2026-01-01T00:00:00Z"},
        {"id": "zyxwvutsrqp", "title": "A channel upload outside YAAS", "published": "2026-01-02T00:00:00Z"},
    ]})

    context = library.series_context("My series")

    titles = [video["title"] for video in context["recent_videos"]]
    assert titles.count("Already in YAAS") == 1
    assert "A channel upload outside YAAS" in titles


def test_researcher_uses_episode_history_and_saves_tracking_fields(monkeypatch):
    prompts = []
    result = {
        "topic": "How black holes bend light", "video_title": "Black Holes Bend Light",
        "key_points": ["Gravity curves spacetime"], "tags": ["space"],
        "series_connection": "This follows the event horizon episode.",
        "next_episode_hint": "Explain gravitational lensing observations.",
    }
    monkeypatch.setattr(researcher, "generate", lambda prompt: prompts.append(prompt) or json.dumps(result))
    monkeypatch.setattr(researcher, "_grounding", lambda topic: {"facts": "", "sources": []})

    research = researcher.research_topic(
        "A channel about black holes", focus_angle="Theoretical Physics",
        channel_series="Black holes, from discovery to observation",
        episode_context={
            "next_episode": 1, "previous_episode_title": "",
            "previous_next_step": "No next-step note has been saved yet.",
            "recent_videos": [{"title": "First tracked episode", "topic": "Black hole formation",
                               "key_points": ["A star collapses"], "published": False}],
        },
    )

    assert "Black holes, from discovery to observation" in prompts[0]
    assert "First tracked episode" in prompts[0]
    assert research["series_episode"] == 1
    assert research["series_name"] == "Black holes, from discovery to observation"


def test_researcher_uses_channel_description_as_default_niche(monkeypatch):
    prompts = []
    result = {"topic": "A topic", "video_title": "A title", "key_points": [], "tags": []}
    monkeypatch.setattr(researcher, "generate", lambda prompt: prompts.append(prompt) or json.dumps(result))
    monkeypatch.setattr(researcher, "_grounding", lambda topic: {"facts": "", "sources": []})

    researcher.research_topic("Only explain practical home gardening", episode_context={"recent_videos": []})

    assert "The channel's main theme is: >>> Only explain practical home gardening <<<" in prompts[0]


def test_scriptwriter_receives_series_continuity_for_both_formats(monkeypatch):
    prompts = []
    generated = json.dumps({"sections": [{"id": i, "narration": "A short narration."} for i in range(1, 5)]})
    monkeypatch.setattr(scriptwriter, "generate", lambda prompt: prompts.append(prompt) or generated)
    research = {
        "topic": "How black holes bend light", "video_title": "How Black Holes Bend Light",
        "key_points": ["Gravity curves spacetime"], "series_name": "Black holes",
        "series_episode": 2, "previous_episode_title": "Inside the event horizon",
        "series_connection": "This follows the episode about the event horizon.",
        "next_episode_hint": "Explain gravitational lensing observations.",
    }

    scriptwriter.write_script(research, "normal")
    scriptwriter.write_script(research, "shorts")

    assert len(prompts) == 2
    for prompt in prompts:
        assert "Black holes (Episode 2)" in prompt
        assert "Inside the event horizon" in prompt
        assert "Explain gravitational lensing observations" in prompt
        assert "understandable on its own" in prompt
