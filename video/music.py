"""
Music Manager — Local Library
==============================
Picks tracks from the  music library/  folder, concatenates them (looping
from the start of the playlist if the video is longer than all tracks
combined), trims to EXACTLY the video duration, then mixes with narration.

  • No network calls, no procedural synthesis, no API keys.
  • Drop any MP3/WAV/OGG into  music library/  and it will be used.
  • Tracks are shuffled randomly each run for variety.
  • If the library is empty the pipeline continues narration-only.

Public API
----------
  mix_music_with_narration(narration_path, output_path, music_volume) -> str
"""

import os
import math
import random

SUPPORTED_EXTENSIONS = (".mp3", ".wav", ".ogg", ".m4a", ".flac")


# ══════════════════════════════════════════════════════════════
#  LIBRARY SCANNER
# ══════════════════════════════════════════════════════════════

def _get_library_tracks(library_dir: str) -> list[str]:
    """
    Return a shuffled list of absolute paths to every supported audio file
    in library_dir.  Returns [] if the folder doesn't exist or is empty.
    """
    if not library_dir or not os.path.isdir(library_dir):
        print(f"   ⚠ Music library not found: {library_dir!r}")
        return []

    tracks = [
        os.path.join(library_dir, f)
        for f in os.listdir(library_dir)
        if os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS
    ]

    if not tracks:
        print(f"   ⚠ Music library is empty — add MP3/WAV files to: {library_dir}")
        return []

    random.shuffle(tracks)
    print(f"   → Music library: {len(tracks)} track(s) found, shuffled")
    return tracks


# ══════════════════════════════════════════════════════════════
#  TRACK ASSEMBLER  — loop tracks until we have enough duration
# ══════════════════════════════════════════════════════════════

def _build_music_clip(tracks: list[str], target_duration: float):
    """
    Load tracks one-by-one, concatenating until we have at least
    target_duration seconds of audio.  If we exhaust the playlist we
    restart from the beginning (loop), giving seamless infinite playback.

    Returns a MoviePy AudioClip trimmed to exactly target_duration seconds.
    Raises RuntimeError if no tracks can be loaded.
    """
    from moviepy.editor import AudioFileClip, concatenate_audioclips

    segments   = []
    total_so_far = 0.0
    track_index  = 0
    n_tracks     = len(tracks)
    loops        = 0

    while total_so_far < target_duration:
        path = tracks[track_index % n_tracks]
        if track_index > 0 and (track_index % n_tracks) == 0:
            loops += 1

        try:
            clip = AudioFileClip(path)
            needed = target_duration - total_so_far

            if clip.duration <= needed:
                segments.append(clip)
                total_so_far += clip.duration
                print(f"      + {os.path.basename(path)}  ({clip.duration:.1f}s)")
            else:
                # This track alone covers the remainder — trim it
                segments.append(clip.subclip(0, needed))
                total_so_far += needed
                print(f"      + {os.path.basename(path)}  (trimmed to {needed:.1f}s)")
                break

        except Exception as e:
            print(f"      ⚠ Could not load {os.path.basename(path)}: {e}")

        track_index += 1

        # Safety: if we've looped the whole library 10× something is wrong
        if loops >= 10:
            print("   ⚠ Looped library 10× — giving up")
            break

    if not segments:
        raise RuntimeError("No music tracks could be loaded from the library.")

    if loops > 0:
        print(f"   → Playlist looped {loops}× to fill {target_duration:.1f}s")

    music = concatenate_audioclips(segments)
    # Guarantee exact length (floating-point rounding can drift by a few ms)
    return music.subclip(0, min(music.duration, target_duration))


# ══════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════

def mix_music_with_narration(narration_path: str,
                              output_path: str,
                              music_volume: float = 0.12,
                              library_dir: str = "") -> str:
    """
    Mix background music from the local library under the narration audio.

    Parameters
    ----------
    narration_path : path to the narration MP3 produced by narrator.py
    output_path    : where to write the mixed MP3
    music_volume   : 0.0–1.0  (0.12 = 12% — subtle; 0.25 = noticeable)
    library_dir    : absolute path to the  music library/  folder

    Returns
    -------
    output_path if mixing succeeded, narration_path if it failed (so the
    pipeline always has a valid audio file to use).
    """
    import shutil
    from moviepy.editor import AudioFileClip, CompositeAudioClip

    # ── Load narration ───────────────────────────────────────
    narr          = AudioFileClip(narration_path)
    target_dur    = narr.duration

    # ── Scan library ─────────────────────────────────────────
    tracks = _get_library_tracks(library_dir)
    if not tracks:
        print("   → No music tracks available — using narration only")
        narr.close()
        shutil.copy2(narration_path, output_path)
        return output_path

    # ── Build music bed ──────────────────────────────────────
    print(f"   → Building {target_dur:.1f}s music bed…")
    try:
        music = _build_music_clip(tracks, target_dur)
    except RuntimeError as e:
        print(f"   ⚠ Music build failed ({e}) — narration only")
        narr.close()
        shutil.copy2(narration_path, output_path)
        return output_path

    # ── Apply volume + fades ─────────────────────────────────
    fade_in  = min(3.0, target_dur * 0.05)
    fade_out = min(4.0, target_dur * 0.08)
    music    = (music
                .volumex(music_volume)
                .audio_fadein(fade_in)
                .audio_fadeout(fade_out))

    # ── Composite and write ──────────────────────────────────
    try:
        CompositeAudioClip([narr, music]).write_audiofile(
            output_path, fps=44100, verbose=False, logger=None,
        )
        narr.close()
        music.close()
        size_kb = os.path.getsize(output_path) // 1024
        print(f"   → Mixed audio: {size_kb} KB  "
              f"(narration + music @ {int(music_volume * 100)}% vol, "
              f"{target_dur:.1f}s)")
        return output_path

    except Exception as e:
        print(f"   ⚠ Mix write failed ({e}) — narration only")
        try:
            narr.close()
            music.close()
        except Exception:
            pass
        shutil.copy2(narration_path, output_path)
        return output_path
