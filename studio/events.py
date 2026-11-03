"""
The live log the browser shows while a video is being made.

Every event (a log line, a stage change, "done"…) gets an increasing id and is
kept for the current run. Each browser tab reads the list on its own, so:
  · two open tabs both see every message (they no longer split one queue),
  · a tab opened mid-run catches up from the start of the run,
  · a dropped connection resumes where it left off: the id goes out as the
    SSE `id:` field and EventSource sends it back as Last-Event-ID.

Log lines come from the standard `logging` module. Only records written by
the pipeline (its thread, and worker threads it hands its context to) reach
the browser; output from other requests stays in the terminal.
"""
import collections
import contextvars
import json
import logging
import threading
import uuid

# Loggers whose messages can appear in the browser log
APP_PACKAGES = ("agents", "apis", "video", "uploader", "studio", "config")

# True inside the pipeline thread. Code that fans work out to worker threads
# passes it on with contextvars.copy_context().run(...).
in_run = contextvars.ContextVar("yaas_in_run", default=False)

_LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "warn": logging.WARNING,
           "warning": logging.WARNING, "error": logging.ERROR}


def _level_name(levelno: int) -> str:
    return "error" if levelno >= logging.ERROR else "warn" if levelno >= logging.WARNING else "info"


class EventLog:
    def __init__(self, maxlen: int = 3000):
        # Changes on every start, so ids remembered from before a restart are ignored
        self.epoch = uuid.uuid4().hex[:8]
        self._cond = threading.Condition()
        self._events = collections.deque(maxlen=maxlen)
        self._next_id = 1
        self._run_start = 1           # id of the first event of the current run

    def new_run(self) -> None:
        """Forget the previous run and announce a new one."""
        with self._cond:
            self._events.clear()
            self._run_start = self._next_id
        self.emit("start")

    def emit(self, kind: str, msg: str = "", level: str | None = None) -> int:
        with self._cond:
            event = {"id": self._next_id, "kind": kind, "msg": msg}
            if level:
                event["level"] = level
            self._events.append(event)
            self._next_id += 1
            self._cond.notify_all()
            return event["id"]

    def cursor(self, last_event_id: str | None) -> int:
        """The id a client has already seen. Missing or from before a restart → replay this run."""
        epoch, _, n = (last_event_id or "").partition(":")
        if epoch == self.epoch and n.isdigit():
            return int(n)
        with self._cond:
            return self._run_start - 1

    def wait(self, after: int, timeout: float) -> list:
        """Events newer than `after`, waiting up to `timeout` seconds for the first one."""
        with self._cond:
            self._cond.wait_for(lambda: self._next_id - 1 > after, timeout)
            return [e for e in self._events if e["id"] > after]

    def sse(self, event: dict) -> str:
        data = json.dumps({k: v for k, v in event.items() if k != "id"})
        return f"id: {self.epoch}:{event['id']}\ndata: {data}\n\n"


events = EventLog()


class RunLogHandler(logging.Handler):
    """Sends the pipeline's log records to the browser log."""

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(record, "yaas_event", False):       # already sent by log() below
            return
        if not in_run.get() or record.name.split(".")[0] not in APP_PACKAGES:
            return
        try:
            events.emit("log", record.getMessage(), _level_name(record.levelno))
        except Exception:
            self.handleError(record)


_handler = None


def install() -> None:
    """Route the app's log records to the browser log (idempotent)."""
    global _handler
    if _handler is None:
        _handler = RunLogHandler()
        logging.getLogger().addHandler(_handler)
    for name in APP_PACKAGES:
        lg = logging.getLogger(name)
        if lg.level == logging.NOTSET:
            lg.setLevel(logging.INFO)


_studio_log = logging.getLogger("studio")


def log(msg: str, level: str = "info") -> None:
    """Show a message in the browser log (from any thread) and in the terminal."""
    level = "warn" if level == "warning" else level
    events.emit("log", msg, level)
    _studio_log.log(_LEVELS.get(level, logging.INFO), msg, extra={"yaas_event": True})
