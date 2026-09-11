"""``pat plane serve``: a loopback HTTP server that runs the typed actions as ``pat`` children.

Security shape, in order: the socket binds 127.0.0.1 only; every request except the page itself
carries the per-start token in a header (the page embeds it, the URL printed at start carries it
once as a fragment); ``Host`` and ``Origin`` must be loopback; each action is one child process
``python -m plutonium_agent_toolkit <argv>`` with validated arguments and a deadline; at most one
job runs at a time and every other request is answered immediately. The server keeps a bounded
list of runs in memory and mirrors each to ``<jobs>/plane-runs/<run id>.json``; jobs write their
own receipts under ``<jobs>/<action>-<n>``. Nothing here reads the bearer token: agent actions
are ``pat agent`` children, which load it from the toolkit configuration themselves.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import signal
import subprocess
import sys
import socket
import threading
import time
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import __version__
from ..core import platform
from ..core.envelope import now
from ..core.errors import BUSY, INPUT_INVALID, INPUT_LIMIT, INPUT_MISSING, OUTPUT_EXISTS, Failure
from ..core.jobs import REPARSE_POINT
from ..dev import compositions, projects
from .actions import BY_ID, argv_for, table

STATIC = Path(__file__).with_name("static")
MAX_BODY = 1024 * 1024
MAX_RUNS = 200
MAX_OUTPUT = 64 * 1024 * 1024   # the child's stdout is parsed whole up to this; beyond it the run keeps a head and no result
MAX_HEAD = 4000
MAX_RECEIPT = 256 * 1024     # a receipt.json larger than this is listed as unreadable, not parsed
MAX_JOB_ROWS = 512           # newest receipts listed per request
MAX_CONNECTIONS = 32         # concurrent connections; beyond that a 503 is answered at once
CONNECTION_TIMEOUT = 30.0    # seconds an idle or half-sent request may hold a connection
REFUSE_DRAIN_SECONDS = 0.5   # total time an over-capacity client gets for an orderly close, off the accept thread
MAX_STDERR = 1024 * 1024     # the child's stderr is kept up to this
MAX_LIBRARY_ROOTS = 16
MAX_SECONDS = 24 * 3600
MAX_CATALOG_ROWS = 2000      # declarations and compositions across every root, per request
MAX_PACKAGES = 512           # loose mod.ff files listed per root for module declare
MAX_DIRECTORIES = 4096       # directories walked per root
STOP_GRACE = 10.0            # seconds a child gets to stop cleanly at shutdown
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}\Z")


def _reject_constant(name: str):
    raise ValueError(f"non-finite JSON constant {name}")


def strict_loads(text):
    """JSON without NaN or Infinity: what the page and any strict client can read back."""
    return json.loads(text, parse_constant=_reject_constant)


def _loopback(value: str | None) -> bool:
    """``Host`` (host[:port]) or ``Origin`` (scheme://host[:port]) names this machine."""
    if not value or len(value) > 256:
        return False
    try:
        host = urllib.parse.urlsplit(value if "://" in value else "//" + value).hostname
    except ValueError:
        return False
    return host in ("127.0.0.1", "localhost", "::1")


def child_env() -> dict:
    """The child imports the same toolkit this server runs from, installed or from a source tree."""
    env = dict(os.environ)
    package_parent = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = package_parent + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def _group_flags() -> dict:
    """The child leads its own process group so a stop reaches it and what it started."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


class _Reader(threading.Thread):
    """Drains one binary pipe into a bounded buffer; past the bound (in bytes) it keeps counting and
    drops what follows. ``text()`` decodes what was kept."""

    def __init__(self, pipe, limit: int):
        super().__init__(daemon=True)
        self.pipe, self.limit = pipe, limit
        self.chunks: list[bytes] = []
        self.size = 0
        self.overflow = False
        self.start()

    def run(self) -> None:
        try:
            while True:
                chunk = self.pipe.read(65536)
                if not chunk:
                    break
                self.size += len(chunk)
                if self.size <= self.limit:
                    self.chunks.append(chunk)
                else:
                    if not self.overflow:
                        self.chunks.append(chunk[: max(0, self.limit - (self.size - len(chunk)))])
                    self.overflow = True
        except (OSError, ValueError):
            pass
        finally:
            try:
                self.pipe.close()
            except OSError:
                pass

    def text(self) -> str:
        return b"".join(self.chunks).decode("utf-8", errors="replace")


def _drain(process: subprocess.Popen, timeout: float, jobs: Path) -> tuple[str, str, bool, int]:
    """Read both pipes with bounded buffers until the child exits or the deadline passes. A child
    that exceeds the stdout bound is stopped rather than allowed to fill memory. Returns the
    texts, whether stdout overflowed, and how many stdout characters the child wrote in total."""
    out, err = _Reader(process.stdout, MAX_OUTPUT), _Reader(process.stderr, MAX_STDERR)
    deadline = time.monotonic() + timeout
    while process.poll() is None:
        if out.overflow:
            _stop_process(process, STOP_GRACE, None)
            break
        if time.monotonic() >= deadline:
            raise subprocess.TimeoutExpired(process.args, timeout, stderr=err.text())
        time.sleep(0.05)
    out.join(STOP_GRACE)
    err.join(STOP_GRACE)
    return out.text(), err.text(), out.overflow, out.size


def _remove_prompts(run: dict) -> None:
    """A dispatched prompt lives on disk only while its child runs; the argv keeps the file name."""
    for index, item in enumerate(run["argv"]):
        if index and run["argv"][index - 1] == "--prompt" and item.startswith("@"):
            try:
                Path(item[1:]).unlink()
            except OSError:
                pass


class _Job:
    """A Windows Job Object handle that is terminated and closed exactly once.

    The thread running a child and whoever stops it both hold this handle, so both reach for it
    when the child ends. Closing a Windows handle twice is not a harmless no-op: the value is
    recycled, so the second close can destroy whatever kernel object took it over in the
    meantime -- a thread's semaphore, say, which ends the interpreter rather than this run."""

    def __init__(self, handle, terminate) -> None:
        self.handle = handle
        self._terminate = terminate
        self._lock = threading.Lock()
        self._closed = False

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._terminate(self.handle)


def _job_for(process: subprocess.Popen):
    """On Windows, a Job Object (kill on close) holding the child and everything it starts."""
    if os.name != "nt":
        return None
    from ..core import _winjob

    handle = None
    try:
        handle = _winjob.create_job()
        _winjob.assign(handle, process)
        return _Job(handle, _winjob.terminate)
    except Failure:
        if handle is not None:
            _winjob.terminate(handle)  # created but never assigned: close it here or it leaks
        return None


def _close_job(job) -> None:
    if job is not None:
        job.close()


def _stop_process(process: subprocess.Popen, grace: float, job=None) -> None:
    """Interrupt the child so it writes its cancelled receipt and stops its backends, then kill the
    whole tree: the process group on POSIX, the Job Object on Windows."""
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(process.pid, signal.SIGINT)
    except (ProcessLookupError, PermissionError, OSError, ValueError):
        pass
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass
    if process.poll() is None:
        try:
            if os.name == "nt":
                if job is not None:
                    _close_job(job)
                    job = None
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            pass
    if os.name == "nt" and job is not None:
        _close_job(job)


class Plane:
    """State shared by the handler threads: roots, token, runs, the single-job lock."""

    def __init__(self, library: list[Path], jobs: Path):
        self.library = [Path(p).resolve() for p in library]
        self.jobs = Path(jobs).resolve()
        self.token = secrets.token_urlsafe(32)
        self.started = now()
        self.runs: list[dict] = []
        self.lock = threading.Lock()
        self.job_lock = threading.Lock()
        self.counter = 0
        self.active: tuple | None = None   # (process, windows job handle or None) while a child runs
        self.settled = threading.Event()   # set once the last run's record is written
        self.settled.set()
        self.stopping = False
        self.stop_requested = False
        self.stopped_runs: set = set()   # runs a caller stopped on purpose: their record says stopped, not failed
        self.prompt_dir = jobs / "plane-prompts"
        (jobs / "plane-runs").mkdir(parents=True, exist_ok=True)
        self.platform = platform.describe()

    # ----- library ---------------------------------------------------------------------
    def catalog(self) -> dict:
        """Declarations, compositions, seed manifests and loose packages under the library roots, read as
        files. Bounded per root (directories, packages) and across roots (rows); a bound reached says so."""
        roots = []
        rows = 0
        truncated = False
        for index, root in enumerate(self.library):
            modules, compositions, packages = [], [], []
            count = 0
            root_truncated = False
            for directory, dirs, files in os.walk(root, followlinks=False):
                dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not (Path(directory) / d).is_symlink())
                count += 1
                if count > MAX_DIRECTORIES or rows >= MAX_CATALOG_ROWS:
                    root_truncated = truncated = True
                    break
                here = Path(directory)
                rel = here.relative_to(root).as_posix()
                if "module.json" in files and not (here / "module.json").is_symlink():
                    modules.append(_summary(here / "module.json", rel, "module"))
                    rows += 1
                if "composition.json" in files and not (here / "composition.json").is_symlink():
                    compositions.append(_summary(here / "composition.json", rel, "composition"))
                    rows += 1
                if "mod.ff" in files and not (here / "mod.ff").is_symlink():
                    if len(packages) < MAX_PACKAGES:
                        packages.append((here / "mod.ff").relative_to(root).as_posix())
                    else:
                        root_truncated = truncated = True
            roots.append({"index": index, "root": str(root), "modules": modules, "compositions": compositions,
                          "packages": packages, "truncated": root_truncated})
        return {"roots": roots, "jobs": str(self.jobs), "truncated": truncated,
                "bounds": {"rows": MAX_CATALOG_ROWS, "directories_per_root": MAX_DIRECTORIES, "packages_per_root": MAX_PACKAGES}}

    def job_index(self) -> dict:
        """Every receipt.json under the jobs directory, one row each, newest first."""
        rows = []
        if self.jobs.is_dir():
            for child in sorted(self.jobs.iterdir()):
                receipt = child / "receipt.json"
                if child.is_symlink() or not child.is_dir() or receipt.is_symlink() or not receipt.is_file():
                    continue
                try:
                    if receipt.stat().st_size > MAX_RECEIPT:
                        raise OSError("receipt larger than the bound")
                    data = strict_loads(receipt.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    rows.append({"directory": child.name, "status": "unreadable"})
                    continue
                if not isinstance(data, dict):
                    continue
                result = data.get("result") if isinstance(data.get("result"), dict) else {}
                error = data.get("error")
                row = {"directory": child.name, "command": data.get("command"), "status": data.get("status"),
                       "started": data.get("started"), "finished": data.get("finished"), "job_id": data.get("job_id"),
                       "mod_ff": result.get("mod_ff"), "name": result.get("name"),
                       "error": error.get("message") if isinstance(error, dict) else (str(error)[:200] if error else None)}
                fetched = result.get("module_dir")
                if data.get("command") == "module fetch" and isinstance(fetched, str) and result.get("kind") in ("module", "composition"):
                    # A fetched snapshot's declaration or composition is selectable from the jobs root.
                    target = Path(fetched) / (result["kind"] + ".json")
                    try:
                        if target.is_file() and not target.is_symlink() and target.resolve().is_relative_to(self.jobs):
                            row[result["kind"]] = target.resolve().relative_to(self.jobs).as_posix()
                    except OSError:
                        pass
                rows.append(row)
        rows.sort(key=lambda r: r.get("started") or "", reverse=True)
        return {"jobs": str(self.jobs), "runs": rows[:MAX_JOB_ROWS], "truncated": len(rows) > MAX_JOB_ROWS}

    # ----- runs ------------------------------------------------------------------------
    def _record(self, run: dict) -> None:
        with self.lock:
            existing = next((i for i, r in enumerate(self.runs) if r["run_id"] == run["run_id"]), None)
            if existing is None:
                self.runs.insert(0, run)
                del self.runs[MAX_RUNS:]
            else:
                self.runs[existing] = run
        path = self.jobs / "plane-runs" / f"{run['run_id']}.json"
        tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        tmp.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)

    def start(self, action_id: str, args: dict, confirmed: bool) -> dict:
        action = BY_ID.get(action_id)
        if action is None:
            raise Failure(INPUT_INVALID, f"Unknown action {action_id!r}", "GET /api/actions lists them")
        row = next(r for r in table(self.platform) if r["id"] == action_id)
        if not row["available_here"]:
            raise Failure("unsupported_platform" if row["requires_windows"] else "not_implemented",
                          f"{action.route} is not available on this host ({row['status']}"
                          + (", requires native Windows" if row["requires_windows"] else "") + ")")
        if action.confirm and confirmed is not True:
            raise Failure(INPUT_INVALID, f"{action.id} changes state; send confirmed: true after the person confirmed it")
        if self.stopping:
            raise Failure(BUSY, "The plane is shutting down; nothing was started")
        # The single-run lock is taken before any argument touches the disk, so a busy request
        # leaves nothing behind; every failure below releases it.
        if not self.job_lock.acquire(blocking=False):
            raise Failure(BUSY, "Another action is still running; the plane runs one at a time", "Poll /api/runs and retry after it finishes")
        run = None
        try:
            self.settled.clear()
            argv = argv_for(action, args, self.library, self.jobs, self.prompt_dir)
            with self.lock:
                self.counter += 1
                number = self.counter
            output = None
            if action.job:
                output = self.jobs / f"{action.id}-{number:04d}"
                if output.exists() or output.is_symlink():
                    raise Failure(OUTPUT_EXISTS, f"{output} already exists; choose another jobs directory")
                argv += ["--output", str(output)]
            argv.append("--json")
            run = {"run_id": uuid.uuid4().hex, "number": number, "action": action.id, "route": action.route, "argv": argv,
                   "output": str(output) if output else None, "status": "running", "started": now(), "finished": None,
                   "exit_code": None, "result": None}
            self._record(run)
            threading.Thread(target=self._execute, args=(run, action.timeout), daemon=True).start()
        except Failure:
            self.job_lock.release()
            self.settled.set()
            raise
        except (OSError, RuntimeError) as exc:
            if run is not None:
                _remove_prompts(run)
                with self.lock:
                    self.runs = [r for r in self.runs if r["run_id"] != run["run_id"]]
            self.job_lock.release()
            self.settled.set()
            raise Failure("operation_failed", f"Could not start the run: {exc}") from exc
        return {k: v for k, v in run.items() if k != "result"}

    def _execute(self, run: dict, timeout: int) -> None:
        job = None
        try:
            # Spawn under the state lock so shutdown either sees the child (and stops it) or is seen
            # here first (and nothing is spawned).
            with self.lock:
                withdrawn = run["run_id"] in self.stopped_runs
                self.stopped_runs.discard(run["run_id"])
                if self.stopping or withdrawn:
                    run.update(status="stopped", exit_code=None, finished=now(), result=None,
                               stderr_head=("the run was stopped before the child started" if withdrawn
                                            else "the plane stopped before the child started"))
                    return
                try:
                    process = subprocess.Popen([sys.executable, "-m", "plutonium_agent_toolkit", *run["argv"]],
                                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(self.jobs),
                                               stdin=subprocess.DEVNULL, env=child_env(), **_group_flags())
                except OSError as exc:
                    run.update(status="failed", exit_code=127, finished=now(), result=None, stderr_head=f"could not start: {exc}")
                    return
                job = _job_for(process)
                self.active = (process, job, run["run_id"])
            try:
                stdout, stderr, overflow, stdout_size = _drain(process, timeout, self.jobs)
                stopped = False
            except subprocess.TimeoutExpired as exc:
                _stop_process(process, STOP_GRACE, job)
                run.update(status="timeout", exit_code=process.returncode, finished=now(), result=None,
                           stderr_head=f"exceeded {timeout} seconds and was stopped; " + str(exc.stderr or "")[:2000])
                return
            finally:
                with self.lock:
                    self.active = None
                    # Taken, not read: the set holds a run only between the stop and this record, so
                    # a server that runs for weeks does not grow one entry per cancelled action.
                    withdrawn = run["run_id"] in self.stopped_runs
                    self.stopped_runs.discard(run["run_id"])
                    stopped = self.stopping or withdrawn
                _close_job(job)  # on Windows this also ends anything the child left behind
            if overflow:
                _stop_process(process, STOP_GRACE, None)
            payload = None
            if not overflow:
                try:
                    payload = strict_loads(stdout) if stdout.strip() else None
                except ValueError:
                    payload = None
            run.update(status="stopped" if withdrawn or (stopped and process.returncode != 0) else "finished", exit_code=process.returncode,
                       finished=now(), result=payload, stdout_head=None if payload is not None else stdout[:MAX_HEAD],
                       stdout_bytes=stdout_size, output_overflow=overflow, stderr_head=(stderr or "")[:MAX_HEAD])
        finally:
            _remove_prompts(run)
            # The lock goes first: a client that reads the finished record may start the next run at
            # once. The record follows, and settled tells shutdown the run is fully written.
            self.job_lock.release()
            try:
                self._record(run)
            except OSError as exc:
                print(f"warning: run record could not be saved ({exc})", file=sys.stderr)
            finally:
                self.settled.set()

    def stop_run(self, run_id: str, grace: float = STOP_GRACE) -> bool:
        """Stop one run's child and wait for its record; True when that run was the one running.

        Unlike ``shutdown`` this does not close the plane: a caller that cancels one action (an MCP
        client withdrawing a request, say) expects the next one to start normally. A stop that
        lands between ``start`` returning and the worker spawning still takes effect: the worker
        sees the id under the same lock and never spawns."""
        with self.lock:
            active = self.active if self.active is not None and self.active[2] == run_id else None
            # Started but not registered yet: the worker takes this lock before it spawns, so
            # leaving the id here means it either never spawns or spawns and is stopped below.
            starting = active is None and not self.settled.is_set()
            if active is not None or starting:
                self.stopped_runs.add(run_id)
        if active is None:
            if not starting:
                return False        # already finished and recorded; there is nothing to stop
            self.settled.wait(grace + 5)
            return True
        _stop_process(active[0], grace, active[1])
        self.settled.wait(grace + 5)
        return True

    def shutdown(self, grace: float = STOP_GRACE) -> dict:
        """Refuse new runs, stop the running child (interrupt, then kill) and wait for its record."""
        with self.lock:
            self.stopping = True
            active = self.active
        if active is not None:
            _stop_process(active[0], grace, active[1])
        self.settled.wait(grace + 5)
        removed = 0
        if self.prompt_dir.is_dir():
            for leftover in self.prompt_dir.glob("prompt-*.txt"):
                try:
                    leftover.unlink()
                    removed += 1
                except OSError:
                    pass
        return {"child_stopped": active is not None, "still_running": self.job_lock.locked(), "prompts_removed": removed}

    def run_rows(self) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.runs]


def _summary(path: Path, rel: str, kind: str) -> dict:
    try:
        raw = path.read_bytes()
        if len(raw) > 256 * 1024:
            return {"path": rel, "kind": kind, "error": "declaration larger than 256 KiB"}
        data = strict_loads(raw)
    except (OSError, ValueError):
        return {"path": rel, "kind": kind, "error": "unreadable"}
    if not isinstance(data, dict):
        return {"path": rel, "kind": kind, "error": "not an object"}
    keys = ("id", "name", "version", "title", "category", "kind", "tags", "bases", "maps", "base", "map", "dependencies",
            "conflicts", "distribution", "menu_route", "modules")
    row = {"path": rel, "kind": kind, **{k: data[k] for k in keys if k in data}}
    # The shape the format requires before anything else is read; full validation is module plan's.
    if data.get("schema") != 1:
        row["error"] = "schema is not 1"
    elif kind == "module" and (not isinstance(data.get("id"), str) or not compositions.ID.match(data["id"])
                               or not isinstance(data.get("version"), str) or not compositions.VERSION.match(data["version"])
                               or ("recipe" in data) == ("seed" in data)):
        row["error"] = "not a module declaration (id, version and exactly one of recipe or seed are required)"
    elif kind == "composition" and (not isinstance(data.get("name"), str) or not projects.NAME.match(data["name"])
                                    or not isinstance(data.get("modules"), list) or not data["modules"]):
        row["error"] = "not a composition (name and a non-empty modules list are required)"
    row["payload"] = "seed" if "seed" in data else "recipe" if "recipe" in data else None
    if kind == "module" and "seed" in data:
        manifest = path.parent / str(data["seed"])
        if manifest.is_file() and not manifest.is_symlink():
            try:
                if manifest.stat().st_size > 4 * 1024 * 1024:
                    raise OSError("seed manifest larger than the bound")
                seed = strict_loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                seed = None
            if not isinstance(seed, dict):
                row["package_present"] = None
                row["seed_error"] = "seed manifest is not a JSON object"
            else:
                files = seed.get("files") or {}
                row["package_present"] = all((path.parent / n).is_file() for n in files) if isinstance(files, dict) and files else None
                row["embedded"] = len(seed.get("embedded") or []) if isinstance(seed.get("embedded"), list) else 0
                row["roots"] = len(seed.get("roots") or []) if isinstance(seed.get("roots"), list) else 0
    return row


# ----- HTTP ---------------------------------------------------------------------------------

class PlaneServer(ThreadingHTTPServer):
    """Loopback server with a bound on concurrent connections: past it a 503 is answered at once
    and the connection closed, so abandoned or half-sent requests cannot hold every worker."""
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address, handler, max_connections: int = MAX_CONNECTIONS):
        super().__init__(address, handler)
        self._slots = threading.BoundedSemaphore(max_connections)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            # Answer at once and hand the orderly close to a short-lived thread: the accept loop
            # never waits on an over-capacity client, and the drain is bounded so a client that
            # trickles bytes cannot hold that thread either.
            threading.Thread(target=self._refuse, args=(request,), daemon=True).start()
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def _refuse(self, request) -> None:
        """Send the 503, then close in order. Closing a socket that still holds unread request
        bytes makes the kernel send a reset, and on Windows the client then sees the connection
        aborted instead of the reply; so stop sending and drain, bounded by a total deadline."""
        try:
            request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            request.shutdown(socket.SHUT_WR)
            deadline = time.monotonic() + REFUSE_DRAIN_SECONDS
            request.settimeout(0.1)
            while time.monotonic() < deadline:
                if not request.recv(4096):
                    break
        except OSError:
            pass
        finally:
            self.shutdown_request(request)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def make_handler(plane: Plane):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"pat-plane/{__version__}"
        timeout = CONNECTION_TIMEOUT  # socket timeout: an incomplete request line or header gives up

        def log_message(self, *args):  # the receipts are the log
            pass

        # ----- helpers -----
        def _send(self, status: int, content_type: str, data: bytes, extra: dict | None = None) -> None:
            """One response; a peer that closed early is not an error worth a traceback."""
            try:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                for key, value in (extra or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(data)
            except OSError:
                self.close_connection = True

        def _json(self, status: int, body: dict) -> None:
            self._send(status, "application/json; charset=utf-8", json.dumps(body, indent=2, ensure_ascii=True, allow_nan=False).encode("ascii"))

        def _fail(self, status: int, exc: Failure) -> None:
            self._json(status, exc.to_dict())

        def _guard(self, need_token: bool = True) -> bool:
            if not _loopback(self.headers.get("Host")):
                self._fail(403, Failure(INPUT_INVALID, "Host header is not loopback"))
                return False
            origin = self.headers.get("Origin")
            if origin and not _loopback(origin):
                self._fail(403, Failure(INPUT_INVALID, "Origin is not loopback"))
                return False
            if need_token and not secrets.compare_digest(self.headers.get("X-Plane-Token", ""), plane.token):
                self._fail(401, Failure("config_invalid", "Missing or wrong plane token", "Open the URL printed by pat plane serve"))
                return False
            return True

        def _body(self) -> dict:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError as exc:
                raise Failure(INPUT_INVALID, "Content-Length is not a number") from exc
            if length < 0 or length > MAX_BODY:
                raise Failure(INPUT_LIMIT, f"Request body is 0 to {MAX_BODY} bytes")
            raw = self.rfile.read(length) if length else b""
            try:
                value = strict_loads(raw or b"{}")
            except ValueError as exc:
                raise Failure(INPUT_INVALID, "Request body is not JSON") from exc
            if not isinstance(value, dict):
                raise Failure(INPUT_INVALID, "Request body is a JSON object")
            return value

        # ----- routes -----
        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                if not self._guard(need_token=False):
                    return
                self._send(200, "text/html; charset=utf-8", (STATIC / "index.html").read_bytes(),
                           {"Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'",
                            "Referrer-Policy": "no-referrer"})
                return
            if path == "/favicon.ico":
                self._send(204, "image/x-icon", b"")
                return
            if path in ("/plane.js", "/plane.css"):
                if not self._guard(need_token=False):
                    return
                self._send(200, "text/javascript; charset=utf-8" if path.endswith(".js") else "text/css; charset=utf-8",
                           (STATIC / path.lstrip("/")).read_bytes())
                return
            if not self._guard():
                return
            try:
                if path == "/api/state":
                    return self._json(200, {"ok": True, "version": __version__, "platform": plane.platform, "started": plane.started,
                                            "library": [str(p) for p in plane.library], "jobs": str(plane.jobs),
                                            "running": plane.job_lock.locked()})
                if path == "/api/actions":
                    return self._json(200, {"ok": True, "actions": table(plane.platform)})
                if path == "/api/library":
                    return self._json(200, {"ok": True, **plane.catalog()})
                if path == "/api/jobs":
                    return self._json(200, {"ok": True, **plane.job_index()})
                if path == "/api/runs":
                    return self._json(200, {"ok": True, "runs": plane.run_rows(), "running": plane.job_lock.locked()})
                if path.startswith("/api/runs/"):
                    run_id = path.rsplit("/", 1)[1]
                    match = next((r for r in plane.run_rows() if r["run_id"] == run_id), None)
                    if match is None:
                        raise Failure(INPUT_MISSING, "No such run")
                    return self._json(200, {"ok": True, "run": match})
                raise Failure("unknown_route", f"No such path {path}")
            except Failure as exc:
                self._fail(404 if exc.code in (INPUT_MISSING, "unknown_route") else 400, exc)

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            if not self._guard():
                return
            try:
                body = self._body()
                if path == "/api/run":
                    action_id = body.get("action")
                    if not isinstance(action_id, str) or not NAME.match(action_id):
                        raise Failure(INPUT_INVALID, "action is an action id from /api/actions")
                    run = plane.start(action_id, body.get("args") or {}, body.get("confirmed", False))
                    return self._json(202, {"ok": True, "run": run})
                raise Failure("unknown_route", f"No such path {path}")
            except Failure as exc:
                status = {BUSY: 409, INPUT_MISSING: 404, "unknown_route": 404, "unsupported_platform": 409, "not_implemented": 409}.get(exc.code, 400)
                self._fail(status, exc)

    return Handler


# ----- entry ----------------------------------------------------------------------------------

def _is_link(path: Path) -> bool:
    """A symbolic link on any OS, or a Windows reparse point (a junction is one and is not a
    symlink to ``Path.is_symlink``). ``core.jobs.entry_kind`` answers the same question for a
    directory entry; a root is given to us by name, so it is asked here."""
    if path.is_symlink():
        return True
    try:
        return bool((getattr(path.lstat(), "st_file_attributes", 0) or 0) & REPARSE_POINT)
    except OSError:
        return False


def validate_roots(library: list[str], jobs: str) -> tuple[list[Path], Path]:
    if len(library) > MAX_LIBRARY_ROOTS:
        raise Failure(INPUT_LIMIT, f"At most {MAX_LIBRARY_ROOTS} library roots")
    roots = []
    for text in library:
        p = Path(text).expanduser()
        if not p.is_absolute():
            raise Failure(INPUT_INVALID, f"Library roots are absolute paths: {text}")
        if _is_link(p) or not p.is_dir():
            raise Failure(INPUT_MISSING, f"Library root is a directory, not a link: {text}")
        roots.append(p.resolve())
    j = Path(jobs).expanduser()
    if not j.is_absolute():
        raise Failure(INPUT_INVALID, f"The jobs directory is an absolute path: {jobs}")
    if _is_link(j) or (j.exists() and not j.is_dir()):
        raise Failure(INPUT_INVALID, f"The jobs directory is a directory, not a link or file: {jobs}")
    j.mkdir(parents=True, exist_ok=True)
    j = j.resolve()
    for r in roots:
        if j.is_relative_to(r) or r.is_relative_to(j):
            raise Failure(INPUT_INVALID, "The jobs directory and the library roots must not contain each other")
    return roots, j


def serve(library: list[str], jobs: str, port: int = 0, seconds: int = 3600, announce=print, ready=None) -> dict:
    """Run until ``seconds`` elapse or SIGINT. Returns the summary for the JSON envelope."""
    if not 0 <= port <= 65535:
        raise Failure(INPUT_INVALID, "port is 0 (any free port) to 65535")
    if not 1 <= seconds <= MAX_SECONDS:
        raise Failure(INPUT_INVALID, f"seconds is 1 to {MAX_SECONDS}")
    roots, jobs_dir = validate_roots(library, jobs)
    plane = Plane(roots, jobs_dir)
    try:
        server = PlaneServer(("127.0.0.1", port), make_handler(plane))
    except OSError as exc:
        raise Failure("busy", f"Cannot bind 127.0.0.1:{port}: {exc.strerror or exc}", "Pass --port 0 for any free port") from exc
    bound = server.server_address[1]
    url = f"http://127.0.0.1:{bound}/#token={plane.token}"
    announce(f"pat plane: {url}", file=sys.stderr)
    announce(f"pat plane: library {[str(r) for r in roots]}; jobs {jobs_dir}; stops after {seconds} s or Ctrl-C", file=sys.stderr)
    if ready is not None:
        ready(bound, plane)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    deadline = time.monotonic() + seconds
    stopped = "deadline"
    try:
        while time.monotonic() < deadline:
            time.sleep(0.2)
            if plane.stop_requested:
                stopped = "requested"
                break
    except KeyboardInterrupt:
        stopped = "interrupted"
    finally:
        server.shutdown()
        server.server_close()
        child = plane.shutdown()
    runs = plane.run_rows()
    return {"origin": f"http://127.0.0.1:{bound}", "library": [str(r) for r in roots], "jobs": str(jobs_dir), "stopped": stopped,
            "runs": len(runs), "runs_finished": sum(1 for r in runs if r["status"] != "running"),
            "child_stopped_at_shutdown": child["child_stopped"], "child_still_running": child["still_running"],
            "run_records": str(jobs_dir / "plane-runs"), "game_touched": False,
            "verification": "served on loopback with a per-start token; every action ran as a pat child with its own receipt; "
                            "a child still running at shutdown was interrupted, then killed, and its run recorded as stopped; nothing here is game evidence"}
