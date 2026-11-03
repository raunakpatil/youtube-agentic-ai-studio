"""The video pipeline, run in a background thread by POST /api/run."""
import json
import logging
import os
import time
from pathlib import Path

import config
from studio.description import build_description
from studio.events import events, in_run, log
from studio.library import archive_project
from studio.state import stage, state, stop_event
from studio.thumbs import make_thumbnail

logger = logging.getLogger(__name__)

def run_pipeline_thread(steps: list, topic_override: str = "", video_type: str = "normal",
                  focus_angle: str = "", use_trends: bool = False):
    in_run.set(True)      # this thread's log records go to the browser log
    state["running"] = True
    state["error"]   = None
    state["stop_requested"] = False
    state["started_at"] = time.time()
    stop_event.clear()

    def _check_stop(after_stage: str):
        """Raise if user clicked Stop."""
        if stop_event.is_set():
            raise InterruptedError(f"Stopped by user after {after_stage}")

    try:
        Path(config.OUTPUT_DIR).mkdir(exist_ok=True)
        Path(config.IMAGES_DIR).mkdir(exist_ok=True)

        from agents.researcher   import research_topic
        from agents.scriptwriter import write_script
        from video.narrator      import generate_narration
        from video.stock         import download_images, section_images
        from video.creator       import create_video
        from video.music         import mix_music_with_narration

        # ── Research ──────────────────────────────────────────
        if "research" in steps:
            stage("research", "running")
            trend_context = None
            if use_trends and not topic_override:
                try:
                    from apis.trends import headlines
                    trend_context = headlines()
                except Exception as e:
                    log(f"Trend Radar unavailable: {e}", "warn")
            research = research_topic(
                channel_description = config.CHANNEL_DESCRIPTION,
                topic_override      = topic_override,
                focus_angle         = focus_angle,
                trend_context       = trend_context,
            )
            state["research"] = research
            state.update(library_id=None, thumb_text=None, thumb_bg_index=0)
            with open(f"{config.OUTPUT_DIR}/research.json", "w", encoding="utf-8") as f:
                json.dump(research, f, indent=2)
            stage("research", "done")
            events.emit("research")
            log(f"Topic: {research['video_title']}")
        else:
            try:
                with open(f"{config.OUTPUT_DIR}/research.json", encoding="utf-8") as f:
                    state["research"] = json.load(f)
            except: pass

        _check_stop("research")
        research = state["research"]
        if not research: raise ValueError("No research data — run Research step first.")

        # ── Script ────────────────────────────────────────────
        if "script" in steps:
            stage("script", "running")
            log(f"Generating {'Shorts' if video_type == 'shorts' else 'normal'} script…")
            script = write_script(research, video_type=video_type)
            state["script"] = script
            with open(f"{config.OUTPUT_DIR}/script.json", "w", encoding="utf-8") as f:
                json.dump(script, f, indent=2)
            stage("script", "done")
            log(f"Script: {len(script['sections'])} sections")
        else:
            try:
                with open(f"{config.OUTPUT_DIR}/script.json", encoding="utf-8") as f:
                    state["script"] = json.load(f)
            except: pass

        _check_stop("script")
        script = state["script"]
        if not script: raise ValueError("No script data — run Script step first.")

        # ── Images ────────────────────────────────────────────
        state["thumb_bg"] = None
        if "images" in steps:
            stage("images", "running")
            image_map = download_images(script, config.OUTPUT_DIR)
            state["image_map"] = image_map
            stage("images", "done")
        else:
            is_shorts = video_type == "shorts" or script.get("video_type") == "shorts"
            image_map = {}
            for s in script.get("sections", []):
                paths = section_images(config.IMAGES_DIR, s["id"])
                image_map[s["id"]] = paths if (paths or is_shorts) else None
            state["image_map"] = image_map

        _check_stop("images")

        # ── Narration ─────────────────────────────────────────
        if "narration" in steps:
            stage("narration", "running")
            audio_path = generate_narration(script, config.OUTPUT_DIR)
            state["audio_path"] = audio_path
            stage("narration", "done")
        else:
            ap = os.path.join(config.OUTPUT_DIR, "narration.mp3")
            state["audio_path"] = ap if os.path.exists(ap) else None

        if not state["audio_path"] or not os.path.exists(state["audio_path"]):
            raise FileNotFoundError("narration.mp3 missing — run Narration step.")

        _check_stop("narration")

        # ── Music  (optional, non-blocking) ───────────────────
        final_audio_path = state["audio_path"]
        if config.MUSIC_ENABLED and "music" in steps:
            log("Mixing background music from library…")
            mixed_path = os.path.join(config.OUTPUT_DIR, "narration_mixed.mp3")
            final_audio_path = mix_music_with_narration(
                narration_path = state["audio_path"],
                output_path    = mixed_path,
                music_volume   = getattr(config, "MUSIC_VOLUME", 0.12),
                library_dir    = getattr(config, "MUSIC_LIBRARY_DIR", ""),
            )
            log("Audio ready (narration + music)")

        _check_stop("music")

        # ── Thumbnail ─────────────────────────────────────────
        log("Generating thumbnail…")
        try:
            image_map_int = {int(k): v for k, v in state["image_map"].items()}
            thumb = make_thumbnail(script, image_map_int, config.OUTPUT_DIR)
            state["thumb_path"] = thumb
            log(f"Thumbnail saved: {thumb}")
        except Exception as e:
            log(f"Thumbnail failed (non-fatal): {e}", "warn")

        _check_stop("thumbnail")

        # ── Video ─────────────────────────────────────────────
        if "video" in steps:
            stage("video", "running")
            image_map_int = {int(k): v for k, v in state["image_map"].items()}
            video_path = create_video(
                script, final_audio_path, config.OUTPUT_DIR, image_map_int,
                video_type=video_type
            )
            state["video_path"] = video_path
            stage("video", "done")
        else:
            vp_short = os.path.join(config.OUTPUT_DIR, "final_short.mp4")
            vp_norm  = os.path.join(config.OUTPUT_DIR, "final_video.mp4")
            vp = vp_short if os.path.exists(vp_short) else vp_norm
            state["video_path"] = vp if os.path.exists(vp) else None

        # ── Build description ─────────────────────────────────
        if state["research"] and state["script"]:
            state["description"] = build_description(
                state["script"], state["research"], video_type=video_type)

        # ── Archive to Library ───────────────────────────────
        if "video" in steps:
            try: archive_project()
            except Exception as e: log(f"Library archive failed (non-fatal): {e}", "warn")

        log("Pipeline complete!", "info")
        events.emit("done")

    except InterruptedError as e:
        log(f"⏹ {e}", "warn")
        for s in state["stages"]:
            if state["stages"][s] == "running":
                state["stages"][s] = "pending"
        events.emit("stopped")

    except Exception as e:
        logger.error("Pipeline failed", exc_info=True, extra={"yaas_event": True})  # terminal only
        state["error"] = str(e)
        for s in state["stages"]:
            if state["stages"][s] == "running":
                state["stages"][s] = "error"
        log(f"ERROR: {e}", "error")
        events.emit("error", str(e))
    finally:
        state["running"] = False
