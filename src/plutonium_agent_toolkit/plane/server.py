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
import subprocess
import sys
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
from .actions import BY_ID, argv_for, table

STATIC = Path(__file__).with_name("static")
MAX_BODY = 1024 * 1024
MAX_RUNS = 200
MAX_OUTPUT = 4 * 1024 * 1024
MAX_LIBRARY_ROOTS = 16
MAX_SECONDS = 24 * 3600
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}\Z")


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


class Plane:
    """State shared by the handler threads: roots, token, runs, the single-job lock."""

    def __init__(self, library: list[Path], jobs: Path):
        self.library = library
        self.jobs = jobs
        self.token = secrets.token_urlsafe(32)
        self.started = now()
        self.runs: list[dict] = []
        self.lock = threading.Lock()
        self.job_lock = threading.Lock()
        self.counter = 0
        self.prompt_dir = jobs / "plane-prompts"
        (jobs / "plane-runs").mkdir(parents=True, exist_ok=True)
        self.platform = platform.describe()

    # ----- library ---------------------------------------------------------------------
    def catalog(self) -> dict:
        """Declarations, compositions and seed manifests under the library roots, read as files."""
        roots = []
        for index, root in enumerate(self.library):
            modules, compositions = [], []
            count = 0
            for directory, dirs, files in os.walk(root, followlinks=False):
                dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not (Path(directory) / d).is_symlink())
                count += 1
                if count > 4096:
                    break
                here = Path(directory)
                rel = here.relative_to(root).as_posix()
                if "module.json" in files:
                    modules.append(_summary(here / "module.json", rel, "module"))
                if "composition.json" in files:
                    compositions.append(_summary(here / "composition.json", rel, "composition"))
            roots.append({"index": index, "root": str(root), "modules": modules, "compositions": compositions,
                          "truncated": count > 4096})
        return {"roots": roots, "jobs": str(self.jobs)}

    def job_index(self) -> dict:
        """Every receipt.json under the jobs directory, one row each, newest first."""
        rows = []
        if self.jobs.is_dir():
            for child in sorted(self.jobs.iterdir()):
                receipt = child / "receipt.json"
                if child.is_symlink() or not child.is_dir() or receipt.is_symlink() or not receipt.is_file():
                    continue
                try:
                    data = json.loads(receipt.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    rows.append({"directory": child.name, "status": "unreadable"})
                    continue
                if not isinstance(data, dict):
                    continue
                result = data.get("result") if isinstance(data.get("result"), dict) else {}
                rows.append({"directory": child.name, "command": data.get("command"), "status": data.get("status"),
                             "started": data.get("started"), "finished": data.get("finished"), "job_id": data.get("job_id"),
                             "mod_ff": result.get("mod_ff"), "name": result.get("name"), "error": (data.get("error") or {}).get("message")})
                if len(rows) >= 512:
                    break
        rows.sort(key=lambda r: r.get("started") or "", reverse=True)
        return {"jobs": str(self.jobs), "runs": rows}

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
        if not self.job_lock.acquire(blocking=False):
            raise Failure(BUSY, "Another action is still running; the plane runs one at a time", "Poll /api/runs and retry after it finishes")
        try:
            self._record(run)
            threading.Thread(target=self._execute, args=(run, action.timeout), daemon=True).start()
        except (OSError, RuntimeError) as exc:
            self.job_lock.release()
            raise Failure("operation_failed", f"Could not start the run: {exc}") from exc
        return {k: v for k, v in run.items() if k != "result"}

    def _execute(self, run: dict, timeout: int) -> None:
        try:
            proc = subprocess.run([sys.executable, "-m", "plutonium_agent_toolkit", *run["argv"]], capture_output=True,
                                  text=True, timeout=timeout, cwd=str(self.jobs), stdin=subprocess.DEVNULL, env=child_env())
            stdout = proc.stdout[:MAX_OUTPUT]
            try:
                payload = json.loads(stdout) if stdout.strip() else None
            except ValueError:
                payload = None
            run.update(status="finished", exit_code=proc.returncode, finished=now(), result=payload,
                       stdout_head=None if payload is not None else stdout[:4000], stderr_head=proc.stderr[:4000])
        except subprocess.TimeoutExpired as exc:
            run.update(status="timeout", exit_code=124, finished=now(), result=None,
                       stderr_head=f"exceeded {timeout} seconds; " + str(exc.stderr or "")[:2000])
        except OSError as exc:
            run.update(status="failed", exit_code=127, finished=now(), result=None, stderr_head=f"could not start: {exc}")
        finally:
            self._record(run)
            self.job_lock.release()

    def run_rows(self) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.runs]


def _summary(path: Path, rel: str, kind: str) -> dict:
    try:
        raw = path.read_bytes()
        if len(raw) > 256 * 1024:
            return {"path": rel, "kind": kind, "error": "declaration larger than 256 KiB"}
        data = json.loads(raw)
    except (OSError, ValueError):
        return {"path": rel, "kind": kind, "error": "unreadable"}
    if not isinstance(data, dict):
        return {"path": rel, "kind": kind, "error": "not an object"}
    keys = ("id", "name", "version", "title", "category", "kind", "tags", "bases", "maps", "base", "map", "dependencies",
            "conflicts", "distribution", "menu_route", "modules")
    row = {"path": rel, "kind": kind, **{k: data[k] for k in keys if k in data}}
    row["payload"] = "seed" if "seed" in data else "recipe" if "recipe" in data else None
    if kind == "module" and "seed" in data:
        manifest = path.parent / str(data["seed"])
        if manifest.is_file() and not manifest.is_symlink():
            try:
                seed = json.loads(manifest.read_text(encoding="utf-8"))
                files = seed.get("files") or {}
                row["package_present"] = all((path.parent / n).is_file() for n in files) if isinstance(files, dict) else None
                row["embedded"] = len(seed.get("embedded") or [])
                row["roots"] = len(seed.get("roots") or [])
            except (OSError, ValueError):
                row["package_present"] = None
    return row


# ----- HTTP ---------------------------------------------------------------------------------

def make_handler(plane: Plane):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"pat-plane/{__version__}"

        def log_message(self, *args):  # the receipts are the log
            pass

        # ----- helpers -----
        def _json(self, status: int, body: dict) -> None:
            data = json.dumps(body, indent=2, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

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
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise Failure(INPUT_LIMIT, f"Request body exceeds {MAX_BODY} bytes")
            raw = self.rfile.read(length) if length else b""
            try:
                value = json.loads(raw or b"{}")
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
                page = (STATIC / "index.html").read_text(encoding="utf-8")
                data = page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(data)
                return
            if path == "/favicon.ico":
                self.send_response(204)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            if path in ("/plane.js", "/plane.css"):
                if not self._guard(need_token=False):
                    return
                data = (STATIC / path.lstrip("/")).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/javascript; charset=utf-8" if path.endswith(".js") else "text/css; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(data)
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

def validate_roots(library: list[str], jobs: str) -> tuple[list[Path], Path]:
    if len(library) > MAX_LIBRARY_ROOTS:
        raise Failure(INPUT_LIMIT, f"At most {MAX_LIBRARY_ROOTS} library roots")
    roots = []
    for text in library:
        p = Path(text).expanduser()
        if not p.is_absolute():
            raise Failure(INPUT_INVALID, f"Library roots are absolute paths: {text}")
        if p.is_symlink() or not p.is_dir():
            raise Failure(INPUT_MISSING, f"Library root is not a directory: {text}")
        roots.append(p.resolve())
    j = Path(jobs).expanduser()
    if not j.is_absolute():
        raise Failure(INPUT_INVALID, f"The jobs directory is an absolute path: {jobs}")
    if j.is_symlink() or (j.exists() and not j.is_dir()):
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
        server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(plane))
    except OSError as exc:
        raise Failure("busy", f"Cannot bind 127.0.0.1:{port}: {exc.strerror or exc}", "Pass --port 0 for any free port") from exc
    server.daemon_threads = True
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
            if getattr(plane, "stop", False):
                stopped = "requested"
                break
    except KeyboardInterrupt:
        stopped = "interrupted"
    finally:
        server.shutdown()
        server.server_close()
    runs = plane.run_rows()
    return {"origin": f"http://127.0.0.1:{bound}", "library": [str(r) for r in roots], "jobs": str(jobs_dir), "stopped": stopped,
            "runs": len(runs), "runs_finished": sum(1 for r in runs if r["status"] != "running"),
            "run_records": str(jobs_dir / "plane-runs"), "game_touched": False,
            "verification": "served on loopback with a per-start token; every action ran as a pat child with its own receipt; nothing here is game evidence"}
