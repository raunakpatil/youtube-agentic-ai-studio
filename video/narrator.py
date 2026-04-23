"""
Narrator — Microsoft Edge TTS (100% free)
Generates broadcast-quality voiceover + word-level subtitle (SRT) file.
The SRT is used by the Shorts creator to burn in synced captions.

Compatible with all edge-tts versions (6.0 → 7.x).
Uses MoviePy's AudioFileClip for duration — guaranteed to match the video render.
"""
import os
import re
import asyncio
import edge_tts
import config


# ══════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════

def _format_srt_time(ms: float) -> str:
    """Convert milliseconds → SRT timestamp  HH:MM:SS,mmm"""
    ms = max(0, int(ms))
    h  = ms // 3_600_000;  ms %= 3_600_000
    m  = ms // 60_000;     ms %= 60_000
    s  = ms // 1_000;      ms %= 1_000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _get_audio_duration_ms(audio_path: str) -> float:
    """
    Return the exact audio duration in milliseconds using MoviePy's
    AudioFileClip — the same engine the video renderer uses, so the number
    is guaranteed to match what creator.py reports.

    Falls back to a rough file-size estimate only if MoviePy itself fails.
    """
    try:
        from moviepy.editor import AudioFileClip
        clip = AudioFileClip(audio_path)
        dur  = clip.duration          # seconds, same value creator.py gets
        clip.close()
        return dur * 1000
    except Exception as e:
        print(f"   ⚠ AudioFileClip duration failed ({e}); using file-size estimate")

    # Rough fallback: 128 kbps assumption
    try:
        return (os.path.getsize(audio_path) / (128 * 1024 / 8)) * 1000
    except Exception:
        return 60_000


# ══════════════════════════════════════════════════════════════
#  SRT WRITERS
# ══════════════════════════════════════════════════════════════

def _write_srt_blocks(blocks: list[tuple[float, float, str]], srt_path: str) -> int:
    """
    Write a list of (start_ms, end_ms, text) tuples as a valid SRT file.
    Returns the number of cues written.
    """
    with open(srt_path, "w", encoding="utf-8") as f:
        for idx, (start_ms, end_ms, text) in enumerate(blocks, 1):
            f.write(f"{idx}\n")
            f.write(f"{_format_srt_time(start_ms)} --> {_format_srt_time(end_ms)}\n")
            f.write(f"{text}\n")
            f.write("\n")
    return len(blocks)


def _group_word_events(word_events: list, words_per_cue: int = 5) -> list:
    """Group word-boundary events into (start_ms, end_ms, text) caption blocks."""
    blocks = []
    for i in range(0, len(word_events), words_per_cue):
        chunk = word_events[i : i + words_per_cue]
        blocks.append((
            chunk[0]["start_ms"],
            chunk[-1]["end_ms"],
            " ".join(w["word"] for w in chunk),
        ))
    return blocks


def _try_submaker_srt(submaker, srt_path: str) -> int:
    """
    Ask SubMaker to produce SRT content, trying every known method name
    across all edge-tts versions:

      6.1.0–6.1.8 : submaker.generate_subs(words_in_cue=N)  → str
      6.1.9–6.x   : submaker.merge_subs(words_in_cue=N)     → str
      7.x          : str(submaker)  or  submaker.srt         → str

    Returns cue count, or 0 if nothing produces valid SRT content.
    """
    srt_content = None

    # Named methods first (most reliable)
    for method in ("merge_subs", "generate_subs"):
        fn = getattr(submaker, method, None)
        if callable(fn):
            try:
                result = fn(words_in_cue=5)
                if result and "-->" in result:
                    srt_content = result
                    break
            except Exception as e:
                print(f"   → SubMaker.{method}() error: {e}")

    # .srt property (7.x)
    if not srt_content:
        raw = getattr(submaker, "srt", None)
        if isinstance(raw, str) and "-->" in raw:
            srt_content = raw

    # __str__ (some 7.x builds)
    if not srt_content:
        try:
            raw = str(submaker)
            if "-->" in raw:
                srt_content = raw
        except Exception:
            pass

    if not srt_content:
        return 0

    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)
    return srt_content.count(" --> ")


def _build_sentence_srt(text: str, audio_path: str, srt_path: str) -> int:
    """
    Fallback SRT builder using CHARACTER-based proportional timing.

    Why character-based instead of word-based:
      TTS engines speak at roughly constant character rate, not word rate.
      "if" (~100ms) and "internationalization" (~700ms) should not get the
      same time budget. Character count × ms_per_char + inter-word pause
      is a much better model of actual speech duration per word.

    Each word is allocated:
      duration_ms = len(word) * ms_per_char + INTER_WORD_MS

    Where ms_per_char is derived from total_ms / total_weighted_chars so
    that all word durations sum exactly to total_ms.

    Captions are grouped into chunks of up to 6 words. No cue ever ends
    past total_ms — the last cue is pinned to total_ms exactly.
    """
    total_ms  = _get_audio_duration_ms(audio_path)
    sentences = [s.strip() for s in re.split(r'(?<=[.!?…])\s+', text) if s.strip()]
    all_words = [w for s in sentences for w in s.split()]

    if not all_words:
        open(srt_path, "w").close()
        return 0

    # Each gap between words is modelled as 1.5 "equivalent characters"
    INTER_WORD_CHAR_EQ = 1.5
    total_weighted = sum(len(w) for w in all_words) + len(all_words) * INTER_WORD_CHAR_EQ
    ms_per_char    = total_ms / total_weighted

    # Pre-compute cumulative start time for every word
    word_starts = []
    cursor      = 0.0
    for w in all_words:
        word_starts.append(cursor)
        cursor += len(w) * ms_per_char + INTER_WORD_CHAR_EQ * ms_per_char

    blocks     = []
    word_index = 0   # absolute index into all_words / word_starts

    for sentence in sentences:
        s_words = sentence.split()
        # Group sentence words into chunks of up to 6
        for ci in range(0, len(s_words), 6):
            chunk      = s_words[ci : ci + 6]
            chunk_abs  = word_index + ci
            c_start    = word_starts[chunk_abs]
            # End = start of the word AFTER the last word in chunk
            last_abs   = chunk_abs + len(chunk) - 1
            last_word  = all_words[last_abs]
            c_end      = min(
                word_starts[last_abs] + len(last_word) * ms_per_char,
                total_ms,
            )
            if c_start >= total_ms:
                break
            blocks.append((c_start, c_end, " ".join(chunk)))
        word_index += len(s_words)

    # Pin last cue to exact audio end (floating-point safety)
    if blocks:
        blocks[-1] = (blocks[-1][0], total_ms, blocks[-1][2])

    cues       = _write_srt_blocks(blocks, srt_path)
    actual_end = blocks[-1][1] / 1000 if blocks else 0.0
    print(f"   → Sentence-level SRT: {cues} cues, 0.0s → {actual_end:.1f}s "
          f"(audio: {total_ms/1000:.1f}s) — exact match ✓")
    return cues


# ══════════════════════════════════════════════════════════════
#  TTS SYNTHESIS
# ══════════════════════════════════════════════════════════════

async def _synthesise(text: str, audio_path: str, srt_path: str) -> int:
    """
    Stream edge-tts audio + word-boundary events.
    Tries SubMaker → raw WordBoundary events → sentence fallback.
    Returns the number of SRT cues written.
    """
    communicate = edge_tts.Communicate(
        text,
        config.VOICE_ID,
        rate=config.VOICE_RATE,
        pitch=config.VOICE_PITCH,
    )

    # Instantiate SubMaker (may not exist in very old edge-tts)
    try:
        submaker     = edge_tts.SubMaker()
        use_submaker = True
    except Exception:
        submaker     = None
        use_submaker = False

    audio_chunks = []
    word_events  = []   # manual fallback list

    async for event in communicate.stream():
        if event["type"] == "audio":
            audio_chunks.append(event["data"])

        elif event["type"] == "WordBoundary":
            # Feed SubMaker using whichever ingestion method this version has
            if use_submaker and submaker is not None:
                for feed_name in ("feed", "create_sub"):
                    fn = getattr(submaker, feed_name, None)
                    if not callable(fn):
                        continue
                    try:
                        if feed_name == "feed":
                            fn(event)   # 6.1.9+: takes the whole event dict
                        else:
                            fn(         # 6.1.0–6.1.8: takes (offset_tuple, text)
                                (event["offset"], event["duration"]),
                                event["text"],
                            )
                    except Exception:
                        pass
                    break

            # Always collect manually too — used if SubMaker yields nothing
            offset_ms   = event["offset"]   / 10_000   # 100-ns ticks → ms
            duration_ms = event["duration"] / 10_000
            word_events.append({
                "word":     event["text"],
                "start_ms": offset_ms,
                "end_ms":   offset_ms + duration_ms,
            })

    # ── Save audio (must happen before any duration checks) ─────────────────
    with open(audio_path, "wb") as f:
        for chunk in audio_chunks:
            f.write(chunk)

    # ── SRT generation cascade ───────────────────────────────────────────────
    cue_count = 0

    # 1. SubMaker (covers 6.1.x and 7.x)
    if use_submaker and submaker is not None:
        cue_count = _try_submaker_srt(submaker, srt_path)
        if cue_count:
            print(f"   → SubMaker SRT: {cue_count} cues  ✓")

    # 2. Raw WordBoundary events (covers 6.0.x)
    if cue_count == 0 and word_events:
        print(f"   → SubMaker empty; building from {len(word_events)} WordBoundary events…")
        blocks    = _group_word_events(word_events)
        cue_count = _write_srt_blocks(blocks, srt_path)
        if cue_count:
            print(f"   → WordBoundary SRT: {cue_count} cues  ✓")

    # 3. Sentence-level fallback (always works, uses AudioFileClip for duration)
    if cue_count == 0:
        if not word_events:
            # Microsoft periodically disables WordBoundary events server-side.
            # The sentence-level fallback always produces correct timing, but
            # word-synced captions require a voice that still emits events.
            WORD_SYNCED = [
                ("en-US-AndrewNeural", "Andrew (US, Warm male)"),
                ("en-GB-LibbyNeural",  "Libby  (UK, Clear female)"),
            ]
            alternatives = [(v, n) for v, n in WORD_SYNCED if v != config.VOICE_ID]
            print(f"   ⚠ '{config.VOICE_ID}' sent no word-timing data (Microsoft server change).")
            print( "      Captions are sentence-level (timing is correct, sync is approximate).")
            if alternatives:
                print( "      For word-synced captions, switch voice in the GUI or set in config.py:")
                for voice_id, label in alternatives:
                    print(f"        {label:<28}  VOICE_ID = \"{voice_id}\"")
        print("   → Using sentence-level caption fallback (approximate sync)…")
        cue_count = _build_sentence_srt(text, audio_path, srt_path)

    return cue_count


# ══════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════

def generate_narration(script: dict, output_dir: str) -> str:
    """
    Concatenates all section narrations → synthesises MP3 → writes SRT.
    Returns path to the saved audio file.
    """
    parts = []
    for section in script["sections"]:
        narration = section.get("narration", "").strip()
        if not narration:
            continue
        if narration.startswith(("Start with", "Deep explanation", "Open with")):
            continue
        parts.append(narration)

    full_text  = "  ...  ".join(parts)
    audio_path = os.path.join(output_dir, "narration.mp3")
    srt_path   = os.path.join(output_dir, "narration.srt")

    print(f"   → Synthesising {len(full_text.split())} words via Edge TTS…")
    asyncio.run(_synthesise(full_text, audio_path, srt_path))

    # ── Post-run report ──────────────────────────────────────────────────────
    size_kb     = os.path.getsize(audio_path) // 1024
    audio_dur_s = _get_audio_duration_ms(audio_path) / 1000

    if not os.path.exists(srt_path):
        print(f"   ⚠ ERROR: SRT file missing at {srt_path}")
        return audio_path

    content        = open(srt_path, encoding="utf-8").read()
    verified_count = content.count(" --> ")

    # Find the last timestamp in the SRT to measure caption coverage
    timestamps = re.findall(r"--> (\d+:\d+:\d+,\d+)", content)
    if timestamps:
        def _ts_to_ms(ts: str) -> int:
            h, m, rest = ts.split(":")
            s, ms = rest.split(",")
            return int(h) * 3_600_000 + int(m) * 60_000 + int(s) * 1_000 + int(ms)
        cap_end_s = max(_ts_to_ms(ts) for ts in timestamps) / 1000
    else:
        cap_end_s = 0.0

    coverage = (cap_end_s / audio_dur_s * 100) if audio_dur_s > 0 else 0

    print(f"   → Audio : {size_kb} KB  |  {audio_dur_s:.1f}s")
    print(f"   → SRT   : {verified_count} cues  |  covers 0s → {cap_end_s:.1f}s  ({coverage:.0f}%)")

    if coverage < 85:
        print(f"   ⚠ Caption coverage {coverage:.0f}% — captions will disappear before audio ends.")
        print( "      Fix: change VOICE_ID in config.py to  en-GB-RyanNeural")
        print( "      That voice emits proper word-level timing events.")

    return audio_path
