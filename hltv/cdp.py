"""Minimal Chrome DevTools Protocol client.

Talks to a real (non-headless) Chrome launched with --remote-debugging-port so
JS renders exactly as a human would see it, including Cloudflare challenges.
"""
from __future__ import annotations

import json
import time

import requests
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
        url = ws_url or find_tab(port, host)
        if not url:
            raise RuntimeError(
                "No page target found on port %d. Launch Chrome with "
                "--remote-debugging-port=%d first (see scripts/open_chrome.sh)." % (port, port)
            )
        self.ws = connect(url, max_size=256 * 1024 * 1024, open_timeout=timeout)
        self._id = 0

    def send(self, method: str, **params):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") != mid:
                continue
            if "error" in msg:
                raise RuntimeError(f"{method}: {msg['error']}")
            return msg.get("result", {})

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
