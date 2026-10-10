"""GestureVoice AI – Phase 6 desktop launcher (Windows / Python 3.12).

Runs the existing backend/gesture_mouse.py and backend/voice_control.py
in separate processes. It does NOT replace either working module.

Start from the project root:
    .\\.venv\\Scripts\\python.exe main.py
"""

from __future__ import annotations

import ctypes
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext


PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND = PROJECT_ROOT / "backend"
SCRIPTS = {
    "gesture": BACKEND / "gesture_mouse.py",
    "voice": BACKEND / "voice_control.py",
}

BG = "#0b1220"
CARD = "#172337"
TEXT = "#ecf4ff"
MUTED = "#a7b6cc"
ACCENT = "#42d6cc"


class GestureVoiceLauncher:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("GestureVoice AI | Unified Controller")
        self.root.geometry("880x660")
        self.root.minsize(690, 510)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.procs: dict[str, subprocess.Popen | None] = {
            "gesture": None,
            "voice": None,
        }
        self.events: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=1200)
        self.labels: dict[str, tk.Label] = {}
        self.closing = False
        self._build_ui()
        self.root.after(100, self._update_ui)

    def _build_ui(self) -> None:
        main = tk.Frame(self.root, bg=BG)
        main.pack(fill="both", expand=True, padx=22, pady=18)

        tk.Label(
            main, text="✋  GestureVoice AI", font=("Segoe UI", 25, "bold"),
            bg=BG, fg=TEXT,
        ).pack(anchor="w")
        tk.Label(
            main, text="One desktop controller for hand gestures + voice actions",
            font=("Segoe UI", 11), bg=BG, fg=MUTED,
        ).pack(anchor="w", pady=(2, 18))

        for module, heading, help_text in [
            ("gesture", "Hand Gesture Engine", "Webcam • MediaPipe • Cursor / Click / Scroll / Zoom"),
            ("voice", "Voice Command Engine", "Microphone • Vosk • Apps / Windows / Files"),
        ]:
            row = tk.Frame(main, bg=CARD, padx=16, pady=12)
            row.pack(fill="x", pady=(0, 10))
            top = tk.Frame(row, bg=CARD)
            top.pack(fill="x")
            tk.Label(
                top, text=heading, font=("Segoe UI", 14, "bold"),
                bg=CARD, fg=TEXT,
            ).pack(side="left")
            label = tk.Label(
                top, text="● Stopped", font=("Segoe UI", 11, "bold"),
                bg=CARD, fg="#f7a6a6",
            )
            label.pack(side="right")
            self.labels[module] = label
            tk.Label(
                row, text=help_text, font=("Segoe UI", 10),
                bg=CARD, fg=MUTED,
            ).pack(anchor="w", pady=(5, 9))
            buttons = tk.Frame(row, bg=CARD)
            buttons.pack(anchor="w")
            self._button(
                buttons, "▶ Start", lambda kind=module: self.start(kind),
                bg="#147d77", fg="white",
            ).pack(side="left", padx=(0, 8))
            self._button(
                buttons, "■ Stop", lambda kind=module: self.stop(kind),
                bg="#37465a", fg=TEXT,
            ).pack(side="left")

        toolbar = tk.Frame(main, bg=BG)
        toolbar.pack(fill="x", pady=(6, 12))
        self._button(toolbar, "▶ Start Both", self.start_all, "#127c76", "white").pack(side="left", padx=(0, 8))
        self._button(toolbar, "■ Stop All", self.stop_all, "#9e3945", "white").pack(side="left", padx=(0, 8))
        self._button(toolbar, "Clear Log", self.clear_log, "#37465a", TEXT).pack(side="left")

        tk.Label(
            main, text="Live logs", font=("Segoe UI", 13, "bold"),
            bg=BG, fg=TEXT,
        ).pack(anchor="w", pady=(3, 5))
        self.log = scrolledtext.ScrolledText(
            main, bg="#0a1524", fg="#c4f0e8", insertbackground="white",
            font=("Consolas", 10), wrap="word", relief="flat", state="disabled",
        )
        self.log.pack(fill="both", expand=True)

        tk.Label(
            main,
            text=("Gesture camera: click its window and press S to enable/disable controls; Q to quit. "
                  "Voice: say your usual commands. Stop All exits both engines."),
            bg=BG, fg=MUTED, font=("Segoe UI", 9), justify="left", wraplength=800,
        ).pack(anchor="w", pady=(10, 0))
        self._log("Controller ready. Start either engine, or click Start Both.")

    @staticmethod
    def _button(parent, text, command, bg, fg):
        return tk.Button(
            parent, text=text, command=command, bg=bg, fg=fg,
            font=("Segoe UI", 10, "bold"), padx=12, pady=6,
            relief="flat", activebackground=bg, activeforeground=fg,
            cursor="hand2",
        )

    def _log(self, line: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", line.rstrip() + "\n")
        # Cap to about 550 lines so prolonged recognition logs stay responsive.
        num_lines = int(self.log.index("end-1c").split(".")[0])
        if num_lines > 550:
            self.log.delete("1.0", "101.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _send_log(self, module: str, text: str) -> None:
        try:
            self.events.put_nowait((module, text))
        except queue.Full:
            # Never block subprocess stdout readers or the GUI on excess logs.
            pass

    def start(self, module: str) -> None:
        existing = self.procs[module]
        if existing is not None and existing.poll() is None:
            self._log(f"[{module}] Already running.")
            return
        script = SCRIPTS[module]
        if not script.is_file():
            messagebox.showerror(
                "Missing Python file",
                f"Could not find:\n{script}\n\nKeep main.py in your GestureVoice-AI root folder.",
                parent=self.root,
            )
            return

        try:
            proc = subprocess.Popen(
                [sys.executable, "-u", str(script)],
                cwd=str(PROJECT_ROOT),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0),
            )
        except OSError as exc:
            messagebox.showerror("Cannot start module", str(exc), parent=self.root)
            return

        self.procs[module] = proc
        self._log(f"[{module}] Started (PID {proc.pid}).")
        threading.Thread(
            target=self._read_stdout, args=(module, proc), daemon=True,
        ).start()

    def _read_stdout(self, module: str, proc: subprocess.Popen) -> None:
        try:
            if proc.stdout:
                for line in proc.stdout:
                    self._send_log(module, line.rstrip("\r\n"))
        except (OSError, ValueError):
            pass

    @staticmethod
    def _release_left_mouse_button() -> None:
        """Avoid leaving a drag held if the gesture engine is stopped forcibly."""
        if os.name == "nt":
            try:
                ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
            except (AttributeError, OSError):
                pass

    def stop(self, module: str) -> None:
        proc = self.procs[module]
        if proc is None or proc.poll() is not None:
            self._log(f"[{module}] Not running.")
            return
        self._log(f"[{module}] Stopping...")
        try:
            # Windows Popen.terminate is immediate. This orchestrator does not
            # modify the existing modules to add cooperative shutdown hooks.
            proc.terminate()
        except OSError as exc:
            self._log(f"[{module}] Stop error: {exc}")
        finally:
            if module == "gesture":
                self._release_left_mouse_button()

    def start_all(self) -> None:
        self.start("gesture")
        self.start("voice")

    def stop_all(self) -> None:
        self.stop("gesture")
        self.stop("voice")

    def _update_ui(self) -> None:
        if self.closing:
            return
        for _ in range(120):
            try:
                module, line = self.events.get_nowait()
            except queue.Empty:
                break
            self._log(f"[{module}] {line}")

        for module, label in self.labels.items():
            proc = self.procs[module]
            active = proc is not None and proc.poll() is None
            label.config(
                text="● Running" if active else "● Stopped",
                fg=ACCENT if active else "#f7a6a6",
            )
            if proc is not None and not active:
                self._log(f"[{module}] Exited (status {proc.returncode}).")
                self.procs[module] = None
                if module == "gesture":
                    self._release_left_mouse_button()
        self.root.after(120, self._update_ui)

    def close(self) -> None:
        if self.closing:
            return
        self.closing = True
        for module in self.procs:
            proc = self.procs[module]
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                except OSError:
                    pass
        self._release_left_mouse_button()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    GestureVoiceLauncher().run()
