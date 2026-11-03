"""Description builder, credits, watermark, config and model-chain behaviour."""
import numpy as np
import pytest

import config
import gui
from studio import description, settings
from agents import gemini_client
from video import creator, stock

SCRIPT = {
    "title": "What If the Moon Disappeared?",
    "description": "A thought experiment about our Moon.",
    "tags": ["moon", "space", "physics"],
    "sections": [{"id": i, "title": f"Part {i}", "narration": "word " * 120} for i in range(1, 6)],
}
RESEARCH = {
    "hook_question": "What happens to Earth without the Moon?",
    "key_points": ["Tides", "Axial tilt", "Night sky"],
    "grounding": {"facts": "", "sources": [
        {"source": "Wikipedia", "title": "Moon", "url": "https://en.wikipedia.org/wiki/Moon"}]},
}


@pytest.fixture(autouse=True)
def _no_credits_file(monkeypatch):
    monkeypatch.setattr(description, "load_credits", lambda: [])


def test_description_has_chapters_sources_and_credit(monkeypatch):
    monkeypatch.setattr(config, "CREDIT_YAAS", True, raising=False)
    d = description.build_description(SCRIPT, RESEARCH, "normal")
    assert "⏱ CHAPTERS" in d and "\n0:00 Part 1" in d
    assert "https://en.wikipedia.org/wiki/Moon" in d
    assert "https://raunakpatil.com" in d
    assert d.rstrip().endswith("#moon #space #physics")     # hashtags stay last
    assert len(d) <= 4900


def test_shorts_description_has_no_chapters():
    d = description.build_description({**SCRIPT, "video_type": "shorts"}, RESEARCH, "shorts")
    assert "CHAPTERS" not in d
    assert "#Shorts" in d


def test_credit_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(config, "CREDIT_YAAS", False, raising=False)
    assert "raunakpatil.com" not in description.build_description(SCRIPT, RESEARCH, "normal")


def test_old_descriptions_get_the_credit(monkeypatch):
    monkeypatch.setattr(config, "CREDIT_YAAS", True, raising=False)
    assert description.with_credit("Old text").endswith(description.CREDIT_LINE)
    already = "x\n" + description.CREDIT_LINE
    assert description.with_credit(already) == already


@pytest.mark.parametrize("w, h", [(1920, 1080), (1080, 1920)])
def test_watermark_fits_inside_frame_and_is_semi_transparent(w, h):
    x, y, rgb, alpha = creator._watermark_patch(w, h)
    ph, pw = alpha.shape[:2]
    assert 0 <= x and x + pw <= w and 0 <= y and y + ph <= h
    assert 0 < alpha.max() <= creator.WATERMARK_OPACITY + 1e-6


def test_watermark_is_burned_into_frames():
    class FakeClip:
        def fl_image(self, fn):
            self.fn = fn
            return self
    clip = creator._apply_watermark(FakeClip(), 1280, 720)
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    out = clip.fn(frame)
    assert out.shape == frame.shape and out.sum() > 0     # white text on black
    assert frame.sum() == 0                               # original frame untouched


def test_watermark_text_is_not_a_setting():
    assert creator.WATERMARK_TEXT == "raunakpatil.com"
    assert not any("WATERMARK" in k for k, _ in settings._SETTINGS.values())


def test_save_env_updates_in_place(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# my keys\nGEMINI_API_KEY=old\nOTHER=keep\n", encoding="utf-8")
    config.save_env({"GEMINI_API_KEY": "new", "PEXELS_API_KEY": "p"}, path=str(env))
    text = env.read_text(encoding="utf-8")
    assert "# my keys" in text and "OTHER=keep" in text
    assert "GEMINI_API_KEY=new" in text and "GEMINI_API_KEY=old" not in text
    assert "PEXELS_API_KEY=p" in text


def test_keys_are_masked_for_the_browser():
    assert settings._mask("") == ""
    assert settings._mask("YOUR_GEMINI_API_KEY") == ""
    assert settings._mask("abcdefghijkl") == "••••ijkl"


def test_model_chain_starts_at_preference():
    chain = gemini_client.build_chain("gemini-2.0-flash")
    assert chain[0] == "gemini-2.0-flash" and len(chain) == len(set(chain))
    assert gemini_client.build_chain("not-a-model")[0] == gemini_client._ALL_MODELS[0]


def test_dropped_connections_are_retried():
    assert gemini_client._should_switch_model(Exception("[WinError 10053] An established connection was aborted"))
    assert gemini_client._should_switch_model(Exception("Read timed out"))
    assert not gemini_client._should_switch_model(Exception("400 API_KEY_INVALID"))


def test_retired_models_are_skipped_not_retried():
    assert gemini_client._is_gone(Exception("404 NOT_FOUND models/gemini-1.5"))
    assert not gemini_client._is_gone(Exception("429 RESOURCE_EXHAUSTED"))


def test_section_images_finds_downloaded_files(tmp_path):
    for name in ("section_01_img01.jpg", "section_01_img02.jpg", "section_02_img01.jpg"):
        (tmp_path / name).write_bytes(b"x")
    assert [p.split("section_")[-1] for p in stock.section_images(str(tmp_path), 1)] == ["01_img01.jpg", "01_img02.jpg"]


def test_pollinations_logo_strip_is_cropped(tmp_path):
    from PIL import Image
    from apis.images import strip_pollinations_logo
    p = tmp_path / "ai.jpg"
    Image.new("RGB", (1024, 576), (10, 10, 10)).save(p)
    strip_pollinations_logo(str(p))
    with Image.open(p) as im:
        assert im.size == (1024, int(576 * 0.93))


def test_page_and_every_static_file_it_references_are_served():
    import re
    client = gui.app.test_client()
    page = client.get("/", headers={"Host": "localhost:7070"})
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assets = re.findall(r'(?:src|href)="(/static/[^"]+)"', html)
    assert "/static/app.css" in assets and "/static/js/boot.js" in assets
    assert assets.index("/static/js/core.js") < assets.index("/static/js/boot.js")  # load order
    for path in assets:
        r = client.get(path, headers={"Host": "localhost:7070"})
        assert r.status_code == 200 and r.data, path
        r.close()


def test_blueprints_are_registered():
    assert set(gui.app.blueprints) == {"pipeline", "review", "library", "upload", "settings", "dashboard"}
