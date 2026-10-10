# GestureVoice AI - Phase 8: Live Camera in React

This is an **incremental patch for the GestureVoice-AI project** whose FastAPI and React Start Both controls already work. It does **not** replace `voice_control.py`, Vosk models, your existing `main.py`, or your frontend dependencies.

## Changes

- `backend/api_server.py` — receives annotated JPEGs from the existing gesture process, provides `GET /api/camera/stream` (MJPEG) and `POST /api/gesture/control`.
- `backend/gesture_mouse.py` — streams frames from its **existing webcam capture**, no second camera connection. In web mode it is controlled from the dashboard, with no OpenCV popup.
- `backend/camera_bridge.py` — new lightweight background sender, bounded to ~6 FPS. Gesture movement continues even when network publishing is slow; control pauses if backend heartbeat disappears.
- `frontend/src/App.tsx` and `frontend/src/index.css` — live video preview and Enable/Pause Cursor Control buttons.

## Before you copy

1. Stop the React dev server and FastAPI (`Ctrl + C` in each VS Code terminal). Press **Stop all** in the dashboard first.
2. Make a backup of these four project files: `backend/api_server.py`, `backend/gesture_mouse.py`, `frontend/src/App.tsx`, `frontend/src/index.css`.
3. Unzip this patch into your **GestureVoice-AI project root**, merging the `backend` and `frontend` folders. Do not accidentally create `frontend/frontend/` or `frontend/backend/`.
4. Confirm `backend/camera_bridge.py` exists. Keep your **original `backend/voice_control.py`** unchanged.

## Run

From the GestureVoice-AI root directory (Terminal 1):

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.api_server:app --host 127.0.0.1 --port 8000
```

From the `frontend` directory (Terminal 2):

```powershell
npm run dev
```

Open http://127.0.0.1:5173. Click **Start both**.

Expected behavior: live camera appears **inside the Hand Gesture Engine card**, showing hand landmarks. When launched from the browser dashboard, OpenCV's separate camera popup is intentionally removed. Click **Enable cursor control** to start gesture mouse actions; **Pause cursor control** to disable. Voice commands and logs continue working as before. Click **Stop all** to release webcam.

If you run `backend/gesture_mouse.py` directly (outside FastAPI), it still opens the old OpenCV popup and uses **S** to toggle / **Q** to exit.

## Safety / limitations

- The API **must stay bound to `127.0.0.1`**. It controls your local PC and exposes a live webcam preview locally; do not deploy this API on a public server.
- On dashboard start, **cursor control starts paused**. You must explicitly enable it.
- The camera sender's heartbeat automatically pauses cursor control if it loses contact with the API for 1.7 seconds; it does not switch control on unexpectedly.
- To stop immediately, press **Stop all** in React. PyAutoGUI's physical mouse-to-screen-corner fail-safe remains available.
- This patch targets the exact React + FastAPI starter from the prior GestureVoice AI integration ZIP. If your teammate changed App.tsx, **merge the preview changes** instead of overwriting their custom frontend.
- The source was syntax-checked and the FastAPI routes smoke-tested. Actual Windows camera, microphone, video stream, and UI behavior still require testing on your laptop.
