"""Live UDP remote-peer discovery for Tekzite's Windows socket view.

Windows' GetExtendedUdpTable exposes only the owning PID and local endpoint.
This module augments that table with Microsoft-Windows-Kernel-Network ETW
send/receive events so the UI can display the actual remote UDP peer.

The monitor is deliberately ephemeral: events live only in process memory and
are retained for a short window while the Live Socket View is open. No packet
payload is captured or stored.
"""
from __future__ import annotations

import ctypes as ct
import ipaddress
import os
import socket
import struct
import threading
import time
import uuid

# Microsoft-Windows-Kernel-Network. Its IPv4/IPv6 keywords expose per-operation
# TCP/UDP metadata including PID, source/destination addresses and ports.
KERNEL_NETWORK_PROVIDER_GUID = "7dd42a49-5329-4832-8dfd-43d979153a88"
KERNEL_NETWORK_KEYWORD_IPV4 = 0x10
KERNEL_NETWORK_KEYWORD_IPV6 = 0x20
UDP_EVENT_IDS = {42, 43, 58, 59}  # IPv4 send/recv, IPv6 send/recv.
UDP_PEER_MAX_AGE = 30.0
UDP_PEER_MAX_ROWS = 1024


def _clean_address(value: str) -> str:
    value = str(value or "").strip()
    if "%" in value:
        value = value.split("%", 1)[0]
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return ""


def _parse_udp_kernel_network_event(event_id: int, payload: bytes):
    """Decode one Kernel-Network UDP send/receive event.

    The provider manifest defines IPv4 events 42/43 as:
      PID, size, daddr, saddr, dport, sport, seqnum, connid
    and IPv6 events 58/59 with 16-byte daddr/saddr fields. Ports are network
    byte order (trace:Port semantics), while scalar counters are little-endian.
    """
    try:
        event_id = int(event_id)
        payload = bytes(payload or b"")
    except Exception:
        return None
    if event_id not in UDP_EVENT_IDS:
        return None

    if event_id in (42, 43):
        if len(payload) < 28:
            return None
        pid, size = struct.unpack_from("<II", payload, 0)
        daddr = socket.inet_ntop(socket.AF_INET, payload[8:12])
        saddr = socket.inet_ntop(socket.AF_INET, payload[12:16])
        dport = struct.unpack_from("!H", payload, 16)[0]
        sport = struct.unpack_from("!H", payload, 18)[0]
        family = "IPv4"
    else:
        if len(payload) < 52:
            return None
        pid, size = struct.unpack_from("<II", payload, 0)
        daddr = socket.inet_ntop(socket.AF_INET6, payload[8:24])
        saddr = socket.inet_ntop(socket.AF_INET6, payload[24:40])
        dport = struct.unpack_from("!H", payload, 40)[0]
        sport = struct.unpack_from("!H", payload, 42)[0]
        family = "IPv6"

    sent = event_id in (42, 58)
    if sent:
        local_address, local_port = saddr, sport
        remote_address, remote_port = daddr, dport
        direction = "send"
    else:
        local_address, local_port = daddr, dport
        remote_address, remote_port = saddr, sport
        direction = "receive"

    return {
        "pid": int(pid),
        "family": family,
        "local_address": _clean_address(local_address),
        "local_port": int(local_port),
        "remote_address": _clean_address(remote_address),
        "remote_port": int(remote_port),
        "direction": direction,
        "size": max(0, int(size)),
    }


class _PeerLedger:
    def __init__(self, *, max_age=UDP_PEER_MAX_AGE, max_rows=UDP_PEER_MAX_ROWS):
        self.max_age = float(max_age)
        self.max_rows = int(max_rows)
        self._lock = threading.RLock()
        self._rows = {}
        self._pids = set()

    def set_pids(self, pids):
        clean = set()
        for value in list(pids or []):
            try:
                pid = int(value or 0)
            except Exception:
                pid = 0
            if pid > 0:
                clean.add(pid)
        with self._lock:
            self._pids = clean
            # Drop process rows immediately once a PID is no longer owned. This
            # prevents PID reuse from inheriting an old peer in the UI.
            for key in list(self._rows):
                if int(key[0]) not in clean:
                    self._rows.pop(key, None)

    def add(self, event, *, now=None):
        if not event:
            return False
        now = float(time.time() if now is None else now)
        pid = int(event.get("pid") or 0)
        with self._lock:
            if pid <= 0 or pid not in self._pids:
                return False
            local_address = _clean_address(event.get("local_address"))
            remote_address = _clean_address(event.get("remote_address"))
            local_port = int(event.get("local_port") or 0)
            remote_port = int(event.get("remote_port") or 0)
            family = str(event.get("family") or "")
            if not local_port or not remote_address or not remote_port:
                return False
            key = (pid, family, local_address, local_port, remote_address, remote_port)
            row = self._rows.get(key)
            if row is None:
                if len(self._rows) >= self.max_rows:
                    oldest = min(self._rows, key=lambda k: float(self._rows[k].get("last_seen", 0.0)))
                    self._rows.pop(oldest, None)
                row = {
                    "pid": pid,
                    "family": family,
                    "local_address": local_address,
                    "local_port": local_port,
                    "remote_address": remote_address,
                    "remote_port": remote_port,
                    "first_seen": now,
                    "last_seen": now,
                    "tx_packets": 0,
                    "rx_packets": 0,
                    "tx_bytes": 0,
                    "rx_bytes": 0,
                }
                self._rows[key] = row
            size = max(0, int(event.get("size") or 0))
            if str(event.get("direction")) == "receive":
                row["rx_packets"] += 1
                row["rx_bytes"] += size
            else:
                row["tx_packets"] += 1
                row["tx_bytes"] += size
            row["last_seen"] = now
            self._prune_locked(now)
            return True

    def _prune_locked(self, now):
        cutoff = float(now) - self.max_age
        for key in list(self._rows):
            if float(self._rows[key].get("last_seen", 0.0)) < cutoff:
                self._rows.pop(key, None)

    def snapshot(self, *, now=None):
        now = float(time.time() if now is None else now)
        with self._lock:
            self._prune_locked(now)
            rows = [dict(row) for row in self._rows.values()]
        rows.sort(key=lambda row: float(row.get("last_seen", 0.0)), reverse=True)
        return rows


class UdpPeerMonitor:
    """Small real-time ETW consumer for Kernel-Network UDP events."""

    def __init__(self):
        self.ledger = _PeerLedger()
        self._lock = threading.RLock()
        self._thread = None
        self._session_handle = 0
        self._trace_handle = 0
        self._session_name = ""
        self._properties_buffer = None
        self._callback = None
        self._stop_requested = False
        self._status = "stopped"
        self._reason = ""

    @property
    def status(self):
        with self._lock:
            return self._status, self._reason

    def set_pids(self, pids):
        self.ledger.set_pids(pids)

    def start(self):
        if os.name != "nt":
            with self._lock:
                self._status = "unsupported"
                self._reason = "UDP ETW peer tracing is available on Windows only."
            return False
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self._status == "running"
            # A permission/provider failure is sticky for the lifetime of this
            # view. Avoid starting a brand-new failed ETW session every 250 ms;
            # closing/reopening the Live Socket View resets the monitor.
            if self._thread is not None and self._status in {"permission", "error"}:
                return False
            self._stop_requested = False
            self._status = "starting"
            self._reason = ""
            self._thread = threading.Thread(target=self._run, name="TekziteUdpPeerETW", daemon=True)
            self._thread.start()
        # Do not block the UI on ETW startup. The next snapshot will report the
        # status and peers as soon as the session is live.
        return True

    def stop(self):
        with self._lock:
            self._stop_requested = True
            session_handle = self._session_handle
            session_name = self._session_name
            props = self._properties_buffer
            trace_handle = self._trace_handle
        if os.name == "nt":
            try:
                api = _EtwApi.instance()
                if session_handle and props is not None:
                    api.ControlTraceW(
                        _TRACEHANDLE(session_handle), session_name,
                        ct.cast(props, ct.POINTER(_EVENT_TRACE_PROPERTIES)), EVENT_TRACE_CONTROL_STOP,
                    )
                if trace_handle and trace_handle != INVALID_PROCESSTRACE_HANDLE:
                    api.CloseTrace(_TRACEHANDLE(trace_handle))
            except Exception:
                pass
        thread = None
        with self._lock:
            thread = self._thread
        if thread is not None and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=0.8)
        with self._lock:
            self._thread = None
            self._session_handle = 0
            self._trace_handle = 0
            self._properties_buffer = None
            self._callback = None
            self._session_name = ""
            self._status = "stopped"
            self._reason = ""

    def snapshot(self):
        status, reason = self.status
        return {"status": status, "reason": reason, "peers": self.ledger.snapshot()}

    def _run(self):
        try:
            self._run_windows()
        except Exception as exc:
            with self._lock:
                self._status = "error"
                self._reason = f"ETW UDP peer monitor failed: {exc}"
        finally:
            with self._lock:
                self._session_handle = 0
                self._trace_handle = 0
                self._properties_buffer = None
                self._callback = None
                if self._status == "running":
                    self._status = "stopped"

    def _run_windows(self):
        api = _EtwApi.instance()
        session_name = f"TekziteUdpPeers-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        props_buf, props_ptr = _make_trace_properties(session_name)
        session = _TRACEHANDLE(0)
        status = int(api.StartTraceW(ct.byref(session), session_name, props_ptr))
        if status != ERROR_SUCCESS:
            reason = _etw_error_text(status)
            with self._lock:
                self._status = "permission" if status == ERROR_ACCESS_DENIED else "error"
                self._reason = reason
            return

        provider = _guid_from_string(KERNEL_NETWORK_PROVIDER_GUID)
        status = int(api.EnableTraceEx2(
            session, ct.byref(provider), EVENT_CONTROL_CODE_ENABLE_PROVIDER,
            TRACE_LEVEL_INFORMATION,
            KERNEL_NETWORK_KEYWORD_IPV4 | KERNEL_NETWORK_KEYWORD_IPV6,
            0, 0, None,
        ))
        if status != ERROR_SUCCESS:
            api.ControlTraceW(session, session_name, props_ptr, EVENT_TRACE_CONTROL_STOP)
            with self._lock:
                self._status = "permission" if status == ERROR_ACCESS_DENIED else "error"
                self._reason = _etw_error_text(status)
            return

        def on_event(record_ptr):
            try:
                record = record_ptr.contents
                if not _guid_equal(record.EventHeader.ProviderId, provider):
                    return
                event_id = int(record.EventHeader.EventDescriptor.Id)
                if event_id not in UDP_EVENT_IDS:
                    return
                length = int(record.UserDataLength or 0)
                if length <= 0 or not record.UserData:
                    return
                payload = ct.string_at(record.UserData, length)
                event = _parse_udp_kernel_network_event(event_id, payload)
                self.ledger.add(event)
            except Exception:
                # ETW callbacks must never unwind through advapi32.
                return

        callback = _EVENT_RECORD_CALLBACK(on_event)
        logfile = _EVENT_TRACE_LOGFILEW()
        logfile.LoggerName = session_name
        logfile.ProcessTraceMode = PROCESS_TRACE_MODE_REAL_TIME | PROCESS_TRACE_MODE_EVENT_RECORD
        logfile.EventRecordCallback = callback
        trace = api.OpenTraceW(ct.byref(logfile))
        if int(trace) == INVALID_PROCESSTRACE_HANDLE:
            err = int(ct.get_last_error() or 0)
            api.ControlTraceW(session, session_name, props_ptr, EVENT_TRACE_CONTROL_STOP)
            with self._lock:
                self._status = "error"
                self._reason = _etw_error_text(err or 1)
            return

        with self._lock:
            self._session_handle = int(session.value)
            self._trace_handle = int(trace)
            self._session_name = session_name
            self._properties_buffer = props_buf
            self._callback = callback
            self._status = "running"
            self._reason = ""

        handle_array = (_TRACEHANDLE * 1)(_TRACEHANDLE(trace))
        result = int(api.ProcessTrace(handle_array, 1, None, None))
        # ERROR_CANCELLED is the normal result when ControlTrace stops a live session.
        if result not in (ERROR_SUCCESS, ERROR_CANCELLED):
            with self._lock:
                if not self._stop_requested:
                    self._status = "error"
                    self._reason = _etw_error_text(result)


# ---- Minimal Win32 ETW declarations. Kept local so Tekzite has no runtime
# dependency on third-party packet-capture or ETW packages. -----------------

ERROR_SUCCESS = 0
ERROR_ACCESS_DENIED = 5
ERROR_CANCELLED = 1223
EVENT_TRACE_CONTROL_STOP = 1
EVENT_TRACE_REAL_TIME_MODE = 0x00000100
EVENT_TRACE_NO_PER_PROCESSOR_BUFFERING = 0x10000000
PROCESS_TRACE_MODE_REAL_TIME = 0x00000100
PROCESS_TRACE_MODE_EVENT_RECORD = 0x10000000
EVENT_CONTROL_CODE_ENABLE_PROVIDER = 1
TRACE_LEVEL_INFORMATION = 4
WNODE_FLAG_TRACED_GUID = 0x00020000
INVALID_PROCESSTRACE_HANDLE = (1 << 64) - 1
_TRACEHANDLE = ct.c_ulonglong


class _GUID(ct.Structure):
    _fields_ = [
        ("Data1", ct.c_uint32), ("Data2", ct.c_uint16), ("Data3", ct.c_uint16),
        ("Data4", ct.c_ubyte * 8),
    ]


def _guid_from_string(value):
    parsed = uuid.UUID(str(value))
    raw = parsed.bytes_le
    result = _GUID()
    result.Data1, result.Data2, result.Data3 = struct.unpack_from("<IHH", raw, 0)
    result.Data4[:] = raw[8:16]
    return result


def _guid_equal(left, right):
    return bytes(ct.string_at(ct.byref(left), ct.sizeof(_GUID))) == bytes(ct.string_at(ct.byref(right), ct.sizeof(_GUID)))


class _WNODE_UNION1(ct.Union):
    class _VERSION_LINKAGE(ct.Structure):
        _fields_ = [("Version", ct.c_uint32), ("Linkage", ct.c_uint32)]
    _fields_ = [("HistoricalContext", ct.c_uint64), ("VersionLinkage", _VERSION_LINKAGE)]


class _WNODE_UNION2(ct.Union):
    _fields_ = [("KernelHandle", ct.c_void_p), ("TimeStamp", ct.c_int64)]


class _WNODE_HEADER(ct.Structure):
    _anonymous_ = ("u1", "u2")
    _fields_ = [
        ("BufferSize", ct.c_uint32), ("ProviderId", ct.c_uint32),
        ("u1", _WNODE_UNION1), ("u2", _WNODE_UNION2),
        ("Guid", _GUID), ("ClientContext", ct.c_uint32), ("Flags", ct.c_uint32),
    ]


class _EVENT_TRACE_PROPERTIES(ct.Structure):
    _fields_ = [
        ("Wnode", _WNODE_HEADER),
        ("BufferSize", ct.c_uint32), ("MinimumBuffers", ct.c_uint32),
        ("MaximumBuffers", ct.c_uint32), ("MaximumFileSize", ct.c_uint32),
        ("LogFileMode", ct.c_uint32), ("FlushTimer", ct.c_uint32),
        ("EnableFlags", ct.c_uint32), ("AgeLimit", ct.c_int32),
        ("NumberOfBuffers", ct.c_uint32), ("FreeBuffers", ct.c_uint32),
        ("EventsLost", ct.c_uint32), ("BuffersWritten", ct.c_uint32),
        ("LogBuffersLost", ct.c_uint32), ("RealTimeBuffersLost", ct.c_uint32),
        ("LoggerThreadId", ct.c_void_p), ("LogFileNameOffset", ct.c_uint32),
        ("LoggerNameOffset", ct.c_uint32),
    ]


class _EVENT_DESCRIPTOR(ct.Structure):
    _fields_ = [
        ("Id", ct.c_uint16), ("Version", ct.c_ubyte), ("Channel", ct.c_ubyte),
        ("Level", ct.c_ubyte), ("Opcode", ct.c_ubyte), ("Task", ct.c_uint16),
        ("Keyword", ct.c_uint64),
    ]


class _EVENT_HEADER(ct.Structure):
    _fields_ = [
        ("Size", ct.c_uint16), ("HeaderType", ct.c_uint16),
        ("Flags", ct.c_uint16), ("EventProperty", ct.c_uint16),
        ("ThreadId", ct.c_uint32), ("ProcessId", ct.c_uint32),
        ("TimeStamp", ct.c_int64), ("ProviderId", _GUID),
        ("EventDescriptor", _EVENT_DESCRIPTOR),
        ("KernelTime", ct.c_uint32), ("UserTime", ct.c_uint32),
        ("ActivityId", _GUID),
    ]


class _ETW_BUFFER_CONTEXT(ct.Structure):
    _fields_ = [("ProcessorNumber", ct.c_ubyte), ("Alignment", ct.c_ubyte), ("LoggerId", ct.c_uint16)]


class _EVENT_HEADER_EXTENDED_DATA_ITEM(ct.Structure):
    _fields_ = [
        ("Reserved1", ct.c_uint16), ("ExtType", ct.c_uint16),
        ("Linkage", ct.c_uint16), ("DataSize", ct.c_uint16),
        ("DataPtr", ct.c_uint64),
    ]


class _EVENT_RECORD(ct.Structure):
    _fields_ = [
        ("EventHeader", _EVENT_HEADER), ("BufferContext", _ETW_BUFFER_CONTEXT),
        ("ExtendedDataCount", ct.c_uint16), ("UserDataLength", ct.c_uint16),
        ("ExtendedData", ct.POINTER(_EVENT_HEADER_EXTENDED_DATA_ITEM)),
        ("UserData", ct.c_void_p), ("UserContext", ct.c_void_p),
    ]


_EVENT_RECORD_CALLBACK = ct.WINFUNCTYPE(None, ct.POINTER(_EVENT_RECORD)) if hasattr(ct, "WINFUNCTYPE") else ct.CFUNCTYPE(None, ct.POINTER(_EVENT_RECORD))


class _EVENT_TRACE_HEADER_CLASS(ct.Structure):
    _fields_ = [("Type", ct.c_ubyte), ("Level", ct.c_ubyte), ("Version", ct.c_uint16)]


class _EVENT_TRACE_HEADER(ct.Structure):
    _fields_ = [
        ("Size", ct.c_uint16), ("HeaderType", ct.c_ubyte), ("MarkerFlags", ct.c_ubyte),
        ("Class", _EVENT_TRACE_HEADER_CLASS), ("ThreadId", ct.c_uint32),
        ("ProcessId", ct.c_uint32), ("TimeStamp", ct.c_int64), ("Guid", _GUID),
        ("ClientContext", ct.c_uint32), ("Flags", ct.c_uint32),
    ]


class _EVENT_TRACE(ct.Structure):
    _fields_ = [
        ("Header", _EVENT_TRACE_HEADER), ("InstanceId", ct.c_uint32),
        ("ParentInstanceId", ct.c_uint32), ("ParentGuid", _GUID),
        ("MofData", ct.c_void_p), ("MofLength", ct.c_uint32), ("ClientContext", ct.c_uint32),
    ]


class _SYSTEMTIME(ct.Structure):
    _fields_ = [
        ("wYear", ct.c_uint16), ("wMonth", ct.c_uint16), ("wDayOfWeek", ct.c_uint16),
        ("wDay", ct.c_uint16), ("wHour", ct.c_uint16), ("wMinute", ct.c_uint16),
        ("wSecond", ct.c_uint16), ("wMilliseconds", ct.c_uint16),
    ]


class _TIME_ZONE_INFORMATION(ct.Structure):
    _fields_ = [
        ("Bias", ct.c_int32), ("StandardName", ct.c_wchar * 32),
        ("StandardDate", _SYSTEMTIME), ("StandardBias", ct.c_int32),
        ("DaylightName", ct.c_wchar * 32), ("DaylightDate", _SYSTEMTIME),
        ("DaylightBias", ct.c_int32),
    ]


class _TRACE_LOGFILE_HEADER(ct.Structure):
    _fields_ = [
        ("BufferSize", ct.c_uint32), ("MajorVersion", ct.c_ubyte),
        ("MinorVersion", ct.c_ubyte), ("SubVersion", ct.c_ubyte),
        ("SubMinorVersion", ct.c_ubyte), ("ProviderVersion", ct.c_uint32),
        ("NumberOfProcessors", ct.c_uint32), ("EndTime", ct.c_int64),
        ("TimerResolution", ct.c_uint32), ("MaximumFileSize", ct.c_uint32),
        ("LogFileMode", ct.c_uint32), ("BuffersWritten", ct.c_uint32),
        ("StartBuffers", ct.c_uint32), ("PointerSize", ct.c_uint32),
        ("EventsLost", ct.c_uint32), ("CpuSpeedInMHz", ct.c_uint32),
        ("LoggerName", ct.c_wchar_p), ("LogFileName", ct.c_wchar_p),
        ("TimeZone", _TIME_ZONE_INFORMATION), ("BootTime", ct.c_int64),
        ("PerfFreq", ct.c_int64), ("StartTime", ct.c_int64),
        ("ReservedFlags", ct.c_uint32), ("BuffersLost", ct.c_uint32),
    ]


class _EVENT_TRACE_LOGFILEW(ct.Structure):
    pass


_EVENT_TRACE_BUFFER_CALLBACK = (ct.WINFUNCTYPE(ct.c_uint32, ct.POINTER(_EVENT_TRACE_LOGFILEW))
                                if hasattr(ct, "WINFUNCTYPE") else ct.CFUNCTYPE(ct.c_uint32, ct.POINTER(_EVENT_TRACE_LOGFILEW)))
_EVENT_TRACE_LOGFILEW._fields_ = [
    ("LogFileName", ct.c_wchar_p), ("LoggerName", ct.c_wchar_p),
    ("CurrentTime", ct.c_int64), ("BuffersRead", ct.c_uint32),
    ("ProcessTraceMode", ct.c_uint32), ("CurrentEvent", _EVENT_TRACE),
    ("LogfileHeader", _TRACE_LOGFILE_HEADER), ("BufferCallback", _EVENT_TRACE_BUFFER_CALLBACK),
    ("BufferSize", ct.c_uint32), ("Filled", ct.c_uint32), ("EventsLost", ct.c_uint32),
    ("EventRecordCallback", _EVENT_RECORD_CALLBACK), ("IsKernelTrace", ct.c_uint32),
    ("Context", ct.c_void_p),
]


def _make_trace_properties(session_name):
    name_bytes = (len(session_name) + 1) * ct.sizeof(ct.c_wchar)
    total = ct.sizeof(_EVENT_TRACE_PROPERTIES) + name_bytes
    buf = ct.create_string_buffer(total)
    ptr = ct.cast(buf, ct.POINTER(_EVENT_TRACE_PROPERTIES))
    props = ptr.contents
    props.Wnode.BufferSize = total
    props.Wnode.ClientContext = 1
    props.Wnode.Flags = WNODE_FLAG_TRACED_GUID
    props.BufferSize = 64  # KB per ETW buffer
    props.MinimumBuffers = 2
    props.MaximumBuffers = 8
    props.LogFileMode = EVENT_TRACE_REAL_TIME_MODE | EVENT_TRACE_NO_PER_PROCESSOR_BUFFERING
    props.FlushTimer = 1
    props.LoggerNameOffset = ct.sizeof(_EVENT_TRACE_PROPERTIES)
    name_addr = ct.addressof(buf) + props.LoggerNameOffset
    ct.memmove(name_addr, ct.create_unicode_buffer(session_name), name_bytes)
    return buf, ptr


def _etw_error_text(code):
    code = int(code or 0)
    if code == ERROR_ACCESS_DENIED:
        return "Windows denied Kernel-Network ETW access; run Tekzite elevated to resolve UDP remote peers."
    try:
        text = ct.FormatError(code).strip()
    except Exception:
        text = ""
    return f"Kernel-Network ETW error {code}{': ' + text if text else ''}"


class _EtwApi:
    _value = None
    _lock = threading.Lock()

    @classmethod
    def instance(cls):
        with cls._lock:
            if cls._value is not None:
                return cls._value
            if os.name != "nt":
                raise RuntimeError("ETW is available on Windows only")
            advapi = ct.WinDLL("advapi32", use_last_error=True)
            api = type("EtwApi", (), {})()
            api.StartTraceW = advapi.StartTraceW
            api.StartTraceW.argtypes = [ct.POINTER(_TRACEHANDLE), ct.c_wchar_p, ct.POINTER(_EVENT_TRACE_PROPERTIES)]
            api.StartTraceW.restype = ct.c_uint32
            api.ControlTraceW = advapi.ControlTraceW
            api.ControlTraceW.argtypes = [_TRACEHANDLE, ct.c_wchar_p, ct.POINTER(_EVENT_TRACE_PROPERTIES), ct.c_uint32]
            api.ControlTraceW.restype = ct.c_uint32
            api.EnableTraceEx2 = advapi.EnableTraceEx2
            api.EnableTraceEx2.argtypes = [
                _TRACEHANDLE, ct.POINTER(_GUID), ct.c_uint32, ct.c_ubyte,
                ct.c_uint64, ct.c_uint64, ct.c_uint32, ct.c_void_p,
            ]
            api.EnableTraceEx2.restype = ct.c_uint32
            api.OpenTraceW = advapi.OpenTraceW
            api.OpenTraceW.argtypes = [ct.POINTER(_EVENT_TRACE_LOGFILEW)]
            api.OpenTraceW.restype = _TRACEHANDLE
            api.ProcessTrace = advapi.ProcessTrace
            api.ProcessTrace.argtypes = [ct.POINTER(_TRACEHANDLE), ct.c_uint32, ct.c_void_p, ct.c_void_p]
            api.ProcessTrace.restype = ct.c_uint32
            api.CloseTrace = advapi.CloseTrace
            api.CloseTrace.argtypes = [_TRACEHANDLE]
            api.CloseTrace.restype = ct.c_uint32
            cls._value = api
            return api


_MONITOR = UdpPeerMonitor()


def ensure_udp_peer_monitor(pids=None):
    _MONITOR.set_pids(pids or [])
    _MONITOR.start()
    return _MONITOR.snapshot()


def udp_peer_snapshot(pids=None):
    if pids is not None:
        _MONITOR.set_pids(pids)
    return _MONITOR.snapshot()


def stop_udp_peer_monitor():
    _MONITOR.stop()


__all__ = [
    "ensure_udp_peer_monitor", "udp_peer_snapshot", "stop_udp_peer_monitor",
    "UdpPeerMonitor", "_PeerLedger", "_parse_udp_kernel_network_event",
]
