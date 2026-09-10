"""Minimal Windows Job Object wrapper (KILL_ON_JOB_CLOSE). Imported only on Windows."""
import ctypes
import time
from ctypes import wintypes as W

from .errors import BACKEND_FAILED, Failure

k = ctypes.WinDLL("kernel32", use_last_error=True)
k.CreateJobObjectW.argtypes = [W.LPVOID, W.LPCWSTR]
k.CreateJobObjectW.restype = W.HANDLE
k.SetInformationJobObject.argtypes = [W.HANDLE, ctypes.c_int, W.LPVOID, W.DWORD]
k.SetInformationJobObject.restype = W.BOOL
k.AssignProcessToJobObject.argtypes = [W.HANDLE, W.HANDLE]
k.AssignProcessToJobObject.restype = W.BOOL
k.TerminateJobObject.argtypes = [W.HANDLE, W.UINT]
k.TerminateJobObject.restype = W.BOOL
k.CloseHandle.argtypes = [W.HANDLE]
k.CloseHandle.restype = W.BOOL
k.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, W.LPVOID, W.DWORD, W.DWORD, W.HANDLE]
k.CreateFileW.restype = W.HANDLE

INVALID_HANDLE_VALUE = W.HANDLE(-1).value
GENERIC_READ = 0x80000000
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80
ERROR_SHARING_VIOLATION = 32


class _Basic(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", W.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", W.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", W.DWORD), ("SchedulingClass", W.DWORD)]


class _Io(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                 "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _Extended(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", _Io), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


def create_job():
    handle = k.CreateJobObjectW(None, None)
    if not handle:
        raise Failure(BACKEND_FAILED, "CreateJobObject failed: " + str(ctypes.WinError(ctypes.get_last_error())))
    info = _Extended()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not k.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
        k.CloseHandle(handle)
        raise Failure(BACKEND_FAILED, "SetInformationJobObject failed: " + str(ctypes.WinError(ctypes.get_last_error())))
    return handle


def assign(handle, process) -> None:
    if not k.AssignProcessToJobObject(handle, W.HANDLE(int(process._handle))):
        raise Failure(BACKEND_FAILED, "AssignProcessToJobObject failed: " + str(ctypes.WinError(ctypes.get_last_error())))


def terminate(handle) -> None:
    k.TerminateJobObject(handle, 130)
    k.CloseHandle(handle)


def wait_until_released(path, timeout: float = 2.0) -> bool:
    """Wait until no other handle to *path* is open; True once it is free or absent.

    Windows closes a terminated process's inherited handles slightly after its process
    object signals, so deleting a job directory right after ``run()`` killed a backend
    tree could fail with ERROR_SHARING_VIOLATION on the step log. Polls an exclusive open
    (share mode 0) until it succeeds or *timeout* seconds pass."""
    deadline = time.monotonic() + timeout
    while True:
        handle = k.CreateFileW(str(path), GENERIC_READ, 0, None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
        if handle != INVALID_HANDLE_VALUE:
            k.CloseHandle(handle)
            return True
        if ctypes.get_last_error() != ERROR_SHARING_VIOLATION:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.001)
