"""
YAAS — youtube-agentic-ai-studio · Desktop GUI
Run:  python gui.py
Open: http://localhost:7070

One page controls everything: dashboard, generate, review, library, upload.
The app itself lives in the studio/ package; this file only starts it.

  python gui.py --import-settings old_config.py
      carry over settings an older version saved into config.py
"""
import os
import sys
import threading

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.chdir(ROOT)   # relative paths (output/, token file) resolve the same from anywhere

from studio import create_app  # noqa: E402  (needs sys.path above)

app = create_app()


if __name__ == "__main__":
    import webbrowser
    if len(sys.argv) == 3 and sys.argv[1] == "--import-settings":
        from studio.settings import import_settings
        import_settings(sys.argv[2])
        sys.exit(0)
    port = int(os.getenv("STUDIO_PORT", 7070))
    print("\n🎬  YAAS — youtube-agentic-ai-studio")
    print(f"   Opening at  http://localhost:{port}\n")
    if os.getenv("STUDIO_NO_BROWSER") != "1":
        threading.Timer(1.4, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True, use_reloader=False)
