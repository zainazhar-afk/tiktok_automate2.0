"""Auto cover/thumbnail generator with frame scoring and styled overlays."""
from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

from app.services import state_store
from app.services.processor import probe_video
from app.services.subtitle_editor import source_video_path
from app.tenant import storage_video_id

OUTPUT_DIR = os.path.abspath("output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def _load_cv2():
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception as exc:
        raise RuntimeError("OpenCV is not installed. Install opencv-python-headless.") from exc
    return cv2, np


def _safe_video_id(video_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", video_id or ""):
        raise ValueError("Invalid video id")
    return video_id


def _hex_to_bgr(color: str, fallback: str) -> tuple[int, int, int]:
    raw = (color or fallback).strip().lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", raw):
        raw = fallback.strip().lstrip("#")
    r, g, b = int(raw[:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
    return b, g, r


def _source_for_cover(video_id: str) -> str | None:
    timeline = os.path.join(OUTPUT_DIR, f"{storage_video_id(video_id)}_timeline.mp4")
    if os.path.isfile(timeline):
        return timeline
    return source_video_path(video_id)


def _face_detector(cv2):
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(cascade_path)
    return None if cascade.empty() else cascade


def _detect_faces(cv2, frame, detector) -> list[tuple[int, int, int, int]]:
    if detector is None:
        return []
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    detections = detector.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=4, minSize=(36, 36))
    return [(int(x), int(y), int(w), int(h)) for x, y, w, h in detections]


def _best_frame(video_path: str, duration: float):
    cv2, _np = _load_cv2()
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError("OpenCV could not open source video")
    detector = _face_detector(cv2)
    candidates = [0.12, 0.22, 0.34, 0.48, 0.62, 0.76]
    best = None
    best_score = -1.0
    for pct in candidates:
        t = max(0.2, min(duration - 0.1, duration * pct))
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        sharpness = min(100.0, cv2.Laplacian(gray, cv2.CV_64F).var() / 8.0)
        brightness = float(gray.mean())
        brightness_score = max(0.0, 100.0 - abs(brightness - 125.0) * 0.8)
        faces = _detect_faces(cv2, frame, detector)
        face_bonus = 35.0 if faces else 0.0
        score = sharpness * 0.5 + brightness_score * 0.25 + face_bonus
        if score > best_score:
            best_score = score
            best = (frame, t, faces)
    cap.release()
    if best is None:
        raise RuntimeError("Could not sample a cover frame")
    return best


def _crop_vertical(frame, faces, out_w: int, out_h: int):
    cv2, _np = _load_cv2()
    h, w = frame.shape[:2]
    target_aspect = out_w / out_h
    crop_w = min(w, int(h * target_aspect))
    crop_h = int(crop_w / target_aspect)
    if crop_h > h:
        crop_h = h
        crop_w = int(crop_h * target_aspect)

    if faces:
        x, y, fw, fh = max(faces, key=lambda item: item[2] * item[3])
        cx = x + fw / 2
        cy = y + fh * 0.45
    else:
        cx = w / 2
        cy = h / 2
    x0 = int(max(0, min(w - crop_w, cx - crop_w / 2)))
    y0 = int(max(0, min(h - crop_h, cy - crop_h * 0.42)))
    crop = frame[y0:y0 + crop_h, x0:x0 + crop_w]
    resized = cv2.resize(crop, (out_w, out_h), interpolation=cv2.INTER_AREA)

    adjusted_faces = []
    sx, sy = out_w / max(1, crop_w), out_h / max(1, crop_h)
    for fx, fy, fw, fh in faces:
        ax = int((fx - x0) * sx)
        ay = int((fy - y0) * sy)
        aw = int(fw * sx)
        ah = int(fh * sy)
        if ax + aw > 0 and ay + ah > 0 and ax < out_w and ay < out_h:
            adjusted_faces.append((ax, ay, aw, ah))
    return resized, adjusted_faces


def _overlay_rect(cv2, image, x1, y1, x2, y2, color, alpha):
    overlay = image.copy()
    cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
    cv2.addWeighted(overlay, alpha, image, 1 - alpha, 0, image)


def _wrap_lines(cv2, text: str, max_width: int, font, scale: float, thickness: int) -> list[str]:
    words = re.findall(r"\S+", (text or "").strip())
    lines: list[str] = []
    cur = ""
    for word in words:
        candidate = f"{cur} {word}".strip()
        width = cv2.getTextSize(candidate, font, scale, thickness)[0][0]
        if cur and width > max_width:
            lines.append(cur)
            cur = word
        else:
            cur = candidate
    if cur:
        lines.append(cur)
    return lines[:4]


def _draw_text_block(cv2, image, headline: str, brand: str, primary, accent):
    font = cv2.FONT_HERSHEY_DUPLEX
    h, w = image.shape[:2]
    headline = headline.strip() or "New short ready"
    lines = _wrap_lines(cv2, headline.upper(), int(w * 0.82), font, 1.9, 4)
    block_h = max(220, len(lines) * 88 + 120)
    y0 = h - block_h - 70
    _overlay_rect(cv2, image, 0, y0 - 30, w, h, (0, 0, 0), 0.58)
    cv2.rectangle(image, (0, y0 - 30), (24, h), primary, -1)
    y = y0 + 55
    for line in lines:
        cv2.putText(image, line, (62, y), font, 1.9, (0, 0, 0), 9, cv2.LINE_AA)
        cv2.putText(image, line, (62, y), font, 1.9, (255, 255, 255), 4, cv2.LINE_AA)
        y += 88
    if brand.strip():
        cv2.putText(image, brand.strip().upper(), (64, h - 70), cv2.FONT_HERSHEY_SIMPLEX, 1.05, (0, 0, 0), 6, cv2.LINE_AA)
        cv2.putText(image, brand.strip().upper(), (64, h - 70), cv2.FONT_HERSHEY_SIMPLEX, 1.05, accent, 3, cv2.LINE_AA)


def _paste_face_cutout(cv2, np, image, faces, accent):
    if not faces:
        return
    h, w = image.shape[:2]
    x, y, fw, fh = max(faces, key=lambda item: item[2] * item[3])
    pad = int(max(fw, fh) * 0.45)
    x1, y1 = max(0, x - pad), max(0, y - pad)
    x2, y2 = min(w, x + fw + pad), min(h, y + fh + pad)
    if x2 <= x1 or y2 <= y1:
        return
    face = image[y1:y2, x1:x2].copy()
    size = 260
    face = cv2.resize(face, (size, size), interpolation=cv2.INTER_AREA)
    mask = np.zeros((size, size), dtype=np.uint8)
    cv2.circle(mask, (size // 2, size // 2), size // 2 - 8, 255, -1)
    border = np.zeros_like(face)
    cv2.circle(border, (size // 2, size // 2), size // 2 - 3, accent, 12)
    px, py = w - size - 70, 105
    roi = image[py:py + size, px:px + size]
    np.copyto(roi, face, where=mask[:, :, None].astype(bool))
    image[py:py + size, px:px + size] = cv2.addWeighted(image[py:py + size, px:px + size], 1.0, border, 1.0, 0)


def _generate_cover_sync(video_path: str, video_id: str, duration: float, headline: str, brand_name: str,
                         brand_color: str, accent_color: str, platform: str) -> dict:
    cv2, np = _load_cv2()
    platform = platform if platform in {"tiktok", "reels", "shorts"} else "tiktok"
    out_w, out_h = 1080, 1920
    frame, selected_time, faces = _best_frame(video_path, duration)
    cover, adjusted_faces = _crop_vertical(frame, faces, out_w, out_h)
    primary = _hex_to_bgr(brand_color, "#06b6d4")
    accent = _hex_to_bgr(accent_color, "#facc15")
    _paste_face_cutout(cv2, np, cover, adjusted_faces, accent)
    _draw_text_block(cv2, cover, headline, brand_name, primary, accent)
    cv2.rectangle(cover, (0, 0), (out_w - 1, out_h - 1), primary, 14)

    output_path = os.path.join(OUTPUT_DIR, f"{storage_video_id(video_id)}_{platform}_cover.jpg")
    if not cv2.imwrite(output_path, cover, [int(cv2.IMWRITE_JPEG_QUALITY), 92]):
        raise RuntimeError("Failed to write cover image")
    return {
        "video_id": video_id,
        "cover_filename": Path(output_path).name,
        "output_path": output_path,
        "selected_time": round(float(selected_time), 3),
        "platform": platform,
    }


async def generate_cover(video_id: str, *, headline: str, brand_name: str, brand_color: str,
                         accent_color: str, platform: str) -> dict:
    video_id = _safe_video_id(video_id)
    video_path = _source_for_cover(video_id)
    if not video_path:
        raise FileNotFoundError("Video not found")
    probe = await probe_video(video_path)
    result = await asyncio.to_thread(
        _generate_cover_sync,
        video_path,
        video_id,
        float(probe.get("duration", 30.0)),
        headline,
        brand_name,
        brand_color,
        accent_color,
        platform,
    )
    state_store.upsert_video(video_id, thumbnail_path=result["output_path"])
    return result
