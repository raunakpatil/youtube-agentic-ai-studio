#!/usr/bin/env python3
"""
YouTube AI Agent — Main Pipeline (Free Edition)
Uses: Gemini 2.5 Flash · Edge TTS · Pexels · MoviePy · Flask · YouTube Data API

Run:  python pipeline.py
"""
import os
import json
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

import config
from agents.researcher   import research_topic
from agents.scriptwriter import write_script
from video.narrator      import generate_narration
from video.stock         import download_images
from video.creator       import create_video
from review.app          import start_review_server
from uploader.youtube    import upload_to_youtube


def banner(text: str):
    print("\n" + "─" * 62)
    print(f"  {text}")
    print("─" * 62)


def run():
    Path(config.OUTPUT_DIR).mkdir(exist_ok=True)
    Path(config.IMAGES_DIR).mkdir(exist_ok=True)

    print("\n🎬  YouTube AI Agent Studio  ·  Video Pipeline\n")

    # ── 1. Research ───────────────────────────────────────────
    banner("1 / 6  ·  Researching trending topic  [Gemini]")
    research = research_topic(config.CHANNEL_DESCRIPTION)
    print(f"\n  ✅  Topic : {research['topic']}")
    print(f"      Title : {research['video_title']}")
    print(f"      Hook  : {research.get('hook_question', '')[:90]}")
    with open(f"{config.OUTPUT_DIR}/research.json", "w") as f:
        json.dump(research, f, indent=2)

    # ── 2. Script ─────────────────────────────────────────────
    banner("2 / 6  ·  Writing script  [Gemini]")
    script = write_script(research)
    print(f"\n  ✅  {len(script['sections'])} sections written")
    for s in script["sections"]:
        words = len(s.get("narration", "").split())
        # Safely grab the title, or default to "Untitled" if the AI forgot it
        title = s.get("title", "Untitled") 
        print(f"      [{s.get('id', 9):02d}] {title:<42} {words:3d} words")
    with open(f"{config.OUTPUT_DIR}/script.json", "w") as f:
        json.dump(script, f, indent=2)

    # ── 3. Stock Images ───────────────────────────────────────
    banner("3 / 6  ·  Downloading stock images  [Pexels]")
    image_map = download_images(script, config.OUTPUT_DIR)
    found = sum(1 for v in image_map.values() if v)
    print(f"\n  ✅  {found}/{len(image_map)} images downloaded")

    # ── 4. Narration ──────────────────────────────────────────
    banner("4 / 6  ·  Generating voiceover  [Edge TTS — free]")
    audio_path = generate_narration(script, config.OUTPUT_DIR)
    print(f"\n  ✅  Audio: {audio_path}")

    # ── 5. Video ──────────────────────────────────────────────
    banner("5 / 6  ·  Building cinematic video  [MoviePy]")
    video_path = create_video(script, audio_path, config.OUTPUT_DIR, image_map)

    # ── 6. Review ─────────────────────────────────────────────
    banner("6 / 6  ·  Human review  [Flask dashboard]")
    print("\n  → Opening review dashboard in your browser…")
    review_data = {
        "research":   research,
        "script":     script,
        "video_path": video_path,
    }
    with open(f"{config.OUTPUT_DIR}/review_data.json", "w") as f:
        json.dump({k: v for k, v in review_data.items() if k != "video_path"},
                  f, indent=2)

    approved = start_review_server(review_data)

    # ── Upload or stop ────────────────────────────────────────
    if approved:
        banner("🚀  Uploading to YouTube")
        url = upload_to_youtube(script, video_path)
        print(f"\n  🎉  Video live: {url}\n")
    else:
        print("\n  ❌  Rejected — pipeline stopped.")
        print("      Tip: edit output/script.json and re-run just the video step.\n")


if __name__ == "__main__":
    run()
