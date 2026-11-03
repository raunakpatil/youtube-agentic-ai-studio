"""Live log: every tab sees every message, streams survive runs, only the pipeline's logs show."""
import json
import logging
import threading

import pytest

import gui
from studio import events as ev, pipeline, runner
from studio.events import EventLog, events, in_run

LOCAL = {"Host": "localhost:7070"}


# ── EventLog ──────────────────────────────────────────────────────────────────

def test_every_reader_gets_every_event():
    log = EventLog()
    log.new_run()
    for i in range(3):
        log.emit("log", f"line {i}")
    start = log.cursor(None)
    tab_a, tab_b = log.wait(start, 0), log.wait(start, 0)
    assert [e["msg"] for e in tab_a] == ["", "line 0", "line 1", "line 2"]
    assert tab_a == tab_b                       # nothing is taken from the other tab


def test_resume_from_last_event_id_and_ignore_ids_from_before_a_restart():
    log = EventLog()
    log.new_run()
    first = log.emit("log", "a")
    log.emit("log", "b")
    assert [e["msg"] for e in log.wait(log.cursor(f"{log.epoch}:{first}"), 0)] == ["b"]
    # an id from an older server process replays the current run instead
    assert [e["kind"] for e in log.wait(log.cursor(f"old0000:{first}"), 0)] == ["start", "log", "log"]


def test_new_run_replaces_the_previous_one():
    log = EventLog()
    log.new_run()
    log.emit("log", "old run")
    log.emit("done")
    log.new_run()
    log.emit("log", "new run")
    assert [e["msg"] for e in log.wait(log.cursor(None), 0)] == ["", "new run"]


def test_wait_times_out_empty_and_wakes_on_emit():
    log = EventLog()
    assert log.wait(log.cursor(None), 0.01) == []
    after = log.cursor(None)
    threading.Timer(0.05, log.emit, args=("log", "late")).start()
    assert [e["msg"] for e in log.wait(after, 2)] == ["late"]


def test_old_events_are_capped():
    log = EventLog(maxlen=5)
    log.new_run()
    for i in range(20):
        log.emit("log", str(i))
    assert [e["msg"] for e in log.wait(log.cursor(None), 0)] == ["15", "16", "17", "18", "19"]


# ── /api/stream ───────────────────────────────────────────────────────────────

def _read(resp, n):
    """The first n SSE events (id + data) from a streaming response."""
    out, buf = [], ""
    for chunk in resp.response:
        buf += chunk.decode() if isinstance(chunk, bytes) else chunk
        while "\n\n" in buf:
            block, buf = buf.split("\n\n", 1)
            fields = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line and not line.startswith(":"))
            if "data" in fields:
                out.append((fields.get("id"), json.loads(fields["data"])))
                if len(out) == n:
                    resp.close()
                    return out
    return out


def test_two_tabs_both_receive_the_whole_run(monkeypatch):
    monkeypatch.setattr(pipeline, "PING_SECS", 0.05)
    events.new_run()
    events.emit("log", "hello", "info")
    events.emit("done")
    tabs = [gui.app.test_client().get("/api/stream", headers=LOCAL, buffered=False) for _ in range(2)]
    a, b = (_read(t, 3) for t in tabs)
    assert [d["kind"] for _, d in a] == ["start", "log", "done"]
    assert [d for _, d in a] == [d for _, d in b]
    assert a[1][1] == {"kind": "log", "msg": "hello", "level": "info"}


def test_stream_stays_open_after_done_and_resumes_with_last_event_id(monkeypatch):
    monkeypatch.setattr(pipeline, "PING_SECS", 0.05)
    events.new_run()
    events.emit("done")
    seen = _read(gui.app.test_client().get("/api/stream", headers=LOCAL, buffered=False), 2)
    last_id = seen[-1][0]
    assert seen[-1][1]["kind"] == "done"

    events.new_run()                            # the next run reaches the same tab
    events.emit("log", "second run")
    resumed = gui.app.test_client().get("/api/stream", buffered=False,
                                        headers={**LOCAL, "Last-Event-ID": last_id})
    assert [d.get("msg") for _, d in _read(resumed, 2)] == ["", "second run"]


# ── logging → browser log ─────────────────────────────────────────────────────

@pytest.fixture
def run_log():
    ev.install()
    events.new_run()
    yield lambda: [(e["level"], e["msg"]) for e in events.wait(events.cursor(None), 0) if e["kind"] == "log"]


def _in_thread(fn, run=False):
    def target():
        if run:
            in_run.set(True)
        fn()
    t = threading.Thread(target=target)
    t.start()
    t.join()


def test_pipeline_thread_logs_reach_the_browser_but_requests_do_not(run_log):
    _in_thread(lambda: logging.getLogger("video.creator").info("rendering"), run=True)
    _in_thread(lambda: logging.getLogger("agents.gemini_client").warning("⚠ from a request"))
    _in_thread(lambda: logging.getLogger("werkzeug").info("GET /api/status"), run=True)
    assert run_log() == [("info", "rendering")]


def test_worker_threads_started_by_the_pipeline_keep_its_context(run_log, monkeypatch):
    from apis import knowledge

    def broken(topic):
        raise RuntimeError("offline")
    broken.__name__ = "wikipedia"
    monkeypatch.setattr(knowledge, "wikipedia", broken)
    monkeypatch.setattr(knowledge, "arxiv", lambda topic: [])
    knowledge.gather_context.cache_clear()
    _in_thread(lambda: knowledge.gather_context("black holes"), run=True)
    knowledge.gather_context.cache_clear()
    assert any(level == "warn" and "wikipedia grounding failed" in msg for level, msg in run_log())


def test_explicit_log_shows_from_any_thread_without_duplicates(run_log):
    _in_thread(lambda: ev.log("Uploaded!", "info"))              # e.g. the upload thread
    _in_thread(lambda: ev.log("Thumbnail refused", "warn"), run=True)
    assert run_log() == [("info", "Uploaded!"), ("warn", "Thumbnail refused")]


def test_run_does_not_touch_sys_stdout(run_log, tmp_path, monkeypatch):
    import sys
    import config
    monkeypatch.setattr(config, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(config, "IMAGES_DIR", str(tmp_path / "images"))
    before = sys.stdout
    seen = []
    t = threading.Thread(target=lambda: (seen.append(sys.stdout), runner.run_pipeline_thread(["video"])))
    t.start(); t.join()
    assert seen == [before] and sys.stdout is before
    kinds = [e["kind"] for e in events.wait(events.cursor(None), 0)]
    assert kinds[-1] == "error"                 # no research data → clean error event
    assert ("error", "ERROR: No research data — run Research step first.") in run_log()


def test_second_run_is_rejected_while_one_is_starting(monkeypatch):
    started = []
    monkeypatch.setattr(pipeline, "run_pipeline_thread", lambda *a: started.append(a))
    monkeypatch.setitem(pipeline.state, "running", False)
    client = gui.app.test_client()
    first = client.post("/api/run", json={"topic": "x", "steps": ["research"]}, headers=LOCAL).get_json()
    second = client.post("/api/run", json={"topic": "y", "steps": ["research"]}, headers=LOCAL).get_json()
    assert first == {"ok": True} and second["ok"] is False
    assert len(started) == 1
    pipeline.state["running"] = False


def test_terminal_still_shows_log_lines(capsys):
    """create_app() puts a handler on the root logger first; terminal output must still work."""
    root = logging.getLogger()
    before_handlers, before_level = list(root.handlers), root.level
    try:
        gui._setup_terminal_logging()
        logging.getLogger("video.creator").info("→ Rendering 1m 0s video…")
        logging.getLogger("werkzeug").info('"GET /api/status HTTP/1.1" 200 -')
        out = capsys.readouterr().out
        assert "→ Rendering 1m 0s video…" in out and "GET /api/status" in out
    finally:
        for h in root.handlers[:]:
            if h not in before_handlers:
                root.removeHandler(h)
        root.setLevel(before_level)
