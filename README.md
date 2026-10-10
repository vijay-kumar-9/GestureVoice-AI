# GestureVoice AI ✋🎤

### AI-Powered Touchless Computer Control Using Hand Gestures and Voice Commands

GestureVoice AI is a **Windows desktop-control prototype** that lets users interact with their computer through a webcam and microphone. It combines real-time hand tracking, offline speech recognition, and a React dashboard to perform common mouse, application, and system actions without relying entirely on a physical mouse or keyboard.

> **Hackathon problem statement:** Control a computer using hand gestures and voice commands for cursor movement, clicking, zooming, scrolling, and system controls.

## ✨ Features

### ✋ Hand gesture controls

| Gesture | Action |
| --- | --- |
| Move index finger | Move the mouse cursor |
| Brief thumb–index pinch | Left-click |
| Thumb–middle pinch | Right-click |
| Two extended fingers + vertical movement | Scroll |
| Three extended fingers + vertical movement | Zoom in/out in supported apps |
| Hold thumb–index pinch and move | Drag and drop |

Gesture recognition works best when the hand is clearly visible to the webcam. Exact mappings depend on the installed `gesture_mouse.py` version.

### 🎤 Voice controls

- Open and close supported apps such as **VS Code, Chrome, Notepad, and Calculator**.
- Open ChatGPT in a browser.
- List detected browsers, common folders, and files; choose an item using a spoken number.
- List open windows and request a normal close of a selected window.
- Control volume, mute, scrolling, zoom, screenshots, and desktop visibility.
- Use **offline speech recognition** with Vosk once the model is installed.

**Example spoken phrases:** `open vscode`, `open chatgpt`, `show browsers`, `folders`, `files`, `show open windows`, `close chrome`, `volume up`, `take screenshot`, `stop listening`.

Speech recognition may occasionally mishear commands, especially in noisy environments. Use the **Stop all** button to end the running engines.

### 🖥️ React control dashboard

- Start/stop the hand-gesture and voice engines separately or together.
- View a live **annotated webcam feed inside the dashboard**.
- Enable or pause gesture-based cursor control.
- Monitor connection status, engine state, and live activity logs.
- Communicate with the local Python backend over HTTP and WebSocket.

## 🛠️ Tech stack

| Area | Technologies |
| --- | --- |
| Frontend | React, TypeScript, Vite, CSS |
| Backend | Python 3.12, FastAPI, Uvicorn, WebSocket |
| Computer vision | OpenCV, MediaPipe Hand Landmarker |
| Voice recognition | Vosk, SoundDevice |
| Computer actions | PyAutoGUI, Windows APIs |
| Development | VS Code, Git, GitHub |

## 🧩 Architecture

```text
                 User
              /        \
           Webcam     Microphone
             |           |
       OpenCV +        Vosk
       MediaPipe   Speech Recognition
             |           |
       Gesture Engine  Voice Engine
              \          /
               Windows Actions
                 (PyAutoGUI)
                      ^
                      |
                FastAPI Backend
              HTTP + WebSocket
                      |
                React Dashboard
          Live camera / logs / controls
```

The Python backend runs **on the same Windows computer being controlled**. The React dashboard is a local interface, not a cloud-hosted remote-control service.

## 📂 Project structure

```text
GestureVoice-AI/
├── backend/
│   ├── api_server.py          # FastAPI control API
│   ├── camera_bridge.py       # Sends annotated frames to local dashboard
│   ├── gesture_mouse.py       # Hand tracking and gesture actions
│   ├── voice_control.py       # Offline voice commands
│   ├── requirements_api.txt   # FastAPI / Uvicorn dependencies
│   └── models/                # Downloaded models (not committed to Git)
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   └── index.css
│   ├── index.html
│   ├── package.json
│   └── vite.config.ts
├── main.py                    # Optional desktop launcher
├── screenshots/               # Local captures (not committed to Git)
├── .gitignore
└── README.md
```

## ⚙️ Setup (Windows 11)

**Prerequisites:** Python **3.12**, Node.js + npm, a working webcam and microphone, and VS Code (optional).

### 1. Clone the repository

```powershell
git clone https://github.com/YOUR_USERNAME/GestureVoice-AI.git
cd GestureVoice-AI
```

If you already have the project folder locally, open it in VS Code and skip cloning.

### 2. Create a Python virtual environment

Run from the **project root**:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
```

### 3. Install Python dependencies

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements_api.txt
.\.venv\Scripts\python.exe -m pip install opencv-python mediapipe pyautogui vosk sounddevice
```

### 4. Install AI models

The large model files are not included in this repository.

**MediaPipe Hand Landmarker:**

```powershell
New-Item -ItemType Directory -Force -Path backend\models
Invoke-WebRequest -Uri "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task" -OutFile "backend\models\hand_landmarker.task"
```

**Vosk small US English:** download the model from [Vosk's model catalog](https://alphacephei.com/vosk/models), or run:

```powershell
Invoke-WebRequest -Uri "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip" -OutFile "vosk-model.zip"
Expand-Archive -Path "vosk-model.zip" -DestinationPath "backend\models" -Force
```

Confirm the expected paths exist:

```text
backend/models/hand_landmarker.task
backend/models/vosk-model-small-en-us-0.15/conf/model.conf
```

### 5. Start the FastAPI backend (Terminal 1)

From the **project root**:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.api_server:app --host 127.0.0.1 --port 8000
```

Health endpoint: `http://127.0.0.1:8000/api/health`

> Opening `http://127.0.0.1:8000/` may return `404 Not Found` because the backend does not serve a homepage at `/`.

### 6. Start React (Terminal 2)

```powershell
cd frontend
npm install
npm run dev
```

Open the dashboard at **http://127.0.0.1:5173/**.

### 7. Use GestureVoice AI

1. Click **Start both** to launch the camera and microphone engines.
2. The live hand-tracking feed appears in the **Hand Gesture Engine** panel.
3. Click **Enable cursor control** to activate hand-based mouse input (it starts paused).
4. Speak a supported voice command such as **“open notepad”**.
5. Click **Pause cursor control** or **Stop all** when finished.

**Note:** When you launch `backend/gesture_mouse.py` directly instead of through the dashboard, its standalone OpenCV window uses **S** to toggle mouse input and **Q** to exit.

## ✅ Build check

To verify the React production bundle:

```powershell
cd frontend
npm run build
```

A successful build generates `frontend/dist/` (which should not be committed).

## 🔒 Safety and privacy

- **Keep FastAPI bound to `127.0.0.1`**; do **not** expose the desktop-control API to the internet.
- The camera preview is intended for local use and is not uploaded to a hosted service by this project.
- Gesture-based cursor control starts paused in dashboard mode.
- PyAutoGUI's mouse-corner fail-safe is enabled for emergency stopping.
- Normal window-close requests let applications ask about unsaved changes; they are not forced process kills.
- Do not commit personal screenshots, `.env` files, `.venv/`, `frontend/node_modules/`, `frontend/dist/`, or `backend/models/`.

## ⚠️ Known limitations

- Tested workflow targets **Windows**; Linux/macOS behavior is not provided.
- Recognition accuracy depends on camera lighting, hand visibility, microphone input, and background noise.
- Some voice commands are rule-based rather than general-purpose natural-language understanding.
- The file chooser browses designated folders, not necessarily every file on the computer.
- Some zoom gestures/shortcuts may behave differently between applications.
- The dashboard and control backend must run locally on the computer being controlled.

## 🔭 Future improvements

- More accurate voice recognition and wake-word options.
- Customizable gesture mapping and sensitivity.
- Improved accessibility controls and multilingual support.
- Gesture/voice activity analytics and automated test coverage.
- Installer and desktop packaging for easier setup.

## 👥 Team

Developed as a **three-member hackathon project**. Add team member names, roles, and relevant acknowledgments here before submission.

---

**GestureVoice AI — Control without touch.**
