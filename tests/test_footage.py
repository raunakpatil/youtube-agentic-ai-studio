"""Pixabay video matching and local caching."""
import json

from video import creator, footage


def test_visual_search_queries_use_the_narration_beats():
    section = {
        "title": "The Twist",
        "narration": "A black hole bends light. The event horizon hides what falls inside.",
        "visuals": [
            {"narration_cue": "A black hole bends light", "search_query": "black hole lensing simulation"},
            {"narration_cue": "The event horizon hides", "search_query": "black hole event horizon simulation"},
        ],
    }
    assert footage._visuals(section) == section["visuals"]


def test_old_scripts_search_their_spoken_sentences_not_generic_filler():
    section = {
        "title": "A generic section title",
        "narration": "The Moon causes ocean tides. Those tides change Earth's rotation.",
        "image_query": "space universe dramatic wide",
    }
    assert footage._visuals(section) == [
        {"search_query": "The Moon causes ocean tides.", "narration_cue": "The Moon causes ocean tides."},
        {"search_query": "Those tides change Earth's rotation.", "narration_cue": "Those tides change Earth's rotation."},
    ]


def test_pixabay_search_results_are_cached_for_24_hours(tmp_path, monkeypatch):
    monkeypatch.setattr(footage.config, "PIXABAY_API_KEY", "test-key", raising=False)
    calls = []

    class Response:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"hits": [{"id": 7}]}

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(footage.requests, "get", fake_get)
    assert footage._cached_hits("black hole lensing", str(tmp_path)) == [{"id": 7}]
    assert footage._cached_hits("black hole lensing", str(tmp_path)) == [{"id": 7}]
    assert len(calls) == 1
    saved = next(tmp_path.glob("*.json"))
    assert json.loads(saved.read_text(encoding="utf-8"))["hits"] == [{"id": 7}]


def test_clip_picker_rejects_too_short_or_wrong_orientation():
    def hit(video_id, duration, width, height):
        return {
            "id": video_id,
            "duration": duration,
            "videos": {"small": {"url": f"https://cdn.example/{video_id}.mp4",
                                  "width": width, "height": height, "size": 1000}},
        }

    picked = footage._pick_hit(
        [hit("short", 2, 720, 1280), hit("wide", 20, 1280, 720), hit("portrait", 20, 720, 1280)],
        "portrait", 10, set())
    assert picked[0]["id"] == "portrait"


def test_video_scene_starts_at_its_narration_cue():
    section = {"narration": "First beat now. Then the second one begins."}
    scenes = creator._visual_scenes(section, 30, [
        {"path": "first.mp4", "narration_cue": "First beat now"},
        {"path": "second.mp4", "narration_cue": "Then the second one begins"},
    ], [])
    assert scenes[0]["start"] == 0
    assert scenes[1]["start"] == 11.25


def test_missing_still_does_not_reuse_an_unrelated_scene_image(monkeypatch):
    first = object()
    scenes = creator._visual_scenes({"narration": "First beat. Next beat."}, 10, [
        {"path": None, "narration_cue": "First beat"},
        {"path": None, "narration_cue": "Next beat"},
    ], [first])
    assert scenes[0]["image"] is first
    assert scenes[1]["image"] is None
    monkeypatch.setattr(creator, "_ken_burns", lambda image, *args, **kwargs: image)
    assert creator._visual_scenes_frame(1, scenes, creator.OrderedDict(), 0) is first
    assert creator._visual_scenes_frame(6, scenes, creator.OrderedDict(), 0) is None
