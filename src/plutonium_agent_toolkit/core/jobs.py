"""One job: a new output directory, bounded backend processes and a receipt.

A ``Job`` owns exactly one output directory that did not exist before. Every
backend it runs is a child process whose whole tree is terminated on timeout,
cancellation or exit: a Job Object on Windows, a process group on Linux. Output size,
file count and log size are bounded. ``receipt.json`` is written when the job
starts, after every step and on every exit path, including failure.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .envelope import now
from .errors import (BACKEND_FAILED, BACKEND_TIMEOUT, BACKEND_UNAVAILABLE, CANCELLED, INPUT_CHANGED,
                     INPUT_INVALID, INPUT_LIMIT, INPUT_MISSING, OUTPUT_LIMIT, Failure)
from .receipts import FILE_FLAGS, MAX_FILES, inventory, new_output_dir, sha256_descriptor, sha256_file

MAX_LOG = 4 * 1024 * 1024
MAX_OUTPUT = 8 * 1024**3
MAX_TREE_FILES = 4096
MAX_TREE_BYTES = 2 * 1024**3
MAX_TREES = 64
CHILD_LAUNCH_FAILED = 127  # returned by _child.py when the backend itself cannot start


REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
# Re-listing a recorded directory goes through a descriptor opened without following links on
# POSIX; Windows cannot open a directory that way and re-lists by name after an lstat check.
DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
DESCRIPTOR_LISTINGS = os.name != "nt" and os.scandir in os.supports_fd and hasattr(os, "O_DIRECTORY")


def entry_kind(st) -> str:
    """What a directory entry is from its own ``lstat``: ``link`` (a symbolic link on any OS or a
    Windows reparse point), ``dir``, ``file`` or ``other``. Recorded beside the name so an entry
    swapped for another kind under the same name is a change."""
    if stat.S_ISLNK(st.st_mode) or ((getattr(st, "st_file_attributes", 0) or 0) & REPARSE_POINT):
        return "link"
    if stat.S_ISDIR(st.st_mode):
        return "dir"
    if stat.S_ISREG(st.st_mode):
        return "file"
    return "other"


def listing_digest(entries) -> str:
    """One hash for a directory's entries as ``(name, kind)`` pairs, order-independent, raw name
    bytes so any name works."""
    h = hashlib.sha256()
    for name, kind in sorted((os.fsencode(n), k) for n, k in entries):
        h.update(len(name).to_bytes(4, "big") + name + b"\0" + kind.encode("ascii") + b"\0")
    return h.hexdigest()


def list_entries(directory: Path, identity: tuple[int, int] | None = None) -> list[tuple[str, str]]:
    """``(name, kind)`` for every entry of a directory, from each entry's own ``lstat``.

    On POSIX the directory is opened without following links and listed through that descriptor,
    whose ``fstat`` must be a directory with the recorded ``identity`` (``st_dev``, ``st_ino``)
    when one was recorded, so a directory swapped for a link or recreated between the caller's
    check and the listing is a change, not a listing of something else. Windows lists by name
    after an ``lstat`` that refuses links; the window between the two is what it leaves open."""
    if not DESCRIPTOR_LISTINGS:
        if entry_kind(os.lstat(directory)) != "dir":
            raise Failure(INPUT_CHANGED, f"Directory changed while the job ran: {directory} is no longer a directory")
        with os.scandir(directory) as it:
            return [(e.name, entry_kind(e.stat(follow_symlinks=False))) for e in it]
    try:
        fd = os.open(directory, DIR_FLAGS)
    except OSError as exc:
        raise Failure(INPUT_CHANGED, f"Directory changed while the job ran: {directory} ({exc.strerror or exc})") from exc
    try:
        opened = os.fstat(fd)
        if not stat.S_ISDIR(opened.st_mode):
            raise Failure(INPUT_CHANGED, f"Directory changed while the job ran: {directory} is no longer a directory")
        if identity is not None and identity[1] and (opened.st_dev, opened.st_ino) != tuple(identity):
            raise Failure(INPUT_CHANGED, f"Directory changed while the job ran: {directory} was replaced")
        # scandir(fd) works on its own duplicate of the descriptor (CPython dups it before
        # fdopendir), so closing the iterator leaves fd open and the close below is the only one.
        with os.scandir(fd) as it:
            return [(e.name, entry_kind(e.stat(follow_symlinks=False))) for e in it]
    finally:
        os.close(fd)


def _write(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)


class Job:
    def __init__(self, output: Path, command: str, argv: list[str], timeout: int = 600):
        self.root = new_output_dir(output).resolve()
        self.command = command
        self.argv = list(argv)
        self.id = uuid.uuid4().hex
        self.started = now()
        self._t0 = time.monotonic()
        self.deadline = self._t0 + timeout
        self.inputs: dict[str, str] = {}
        self.listings: dict[str, str] = {}
        self._listing_identity: dict[str, tuple[int, int]] = {}
        self.trees: dict[str, dict[str, str]] = {}
        self.steps: list[dict] = []
        self.repairs: list[str] = []
        self._save("running")

    # ----- receipt -----------------------------------------------------------------
    def _receipt(self, status: str, **extra) -> dict:
        return {
            "schema_version": 1, "job_id": self.id, "command": self.command, "argv": self.argv,
            "status": status, "started": self.started, "updated": now(),
            "elapsed_seconds": round(time.monotonic() - self._t0, 3), "output": str(self.root),
            "inputs": self.inputs, "input_listings": self.listings, "input_trees": self.trees, "steps": self.steps,
            **({"receipt_path_repaired": list(self.repairs)} if self.repairs else {}), **extra,
        }

    def _save(self, status: str, **extra) -> None:
        """A backend that replaced receipt.json with a directory or link gets that entry
        moved aside (never deleted) so the receipt is always a regular file here."""
        path = self.root / "receipt.json"
        if path.is_symlink() or (path.exists() and not path.is_file()):
            aside = path.with_name(path.name + ".replaced-by-backend." + uuid.uuid4().hex)
            path.rename(aside)
            self.repairs.append(aside.name)
        _write(path, self._receipt(status, **extra))

    @property
    def receipt_path(self) -> Path:
        return self.root / "receipt.json"

    # ----- inputs ------------------------------------------------------------------
    def check_deadline(self) -> None:
        if time.monotonic() >= self.deadline:
            raise Failure(BACKEND_TIMEOUT, "Job deadline exceeded")

    def input(self, path: Path, limit: int = MAX_TREE_BYTES) -> Path:
        self.check_deadline()
        p = Path(path).expanduser().absolute()
        if p.is_symlink() or not p.is_file():
            raise Failure(INPUT_MISSING, f"Input is missing or not a regular file: {p}")
        if p.stat().st_size > limit:
            raise Failure(INPUT_LIMIT, f"Input exceeds {limit} bytes: {p}")
        p = p.resolve()
        if p.is_relative_to(self.root):
            raise Failure(INPUT_INVALID, "Inputs must live outside the job's output directory")
        key = str(p)
        if key not in self.inputs:
            if len(self.inputs) >= MAX_FILES:
                raise Failure(INPUT_LIMIT, "Too many declared inputs")
            self.inputs[key] = sha256_file(p)
        return p

    def record_input(self, path: Path, digest: str) -> None:
        """Register an input the caller has already hashed through its own descriptor (a scan
        that opened the file without following links). The receipt lists it and ``finish``
        re-hashes it like any other input, so a change after the read fails the job."""
        p = Path(path).absolute()
        if p.is_relative_to(self.root):
            raise Failure(INPUT_INVALID, "Inputs must live outside the job's output directory")
        if not isinstance(digest, str) or len(digest) != 64:
            raise Failure(INPUT_INVALID, f"Not a sha256 digest for {p}")
        key = str(p)
        if key not in self.inputs:
            if len(self.inputs) >= MAX_FILES:
                raise Failure(INPUT_LIMIT, "Too many declared inputs")
            self.inputs[key] = digest

    def record_listing(self, path: Path, entries, identity: tuple[int, int] | None = None) -> None:
        """Register a directory listing the caller enumerated, as ``(name, kind)`` pairs (see
        ``entry_kind``), with the directory's own identity (``st_dev``, ``st_ino``) when the
        caller holds it. ``finish`` lists the directory again through a no-follow descriptor and
        compares, so an entry added, removed or swapped for another kind under the same name
        after the caller looked fails the job, as does the directory itself becoming a link,
        being recreated or disappearing."""
        p = Path(path).absolute()
        if p.is_relative_to(self.root):
            raise Failure(INPUT_INVALID, "Inputs must live outside the job's output directory")
        key = str(p)
        if key not in self.listings:
            if len(self.listings) >= MAX_FILES:
                raise Failure(INPUT_LIMIT, "Too many declared inputs")
            self.listings[key] = listing_digest(entries)
            if identity is not None:
                self._listing_identity[key] = (int(identity[0]), int(identity[1]))

    def input_tree(self, root: Path) -> Path:
        root = Path(root).resolve()
        if not root.is_dir():
            raise Failure(INPUT_MISSING, f"Source directory is missing: {root}")
        if self.root.is_relative_to(root):
            raise Failure(INPUT_INVALID, "Output must be outside the source tree")
        if str(root) not in self.trees and len(self.trees) >= MAX_TREES:
            raise Failure(INPUT_LIMIT, f"More than {MAX_TREES} source trees")
        snapshot: dict[str, str] = {}
        total = 0
        for directory, dirs, files in os.walk(root, followlinks=False):
            self.check_deadline()
            dirs.sort()
            for name in dirs:
                linked = Path(directory) / name
                if linked.is_symlink() or (os.name == "nt" and linked.lstat().st_file_attributes & 0x400):
                    raise Failure(INPUT_INVALID, f"Linked source directories are not supported: {linked}")
            for name in sorted(files):
                p = Path(directory) / name
                if p.is_symlink():
                    raise Failure(INPUT_INVALID, f"Linked source files are not supported: {p}")
                total += p.stat().st_size
                if len(snapshot) >= MAX_TREE_FILES or total > MAX_TREE_BYTES:
                    raise Failure(INPUT_LIMIT, f"Source tree exceeds {MAX_TREE_FILES} files or {MAX_TREE_BYTES} bytes")
                snapshot[p.relative_to(root).as_posix()] = self.inputs.setdefault(str(p.resolve()), sha256_file(p))
        self.trees[str(root)] = snapshot
        return root

    # ----- execution ---------------------------------------------------------------
    def run(self, argv: list, *, cwd: Path | None = None, timeout: int = 300) -> Path:
        argv = [str(a) for a in argv]
        started = time.monotonic()
        timeout = min(timeout, self.deadline - started)
        if timeout <= 0:
            raise Failure(BACKEND_TIMEOUT, "Job deadline exceeded")
        log = self.root / f"step-{len(self.steps) + 1:02d}.log"
        step = {"argv": argv, "log": log.name, "timeout_seconds": round(timeout, 1)}
        self.steps.append(step)
        try:
            code = (_run_windows if os.name == "nt" else _run_posix)(self, argv, cwd or self.root, timeout, log)
            if log.exists() and log.stat().st_size > MAX_LOG:
                step["exit_code"] = code
                raise Failure(OUTPUT_LIMIT, "Backend diagnostic output exceeded its bound", log=log.name)
            step["exit_code"] = code
            if code == CHILD_LAUNCH_FAILED:
                raise Failure(BACKEND_UNAVAILABLE, f"Cannot execute {argv[0]}; see {log.name}", "Run: pat dev setup",
                              log=log.name)
            if code:
                raise Failure(BACKEND_FAILED, f"Backend exited with status {code}", log=log.name, exit_code=code)
            return log
        except OSError as exc:
            # FileNotFoundError, PermissionError and "not a valid Win32 application" all land here.
            step["exit_code"] = None
            raise Failure(BACKEND_UNAVAILABLE, f"Cannot execute {argv[0]}: {exc.strerror or exc}",
                          "Run: pat dev setup, or check the PAT_BACKEND_* override") from exc
        finally:
            step["elapsed_seconds"] = round(time.monotonic() - started, 3)
            if log.exists() and log.stat().st_size > MAX_LOG:
                with log.open("r+b") as handle:
                    handle.truncate(MAX_LOG)
                step["log_truncated"] = True
            self._save("running")

    def _watch_output(self) -> None:
        """Bound the output directory while a backend runs; tolerate transient files."""
        count = total = 0
        for directory, dirs, files in os.walk(self.root, followlinks=False):
            count += len(dirs) + len(files)
            for name in files:
                try:
                    total += (Path(directory) / name).stat().st_size
                except FileNotFoundError:
                    continue
            if count > MAX_FILES or total > MAX_OUTPUT:
                raise Failure(OUTPUT_LIMIT, "Backend exceeded the output file count or size bound")

    # ----- completion --------------------------------------------------------------
    def _recorded_ancestors(self, parent: str) -> list[Path]:
        """The recorded directories from the topmost recorded ancestor of ``parent`` down to
        ``parent`` itself; empty when ``parent`` was never recorded."""
        chain = []
        path = Path(parent)
        while str(path) in self.listings:
            chain.append(path)
            if path.parent == path:
                break
            path = path.parent
        chain.reverse()
        return chain

    def _identity_ok(self, key: str, opened: os.stat_result) -> None:
        if not stat.S_ISDIR(opened.st_mode):
            raise Failure(INPUT_CHANGED, f"Directory changed while the job ran: {key} is no longer a directory")
        identity = self._listing_identity.get(key)
        if identity is not None and identity[1] and (opened.st_dev, opened.st_ino) != identity:
            raise Failure(INPUT_CHANGED, f"Directory changed while the job ran: {key} was replaced")

    def _open_chain(self, chain: list[Path]) -> list[int]:
        """Descriptors for the recorded ancestors, the first opened by name and each next relative
        to the previous, none following links, each a directory with the identity recorded when it
        was walked. The caller closes every descriptor returned."""
        fds: list[int] = []
        try:
            for i, directory in enumerate(chain):
                fd = os.open(directory, DIR_FLAGS) if i == 0 else os.open(directory.name, DIR_FLAGS, dir_fd=fds[-1])
                fds.append(fd)
                self._identity_ok(str(directory), os.fstat(fd))
        except OSError as exc:
            for fd in fds:
                os.close(fd)
            raise Failure(INPUT_CHANGED, f"Directory changed while the job ran: {chain[len(fds)]} ({exc.strerror or exc})") from exc
        except Failure:
            for fd in fds:
                os.close(fd)
            raise
        return fds

    def _rehash(self, key: str) -> str:
        """The current hash of a recorded input. A file whose parent directory is a recorded
        listing is opened relative to its recorded ancestors (``_open_chain``), so no ancestor can
        redirect the open outside the tree and every ancestor is checked before a byte is read;
        an input declared by name alone (``input``) is re-hashed by name, its final component
        never followed as a link. Windows has no descriptor-relative opens: every recorded ancestor
        is re-checked by name for links immediately before the open, and the moment between that
        check and the open is the window it leaves."""
        path = Path(key)
        chain = self._recorded_ancestors(str(path.parent))
        try:
            if not chain:
                return sha256_file(path, check=self.check_deadline)
            if not DESCRIPTOR_LISTINGS:
                for directory in chain:
                    if entry_kind(os.lstat(directory)) != "dir":
                        raise Failure(INPUT_CHANGED, f"Directory changed while the job ran: {directory} is no longer a directory")
                return sha256_file(path, check=self.check_deadline)
            fds = self._open_chain(chain)
            try:
                try:
                    fd = os.open(path.name, FILE_FLAGS, dir_fd=fds[-1])
                except OSError as exc:
                    raise Failure(INPUT_CHANGED, f"Input changed while the job ran: {key} ({exc.strerror or exc})") from exc
                return sha256_descriptor(fd, key, check=self.check_deadline)
            finally:
                for fd in fds:
                    os.close(fd)
        except Failure as exc:
            # A file that cannot be hashed any more is an input change; running out of time or
            # being cancelled is not, and keeps its own code.
            if exc.code in (INPUT_CHANGED, BACKEND_TIMEOUT, CANCELLED):
                raise
            raise Failure(INPUT_CHANGED, f"Input changed while the job ran: {key} ({exc.message})") from exc

    def finish(self, result: dict) -> dict:
        self.check_deadline()
        # Re-hashing a large recorded tree is itself work: the deadline is checked before every
        # file and every listing, and inside each read, so a job cannot succeed after its deadline.
        for key, digest in self.inputs.items():
            self.check_deadline()
            if self._rehash(key) != digest:
                raise Failure(INPUT_CHANGED, f"Input changed while the job ran: {key}")
        for key, digest in self.listings.items():
            self.check_deadline()
            try:
                entries = list_entries(Path(key), self._listing_identity.get(key))
            except OSError as exc:
                raise Failure(INPUT_CHANGED, f"Directory changed while the job ran: {key} ({exc.strerror or exc})") from exc
            if listing_digest(entries) != digest:
                raise Failure(INPUT_CHANGED, f"Directory changed while the job ran: {key}")
        # The periodic scan during run() can miss a final burst; recheck before declaring success.
        self._watch_output()
        outputs = {rel: digest for rel, digest in inventory(self.root).items() if rel != "receipt.json"}
        self._save("succeeded", exit_code=0, ok=True, result=result, outputs=outputs, finished=now())
        return {"job_id": self.id, "output": str(self.root), "receipt": str(self.receipt_path),
                "artifact_count": len(outputs), **result}

    def fail(self, error: Failure) -> None:
        status = "cancelled" if error.code == CANCELLED else "failed"
        try:
            self._save(status, exit_code=error.exit_status(), ok=False, error=error.to_dict(), finished=now())
        except OSError as exc:
            # Storage is gone or unwritable. The stdout JSON is still the caller's receipt.
            print(f"warning: receipt could not be saved ({exc})", file=sys.stderr)


# ----- platform runners --------------------------------------------------------------

def _run_posix(job: Job, argv: list[str], cwd: Path, timeout: float, log: Path) -> int:
    import signal

    with log.open("xb") as output:
        process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=output,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            return _wait(job, process, timeout, log)
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


def _run_windows(job: Job, argv: list[str], cwd: Path, timeout: float, log: Path) -> int:
    from . import _winjob

    try:
        with log.open("xb") as output:
            handle = _winjob.create_job()
            process = None
            try:
                process = subprocess.Popen([sys.executable, str(Path(__file__).with_name("_child.py"))],
                                           stdin=subprocess.PIPE, stdout=output, stderr=subprocess.STDOUT, cwd=cwd,
                                           creationflags=subprocess.CREATE_NO_WINDOW)
                _winjob.assign(handle, process)
                process.stdin.write((json.dumps(argv) + "\n").encode("utf-8"))
                process.stdin.close()
                return _wait(job, process, timeout, log)
            finally:
                _winjob.terminate(handle)
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                    process.wait()
    finally:
        # Our handle is closed now. A terminated backend tree's inherited handle to the log can
        # outlive process.wait() by a scheduler tick; wait so the caller can delete the job directory.
        waited = time.monotonic()
        if not _winjob.wait_until_released(log):
            job.steps[-1]["log_still_open"] = True
            job.steps[-1]["log_release_wait_seconds"] = round(time.monotonic() - waited, 3)


def _wait(job: Job, process: subprocess.Popen, timeout: float, log: Path) -> int:
    started = time.monotonic()
    next_scan = started
    while process.poll() is None:
        if time.monotonic() - started > timeout:
            raise Failure(BACKEND_TIMEOUT, f"Backend exceeded {round(timeout)} seconds", log=log.name)
        if log.exists() and log.stat().st_size > MAX_LOG:
            raise Failure(OUTPUT_LIMIT, "Backend diagnostic output exceeded its bound", log=log.name)
        if time.monotonic() >= next_scan:
            job._watch_output()
            next_scan = time.monotonic() + 0.5
        time.sleep(0.05)
    return process.returncode
