# GestureVoice AI — React + FastAPI Integration

## What this patch does

It adds a **local-only** FastAPI service and a React dashboard that start/stop your two **existing** Python modules and show their logs. It **does not replace** `backend/gesture_mouse.py`, `backend/voice_control.py`, or the working Tkinter `main.py`. The hand camera still opens in its own OpenCV window; there is no in-browser webcam feed yet.

## 1. Extract patch into your existing project

Stop the running `main.py` launcher first (click **Stop All**, then close it). Extract the integration ZIP and **copy its contents** into your existing `GestureVoice-AI` folder, merging `backend` and `frontend`. Do **not** place the integration folder itself one directory too deep.

Your project should contain:

```
GestureVoice-AI/
  .venv/
  main.py                        (your old launcher, still works)
  backend/
    models/                      (your downloaded models)
    gesture_mouse.py             (your existing code)
    voice_control.py             (your existing code)
    api_server.py                (NEW)
    requirements_api.txt         (NEW)
  frontend/
    package.json                 (NEW)
    index.html                   (NEW)
    vite.config.ts               (NEW)
    tsconfig.json                (NEW)
    src/App.tsx                  (NEW)
    src/main.tsx                 (NEW)
    src/index.css                (NEW)
```

If a teammate has already created frontend code, **back it up** first; use the provided React `App.tsx` as a working reference and wire their UI to the endpoints below instead of overwriting it.

## 2. Terminal 1 — start the backend (from GestureVoice-AI)

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements_api.txt
.\.venv\Scripts\python.exe -m uvicorn backend.api_server:app --host 127.0.0.1 --port 8000
```

Backend health check in browser: `http://127.0.0.1:8000/api/health` (should show `{"status":"ok","mode":"local-only"}`).

## 3. Terminal 2 — start React

```powershell
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173` in Chrome or Edge. The dashboard should say **Backend connected**.

## 4. Test

1. Click **Start both**.
2. The MediaPipe/OpenCV camera window should open. Click the camera window and press **S** to enable mouse control.
3. Say your usual voice phrases. Its recognized phrases should appear under **Live activity** (the process might take a moment to initialize Vosk).
4. Click **Stop all**. Both engine statuses should become stopped. Your old `main.py` still works, but **do not run both launchers simultaneously**; two instances compete for the mic/camera.

You can stop the API using `Ctrl + C` in terminal 1; Vite using `Ctrl + C` in terminal 2.

## API contract for your teammate's frontend

- `GET /api/health` → `{"status":"ok","mode":"local-only"}`
- `GET /api/status` → `{"engines":{"gesture":{"running":false,"pid":null},"voice":{"running":false,"pid":null}}}`
- `POST /api/engines/gesture/start`
- `POST /api/engines/gesture/stop`
- `POST /api/engines/voice/start`
- `POST /api/engines/voice/stop`
- `POST /api/start-all`
- `POST /api/stop-all`
- `GET /api/logs`
- `WS /ws` → first message `{"type":"snapshot","engines":{...},"logs":[...]}`, then messages `{"type":"log","source":"voice","message":"...","timestamp":"..."}` and status updates `{"type":"status","engines":{...}}`.

In the dev React app, Vite proxies `/api` and `/ws` to the local FastAPI server automatically.

## Important limitations and safety

- The backend **controls the PC on which FastAPI is running**. It isn't a cloud service for controlling another laptop.
- Backend binds to **127.0.0.1 only**, for local use. Do **not** expose the service to the public internet; API routes can start programs and control your desktop.
- The dashboard reports whether each Python **process is running**, not whether MediaPipe or Vosk has fully initialized. Read logs for model startup/errors.
- **Stop** currently terminates each existing Python process, like the original `main.py`. Mouse-up is sent as a safety fallback after stopping gestures. For a future production version we'll add cooperative process shutdown.
- Voice controls may still trigger on ambient speech in the currently selected `voice_control.py`. Test carefully; a reliable wake word and action confirmations are a separate feature.
- While running, the camera preview and any Tkinter chooser windows stay native Windows windows. Embedding the camera into React requires a redesign that sends gesture frames from the **same** OpenCV capture process (opening the camera twice often fails).
