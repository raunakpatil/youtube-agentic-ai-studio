"""Tests for Shorts timing configuration and 20-30 second constraints."""
import json
from unittest.mock import patch

import config
from agents import scriptwriter
from video import creator


def test_shorts_timing_config_constants():
    assert config.SHORTS_TARGET_MIN == 20.0
    assert config.SHORTS_TARGET_MAX == 30.0


def test_shorts_scriptwriter_prompt_specifies_20_30_seconds():
    research = {
        "topic": "Black Holes",
        "video_title": "What If You Fell Into A Black Hole?",
        "hook_question": "Can anything escape?",
        "key_points": ["Event horizon", "Spaghettification", "Time dilation"],
        "grounding": {"facts": "Black holes are regions of spacetime where gravity is strong."},
    }

    mock_script_response = json.dumps({
        "title": "What If You Fell Into A Black Hole? #Shorts",
        "description": "What happens inside a black hole? The answer will bend your reality.",
        "tags": ["space", "blackhole", "Shorts", "YouTubeShorts"],
        "sections": [
            {
                "id": 1,
                "section_type": "hook",
                "title": "hook_internal",
                "narration": "What happens if you fall into a black hole? You won't just die—reality itself breaks.",
                "duration_seconds": 5,
            },
            {
                "id": 2,
                "section_type": "story",
                "title": "story_internal",
                "narration": "Gravity stretches your body into a single strand of atoms in a process called spaghettification, while time slows to a dead stop.",
                "duration_seconds": 13,
            },
            {
                "id": 3,
                "section_type": "twist",
                "title": "twist_internal",
                "narration": "To the outside world, you are frozen forever. Follow for more mind-bending physics.",
                "duration_seconds": 8,
            },
        ],
    })

    captured_prompt = []

    def mock_generate(prompt):
        captured_prompt.append(prompt)
        return mock_script_response

    with patch("agents.scriptwriter.generate", mock_generate):
        script = scriptwriter.write_script(research, video_type="shorts")

    assert len(captured_prompt) == 1
    prompt_text = captured_prompt[0]

    # Verify prompt instructs 20-30 seconds, 50-70 words, and Hook → Story → Twist
    assert "20-30 second" in prompt_text
    assert "50-70 words" in prompt_text
    assert "Hook → Story → Twist" in prompt_text
    assert "50-60" not in prompt_text
    assert "120-160" not in prompt_text

    # Verify section types adhere to Hook → Story → Twist
    section_types = [s["section_type"] for s in script["sections"]]
    assert section_types == ["hook", "story", "twist"]

    # Verify section duration sum fits 20-30 seconds
    total_dur = sum(s.get("duration_seconds", 0) for s in script["sections"])
    assert 20 <= total_dur <= 30
    assert script["video_type"] == "shorts"


def test_shorts_video_hook_story_twist_acts():
    """Verify that _build_shorts_clip properly handles section_acts and twist highlights."""
    import numpy as np
    from PIL import Image

    img1 = np.full((1920, 1080, 3), 50, dtype=np.uint8)
    img2 = np.full((1920, 1080, 3), 100, dtype=np.uint8)
    img3 = np.full((1920, 1080, 3), 150, dtype=np.uint8)

    section_acts = [
        {"id": 1, "type": "hook", "start": 0.0, "end": 5.0, "images": [img1]},
        {"id": 2, "type": "story", "start": 5.0, "end": 18.0, "images": [img2]},
        {"id": 3, "type": "twist", "start": 18.0, "end": 26.0, "images": [img3]},
    ]
    captions = [
        {"start": 1.0, "end": 4.0, "text": "THE HOOK QUESTION"},
        {"start": 6.0, "end": 12.0, "text": "THE STORY BUILDS"},
        {"start": 19.0, "end": 24.0, "text": "SHOCKING TWIST REVEAL"},
    ]

    clip = creator._build_shorts_clip([img1, img2, img3], 26.0, captions, section_acts=section_acts)
    assert clip.duration == 26.0

    # Sample a frame from hook, story, and twist
    hook_frame = clip.get_frame(2.0)
    story_frame = clip.get_frame(10.0)
    twist_frame = clip.get_frame(20.0)

    assert hook_frame.shape == (creator.H, creator.W, 3)
    assert story_frame.shape == (creator.H, creator.W, 3)
    assert twist_frame.shape == (creator.H, creator.W, 3)
