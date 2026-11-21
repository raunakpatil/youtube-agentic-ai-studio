"""Tests for MoviePy 2 video/audio creation and effects compatibility."""
import os
import tempfile
import numpy as np
import pytest

from video.creator import _watermark_patch, _apply_watermark, _clip_with_audio, _clip_subclip
from video.music import _build_music_clip, mix_music_with_narration

try:
    from moviepy import VideoClip, AudioClip, AudioFileClip, CompositeAudioClip
except ImportError:
    from moviepy.editor import VideoClip, AudioClip, AudioFileClip, CompositeAudioClip


def test_watermark_patch_generation():
    x, y, rgb, alpha = _watermark_patch(1280, 720, text="sample")
    assert rgb.shape[2] == 3
    assert alpha.shape[2] == 1
    assert 0 <= x < 1280
    assert 0 <= y < 720


def test_video_clip_watermark_and_export():
    def make_frame(t):
        return np.zeros((240, 320, 3), dtype=np.uint8)

    clip = VideoClip(make_frame, duration=0.5)
    clip_wm = _apply_watermark(clip, 320, 240, text="sample")
    frame = clip_wm.get_frame(0)
    assert frame.shape == (240, 320, 3)

    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, "test_render.mp4")
        clip_wm.write_videofile(
            out_path,
            fps=10,
            codec="libx264",
            audio=False,
            preset="ultrafast",
            threads=2,
            logger=None,
        )
        assert os.path.exists(out_path)
        assert os.path.getsize(out_path) > 0


def test_audio_clip_effects_and_export():
    def make_audio_frame(t):
        return np.sin(440 * 2 * np.pi * t)

    clip = AudioClip(make_audio_frame, duration=1.0, fps=22050)
    sub = _clip_subclip(clip, 0, 0.5)
    assert abs(sub.duration - 0.5) < 0.05

    # Test effects integration
    try:
        from moviepy.audio.fx import AudioFadeIn, AudioFadeOut, MultiplyVolume
        c_fx = sub.with_effects([MultiplyVolume(0.8), AudioFadeIn(0.1), AudioFadeOut(0.1)])
    except (ImportError, AttributeError):
        c_fx = sub.volumex(0.8).audio_fadein(0.1).audio_fadeout(0.1)

    with tempfile.TemporaryDirectory() as td:
        out_audio = os.path.join(td, "test_audio.mp3")
        CompositeAudioClip([c_fx]).write_audiofile(out_audio, fps=22050, logger=None)
        assert os.path.exists(out_audio)
        assert os.path.getsize(out_audio) > 0
