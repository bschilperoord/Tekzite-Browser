from __future__ import annotations

"""Low-risk Windows latency tuning for Tekzite Browser.

This module intentionally avoids undocumented hooks and never touches Tekzite's
DWM/window-procedure path.  It only adjusts the current process/thread scheduler
policy and timer resolution, then restores the timer resolution on shutdown.
"""

import atexit
import ctypes
from ctypes import wintypes
import os
import sys
import threading

_APPLIED = False
_TIMER_1MS = False
_STATUS = {
    "enabled": False,
    "platform": os.name,
    "timer_1ms": False,
    "process_above_normal": False,
    "ui_thread_above_normal": False,
    "power_throttling_disabled": False,
    "python_switch_interval_ms": None,
}


def _restore_timer_resolution() -> None:
    global _TIMER_1MS
    if not _TIMER_1MS or os.name != "nt":
        return
    try:
        ctypes.WinDLL("winmm").timeEndPeriod(1)
    except Exception:
        pass
    _TIMER_1MS = False


def apply_ultraspeed() -> dict:
    """Apply idempotent, conservative latency tuning and return diagnostics."""
    global _APPLIED, _TIMER_1MS
    if _APPLIED:
        return dict(_STATUS)

    _APPLIED = True
    os.environ["TEKZITE_ULTRASPEED"] = "1"

    # Shorten GIL hand-off latency between Tk's UI thread and Tekzite's worker
    # threads without using an excessively tiny interval that would waste CPU.
    try:
        sys.setswitchinterval(0.002)
        _STATUS["python_switch_interval_ms"] = round(sys.getswitchinterval() * 1000.0, 3)
    except Exception:
        pass

    if os.name != "nt":
        _STATUS["enabled"] = True
        return dict(_STATUS)

    try:
        winmm = ctypes.WinDLL("winmm")
        if int(winmm.timeBeginPeriod(1)) == 0:
            _TIMER_1MS = True
            _STATUS["timer_1ms"] = True
            atexit.register(_restore_timer_resolution)
    except Exception:
        pass

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        process = kernel32.GetCurrentProcess()

        # ABOVE_NORMAL_PRIORITY_CLASS. Deliberately not HIGH/REALTIME so
        # Chromium, audio and the rest of Windows still get fair scheduling.
        ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
        if kernel32.SetPriorityClass(process, ABOVE_NORMAL_PRIORITY_CLASS):
            _STATUS["process_above_normal"] = True

        # Give the Tk/UI thread a small latency bias inside the process.
        THREAD_PRIORITY_ABOVE_NORMAL = 1
        thread = kernel32.GetCurrentThread()
        if kernel32.SetThreadPriority(thread, THREAD_PRIORITY_ABOVE_NORMAL):
            _STATUS["ui_thread_above_normal"] = True

        # Keep Windows from placing the browser into execution-speed throttling
        # (EcoQoS-style power throttling). Failure is harmless on older systems.
        class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
            _fields_ = [
                ("Version", wintypes.DWORD),
                ("ControlMask", wintypes.DWORD),
                ("StateMask", wintypes.DWORD),
            ]

        ProcessPowerThrottling = 4
        PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1
        PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1
        state = PROCESS_POWER_THROTTLING_STATE(
            PROCESS_POWER_THROTTLING_CURRENT_VERSION,
            PROCESS_POWER_THROTTLING_EXECUTION_SPEED,
            0,
        )
        try:
            kernel32.SetProcessInformation.argtypes = [
                wintypes.HANDLE,
                ctypes.c_int,
                ctypes.c_void_p,
                wintypes.DWORD,
            ]
            kernel32.SetProcessInformation.restype = wintypes.BOOL
            if kernel32.SetProcessInformation(
                process,
                ProcessPowerThrottling,
                ctypes.byref(state),
                ctypes.sizeof(state),
            ):
                _STATUS["power_throttling_disabled"] = True
        except Exception:
            pass
    except Exception:
        pass

    _STATUS["enabled"] = True
    return dict(_STATUS)


def status() -> dict:
    return dict(_STATUS)
