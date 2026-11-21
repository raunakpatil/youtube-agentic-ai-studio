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

    # Verify prompt instructs 20-30 seconds, 40-50 words, and Hook → Story → Twist
    assert "20-30 second" in prompt_text
    assert "40-50 words" in prompt_text
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


def test_shorts_voice_rate_settings():
    from studio import settings
    assert "shorts_voice_rate" in settings._SETTINGS
    assert settings._SETTINGS["shorts_voice_rate"] == ("SHORTS_VOICE_RATE", str)
    assert "SHORTS_VOICE_RATE" in config.USER_SETTINGS
    assert getattr(config, "SHORTS_VOICE_RATE", None) == "+15%"


def test_narrator_shorts_joiner_and_voice_rate(tmp_path):
    from video import narrator

    script = {
        "video_type": "shorts",
        "sections": [
            {"id": 1, "narration": "What if the sun turned blue right now?"},
            {"id": 2, "narration": "The sudden ultraviolet radiation would vaporize our ozone layer within minutes."},
            {"id": 3, "narration": "Earth would freeze in absolute darkness. Subscribe for more cosmic questions."},
        ],
    }

    synthesised_args = []

    async def mock_synth(text, audio_p, srt_p, rate="+0%"):
        synthesised_args.append((text, rate))
        with open(audio_p, "wb") as f:
            f.write(b"fake audio data")
        with open(srt_p, "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,000 --> 00:00:05,000\nWhat if the sun turned blue right now?\n\n")
        return 1

    with patch.object(narrator, "_synthesise", side_effect=mock_synth):
        with patch.object(narrator, "_get_audio_duration_ms", return_value=22000):
            out_dir = str(tmp_path)
            narrator.generate_narration(script, out_dir)

    assert len(synthesised_args) == 1
    synth_text, synth_rate = synthesised_args[0]
    # Verify single space joiner was used instead of "  ...  "
    assert "  ...  " not in synth_text
    assert synth_text == (
        "What if the sun turned blue right now? "
        "The sudden ultraviolet radiation would vaporize our ozone layer within minutes. "
        "Earth would freeze in absolute darkness. Subscribe for more cosmic questions."
    )
    assert synth_rate == "+15%"


def test_creator_retime_audio_and_srt(tmp_path):
    import subprocess
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    audio_path = str(tmp_path / "narration.mp3")
    srt_path = str(tmp_path / "narration.srt")

    # Generate a 35s dummy mp3
    subprocess.run([
        ffmpeg, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=35",
        "-c:a", "libmp3lame", audio_path
    ], check=True, capture_output=True)

    # Write a test SRT up to 35s
    srt_text = (
        "1\n00:00:00,000 --> 00:00:10,000\nHook line here.\n\n"
        "2\n00:00:10,000 --> 00:00:25,000\nStory line here.\n\n"
        "3\n00:00:25,000 --> 00:00:35,000\nTwist line here.\n\n"
    )
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_text)

    final_dur = creator.retime_audio_and_srt(audio_path, srt_path, max_duration=30.0)

    assert final_dur <= 30.0
    assert 28.0 <= final_dur <= 30.0

    # Verify SRT was scaled proportionally
    new_srt = open(srt_path, encoding="utf-8").read()
    assert "00:00:35,000" not in new_srt

