"""Minimal Chrome DevTools Protocol client.

Talks to a real (non-headless) Chrome launched with --remote-debugging-port so
JS renders exactly as a human would see it, including Cloudflare challenges.
"""
from __future__ import annotations

import json
import time
from typing import Any

import requests
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

DEFAULT_PORT = 9222


def targets(port: int = DEFAULT_PORT) -> list[dict]:
    return requests.get(f"http://127.0.0.1:{port}/json", timeout=10).json()


def find_tab(port: int = DEFAULT_PORT, host: str = "hltv.org") -> str | None:
    """Return the websocket URL of the page target most likely to be ours."""
    pages = [t for t in targets(port) if t.get("type") == "page"]
    if not pages:
        return None
    for t in pages:
        if host in (t.get("url") or ""):
            return t["webSocketDebuggerUrl"]
    return pages[-1]["webSocketDebuggerUrl"]


class CDP:
    """One CDP websocket session bound to a single page target."""

    def __init__(self, ws_url: str | None = None, port: int = DEFAULT_PORT,
                 host: str = "hltv.org", timeout: int = 30):
        self._ws_url = ws_url
        self._port = port
        self._host = host
        self._timeout = timeout
        self._id = 0
        self.ws: Any = None
        self._connect()

    def _connect(self) -> None:
        url = self._ws_url or find_tab(self._port, self._host)
        if not url:
            raise RuntimeError(
                "No page target found on port %d. Launch Chrome with "
                "--remote-debugging-port=%d first (see scripts/open_chrome.sh)." % (self._port, self._port)
            )
        self.ws = connect(url, max_size=256 * 1024 * 1024, open_timeout=self._timeout)

    def _reconnect(self) -> None:
        """Re-attach after Chrome restarts or the socket drops.

        The page target may have been recreated, so the websocket URL is
        re-resolved instead of reused.
        """
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass
        self._ws_url = None
        time.sleep(1.0)
        self._connect()

    def send(self, method: str, **params):
        self._id += 1
        mid = self._id
        payload = json.dumps({"id": mid, "method": method, "params": params})
        for attempt in (1, 2):
            try:
                self.ws.send(payload)
                while True:
                    msg = json.loads(self.ws.recv())
                    if msg.get("id") != mid:
                        continue
                    if "error" in msg:
                        raise RuntimeError(f"{method}: {msg['error']}")
                    return msg.get("result", {})
            except (ConnectionClosed, ConnectionError, OSError) as exc:
                if attempt == 2:
                    raise RuntimeError(
                        f"{method}: connection lost ({exc}) — is Chrome still running? "
                        "Re-launch it with scripts/open_chrome.sh and re-run; "
                        "progress is kept in raw_*.jsonl."
                    ) from exc
                self._reconnect()

    def js(self, expr: str, await_promise: bool = True, user_gesture: bool = True):
        """Evaluate a JS expression in the page and return its value."""
        res = self.send(
            "Runtime.evaluate",
            expression=expr,
            returnByValue=True,
            awaitPromise=await_promise,
            userGesture=user_gesture,
        )
        if "exceptionDetails" in res:
            d = res["exceptionDetails"]
            desc = (d.get("exception") or {}).get("description") or d.get("text")
            raise RuntimeError(f"JS error: {desc}")
        return res["result"].get("value")

    def goto(self, url: str, wait: bool = True, timeout: int = 60) -> None:
        self.send("Page.navigate", url=url)
        if wait:
            self.wait_idle(timeout)

    def wait_idle(self, timeout: int = 60) -> bool:
        """Wait for document.readyState == complete, then settle briefly."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.js("document.readyState", await_promise=False) == "complete":
                    time.sleep(1.0)
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    def title(self) -> str:
        return self.js("document.title", await_promise=False)

    def url(self) -> str:
        return self.js("location.href", await_promise=False)

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass

    def __enter__(self) -> "CDP":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
