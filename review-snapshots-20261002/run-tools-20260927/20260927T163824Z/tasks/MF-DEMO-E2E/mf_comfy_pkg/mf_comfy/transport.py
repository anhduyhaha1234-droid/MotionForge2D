"""Transport layer for the ComfyUI local server: loopback HTTP + WebSocket.

Endpoints used (verified against the pinned ComfyUI commit `306af3a8`, v0.28.2):
  POST /prompt                -> {"prompt_id", "number", ...} | 4xx/5xx + node_errors
  GET  /history/{prompt_id}   -> history entry (authoritative completion record)
  GET  /queue                 -> {"queue_running": [...], "queue_pending": [...]}
  GET  /object_info           -> node/nodeless capability inventory
  GET  /system_stats          -> version + device info
  POST /interrupt             -> cancels the running execution on the instance
  GET  /view?filename&subfolder&type -> artifact bytes

The transport never re-submits a prompt. The only retry is a WebSocket
reconnect, which is explicitly NOT proof of job failure.
"""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .errors import (
    InvalidGraph,
    MissingModel,
    MissingNode,
    NonLoopbackEndpoint,
    TransportError,
    WsDisconnected,
)

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


def parse_base_url(base_url: str) -> urllib.parse.SplitResult:
    parts = urllib.parse.urlsplit(base_url)
    if parts.scheme not in ("http", "https"):
        raise NonLoopbackEndpoint("base_url must be http(s)", base_url=base_url)
    if (parts.hostname or "").lower() not in LOOPBACK_HOSTS:
        raise NonLoopbackEndpoint(
            "ComfyUI adapter is loopback-only; refusing a non-loopback endpoint",
            base_url=base_url,
            host=parts.hostname,
        )
    return parts


@dataclass
class SubmitResult:
    prompt_id: str
    number: int | None = None
    node_errors: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


class Transport(Protocol):
    def system_stats(self) -> dict: ...
    def object_info(self) -> dict: ...
    def submit(self, graph: dict, client_id: str) -> SubmitResult: ...
    def history(self, prompt_id: str) -> dict: ...
    def queue(self) -> dict: ...
    def interrupt(self, prompt_id: str) -> dict: ...
    def fetch_view(self, item: dict) -> bytes: ...
    def drain_events(self, client_id: str, timeout_s: float) -> list[dict]: ...
    def close(self) -> None: ...


def _classify_prompt_rejection(payload: dict, status: int, graph: dict) -> Exception:
    """Map a rejected /prompt response onto a typed failure.

    Classified against the REAL server's bodies (recorded in
    `EV/raw/probe_rejections.json` for ComfyUI 0.28.2):
      * unknown class  -> 400 {"error":{"type":"missing_node_type",
                               "message":"Node 'X' not found. The custom node may not be installed."}}
      * absent model   -> 400 {"error":{"type":"prompt_outputs_failed_validation"},
                               "node_errors":{"4":{"errors":[{"type":"value_not_in_list", ...}]}}}
      * bad structure  -> 400 {"error":{"type":"prompt_outputs_failed_validation"},
                               "node_errors":{... "required_input_missing" ...}}
      * empty graph    -> 400 {"error":{"type":"prompt_no_outputs"}}
    Both the underscored error `type` and the spaced human `message` are matched.
    """
    err = (payload or {}).get("error") or {}
    node_errors = (payload or {}).get("node_errors") or {}
    blob = json.dumps({"error": err, "node_errors": node_errors}, ensure_ascii=False).lower()
    etype = str(err.get("type") or "")
    node_markers = ("missing_node_type", "missing node", "invalid node type",
                    "not found. the custom node", "node type not found")
    if any(m in blob for m in node_markers):
        return MissingNode("workflow references a node class the server does not expose",
                           engine_error=err, node_errors=node_errors, status=status)
    model_markers = ("value_not_in_list", "value not in list", "not in list")
    if any(m in blob for m in model_markers):
        return MissingModel("workflow references a model the server cannot resolve",
                            engine_error=err, node_errors=node_errors, status=status)
    return InvalidGraph(f"prompt rejected by server ({etype or 'validation'})",
                        engine_error=err, node_errors=node_errors, status=status)


class HttpTransport:
    """Loopback HTTP + WS transport for a running ComfyUI server."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8188",
        http_timeout_s: float = 60.0,
        ws_timeout_s: float = 5.0,
        ws_reconnect_attempts: int = 5,
        ws_connector: Callable[[str], Any] | None = None,
    ) -> None:
        parts = parse_base_url(base_url)
        self.base_url = f"{parts.scheme}://{parts.netloc}"
        self.host = parts.hostname or "127.0.0.1"
        self.port = parts.port or (443 if parts.scheme == "https" else 80)
        self.http_timeout_s = http_timeout_s
        self.ws_timeout_s = ws_timeout_s
        self.ws_reconnect_attempts = ws_reconnect_attempts
        self._ws_connector = ws_connector
        self._ws = None
        self._ws_client_id: str | None = None
        self._ws_events: list[dict] = []
        self.ws_disconnects = 0
        self.ws_reconnects = 0
        self.capabilities: dict = {}

    # -- HTTP -------------------------------------------------------------
    def _request(self, method: str, path: str, payload: dict | None = None, timeout_s: float | None = None):
        url = self.base_url + path
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout_s or self.http_timeout_s) as resp:
                body = resp.read()
                return resp.status, body
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as exc:
            raise TransportError("HTTP request to the ComfyUI server failed",
                                 method=method, path=path, error=f"{type(exc).__name__}:{exc}") from exc

    def _json(self, method: str, path: str, payload: dict | None = None, timeout_s: float | None = None) -> dict:
        status, body = self._request(method, path, payload, timeout_s)
        try:
            parsed = json.loads(body.decode("utf-8")) if body else {}
        except ValueError as exc:
            raise TransportError("server returned non-JSON", path=path, status=status,
                                 body=body[:400].decode("utf-8", "replace")) from exc
        if status >= 400:
            raise TransportError("server returned an error status", path=path, status=status,
                                 body=parsed if isinstance(parsed, dict) else str(parsed)[:400])
        return parsed if isinstance(parsed, dict) else {"_list": parsed}

    def system_stats(self) -> dict:
        return self._json("GET", "/system_stats")

    def object_info(self) -> dict:
        return self._json("GET", "/object_info")

    def submit(self, graph: dict, client_id: str) -> SubmitResult:
        status, body = self._request("POST", "/prompt", {"prompt": graph, "client_id": client_id})
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except ValueError:
            payload = {}
        if status >= 400:
            raise _classify_prompt_rejection(payload, status, graph)
        prompt_id = payload.get("prompt_id")
        if not prompt_id:
            raise InvalidGraph("server accepted the request but returned no prompt_id",
                               status=status, body=payload)
        return SubmitResult(prompt_id=prompt_id, number=payload.get("number"),
                            node_errors=payload.get("node_errors") or {}, raw=payload)

    def history(self, prompt_id: str = "") -> dict:
        """History entry for one prompt_id; `""` returns the full history map."""
        path = f"/history/{urllib.parse.quote(prompt_id)}" if prompt_id else "/history"
        return self._json("GET", path)

    def queue(self) -> dict:
        return self._json("GET", "/queue")

    def interrupt(self, prompt_id: str) -> dict:
        """POST /interrupt. Callers MUST hold the exclusive instance lease."""
        style = self.capabilities.get("interrupt_payload", "json")
        try:
            if style == "json":
                return self._json("POST", "/interrupt", {"prompt_id": prompt_id})
            return self._json("POST", "/interrupt")
        except TransportError as exc:
            if style == "json" and exc.details.get("status") in (400, 422):
                # protocol negotiation, not a prompt retry
                self.capabilities["interrupt_payload"] = "empty"
                return self._json("POST", "/interrupt")
            raise

    def fetch_view(self, item: dict) -> bytes:
        query = urllib.parse.urlencode(
            {
                "filename": item.get("filename", ""),
                "subfolder": item.get("subfolder", ""),
                "type": item.get("type", "output"),
            }
        )
        status, body = self._request("GET", f"/view?{query}")
        if status >= 400:
            raise TransportError("artifact fetch failed", status=status, item=item)
        return body

    # -- WebSocket --------------------------------------------------------
    def _ws_connect(self, client_id: str):
        url = f"ws://{self.host}:{self.port}/ws?clientId={urllib.parse.quote(client_id)}"
        if self._ws_connector is not None:
            return self._ws_connector(url)
        import websocket  # websocket-client

        ws = websocket.WebSocket()
        ws.connect(url, timeout=self.ws_timeout_s, enable_multithread=True)
        ws.settimeout(self.ws_timeout_s)
        return ws

    def drain_events(self, client_id: str, timeout_s: float) -> list[dict]:
        """Collect websocket events for up to timeout_s.

        A dropped socket is reconnected (bounded attempts). Losing the socket is
        NOT a job failure; completion authority stays with /history.
        """
        from websocket import WebSocketConnectionClosedException, WebSocketTimeoutException  # type: ignore

        if self._ws is None or self._ws_client_id != client_id:
            self.close_ws()
            self._ws = self._ws_connect(client_id)
            self._ws_client_id = client_id
            self._ws_events = []

        deadline = time.monotonic() + max(0.0, timeout_s)
        received: list[dict] = []
        attempts = 0
        while time.monotonic() < deadline:
            try:
                self._ws.settimeout(max(0.05, deadline - time.monotonic()))
                raw = self._ws.recv()
                if isinstance(raw, bytes):
                    continue  # binary preview frames
                try:
                    received.append(json.loads(raw))
                except ValueError:
                    continue
            except WebSocketTimeoutException:
                break
            except (WebSocketConnectionClosedException, OSError, socket.timeout) as exc:
                self.ws_disconnects += 1
                detail = f"{type(exc).__name__}:{exc}"
                if attempts >= self.ws_reconnect_attempts:
                    raise WsDisconnected("websocket dropped and reconnect attempts exhausted",
                                         attempts=attempts, error=detail) from exc
                attempts += 1
                time.sleep(min(2.0, 0.2 * (2 ** attempts)))
                self._ws = self._ws_connect(client_id)
                self._ws_client_id = client_id
                self.ws_reconnects += 1
                received.append({"type": "mf_ws_reconnect", "attempt": attempts, "socket_error": detail})
        self._ws_events.extend(received)
        return received

    def close_ws(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:  # noqa: BLE001 - best effort close
                pass
        self._ws = None

    def close(self) -> None:
        self.close_ws()

    # -- capability -------------------------------------------------------
    def probe_capabilities(self, object_info: dict | None = None) -> dict:
        stats = self.system_stats()
        oi = object_info if object_info is not None else self.object_info()
        system = stats.get("system") or {}
        devices = stats.get("devices") or []
        version = str(system.get("comfyui_version") or "")
        caps = {
            "base_url": self.base_url,
            "loopback_only": True,
            "comfyui_version": version,
            "python_version": system.get("python_version", ""),
            "os": system.get("os", ""),
            "device_name": (devices[0].get("name") if devices else ""),
            "device_total_vram_mib": (round((devices[0].get("vram_total", 0) or 0) / (1024 * 1024))
                                      if devices else 0),
            "node_class_count": len(oi or {}),
            "endpoints": ["/prompt", "/history/{prompt_id}", "/queue", "/object_info",
                          "/system_stats", "/interrupt", "/view", "/ws"],
            "interrupt_payload": "json",
            "history_direct_endpoint": True,
            "history_authoritative": True,
            "ws_role": "progress-only",
        }
        self.capabilities = caps
        return caps
