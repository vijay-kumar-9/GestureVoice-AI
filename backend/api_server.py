"""Local FastAPI + WebSocket bridge for the EXISTING GestureVoice AI modules.

Run from the GestureVoice-AI root (Windows):
    .\\.venv\\Scripts\\python.exe -m uvicorn backend.api_server:app --host 127.0.0.1 --port 8000

This file does NOT replace gesture_mouse.py, voice_control.py, or main.py.
Never expose this desktop-control API publicly.
"""

from __future__ import annotations

import asyncio
import ctypes
import os
import time
import queue
import subprocess
import sys
import threading
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = {
    "gesture": ROOT / "backend" / "gesture_mouse.py",
    "voice": ROOT / "backend" / "voice_control.py",
}
ALLOWED_WS_ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}


class EngineManager:
    def __init__(self) -> None:
        self.processes: dict[str, subprocess.Popen[str] | None] = {
            "gesture": None,
            "voice": None,
        }
        self.lock = threading.RLock()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.logs: deque[dict[str, Any]] = deque(maxlen=200)
        self.listeners: set[asyncio.Queue[dict[str, Any]]] = set()
        self.gesture_enabled = False
        self._camera_token = os.urandom(24).hex()
        self._camera_jpeg: bytes | None = None
        self._camera_seq = 0
        self._camera_time = 0.0
        self.current_gesture = "NO HAND"

    def _publish(self, event: dict[str, Any]) -> None:
        """Runs on the FastAPI event loop; fan out updates to browser clients."""
        if event["type"] == "log":
            self.logs.append(event)
        for listener in tuple(self.listeners):
            if listener.full():
                try:
                    listener.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                listener.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def emit(self, source: str, message: str) -> None:
        event = {
            "type": "log",
            "source": source,
            "message": message.rstrip(),
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        if self.loop is not None and self.loop.is_running():
            self.loop.call_soon_threadsafe(self._publish, event)
        else:
            self.logs.append(event)

    def status(self) -> dict[str, dict[str, Any]]:
        with self.lock:
            return {
                name: {
                    "running": proc is not None and proc.poll() is None,
                    "pid": proc.pid if proc is not None and proc.poll() is None else None,
                }
                for name, proc in self.processes.items()
            }

    def start(self, name: str) -> None:
        if name not in SCRIPTS:
            raise ValueError("Unknown engine")
        path = SCRIPTS[name]
        if not path.is_file():
            raise FileNotFoundError(f"Missing {path}. Copy this bridge into your existing project.")
        with self.lock:
            existing = self.processes[name]
            if existing is not None and existing.poll() is None:
                self.emit(name, "Already running")
                return
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            if name == "gesture":
                self.gesture_enabled = False
                self._camera_jpeg = None
                self._camera_token = os.urandom(24).hex()
                env["GESTUREVOICE_CAMERA_URL"] = "http://127.0.0.1:8000/api/camera/frame"
                env["GESTUREVOICE_FRAME_TOKEN"] = self._camera_token
            proc = subprocess.Popen(
                [sys.executable, "-u", str(path)],
                cwd=str(ROOT),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
                creationflags=flags,
            )
            self.processes[name] = proc
            self.emit(name, f"Started (PID {proc.pid}).")
            threading.Thread(target=self._read_output, args=(name, proc), daemon=True).start()

    def _read_output(self, name: str, proc: subprocess.Popen[str]) -> None:
        try:
            if proc.stdout is not None:
                for line in proc.stdout:
                    line = line.rstrip("\r\n")
                    if line:
                        self.emit(name, line)
        except (OSError, ValueError) as exc:
            self.emit(name, f"Log reader stopped: {exc}")
        finally:
            self.emit(name, f"Exited (code {proc.poll()}).")
            if name == "gesture":
                with self.lock:
                    self.gesture_enabled = False
                    self._camera_jpeg = None
                self.release_left_button()

    @staticmethod
    def release_left_button() -> None:
        """Best effort: undo a held drag after an abrupt gesture stop."""
        if os.name == "nt":
            try:
                ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
            except (AttributeError, OSError):
                pass

    def stop(self, name: str) -> None:
        if name not in SCRIPTS:
            raise ValueError("Unknown engine")
        with self.lock:
            proc = self.processes[name]
            if proc is None or proc.poll() is not None:
                self.emit(name, "Not running")
                return
            self.emit(name, "Stopping...")
            try:
                # Legacy gesture and voice scripts lack cooperative stop IPC.
                # Keep the same process-stop behavior as the existing main.py.
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
            finally:
                if name == "gesture":
                    self.gesture_enabled = False
                    self._camera_jpeg = None
                    self.release_left_button()
            self.emit(name, "Stopped")

    def stop_all(self) -> None:
        for name in SCRIPTS:
            try:
                self.stop(name)
            except (OSError, subprocess.TimeoutExpired) as exc:
                self.emit(name, f"Stop error: {exc}")

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        listener: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=250)
        self.listeners.add(listener)
        return listener

    def unsubscribe(self, listener: asyncio.Queue[dict[str, Any]]) -> None:
        self.listeners.discard(listener)


manager = EngineManager()


@asynccontextmanager
async def lifespan(_: FastAPI):
    manager.loop = asyncio.get_running_loop()
    manager.emit("system", "GestureVoice AI API is ready on this computer.")
    yield
    manager.stop_all()


app = FastAPI(title="GestureVoice AI Local Controller", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "local-only"}


@app.get("/api/status")
def get_status() -> dict[str, Any]:
    return {"engines": manager.status(), "gesture_enabled": manager.gesture_enabled}


@app.get("/api/logs")
def get_logs() -> dict[str, Any]:
    return {"logs": list(manager.logs)}


@app.post("/api/engines/{name}/start")
def start_engine(name: str) -> dict[str, Any]:
    if name not in SCRIPTS:
        raise HTTPException(status_code=404, detail="Unknown engine")
    try:
        manager.start(name)
    except (OSError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"engines": manager.status()}


@app.post("/api/engines/{name}/stop")
def stop_engine(name: str) -> dict[str, Any]:
    if name not in SCRIPTS:
        raise HTTPException(status_code=404, detail="Unknown engine")
    try:
        manager.stop(name)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"engines": manager.status()}


@app.post("/api/start-all")
def start_all() -> dict[str, Any]:
    problems = []
    for name in SCRIPTS:
        try:
            manager.start(name)
        except OSError as exc:
            problems.append(f"{name}: {exc}")
    return {"engines": manager.status(), "errors": problems}


@app.post("/api/stop-all")
def stop_all() -> dict[str, Any]:
    manager.stop_all()
    return {"engines": manager.status()}




@app.post("/api/gesture/control")
async def control_gesture(request: Request) -> dict[str, Any]:
    """Enable/pause gestures from the local dashboard; never start enabled."""
    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Expected JSON")
    if not isinstance(body, dict) or not isinstance(body.get("enabled"), bool):
        raise HTTPException(status_code=400, detail="Provide enabled: true or false")
    if not manager.status()["gesture"]["running"]:
        raise HTTPException(status_code=409, detail="Start gesture engine first")
    with manager.lock:
        manager.gesture_enabled = body["enabled"]
    manager.emit("gesture", "Cursor " + ("enabled" if body["enabled"] else "paused") + " from dashboard")
    return {"gesture_enabled": manager.gesture_enabled, "engines": manager.status()}


@app.post("/api/camera/frame")
async def camera_frame(request: Request) -> dict[str, Any]:
    """Internal endpoint: accepts a JPEG from the ONE process owning the webcam."""
    if request.client is None or request.client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="Local only")
    if request.headers.get("x-gesturevoice-token") != manager._camera_token:
        raise HTTPException(status_code=403, detail="Unauthorized camera publisher")
    if request.headers.get("content-type") != "image/jpeg":
        raise HTTPException(status_code=415, detail="JPEG required")
    if int(request.headers.get("content-length", "0")) > 300_000:
        raise HTTPException(status_code=413, detail="Frame too large")
    raw = await request.body()
    if not raw.startswith(b"\xff\xd8") or len(raw) > 300_000:
        raise HTTPException(status_code=400, detail="Invalid camera frame")
    with manager.lock:
        manager._camera_jpeg = raw
        manager._camera_seq += 1
        manager._camera_time = time.monotonic()
        manager.current_gesture = request.headers.get("x-gesturevoice-gesture", "NO HAND")[:40]
        enabled = manager.gesture_enabled
    return {"enabled": enabled}


@app.get("/api/camera/stream")
async def camera_stream(request: Request) -> StreamingResponse:
    # Require dashboard navigation (not a random cross-origin web page).
    referer = request.headers.get("referer", "")
    fetch_site = request.headers.get("sec-fetch-site", "")
    if fetch_site == "cross-site" or (referer and not referer.startswith((
        "http://127.0.0.1:5173/", "http://localhost:5173/"
    ))):
        raise HTTPException(status_code=403, detail="Dashboard preview only")

    async def frames():
        last_seq = -1
        while True:
            if await request.is_disconnected():
                return
            with manager.lock:
                seq, jpeg = manager._camera_seq, manager._camera_jpeg
                fresh = time.monotonic() - manager._camera_time < 1.7
            if jpeg is not None and fresh and seq != last_seq:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n"
                       + f"Content-Length: {len(jpeg)}\r\n\r\n".encode()
                       + jpeg + b"\r\n")
                last_seq = seq
            await asyncio.sleep(0.10)

    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.websocket("/ws")
async def events(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin")
    if origin and origin not in ALLOWED_WS_ORIGINS:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    listener = manager.subscribe()
    try:
        await websocket.send_json({
            "type": "snapshot", "engines": manager.status(), "logs": list(manager.logs),
            "gesture_enabled": manager.gesture_enabled
        })
        while True:
            try:
                event = await asyncio.wait_for(listener.get(), timeout=1.0)
            except asyncio.TimeoutError:
                event = {"type": "status", "engines": manager.status(),
                         "gesture_enabled": manager.gesture_enabled}
            await websocket.send_json(event)
    except (WebSocketDisconnect, RuntimeError, OSError):
        pass
    finally:
        manager.unsubscribe(listener)
