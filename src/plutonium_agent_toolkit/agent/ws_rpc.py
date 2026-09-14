"""Bounded, one-call Effect JSON RPC transport for T3 orchestration protocol 2.

Only launchThread and dispatchCommand are admitted. Authentication is an upgrade header,
never a URL or RPC payload. A write is never retried; loss after send is uncertain.

Wire contract (effect@4.0.0-rc.112 RpcMessage/RpcSerialization schemas; see docs/AGENT-HOSTS.md):
- URL: http(s)://host[:port] becomes ws(s)://host[:port]/ws?orchestrationProtocol=2. The
  sync client never follows redirects and never uses a proxy (``proxy=None``).
- One text frame: ``{"_tag": "Request", "id": <client string>, "tag": <method>,
  "payload": {...}, "headers": []}``. The bearer travels only in the WebSocket upgrade
  ``Authorization`` header, so it never appears in a URL, frame or receipt.
- Replies may batch (a JSON array of messages). The terminal message for this call is
  ``{"_tag": "Exit", "requestId": <our id>, "exit": ...}`` with exit
  ``{"_tag": "Success", "value": <object>}`` or ``{"_tag": "Failure", "cause": [...]}``.
  Ping/Pong/Ack/Eof/Request/Chunk/Interrupt frames and Exits for other request ids are
  skipped; ``{"_tag": "Defect"}`` and ``ClientProtocolError`` end the call as uncertain.
- ``Fail`` error tags map to stable error codes; anything unexplained stays uncertain.

Bounds: one Request per call, never retried; total wall time ``timeout`` shared by
handshake, send and wait (unrelated frames never reset it), plus at most one second for close; ``MAX_BODY`` bytes per frame
in both directions. The sync websockets ``send`` has no timeout argument and the socket is
blocking after the handshake, so the remaining budget is installed as a socket timeout
around the send and removed afterwards. Failure messages carry no exception text, close
reason or server response detail, so no bearer or server secret can reach a receipt; the
connection logger is an isolated, non-propagating, disabled logger.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.parse
import uuid

from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

from ..core.errors import (BACKEND_FAILED, BACKEND_TIMEOUT, CONFIG_INVALID, DELIVERY_UNCERTAIN,
                           INPUT_INVALID, INPUT_LIMIT, NOT_IMPLEMENTED, Failure)

PROTOCOL = 2
WS_PATH = "/ws"
MAX_BODY = 8 * 1024 * 1024
MAX_TIMEOUT = 600.0
CLOSE_TIMEOUT = 1.0
ALLOWED_METHODS = frozenset(("orchestration.launchThread", "orchestration.dispatchCommand"))
REJECTION_CODES = {
    "OrchestrationV2DispatchCommandError": INPUT_INVALID,
    "OrchestrationV2ThreadLaunchError": INPUT_INVALID,
    "EnvironmentAuthorizationError": CONFIG_INVALID,
}
SKIP_TAGS = frozenset(("Ping", "Pong", "Ack", "Eof", "Request", "Chunk", "Interrupt"))
UNCERTAIN_HINT = ("The command may have been applied. Inspect agent status before sending "
                   "anything again; never replay the command.")


def _logger() -> logging.Logger:
    """An isolated logger that can never emit: not registered with the logging manager,
    non-propagating, disabled. websockets logs handshake and close detail through it."""
    log = logging.Logger("pat.ws_rpc." + uuid.uuid4().hex)
    log.propagate = False
    log.disabled = True
    return log


def ws_url(origin: str) -> str:
    """The protocol-2 WebSocket endpoint for an http(s) origin. No bearer, ever."""
    parsed = urllib.parse.urlsplit(origin if "://" in origin else "http://" + str(origin))
    host = parsed.hostname
    try:
        port = parsed.port
    except ValueError as exc:
        raise Failure(INPUT_INVALID, f"Server origin has an invalid port: {origin!r}") from exc
    if parsed.scheme not in ("http", "https") or not host or parsed.path not in ("", "/") \
            or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise Failure(INPUT_INVALID, f"Server origin must be http(s)://host[:port]: {origin!r}")
    scheme = "ws" if parsed.scheme == "http" else "wss"
    authority = f"[{host}]" if ":" in host else host
    return f"{scheme}://{authority}" + (f":{port}" if port is not None else "") \
        + WS_PATH + f"?orchestrationProtocol={PROTOCOL}"


def _uncertain(method: str, request_id: str, what: str) -> Failure:
    return Failure(DELIVERY_UNCERTAIN, f"{method} request {request_id} was sent, but {what}",
                   UNCERTAIN_HINT, method=method, request_id=request_id)


def _handshake_failure(url: str, status: int | None) -> Failure:
    if status in (401, 403):
        what = ("the server rejected the bearer token" if status == 401
                else "the token lacks the required orchestration scope")
        return Failure(CONFIG_INVALID, f"WebSocket handshake to {url} was refused (HTTP {status}): {what}",
                       "Issue a token with your T3 Code CLI (t3 auth session issue --token-only), "
                       "then pat configure --t3-bearer-token <token>.")
    if status == 426:
        return Failure(NOT_IMPLEMENTED, f"WebSocket handshake to {url} was refused (HTTP 426): "
                       "the server requires a different orchestration protocol",
                       "Run pat agent probe and compare orchestrationProtocol with docs/AGENT-HOSTS.md.")
    if status is None:
        return Failure(BACKEND_FAILED, f"WebSocket handshake to {url} was refused",
                       "Is the T3 Code server running? pat agent probe finds it.")
    return Failure(BACKEND_FAILED, f"WebSocket handshake to {url} was refused (HTTP {status})",
                   "Is the T3 Code server running? pat agent probe finds it.")


def _open(url: str, bearer: str, deadline: float) -> object:
    """Pre-send: a failure here means the command was never written, so it is never
    uncertain. Statuses, origins and seconds appear in messages; response bodies never."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise Failure(BACKEND_TIMEOUT, f"The WebSocket handshake to {url} did not fit the call budget",
                      "Nothing was sent; nothing needs inspecting.")
    try:
        return connect(url, additional_headers={"Authorization": "Bearer " + bearer}, proxy=None,
                       max_size=MAX_BODY, open_timeout=remaining, close_timeout=min(CLOSE_TIMEOUT, remaining),
                       logger=_logger())
    except InvalidStatus as exc:
        response = getattr(exc, "response", None)
        raise _handshake_failure(url, getattr(response, "status_code", None)) from exc
    except TimeoutError as exc:
        raise Failure(BACKEND_TIMEOUT, f"The WebSocket handshake to {url} did not complete in time",
                      "Nothing was sent; nothing needs inspecting.") from exc
    except Exception as exc:
        raise Failure(BACKEND_FAILED, f"Cannot open the orchestration WebSocket at {url}",
                      "Is the T3 Code server running? pat agent probe finds it.") from exc


def _send(sock: object, body: str, deadline: float, method: str, request_id: str) -> None:
    """One Request frame. Any loss from here on is uncertain: the server may have read it.
    websockets.sync send has no timeout, so the remaining budget bounds the blocking write
    through the socket timeout; a stall fails the send (and the call) at the deadline."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise Failure(BACKEND_TIMEOUT, f"{method} request {request_id} was not sent: the call budget ran out",
                      "Nothing was sent; nothing needs inspecting.", method=method, request_id=request_id)
    raw = getattr(sock, "socket", None)
    bounded = False
    if raw is not None:
        try:
            raw.settimeout(remaining)
            bounded = True
        except OSError as exc:
            raise Failure(BACKEND_FAILED, "Cannot bound the WebSocket write; no command was sent",
                          method=method, request_id=request_id) from exc
    try:
        sock.send(body)
    except TimeoutError as exc:
        raise _uncertain(method, request_id, "the write did not finish within the call budget") from exc
    except Exception as exc:
        raise _uncertain(method, request_id, "the connection failed while writing it") from exc
    finally:
        if bounded:
            try:
                raw.settimeout(None)
            except OSError:
                pass


def _decode(frame: object) -> list:
    """Parse one frame into messages; a frame may batch a JSON array. Raises ValueError
    for anything malformed, oversized or non-object, all of which is uncertain."""
    if isinstance(frame, (bytes, bytearray)):
        text = frame.decode("utf-8")
        size = len(frame)
    elif isinstance(frame, str):
        text = frame
        size = len(frame.encode("utf-8", "surrogatepass"))
    else:
        raise ValueError("frame is neither text nor bytes")
    if size > MAX_BODY:
        raise ValueError("frame exceeds the message bound")
    value = json.loads(text)
    messages = value if isinstance(value, list) else [value]
    if any(not isinstance(m, dict) for m in messages):
        raise ValueError("frame contains a non-object message")
    return messages


def _exit(method: str, request_id: str, exit_: object) -> dict | None:
    """The terminal Exit for our id: its value, or a mapped, sanitized Failure."""
    if not isinstance(exit_, dict):
        raise _uncertain(method, request_id, "its Exit envelope is malformed")
    tag = exit_.get("_tag")
    if tag == "Success":
        value = exit_.get("value")
        if not isinstance(value, dict):
            raise _uncertain(method, request_id, "its success value is not an object")
        return value
    if tag != "Failure":
        raise _uncertain(method, request_id, "its Exit has no Success or Failure tag")
    cause = exit_.get("cause")
    if not isinstance(cause, list) or not cause:
        raise _uncertain(method, request_id, "its Failure carries no readable cause")
    tags = []
    for step in cause:
        error = step.get("error") if isinstance(step, dict) else None
        error_tag = error.get("_tag") if isinstance(error, dict) else None
        if not isinstance(step, dict) or step.get("_tag") != "Fail" or not isinstance(error_tag, str) or error_tag not in REJECTION_CODES:
            raise _uncertain(method, request_id, "its Failure cause is not a recognized typed rejection")
        tags.append(error_tag)
    if REJECTION_CODES[tags[0]] == INPUT_INVALID:
        raise Failure(INPUT_INVALID, f"The server rejected {method} ({tags[0]})",
                      "Inspect agent status before retrying; rejection does not establish rollback. See docs/AGENT-HOSTS.md.",
                      method=method, request_id=request_id, error_tag=tags[0])
    raise Failure(CONFIG_INVALID, f"The server rejected {method}: the token is not authorized for this environment",
                  "Issue a token with your T3 Code CLI (t3 auth session issue --token-only), "
                  "then pat configure --t3-bearer-token <token>.",
                  method=method, request_id=request_id, error_tag=tags[0])


def _scan(frame: object, method: str, request_id: str) -> dict | None:
    """Process one frame. Returns a success value, or None to keep waiting under the same
    deadline. Raises the sanitized Failure for terminal frames and malformed input."""
    try:
        messages = _decode(frame)
    except (ValueError, RecursionError) as exc:
        raise _uncertain(method, request_id, "the reply frame was malformed or oversized") from exc
    for message in messages:
        tag = message.get("_tag")
        if not isinstance(tag, str):
            raise _uncertain(method, request_id, "the reply carried a malformed message tag")
        if tag == "Exit":
            if str(message.get("requestId")) == request_id:
                return _exit(method, request_id, message.get("exit"))
        elif tag in ("Defect", "ClientProtocolError"):
            raise _uncertain(method, request_id, "the server reported a protocol-level defect")
        elif tag not in SKIP_TAGS:
            raise _uncertain(method, request_id, "the reply carried an unknown message tag")
    return None


def _await(sock: object, method: str, request_id: str, deadline: float, timeout: float) -> dict:
    """Wait for the correlated Exit under one deadline; unrelated frames never reset it."""
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Failure(DELIVERY_UNCERTAIN,
                          f"{method} request {request_id} was sent, but no reply arrived within the {timeout:g} s budget",
                          UNCERTAIN_HINT, method=method, request_id=request_id)
        try:
            frame = sock.recv(timeout=remaining)
        except Failure:
            raise
        except TimeoutError as exc:
            raise Failure(DELIVERY_UNCERTAIN,
                          f"{method} request {request_id} was sent, but no reply arrived within the {timeout:g} s budget",
                          UNCERTAIN_HINT, method=method, request_id=request_id) from exc
        except Exception as exc:
            raise _uncertain(method, request_id, "the connection closed before a reply") from exc
        value = _scan(frame, method, request_id)
        if value is not None:
            return value


def call(origin: str, bearer: str, method: str, payload: dict, *, timeout: float = 60) -> dict:
    """Return the matching successful Exit value, or a sanitized Failure.

    Transport contract: /ws?orchestrationProtocol=2; Effect Request/Exit JSON envelopes
    (including batched frames), bounded bytes and total time, no redirects or proxies.
    """
    if method not in ALLOWED_METHODS:
        raise Failure(INPUT_INVALID,
                      f"Method {method!r} is not an allowed orchestration RPC {sorted(ALLOWED_METHODS)}")
    if not isinstance(bearer, str) or not bearer:
        raise Failure(CONFIG_INVALID, "No bearer token is configured for this call")
    if not isinstance(payload, dict):
        raise Failure(INPUT_INVALID, "The RPC payload must be an object")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) \
            or not 0 < float(timeout) <= MAX_TIMEOUT:
        raise Failure(INPUT_INVALID, f"timeout must be a number of seconds in (0, {MAX_TIMEOUT:g}]")
    url = ws_url(origin)
    request_id = uuid.uuid4().hex
    envelope = {"_tag": "Request", "id": request_id, "tag": method, "payload": payload, "headers": []}
    try:
        body = json.dumps(envelope, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise Failure(INPUT_INVALID, "The RPC payload is not JSON") from exc
    if len(body) > MAX_BODY:
        raise Failure(INPUT_LIMIT, f"The serialized request exceeds the {MAX_BODY} byte message bound")
    timeout = float(timeout)
    deadline = time.monotonic() + timeout
    sock = None
    try:
        sock = _open(url, bearer, deadline)
        _send(sock, body, deadline, method, request_id)
        return _await(sock, method, request_id, deadline, timeout)
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
