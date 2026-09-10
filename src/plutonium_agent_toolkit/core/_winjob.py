"""Minimal Windows Job Object wrapper (KILL_ON_JOB_CLOSE). Imported only on Windows."""
import ctypes
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
