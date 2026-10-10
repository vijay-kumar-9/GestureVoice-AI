"""Publish annotated gesture frames to the local GestureVoice FastAPI process.

Only activated for gesture_mouse.py started by FastAPI. No extra webcam opens.
If backend heartbeat is lost, gesture control is automatically paused.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from urllib.request import Request, urlopen

import cv2


class CameraBridge:
    def __init__(self) -> None:
        self.url = os.getenv("GESTUREVOICE_CAMERA_URL", "")
        self.token = os.getenv("GESTUREVOICE_FRAME_TOKEN", "")
        self.web_mode = bool(self.url and self.token)
        self._queue: queue.Queue = queue.Queue(maxsize=1)
        self._last_queued = 0.0
        self._lock = threading.Lock()
        self._enabled = False
        self._last_success = 0.0
        if self.web_mode:
            threading.Thread(target=self._publisher, daemon=True, name="gesturevoice-camera").start()

    def offer(self, frame, gesture: str) -> None:
        if not self.web_mode:
            return
        now = time.monotonic()
        if now - self._last_queued < 0.16:  # no more than ~6 FPS
            return
        self._last_queued = now
        try:
            self._queue.put_nowait((frame.copy(), gesture))
        except queue.Full:
            pass  # prioritize fresh data; never block cursor movement

    def controls_enabled(self) -> bool:
        if not self.web_mode:
            return False
        with self._lock:
            return self._enabled and (time.monotonic() - self._last_success < 1.7)

    def _publisher(self) -> None:
        while True:
            frame, gesture = self._queue.get()
            try:
                height, width = frame.shape[:2]
                size = (min(560, width), max(1, round(height * min(560, width) / width)))
                preview = cv2.resize(frame, size)
                ok, encoded = cv2.imencode(".jpg", preview, [int(cv2.IMWRITE_JPEG_QUALITY), 65])
                if not ok:
                    continue
                request = Request(
                    self.url,
                    data=encoded.tobytes(),
                    method="POST",
                    headers={
                        "Content-Type": "image/jpeg",
                        "X-GestureVoice-Token": self.token,
                        "X-GestureVoice-Gesture": gesture,
                    },
                )
                with urlopen(request, timeout=0.9) as response:
                    body = json.loads(response.read().decode("utf-8"))
                with self._lock:
                    self._enabled = bool(body.get("enabled", False))
                    self._last_success = time.monotonic()
            except Exception:
                # Network/API failures should never freeze the gesture engine.
                with self._lock:
                    self._enabled = False
