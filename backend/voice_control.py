"""GestureVoice AI - Windows voice launcher, controls, and safe window closing.

Offline Vosk recognition + on-screen browser/folder/file/window chooser.
Application closing sends normal Windows close requests (no forced process kills).
Run from the GestureVoice-AI project using its virtual environment.
"""

import json
import os
import queue
import re
import shutil
import subprocess
import time
import tkinter as tk
import webbrowser
import winreg
from datetime import datetime
from pathlib import Path

import pyautogui
import sounddevice as sd
from vosk import KaldiRecognizer, Model, SetLogLevel

BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = BASE_DIR / "models" / "vosk-model-small-en-us-0.15"
SCREENSHOT_DIR = BASE_DIR.parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True, parents=True)

pyautogui.FAILSAFE = True
SetLogLevel(-1)
AUDIO_QUEUE = queue.Queue(maxsize=30)
COOLDOWN_SECONDS = 0.8
PAGE_SIZE = 10

# Voice grammar is restricted to supported instructions so Vosk can better
# recognize short commands. "[unk]" allows unknown speech to be ignored.
PHRASES = [
    "browser", "browsers", "show browsers", "show browser",
    "show all browsers", "list browsers", "open browser",
    "folders", "show folders", "list folders", "open folders",
    "files", "show files", "list files", "open files",
    "open chrome", "open edge", "open microsoft edge", "open firefox",
    "open brave", "open opera", "open opera gx", "open vivaldi",
    "open vscode", "open vs code", "open visual studio code", "open code",
    "open chatgpt", "open chat g p t", "chatgpt", "chat g p t",
    "open notepad", "open calculator", "volume up", "increase volume",
    "volume down", "decrease volume", "mute", "take screenshot",
    "screenshot", "scroll up", "scroll down", "zoom in", "zoom out",
    "show desktop", "stop listening", "exit voice control", "close menu",
    "close window", "close current window", "close active window",
    "close tab", "close current tab", "close browser tab",
    "close folder", "close file", "close explorer",
    "close vscode", "close vs code", "close visual studio code",
    "close notepad", "close calculator", "close browser",
    "close chrome", "close edge", "close microsoft edge", "close firefox",
    "close brave", "close opera", "close chatgpt", "close chat g p t",
    "running apps", "show running apps", "show open windows", "open windows",
    "next", "next page", "previous", "previous page", "back",
    "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "first", "second", "third", "fourth", "fifth",
    "sixth", "seventh", "eighth", "ninth", "tenth",
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
    "computer", "[unk]",
]
PHRASES += ["computer " + p for p in PHRASES if p != "[unk]" and not p.startswith("computer")]


# -------- Windows installed browser discovery --------

def add_browser(found, name, executable):
    if not executable:
        return
    path = Path(os.path.expandvars(str(executable).strip('"')))
    if path.is_file() and path.suffix.lower() == ".exe":
        found[str(path).casefold()] = {"name": name, "kind": "browser", "path": path}


def browsers_on_pc():
    found = {}
    pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    pf86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))
    known = [
        ("Google Chrome", Path(pf) / "Google/Chrome/Application/chrome.exe"),
        ("Google Chrome", Path(pf86) / "Google/Chrome/Application/chrome.exe"),
        ("Google Chrome", Path(local) / "Google/Chrome/Application/chrome.exe"),
        ("Microsoft Edge", Path(pf86) / "Microsoft/Edge/Application/msedge.exe"),
        ("Microsoft Edge", Path(pf) / "Microsoft/Edge/Application/msedge.exe"),
        ("Mozilla Firefox", Path(pf) / "Mozilla Firefox/firefox.exe"),
        ("Mozilla Firefox", Path(pf86) / "Mozilla Firefox/firefox.exe"),
        ("Brave", Path(pf) / "BraveSoftware/Brave-Browser/Application/brave.exe"),
        ("Brave", Path(local) / "BraveSoftware/Brave-Browser/Application/brave.exe"),
        ("Opera", Path(local) / "Programs/Opera/launcher.exe"),
        ("Opera GX", Path(local) / "Programs/Opera GX/launcher.exe"),
        ("Vivaldi", Path(local) / "Vivaldi/Application/vivaldi.exe"),
        ("Vivaldi", Path(pf) / "Vivaldi/Application/vivaldi.exe"),
    ]
    for name, path in known:
        add_browser(found, name, path)

    # Browsers registered in Windows default-program listings (may find more).
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, r"SOFTWARE\Clients\StartMenuInternet") as parent:
                count = winreg.QueryInfoKey(parent)[0]
                for i in range(count):
                    keyname = winreg.EnumKey(parent, i)
                    try:
                        with winreg.OpenKey(parent, keyname) as app:
                            try:
                                label = winreg.QueryValueEx(app, "")[0]
                            except OSError:
                                label = keyname
                            with winreg.OpenKey(app, r"shell\open\command") as cmd_key:
                                command = winreg.QueryValueEx(cmd_key, "")[0]
                            # Windows commands usually start with a quoted exe path.
                            match = re.search(r'"([^"\r\n]+?\.exe)"|([^"\r\n]+?\.exe)', command, re.I)
                            if match:
                                add_browser(found, str(label), match.group(1) or match.group(2))
                    except OSError:
                        continue
        except OSError:
            continue
    return sorted(found.values(), key=lambda item: item["name"].casefold())


def known_folder(reg_name, fallback):
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        ) as key:
            value = winreg.QueryValueEx(key, reg_name)[0]
            path = Path(os.path.expandvars(value))
            if path.is_dir():
                return path
    except OSError:
        pass
    candidates = [Path.home() / fallback]
    if os.environ.get("OneDrive"):
        candidates.append(Path(os.environ["OneDrive"]) / fallback)
    return next((p for p in candidates if p.is_dir()), None)


def folders_on_pc():
    specs = [
        ("Desktop", "Desktop", "Desktop"),
        ("Documents", "Personal", "Documents"),
        ("Downloads", "{374DE290-123F-4565-9164-39C4925E467B}", "Downloads"),
        ("Pictures", "My Pictures", "Pictures"),
        ("Music", "My Music", "Music"),
        ("Videos", "My Video", "Videos"),
    ]
    items = []
    seen = set()
    for name, registry_name, fallback in specs:
        path = known_folder(registry_name, fallback)
        if path and str(path).casefold() not in seen:
            items.append({"name": name, "kind": "folder", "path": path})
            seen.add(str(path).casefold())
    return items


def files_in_folder(folder):
    """List files directly in the chosen folder (not the entire disk)."""
    try:
        paths = [p for p in folder.iterdir() if p.is_file()]
        paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return [{"name": p.name, "kind": "file", "path": p} for p in paths[:100]]
    except (OSError, PermissionError) as exc:
        print("Cannot list files:", exc)
        return []


# -------- Voice actions and on-screen choices --------

class GestureVoiceApp:
    def __init__(self):
        self.running = True
        self.last_action_time = 0.0
        self.items = []
        self.page = 0
        self.mode = ""
        folders = folders_on_pc()
        self.current_folder = next((x["path"] for x in folders if x["name"] == "Downloads"), Path.home())

        self.root = tk.Tk()
        self.root.title("GestureVoice AI | Voice Launcher")
        self.root.geometry("740x460")
        self.root.configure(bg="#101827")
        self.heading = tk.Label(self.root, font=("Segoe UI", 17, "bold"), fg="white", bg="#101827")
        self.heading.pack(padx=20, pady=(18, 8), anchor="w")
        self.hint = tk.Label(self.root, font=("Segoe UI", 10), fg="#a5bbd7", bg="#101827")
        self.hint.pack(padx=20, pady=(0, 10), anchor="w")
        self.listbox = tk.Listbox(self.root, font=("Segoe UI", 12), bg="#172338", fg="white", height=12,
                                  selectbackground="#3868ad", highlightthickness=0, borderwidth=0)
        self.listbox.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        self.listbox.bind("<Double-Button-1>", self.open_clicked)
        self.footer = tk.Label(self.root, font=("Segoe UI", 10), fg="#9ccfff", bg="#101827")
        self.footer.pack(padx=20, pady=(0, 16))
        self.root.protocol("WM_DELETE_WINDOW", self.root.withdraw)
        self.root.withdraw()  # Show only when a list is requested.

    def display(self, heading, items, mode):
        self.mode, self.items, self.page = mode, items, 0
        self.heading.config(text=heading)
        self.hint.config(text="Say 'one' to 'ten' or double-click an item. Say 'next page' for more.")
        self.render_page()
        self.root.deiconify()
        self.root.lift()
        print(f"\n{heading}: {len(items)} found")

    def render_page(self):
        self.listbox.delete(0, tk.END)
        page_items = self.items[self.page * PAGE_SIZE:(self.page + 1) * PAGE_SIZE]
        for number, item in enumerate(page_items, 1):
            self.listbox.insert(tk.END, f" {number}.  {item['name']}")
        if not page_items:
            self.listbox.insert(tk.END, " No items found in this location.")
        pages = max(1, (len(self.items) + PAGE_SIZE - 1) // PAGE_SIZE)
        self.footer.config(text=f"Page {self.page + 1}/{pages}  |  Say 'close menu' to hide")

    def open_clicked(self, _event):
        selected = self.listbox.curselection()
        if selected:
            self.choose(selected[0] + 1)

    def choose(self, number):
        index = self.page * PAGE_SIZE + (number - 1)
        if not 0 <= index < len(self.items):
            print("No item with that number on this page.")
            return
        item = self.items[index]
        print("Selected:", item["name"])
        if item["kind"] == "close_window":
            # A normal close request gives applications a chance to prompt
            # about unsaved documents instead of terminating a process.
            try:
                item["window"].close()
                print("Requested window close:", item["name"])
            except Exception as exc:
                print("Could not close window:", exc)
            self.root.withdraw()
            self.items = []
            return
        path = item["path"]
        if item["kind"] == "browser":
            subprocess.Popen([str(path)])
        elif item["kind"] == "folder":
            self.current_folder = path
            os.startfile(path)
            print("Current file folder:", path)
        else:
            # Avoid voice-triggered execution of EXE/script files.
            safe_suffixes = {
                ".pdf", ".txt", ".md", ".csv", ".doc", ".docx", ".xls", ".xlsx",
                ".ppt", ".pptx", ".jpg", ".jpeg", ".png", ".gif", ".webp",
                ".mp3", ".mp4", ".mov", ".wav", ".json",
            }
            if path.suffix.lower() in safe_suffixes:
                os.startfile(path)
            else:
                subprocess.Popen(["explorer.exe", "/select,", str(path)])
                print("Opened file location rather than executing an unknown file type.")

    # -------- Close windows safely (Windows normal close, not process kill) --------

    def open_desktop_windows(self):
        """Get titled windows, excluding the voice selection popup."""
        try:
            return [
                window for window in pyautogui.getAllWindows()
                if window.title.strip()
                and window.title != self.root.title()
                and window.visible
            ]
        except Exception as exc:
            print("Cannot enumerate desktop windows:", exc)
            return []

    @staticmethod
    def window_matches(window, app):
        title = window.title.casefold()
        match_terms = {
            "vscode": ("visual studio code",),
            "notepad": ("notepad",),
            "calculator": ("calculator",),
            "chrome": ("google chrome",),
            "edge": ("microsoft edge",),
            "firefox": ("mozilla firefox",),
            "brave": ("brave",),
            "opera": ("opera",),
            # A browser window is considered a browser when its title has
            # a recognizable browser name (not all browsers show one).
            "browser": (
                "google chrome", "microsoft edge", "mozilla firefox",
                "brave", "opera", "vivaldi",
            ),
        }
        return any(term in title for term in match_terms.get(app, ()))

    def show_close_choices(self, title, windows):
        if not windows:
            print(f"No matching open window found for {title}.")
            return
        items = [
            {"name": window.title, "kind": "close_window", "window": window}
            for window in windows
        ]
        self.display(f"Choose a window to close: {title}", items, "close_windows")

    def close_active_window(self):
        window = pyautogui.getActiveWindow()
        if window is None:
            print("No active window found. Focus a window and try again.")
            return
        if window.title == self.root.title():
            self.root.withdraw()
            print("Closed the voice selection menu. Focus the target app to close it.")
            return
        title = window.title or "current window"
        window.close()  # WM_CLOSE: app can show a save-changes prompt.
        print("Requested close for:", title)

    def close_named_app(self, app):
        windows = [w for w in self.open_desktop_windows() if self.window_matches(w, app)]
        if len(windows) == 1:
            window = windows[0]
            window.close()
            print("Requested close for:", window.title)
        else:
            self.show_close_choices(app, windows)

    def close_chatgpt_tab(self):
        # Chrome/Edge tab contents cannot be reliably selected by website
        # name without browser automation. Only close the CURRENT tab if
        # its title clearly says ChatGPT, so other tabs are not affected.
        active = pyautogui.getActiveWindow()
        if active and "chatgpt" in active.title.casefold() and self.window_matches(active, "browser"):
            pyautogui.hotkey("ctrl", "w")
            print("Closed active ChatGPT tab.")
        else:
            print("Switch to the ChatGPT browser tab, then say 'close chatgpt' or 'close tab'.")

    def execute(self, text):
        text = " ".join(text.lower().split())
        if text.startswith("computer "):
            text = text[len("computer "):]
        aliases = {
            "open browser": "show browsers", "browser": "show browsers", "browsers": "show browsers",
            "show browser": "show browsers", "show all browsers": "show browsers", "list browsers": "show browsers",
            "folders": "show folders", "open folders": "show folders", "list folders": "show folders",
            "files": "show files", "open files": "show files", "list files": "show files",
            "open vs code": "open vscode", "open visual studio code": "open vscode", "open code": "open vscode",
            "open chat g p t": "open chatgpt", "chatgpt": "open chatgpt", "chat g p t": "open chatgpt",
            "increase volume": "volume up", "decrease volume": "volume down", "screenshot": "take screenshot",
            "exit voice control": "stop listening", "next": "next page", "previous": "previous page",
            "close current window": "close window", "close active window": "close window",
            "close current tab": "close tab", "close browser tab": "close tab",
            "close folder": "close window", "close file": "close window", "close explorer": "close window",
            "close vs code": "close vscode", "close visual studio code": "close vscode",
            "close microsoft edge": "close edge", "close chat g p t": "close chatgpt",
            "running apps": "show open windows", "show running apps": "show open windows",
            "open windows": "show open windows",
        }
        text = aliases.get(text, text)
        if text in ("stop listening",):
            print("Stopping voice control...")
            self.running = False
            return
        if text == "close menu":
            self.root.withdraw()
            return
        if text == "back":
            self.display("Folders", folders_on_pc(), "folders")
            return
        if text in ("next page", "previous page"):
            if self.items:
                last = (len(self.items) - 1) // PAGE_SIZE
                self.page = min(last, self.page + 1) if text == "next page" else max(0, self.page - 1)
                self.render_page()
            return
        number_words = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
            "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
            "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
        }
        if self.items and (text in number_words or text in {str(i) for i in range(1, 11)}):
            self.choose(number_words.get(text, int(text) if text.isdigit() else 0))
            return
        if time.monotonic() - self.last_action_time < COOLDOWN_SECONDS:
            print("Waiting for command cooldown...")
            return
        self.last_action_time = time.monotonic()
        if text == "close window":
            self.close_active_window()
        elif text == "close tab":
            # Closes the currently active tab/editor, not an arbitrary tab.
            if pyautogui.getActiveWindow() and pyautogui.getActiveWindow().title == self.root.title():
                print("Close the selection menu first, then focus your browser and say 'close tab'.")
            else:
                pyautogui.hotkey("ctrl", "w")
                print("Requested close of active tab/editor.")
        elif text == "close chatgpt":
            self.close_chatgpt_tab()
        elif text.startswith("close ") and text[6:] in (
            "vscode", "notepad", "calculator", "browser", "chrome", "edge",
            "firefox", "brave", "opera",
        ):
            self.close_named_app(text[6:])
        elif text == "show open windows":
            self.show_close_choices("open desktop windows", self.open_desktop_windows())
        elif text == "show browsers":
            self.display("Browsers installed on this PC", browsers_on_pc(), "browsers")
        elif text == "show folders":
            self.display("Common folders on this PC", folders_on_pc(), "folders")
        elif text == "show files":
            self.display(f"Files in: {self.current_folder}", files_in_folder(self.current_folder), "files")
        elif text == "open chatgpt":
            webbrowser.open("https://chatgpt.com/")
            print("Opening ChatGPT in your default browser.")
        elif text == "open vscode":
            local = os.environ.get("LOCALAPPDATA", "")
            pf = os.environ.get("PROGRAMFILES", "")
            exe_candidates = [
                Path(local) / "Programs/Microsoft VS Code/Code.exe",
                Path(pf) / "Microsoft VS Code/Code.exe",
            ]
            executable = next((str(p) for p in exe_candidates if p.is_file()), None)
            executable = executable or shutil.which("code.cmd") or shutil.which("code")
            if executable:
                if str(executable).lower().endswith((".cmd", ".bat")):
                    subprocess.Popen(["cmd.exe", "/c", str(executable)])
                else:
                    subprocess.Popen([str(executable)])
                print("Opening VS Code.")
            else:
                print("VS Code wasn't found in the usual installation paths.")
        elif text.startswith("open ") and text[5:] in ("chrome", "edge", "microsoft edge", "firefox", "brave", "opera", "opera gx", "vivaldi"):
            desired = text[5:]
            browsers = browsers_on_pc()
            match = next((b for b in browsers if desired in b["name"].casefold() or desired in b["path"].name.casefold()), None)
            if match:
                self.choose_browser(match)
            else:
                print(f"Could not find installed browser: {desired}")
                self.display("Detected browsers", browsers, "browsers")
        elif text == "open notepad":
            subprocess.Popen(["notepad.exe"])
        elif text == "open calculator":
            subprocess.Popen(["calc.exe"])
        elif text == "volume up":
            pyautogui.press("volumeup", presses=3, interval=0.1)
        elif text == "volume down":
            pyautogui.press("volumedown", presses=3, interval=0.1)
        elif text == "mute":
            pyautogui.press("volumemute")
        elif text == "take screenshot":
            outfile = SCREENSHOT_DIR / f"screenshot_{datetime.now():%Y%m%d_%H%M%S_%f}.png"
            pyautogui.screenshot().save(outfile)
            print("Screenshot saved:", outfile)
        elif text == "scroll up":
            pyautogui.scroll(5)
        elif text == "scroll down":
            pyautogui.scroll(-5)
        elif text == "zoom in":
            pyautogui.hotkey("ctrl", "=")
        elif text == "zoom out":
            pyautogui.hotkey("ctrl", "-")
        elif text == "show desktop":
            pyautogui.hotkey("win", "d")
        else:
            print("Unknown command:", text)

    @staticmethod
    def choose_browser(item):
        subprocess.Popen([str(item["path"])])
        print("Opened", item["name"])

    def run(self):
        if not (MODEL_PATH / "conf" / "model.conf").is_file():
            print("Vosk model missing or incomplete:", MODEL_PATH)
            return
        print("Loading offline Vosk model...")
        model = Model(str(MODEL_PATH))
        device = sd.query_devices(kind="input")
        sample_rate = int(device["default_samplerate"])
        recognizer = KaldiRecognizer(model, sample_rate, json.dumps(PHRASES))
        print("\nVoice control ready! Try saying:")
        print("  'open vscode' | 'open chatgpt' | 'browsers' | 'folders' | 'files'")
        print("  'close window' | 'close tab' | 'close vscode' | 'close chrome'")
        print("  'close chatgpt' (only active ChatGPT tab) | 'show open windows'")
        print("  'one' (select) | 'next page' | 'stop listening'")
        print("Press Ctrl+C to stop at any time.\n")

        def audio_callback(indata, frames, audio_time, status):
            if status:
                print("Microphone:", status)
            try:
                AUDIO_QUEUE.put_nowait(bytes(indata))
            except queue.Full:
                pass

        try:
            with sd.RawInputStream(
                samplerate=sample_rate, blocksize=8000, dtype="int16", channels=1,
                callback=audio_callback,
            ):
                while self.running:
                    # Keep the small Tkinter selection window responsive.
                    self.root.update()
                    try:
                        chunk = AUDIO_QUEUE.get(timeout=0.07)
                    except queue.Empty:
                        continue
                    if recognizer.AcceptWaveform(chunk):
                        phrase = json.loads(recognizer.Result()).get("text", "").strip()
                        if phrase:
                            print("Heard:", phrase)
                            try:
                                self.execute(phrase)
                            except pyautogui.FailSafeException:
                                print("Emergency PyAutoGUI stop activated.")
                                break
                            except Exception as exc:
                                print("Command error:", exc)
        except KeyboardInterrupt:
            print("Voice control stopped by Ctrl+C.")
        finally:
            self.root.destroy()
            print("GestureVoice AI voice control closed.")


if __name__ == "__main__":
    GestureVoiceApp().run()
