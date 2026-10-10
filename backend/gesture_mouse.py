"""GestureVoice AI: webcam hand tracking and desktop gesture control.

Press S in the camera preview to toggle controls; Q or Esc quits.
Requires backend/models/hand_landmarker.task (not included in this source zip).
"""

import math
import time
from pathlib import Path

import cv2
import mediapipe as mp
import pyautogui

try:
    from .camera_bridge import CameraBridge
except ImportError:
    from camera_bridge import CameraBridge

MODEL_PATH = Path(__file__).parent / "models" / "hand_landmarker.task"
if not MODEL_PATH.is_file():
    raise FileNotFoundError(f"Hand tracking model not found: {MODEL_PATH}")

options = mp.tasks.vision.HandLandmarkerOptions(
    base_options=mp.tasks.BaseOptions(model_asset_path=str(MODEL_PATH)),
    running_mode=mp.tasks.vision.RunningMode.VIDEO,
    num_hands=1,
    min_hand_detection_confidence=0.65,
    min_hand_presence_confidence=0.65,
    min_tracking_confidence=0.65,
)

screen_w, screen_h = pyautogui.size()
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0
smooth_x, smooth_y = pyautogui.position()
mouse_enabled = False

GESTURE_STABLE_TIME = 0.18
CLICK_COOLDOWN = 0.70
DRAG_DELAY = 0.80
SCROLL_THRESHOLD = 0.045
ZOOM_THRESHOLD = 0.075
SMOOTHING = 0.35

candidate_mode = "NO HAND"
stable_mode = "NO HAND"
candidate_since = time.monotonic()
left_pinch_start = None
dragging = False
last_click_time = 0.0
motion_reference = None
last_timestamp = -1


def distance(p1, p2):
    return math.hypot(p1.x - p2.x, p1.y - p2.y)


def finger_up(hand, tip, pip):
    return hand[tip].y < hand[pip].y - 0.015


def move_cursor(index_finger):
    global smooth_x, smooth_y
    x = max(0.0, min(1.0, (index_finger.x - 0.15) / 0.70))
    y = max(0.0, min(1.0, (index_finger.y - 0.15) / 0.70))
    target_x = 10 + x * (screen_w - 20)
    target_y = 10 + y * (screen_h - 20)
    smooth_x += (target_x - smooth_x) * SMOOTHING
    smooth_y += (target_y - smooth_y) * SMOOTHING
    pyautogui.moveTo(int(smooth_x), int(smooth_y))


def detect_gesture(hand):
    thumb, index, middle = hand[4], hand[8], hand[12]
    palm_width = max(distance(hand[5], hand[17]), 0.001)
    index_distance = distance(thumb, index) / palm_width
    middle_distance = distance(thumb, middle) / palm_width
    left_pinch = (index_distance < 0.35 and middle_distance > 0.48
                  and middle_distance > index_distance * 1.35)
    right_pinch = (middle_distance < 0.35 and index_distance > 0.48
                   and index_distance > middle_distance * 1.35)
    index_up = finger_up(hand, 8, 6)
    middle_up = finger_up(hand, 12, 10)
    ring_up = finger_up(hand, 16, 14)
    pinky_up = finger_up(hand, 20, 18)
    if left_pinch:
        return "LEFT PINCH"
    if right_pinch:
        return "RIGHT PINCH"
    if index_up and middle_up and ring_up and not pinky_up:
        return "ZOOM"
    if index_up and middle_up and not ring_up and not pinky_up:
        return "SCROLL"
    return "CURSOR"


def release_drag():
    global dragging, left_pinch_start
    if dragging:
        pyautogui.mouseUp(button="left")
        print("Drag Released")
    dragging = False
    left_pinch_start = None


def change_mode(new_mode, now):
    global stable_mode, left_pinch_start, last_click_time, motion_reference
    old_mode = stable_mode
    if old_mode == new_mode:
        return
    if old_mode == "LEFT PINCH":
        if dragging:
            release_drag()
        elif (new_mode == "CURSOR" and left_pinch_start is not None
              and now - last_click_time >= CLICK_COOLDOWN):
            pyautogui.click(button="left")
            last_click_time = now
            print("Left Click")
        left_pinch_start = None
    if new_mode == "LEFT PINCH":
        left_pinch_start = now
    if new_mode == "RIGHT PINCH" and now - last_click_time >= CLICK_COOLDOWN:
        pyautogui.click(button="right")
        last_click_time = now
        print("Right Click")
    stable_mode = new_mode
    motion_reference = None


def main():
    global mouse_enabled, candidate_mode, candidate_since, stable_mode
    global motion_reference, smooth_x, smooth_y, last_timestamp, dragging

    bridge = CameraBridge()
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise RuntimeError("Unable to access webcam!")
    print("GestureVoice AI Started | S: toggle | Q/Esc: quit")
    try:
        with mp.tasks.vision.HandLandmarker.create_from_options(options) as landmarker:
            while True:
                success, frame = cap.read()
                if not success:
                    print("Camera frame unavailable")
                    break
                frame = cv2.flip(frame, 1)
                height, width, _ = frame.shape
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                now = time.monotonic()
                timestamp = max(int(now * 1000), last_timestamp + 1)
                last_timestamp = timestamp
                result = landmarker.detect_for_video(mp_image, timestamp)
                hand = result.hand_landmarks[0] if result.hand_landmarks else None
                detected_mode = detect_gesture(hand) if hand is not None else "NO HAND"
                if hand is not None:
                    for point in hand:
                        cv2.circle(frame, (int(point.x * width), int(point.y * height)),
                                   4, (0, 255, 0), -1)
                    index = hand[8]
                    cv2.circle(frame, (int(index.x * width), int(index.y * height)),
                               10, (255, 0, 255), -1)
                # In dashboard mode, cursor ON/OFF is controlled from React.
                # Missing backend heartbeat immediately pauses mouse control.
                if bridge.web_mode:
                    desired = bridge.controls_enabled()
                    if desired != mouse_enabled:
                        mouse_enabled = desired
                        release_drag()
                        stable_mode = candidate_mode = "NO HAND"
                        candidate_since = now
                        motion_reference = None
                        smooth_x, smooth_y = pyautogui.position()
                        print("Mouse control", "ON" if mouse_enabled else "OFF")
                if mouse_enabled:
                    if detected_mode != candidate_mode:
                        candidate_mode = detected_mode
                        candidate_since = now
                    elif (candidate_mode != stable_mode
                          and now - candidate_since >= GESTURE_STABLE_TIME):
                        change_mode(candidate_mode, now)

                    if hand is not None:
                        if (stable_mode in ("CURSOR", "LEFT PINCH", "RIGHT PINCH")
                                and detected_mode == stable_mode):
                            move_cursor(hand[8])
                        if (stable_mode == detected_mode == "LEFT PINCH"
                                and left_pinch_start is not None and not dragging
                                and now - left_pinch_start >= DRAG_DELAY):
                            pyautogui.mouseDown(button="left")
                            dragging = True
                            print("Drag Started")
                        if stable_mode == detected_mode == "SCROLL":
                            current_y = hand[9].y
                            if motion_reference is None:
                                motion_reference = current_y
                            else:
                                difference = current_y - motion_reference
                                if abs(difference) > SCROLL_THRESHOLD:
                                    pyautogui.scroll(3 if difference < 0 else -3)
                                    motion_reference = current_y
                        elif stable_mode == detected_mode == "ZOOM":
                            current_y = hand[9].y
                            if motion_reference is None:
                                motion_reference = current_y
                            else:
                                difference = current_y - motion_reference
                                if abs(difference) > ZOOM_THRESHOLD:
                                    pyautogui.hotkey("ctrl", "=" if difference < 0 else "-")
                                    motion_reference = current_y
                        elif stable_mode not in ("SCROLL", "ZOOM"):
                            motion_reference = None
                status = "ON" if mouse_enabled else "OFF"
                cv2.putText(frame, f"Mouse Control: {status}", (20, 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
                cv2.putText(frame, f"Gesture: {stable_mode}", (20, 80),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                cv2.putText(frame, "S: Toggle | Q/Esc: Quit", (20, 120),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                if bridge.web_mode:
                    # Publish the SAME webcam frames already used by MediaPipe.
                    # No second camera access, and no extra OpenCV window.
                    bridge.offer(frame, detected_mode)
                else:
                    cv2.imshow("GestureVoice AI", frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key in (ord("q"), 27):
                        break
                    if key == ord("s"):
                        mouse_enabled = not mouse_enabled
                        release_drag()
                        stable_mode = candidate_mode = "NO HAND"
                        candidate_since = time.monotonic()
                        motion_reference = None
                        smooth_x, smooth_y = pyautogui.position()
                        print("Mouse control", "ON" if mouse_enabled else "OFF")
    except KeyboardInterrupt:
        print("Stopped by user")
    except pyautogui.FailSafeException:
        print("Emergency PyAutoGUI stop activated")
    finally:
        if dragging:
            original_failsafe = pyautogui.FAILSAFE
            try:
                pyautogui.FAILSAFE = False
                pyautogui.mouseUp(button="left")
            finally:
                pyautogui.FAILSAFE = original_failsafe
        cap.release()
        cv2.destroyAllWindows()
        print("GestureVoice AI Closed")


if __name__ == "__main__":
    main()
