"""Native Win32 console transport for Plutonium T6 Zombies. Imported only by the
bounded game worker on Windows.

What it does: enumerate visible game windows by exact title, pin one process by
PID plus creation time, attach to that process's existing external console,
read its screen buffer and write one bounded ASCII command as console input
records. What it never does: read process memory or command lines, focus or
move windows, simulate player keys, flush or consume the user's typed input,
kill anything, or retry a write.
"""
from __future__ import annotations

import ctypes as C
import os
import re
import time
from contextlib import contextmanager
from ctypes import wintypes as W

from ..core.errors import BUSY, DELIVERY_UNCERTAIN, GAME_AMBIGUOUS, GAME_NOT_FOUND, Failure

TITLE = re.compile(r"Plutonium T6 Zombies(?: \(r\d+\))?")
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
BOOTSTRAPPER = "plutonium-bootstrapper-win32.exe"
MUTEX = r"Local\PlutoniumAgentToolkit.T6.v1"
PROMPT = re.compile(r"Plutonium r\d+ > ")
MAX_COMMAND = 900
MAX_ROWS = 641
MAX_WIDTH = 4096


class COORD(C.Structure):
    _fields_ = [("X", C.c_int16), ("Y", C.c_int16)]


class RECT(C.Structure):
    _fields_ = [(n, C.c_int16) for n in ("left", "top", "right", "bottom")]


class INFO(C.Structure):
    _fields_ = [("size", COORD), ("cursor", COORD), ("attributes", C.c_uint16), ("window", RECT), ("maximum", COORD)]


class RECORD(C.Structure):
    _fields_ = [("type", C.c_uint16), ("padding", C.c_uint16), ("down", C.c_int32), ("repeat", C.c_uint16),
                ("key", C.c_uint16), ("scan", C.c_uint16), ("character", C.c_uint16), ("control", C.c_uint32)]


assert C.sizeof(RECORD) == 20 and C.sizeof(INFO) == 22

_API = None


def api():
    global _API
    if _API is not None:
        return _API
    if os.name != "nt":
        raise Failure("unsupported_platform", "Native game control requires Windows")
    k = C.WinDLL("kernel32", use_last_error=True)
    u = C.WinDLL("user32", use_last_error=True)
    callback = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    for lib, name, args, result in [
        (k, "CreateMutexW", [C.c_void_p, W.BOOL, W.LPCWSTR], W.HANDLE),
        (k, "ReleaseMutex", [W.HANDLE], W.BOOL),
        (k, "WaitForSingleObject", [W.HANDLE, W.DWORD], W.DWORD),
        (k, "CloseHandle", [W.HANDLE], W.BOOL),
        (k, "OpenProcess", [W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
        (k, "GetProcessTimes", [W.HANDLE] + [C.POINTER(W.FILETIME)] * 4, W.BOOL),
        (k, "QueryFullProcessImageNameW", [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)], W.BOOL),
        (k, "FreeConsole", [], W.BOOL),
        (k, "AttachConsole", [W.DWORD], W.BOOL),
        (k, "GetConsoleProcessList", [C.POINTER(W.DWORD), W.DWORD], W.DWORD),
        (k, "CreateFileW", [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE], W.HANDLE),
        (k, "GetConsoleScreenBufferInfo", [W.HANDLE, C.POINTER(INFO)], W.BOOL),
        (k, "GetNumberOfConsoleInputEvents", [W.HANDLE, C.POINTER(W.DWORD)], W.BOOL),
        (k, "ReadConsoleOutputCharacterW", [W.HANDLE, W.LPWSTR, W.DWORD, COORD, C.POINTER(W.DWORD)], W.BOOL),
        (k, "WriteConsoleInputW", [W.HANDLE, C.POINTER(RECORD), W.DWORD, C.POINTER(W.DWORD)], W.BOOL),
        (u, "EnumWindows", [callback, W.LPARAM], W.BOOL),
        (u, "GetWindowTextW", [W.HWND, W.LPWSTR, C.c_int], C.c_int),
        (u, "GetWindowThreadProcessId", [W.HWND, C.POINTER(W.DWORD)], W.DWORD),
        (u, "IsWindowVisible", [W.HWND], W.BOOL),
        (u, "GetForegroundWindow", [], W.HWND),
        (u, "VkKeyScanW", [C.c_wchar], C.c_int16),
        (u, "MapVirtualKeyW", [W.UINT, W.UINT], W.UINT),
    ]:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, result
    _API = (k, u, callback)
    return _API


def checked(value, message: str, code: str = "game_not_found"):
    if not value:
        raise Failure(code, f"{message} (Win32 error {C.get_last_error()})")
    return value


@contextmanager
def lock():
    """One live game operation at a time across every toolkit copy on this machine."""
    k, _, _ = api()
    handle = checked(k.CreateMutexW(None, False, MUTEX), "Cannot create the toolkit mutex", BUSY)
    owned = False
    try:
        owned = k.WaitForSingleObject(handle, 0) in (0, 0x80)
        if not owned:
            raise Failure(BUSY, "Another game operation owns the toolkit mutex; nothing was sent",
                          "Wait for that operation's result. Do not queue retries.")
        yield
    finally:
        if owned:
            k.ReleaseMutex(handle)
        k.CloseHandle(handle)


def windows() -> dict[int, str]:
    """PID -> title for every visible window whose title is exactly the T6 Zombies game."""
    _, u, callback = api()
    found: dict[int, str] = {}

    @callback
    def visit(hwnd, _):
        title = C.create_unicode_buffer(256)
        if u.IsWindowVisible(hwnd) and u.GetWindowTextW(hwnd, title, len(title)) and TITLE.fullmatch(title.value):
            pid = W.DWORD()
            u.GetWindowThreadProcessId(hwnd, C.byref(pid))
            if pid.value:
                found[pid.value] = title.value
        return True

    checked(u.EnumWindows(visit, 0), "Cannot enumerate windows")
    return found


def foreground() -> dict:
    """Title and PID of the current foreground window; used only to log focus changes."""
    _, u, _ = api()
    hwnd = u.GetForegroundWindow()
    if not hwnd:
        return {"pid": 0, "title": ""}
    title = C.create_unicode_buffer(256)
    u.GetWindowTextW(hwnd, title, len(title))
    pid = W.DWORD()
    u.GetWindowThreadProcessId(hwnd, C.byref(pid))
    return {"pid": pid.value, "title": title.value}


class Console:
    """Attach to the unique running game's external console."""

    def __init__(self, expected: dict | None = None):
        self.k, self.u, _ = api()
        self.handles: list = []
        self.attached = False
        try:
            matches = windows()
            if not matches:
                raise Failure(GAME_NOT_FOUND, "No Plutonium T6 Zombies game window is open; the launcher alone is not a game")
            if len(matches) > 1:
                raise Failure(GAME_AMBIGUOUS, f"{len(matches)} T6 Zombies windows are open; close all but the intended one")
            self.pid, self.title = next(iter(matches.items()))
            self.process = self.keep(checked(self.k.OpenProcess(0x100000 | 0x1000, False, self.pid),
                                             "Cannot open the game process; use the same Windows user without elevation"))
            created, exited, kernel, user = (W.FILETIME() for _ in range(4))
            checked(self.k.GetProcessTimes(self.process, *(C.byref(t) for t in (created, exited, kernel, user))),
                    "Cannot read process creation time")
            name = C.create_unicode_buffer(32768)
            size = W.DWORD(len(name))
            checked(self.k.QueryFullProcessImageNameW(self.process, 0, name, C.byref(size)), "Cannot read the process image name")
            if name.value.replace("\\", "/").rsplit("/", 1)[-1].lower() != BOOTSTRAPPER:
                raise Failure(GAME_NOT_FOUND, "The matching window does not belong to the Plutonium bootstrapper")
            self.identity = {"pid": self.pid, "created": (created.dwHighDateTime << 32) | created.dwLowDateTime}
            if expected is not None and self.identity != expected:
                raise Failure(GAME_NOT_FOUND, "The original game process is gone; this receipt cannot be checked against a different process")
            self.k.FreeConsole()
            checked(self.k.AttachConsole(self.pid), "Cannot attach to the game's external console; see docs/GAME-CONTROL.md")
            self.attached = True
            self.input = self.open_console("CONIN$", 0xC0000000)
            self.output = self.open_console("CONOUT$", 0x80000000)
            self.alive()
        except BaseException:
            self.close()
            raise

    def keep(self, handle):
        self.handles.append(handle)
        return handle

    def open_console(self, name: str, access: int):
        handle = self.k.CreateFileW(name, access, 3, None, 3, 0, None)
        if handle == C.c_void_p(-1).value:
            raise Failure(GAME_NOT_FOUND, "The external game console is unavailable")
        return self.keep(handle)

    def alive(self) -> None:
        if self.k.WaitForSingleObject(self.process, 0) != 258:
            raise Failure(GAME_NOT_FOUND, "The pinned game process exited; nothing will be replayed")
        pids = (W.DWORD * 64)()
        count = self.k.GetConsoleProcessList(pids, len(pids))
        if not 0 < count <= len(pids) or self.pid not in pids[:count]:
            raise Failure(GAME_NOT_FOUND, "The console no longer belongs to the pinned game")

    def info(self) -> INFO:
        self.alive()
        info = INFO()
        checked(self.k.GetConsoleScreenBufferInfo(self.output, C.byref(info)), "Cannot inspect the console buffer")
        if not 0 < info.size.X <= MAX_WIDTH or not 0 <= info.cursor.X < info.size.X or not 0 <= info.cursor.Y < info.size.Y:
            raise Failure(GAME_NOT_FOUND, "Unsupported console dimensions")
        return info

    def line(self, y: int, width: int) -> str:
        if width == 0:
            return ""
        buf = C.create_unicode_buffer(width + 1)
        got = W.DWORD()
        checked(self.k.ReadConsoleOutputCharacterW(self.output, buf, width, COORD(0, y), C.byref(got)), "Cannot read the console")
        if got.value != width:
            raise Failure(GAME_NOT_FOUND, "Incomplete console read")
        return ANSI.sub("", buf[:got.value])

    def screen(self) -> list[str]:
        info = self.info()
        return [self.line(y, info.size.X).strip() for y in range(max(0, info.cursor.Y - (MAX_ROWS - 1)), info.cursor.Y + 1)]

    def send(self, command: str, timeout: float = 3) -> None:
        """Write one command plus Enter as console input, exactly once.

        Waits (bounded) for an empty prompt with no queued input so the user's own
        typing is never interleaved or consumed. A partial write is uncertain and
        is reported as such; nothing is ever retried here.
        """
        if not isinstance(command, str) or not 1 <= len(command) <= MAX_COMMAND or any(not 32 <= ord(c) <= 126 for c in command):
            raise Failure("input_invalid", "Console commands are bounded printable ASCII")
        records = (RECORD * (2 * (len(command) + 1)))()
        for index, character in enumerate(command + "\r"):
            mapping = 13 if character == "\r" else self.u.VkKeyScanW(character)
            if mapping == -1:
                raise Failure("input_invalid", f"Character {character!r} is unavailable in the current keyboard layout; nothing sent")
            key = mapping & 255
            modifiers = (0x10 if mapping & 0x100 else 0) | (8 if mapping & 0x200 else 0) | (2 if mapping & 0x400 else 0)
            for edge, down in enumerate((1, 0)):
                records[index * 2 + edge] = RECORD(1, 0, down, 1, key, self.u.MapVirtualKeyW(key, 0), ord(character), modifiers)
        deadline = time.monotonic() + min(40, max(0, timeout))
        while True:
            info = self.info()
            prompt = self.line(info.cursor.Y, info.cursor.X)
            queued = W.DWORD()
            checked(self.k.GetNumberOfConsoleInputEvents(self.input, C.byref(queued)), "Cannot inspect the console input queue")
            if PROMPT.fullmatch(prompt) and queued.value == 0:
                break
            if time.monotonic() >= deadline:
                raise Failure(BUSY, "The console is busy or contains typed text; nothing sent, existing text preserved")
            time.sleep(0.05)
        self.alive()
        written = W.DWORD()
        if not self.k.WriteConsoleInputW(self.input, records, len(records), C.byref(written)) or written.value != len(records):
            raise Failure(DELIVERY_UNCERTAIN, "Console write incomplete; delivery uncertain. Never replay automatically")

    def close(self) -> None:
        for handle in reversed(self.handles):
            self.k.CloseHandle(handle)
        self.handles.clear()
        if self.attached:
            self.k.FreeConsole()
            self.attached = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
