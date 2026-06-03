"""运动检测服务 —— OpenCV 帧差法分析"""

import cv2
import numpy as np
from pathlib import Path
from typing import Tuple


def frame_diff_analysis(prev_frame: np.ndarray, curr_frame: np.ndarray) -> dict:
    """
    两帧之间的运动分析。
    返回: {intensity, magnitude, num_regions}
    """
    prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
    curr_gray = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY)
    prev_gray = cv2.GaussianBlur(prev_gray, (5, 5), 0)
    curr_gray = cv2.GaussianBlur(curr_gray, (5, 5), 0)

    diff = cv2.absdiff(prev_gray, curr_gray)
    _, thresh = cv2.threshold(diff, 15, 255, cv2.THRESH_BINARY)

    total_pixels = thresh.shape[0] * thresh.shape[1]
    motion_pixels = np.count_nonzero(thresh)

    intensity = motion_pixels / max(total_pixels, 1)
    magnitude = np.mean(diff) / 255.0

    num_regions = 0
    if motion_pixels > 100:
        kernel = np.ones((3, 3), np.uint8)
        cleaned = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
        num_labels, _ = cv2.connectedComponents(cleaned)
        num_regions = max(0, num_labels - 1)

    return {
        "intensity": round(intensity, 6),
        "magnitude": round(magnitude, 6),
        "num_regions": num_regions,
    }


def analyze_video_motion(video_path: Path, fps: int = 8) -> dict:
    """
    对整段视频进行运动分析，返回逐帧运动曲线。
    返回: {total_frames, motion_curve, avg_intensity, peak_intensity, durations}
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return {"error": "无法打开视频"}

    motion_curve = []      # [(time_sec, intensity, num_regions), ...]
    prev_frame = None
    frame_idx = 0
    source_fps = cap.get(cv2.CAP_PROP_FPS)
    if source_fps <= 0:
        source_fps = fps

    frame_interval = max(1, int(source_fps / fps))  # 降采样间隔

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # 降采样
        if frame_idx % frame_interval != 0:
            frame_idx += 1
            continue

        if prev_frame is not None:
            result = frame_diff_analysis(prev_frame, frame)
            time_sec = frame_idx / source_fps
            motion_curve.append({
                "time": round(time_sec, 2),
                "intensity": result["intensity"],
                "magnitude": result["magnitude"],
                "num_regions": result["num_regions"],
            })

        prev_frame = frame
        frame_idx += 1

    cap.release()

    total_frames = len(motion_curve)

    if total_frames == 0:
        return {"error": "无有效帧", "total_frames": 0}

    intensities = [m["intensity"] for m in motion_curve]
    avg_intensity = np.mean(intensities) if intensities else 0
    peak_intensity = max(intensities) if intensities else 0

    duration = frame_idx / source_fps if source_fps > 0 else 0

    return {
        "total_frames": total_frames,
        "video_duration": round(duration, 2),
        "fps": round(source_fps, 2),
        "motion_curve": motion_curve,
        "avg_intensity": round(float(avg_intensity), 6),
        "peak_intensity": round(float(peak_intensity), 6),
    }
