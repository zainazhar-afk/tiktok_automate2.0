"""OpenCV-backed face/object tracking for timeline smart crop keyframes."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from app.models.schemas import TimelineClip


TARGET_ASPECT = 9 / 16
MAX_KEYFRAMES = 80


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float
    score: float = 1.0

    @property
    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)

    @property
    def center(self) -> tuple[float, float]:
        return self.x + self.w / 2.0, self.y + self.h / 2.0


def _load_cv2():
    try:
        import cv2  # type: ignore
    except Exception as exc:
        raise RuntimeError("OpenCV is not installed. Install opencv-python-headless.") from exc
    return cv2


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _select_box(boxes: Iterable[Box], frame_w: int, frame_h: int, previous: tuple[float, float] | None) -> Box | None:
    candidates = list(boxes)
    if not candidates:
        return None
    diag = math.hypot(frame_w, frame_h) or 1.0

    def score(box: Box) -> float:
        area_score = min(1.0, box.area / max(1.0, frame_w * frame_h * 0.18))
        if previous:
            cx, cy = box.center
            dist_score = 1.0 - min(1.0, math.hypot(cx - previous[0], cy - previous[1]) / diag)
        else:
            cx, cy = box.center
            dist_score = 1.0 - min(1.0, math.hypot(cx - frame_w / 2, cy - frame_h / 2) / diag)
        return box.score * 0.35 + area_score * 0.4 + dist_score * 0.25

    return max(candidates, key=score)


def _face_boxes(cv2, frame, cascade) -> list[Box]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    detections = cascade.detectMultiScale(
        gray,
        scaleFactor=1.08,
        minNeighbors=4,
        flags=cv2.CASCADE_SCALE_IMAGE,
        minSize=(36, 36),
    )
    return [Box(float(x), float(y), float(w), float(h), 1.0) for x, y, w, h in detections]


def _motion_boxes(cv2, frame, previous_gray) -> list[Box]:
    if previous_gray is None:
        return []
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    diff = cv2.absdiff(gray, previous_gray)
    diff = cv2.GaussianBlur(diff, (7, 7), 0)
    _threshold, mask = cv2.threshold(diff, 24, 255, cv2.THRESH_BINARY)
    mask = cv2.dilate(mask, None, iterations=3)
    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    frame_h, frame_w = gray.shape[:2]
    min_area = frame_w * frame_h * 0.003
    max_area = frame_w * frame_h * 0.72
    boxes: list[Box] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area or area > max_area:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if w < 24 or h < 24:
            continue
        boxes.append(Box(float(x), float(y), float(w), float(h), min(1.0, area / max_area + 0.25)))
    return boxes


def _saliency_boxes(cv2, frame) -> list[Box]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 60, 150)
    edges = cv2.dilate(edges, None, iterations=2)
    contours, _hierarchy = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    frame_h, frame_w = gray.shape[:2]
    min_area = frame_w * frame_h * 0.008
    max_area = frame_w * frame_h * 0.55
    boxes: list[Box] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area or area > max_area:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if w < 40 or h < 40:
            continue
        boxes.append(Box(float(x), float(y), float(w), float(h), min(0.75, area / max_area + 0.15)))
    return boxes


def _crop_keyframe(time_value: float, box: Box | None, frame_w: int, frame_h: int, mode: str) -> dict:
    crop_w = min(float(frame_w), float(frame_h) * TARGET_ASPECT)
    crop_h = crop_w / TARGET_ASPECT
    if crop_h > frame_h:
        crop_h = float(frame_h)
        crop_w = crop_h * TARGET_ASPECT

    if box:
        cx, cy = box.center
        y_bias = 0.43 if mode == "face" else 0.5
        x = cx - crop_w / 2.0
        y = cy - crop_h * y_bias
    else:
        x = (frame_w - crop_w) / 2.0
        y = (frame_h - crop_h) / 2.0

    x = _clamp(x, 0.0, max(0.0, frame_w - crop_w))
    y = _clamp(y, 0.0, max(0.0, frame_h - crop_h))
    return {
        "time": round(time_value, 3),
        "x_pct": round(x / frame_w, 5),
        "y_pct": round(y / frame_h, 5),
        "w_pct": round(crop_w / frame_w, 5),
        "h_pct": round(crop_h / frame_h, 5),
    }


def _smooth_keyframes(keyframes: list[dict]) -> list[dict]:
    if len(keyframes) < 3:
        return keyframes
    smoothed: list[dict] = []
    for idx, keyframe in enumerate(keyframes):
        window = keyframes[max(0, idx - 1): min(len(keyframes), idx + 2)]
        next_frame = dict(keyframe)
        next_frame["x_pct"] = round(sum(item["x_pct"] for item in window) / len(window), 5)
        next_frame["y_pct"] = round(sum(item["y_pct"] for item in window) / len(window), 5)
        smoothed.append(next_frame)
    return smoothed


def analyze_clip(source_path: str, clip: TimelineClip, mode: str = "face", sample_interval: float = 0.5) -> dict:
    cv2 = _load_cv2()
    cap = cv2.VideoCapture(source_path)
    if not cap.isOpened():
        raise RuntimeError("OpenCV could not open source video")

    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if frame_w <= 0 or frame_h <= 0:
        cap.release()
        raise RuntimeError("OpenCV could not read source dimensions")

    mode = mode if mode in {"face", "object"} else "face"
    duration = max(0.1, clip.source_end - clip.source_start)
    interval = max(sample_interval, duration / MAX_KEYFRAMES)
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    face_cascade = cv2.CascadeClassifier(cascade_path)
    if face_cascade.empty() and mode == "face":
        cap.release()
        raise RuntimeError("OpenCV face detector could not be loaded")

    previous_gray = None
    previous_center: tuple[float, float] | None = None
    smoothed_box: Box | None = None
    detections = 0
    frames_analyzed = 0
    keyframes: list[dict] = []
    t = clip.source_start

    while t <= clip.source_end + 0.001:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000.0)
        ok, frame = cap.read()
        if not ok or frame is None:
            break

        frames_analyzed += 1
        boxes: list[Box] = []
        if mode == "face":
            boxes.extend(_face_boxes(cv2, frame, face_cascade))
        else:
            boxes.extend(_motion_boxes(cv2, frame, previous_gray))
            if not boxes:
                boxes.extend(_saliency_boxes(cv2, frame))
            if not boxes and not face_cascade.empty():
                boxes.extend(_face_boxes(cv2, frame, face_cascade))

        chosen = _select_box(boxes, frame_w, frame_h, previous_center)
        if chosen:
            detections += 1
            if smoothed_box:
                alpha = 0.34
                chosen = Box(
                    x=smoothed_box.x * (1 - alpha) + chosen.x * alpha,
                    y=smoothed_box.y * (1 - alpha) + chosen.y * alpha,
                    w=smoothed_box.w * (1 - alpha) + chosen.w * alpha,
                    h=smoothed_box.h * (1 - alpha) + chosen.h * alpha,
                    score=chosen.score,
                )
            smoothed_box = chosen
            previous_center = chosen.center

        keyframes.append(_crop_keyframe(t, smoothed_box, frame_w, frame_h, mode))
        previous_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        t += interval

    cap.release()

    if keyframes and keyframes[-1]["time"] < clip.source_end:
        keyframes.append(_crop_keyframe(clip.source_end, smoothed_box, frame_w, frame_h, mode))

    keyframes = _smooth_keyframes(keyframes)
    confidence = round((detections / frames_analyzed) * 100.0, 1) if frames_analyzed else 0.0
    message = (
        f"Tracked {detections}/{frames_analyzed} sampled frames"
        if detections
        else "No confident target found; centered crop keyframes were generated"
    )
    return {
        "keyframes": keyframes,
        "detections": detections,
        "frames_analyzed": frames_analyzed,
        "confidence": confidence,
        "tracker": f"opencv-{mode}",
        "message": message,
    }
