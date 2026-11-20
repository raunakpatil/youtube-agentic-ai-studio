"""Tests for Unsplash stock image integration and configuration."""
import json
import pytest
from unittest.mock import patch, MagicMock

import config
import gui
from apis import images as image_apis
from video import stock

LOCAL = {"Host": "localhost:7070"}


def test_unsplash_ready_helper(monkeypatch):
    monkeypatch.setattr(config, "UNSPLASH_ACCESS_KEY", "")
    assert not stock._unsplash_ready()

    monkeypatch.setattr(config, "UNSPLASH_ACCESS_KEY", "YOUR_KEY_HERE")
    assert not stock._unsplash_ready()

    monkeypatch.setattr(config, "UNSPLASH_ACCESS_KEY", "test_access_key_123")
    assert stock._unsplash_ready()


def test_unsplash_search_parsing(monkeypatch):
    monkeypatch.setattr(config, "UNSPLASH_ACCESS_KEY", "valid_key")

    mock_resp = {
        "results": [
            {
                "id": "photo_1",
                "width": 1920,
                "height": 1080,
                "urls": {
                    "raw": "https://images.unsplash.com/raw_1",
                    "full": "https://images.unsplash.com/full_1",
                    "regular": "https://images.unsplash.com/reg_1",
                    "small": "https://images.unsplash.com/small_1",
                },
                "links": {
                    "html": "https://unsplash.com/photos/photo_1",
                    "download_location": "https://api.unsplash.com/photos/photo_1/download",
                },
                "user": {
                    "name": "Jane Photographer",
                    "username": "janephoto",
                },
            }
        ]
    }

    mock_get = MagicMock()
    mock_get.return_value.status_code = 200
    mock_get.return_value.ok = True
    mock_get.return_value.json.return_value = mock_resp

    with patch("requests.get", mock_get):
        candidates = stock._unsplash("galaxy stars", "landscape", count=1)

    assert len(candidates) == 1
    cand = candidates[0]
    assert cand["url"] == "https://images.unsplash.com/reg_1"
    assert cand["download_location"] == "https://api.unsplash.com/photos/photo_1/download"
    assert cand["credit"]["source"] == "Unsplash"
    assert cand["credit"]["author"] == "Jane Photographer"
    assert cand["credit"]["license"] == "Unsplash License"
    assert cand["credit"]["link"] == "https://unsplash.com/photos/photo_1"


def test_unsplash_provider_in_images_api(monkeypatch):
    monkeypatch.setattr(config, "UNSPLASH_ACCESS_KEY", "valid_key")

    mock_data = {
        "results": [
            {
                "id": "api_photo_1",
                "urls": {"regular": "https://images.unsplash.com/reg_api"},
                "links": {"html": "https://unsplash.com/photos/api_1", "download_location": "https://api.unsplash.com/dl"},
                "user": {"name": "Bob Visuals"},
            }
        ]
    }

    with patch("apis.images.get_json", return_value=mock_data):
        results = image_apis._unsplash("nebula", "portrait", count=1)

    assert len(results) == 1
    assert results[0]["credit"]["source"] == "Unsplash"
    assert results[0]["credit"]["author"] == "Bob Visuals"


def test_unsplash_setting_saved_to_env(monkeypatch):
    env = {}
    monkeypatch.setattr(config, "save_env", env.update)
    monkeypatch.setattr(config, "UNSPLASH_ACCESS_KEY", "", raising=False)

    r = gui.app.test_client().post(
        "/api/save-settings",
        headers=LOCAL,
        json={"unsplash_key": "unsplash_test_key_xyz"},
    )
    assert r.get_json() == {"ok": True}
    assert env.get("UNSPLASH_ACCESS_KEY") == "unsplash_test_key_xyz"
