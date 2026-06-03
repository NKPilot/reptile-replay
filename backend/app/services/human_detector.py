"""
人物检测模块 —— HOG 人体检测 + Haar 人脸检测双保险。

供 Web 处理管线 (video_processor.py) 和 CLI 筛选 (screen_clips.py) 共用。
所有依赖均为 OpenCV 内置，无需下载额外模型。
"""

from pathlib import Path
from typing import Tuple

import cv2
import numpy as np

# 默认规则（可被调用方覆盖）
DEFAULT_RULES = {
    "hog_hit_threshold": 0.0,       # 降低阈值，提高召回率
    "hog_scale": 1.05,
    "face_min_size": [30, 30],      # 降低最小尺寸
    "face_min_neighbors": 3,         # 降低邻居数，提高召回率
}

# 全局缓存
_hog_detector = None
_face_cascade = None


def _get_hog_detector():
    """懒加载 HOG 人体检测器"""
    global _hog_detector
    if _hog_detector is None:
        _hog_detector = cv2.HOGDescriptor()
        _hog_detector.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    return _hog_detector


def _get_face_cascade():
    """懒加载 Haar 人脸检测器"""
    global _face_cascade
    if _face_cascade is None:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        _face_cascade = cv2.CascadeClassifier(cascade_path)
    return _face_cascade


def detect_human(frame: np.ndarray, human_rules: dict | None = None) -> Tuple[bool, str, float]:
    """
    单帧人物检测。

    参数:
        frame: BGR 图像 (numpy array)
        human_rules: 配置字典，可选。可覆盖 hog_hit_threshold, hog_scale 等

    返回:
        (has_human: bool, method: str, confidence: float)
        method: "hog" | "haar_face" | "hog+haar_face" | "none"
    """
    rules = {**DEFAULT_RULES, **(human_rules or {})}
    hog = _get_hog_detector()
    face_cascade = _get_face_cascade()

    has_human = False
    method = "none"
    max_conf = 0.0

    # 1. HOG 人体检测
    try:
        h, w = frame.shape[:2]
        if max(w, h) > 640:
            scale = 640.0 / max(w, h)
            small = cv2.resize(frame, (int(w * scale), int(h * scale)))
        else:
            small = frame

        rects, weights = hog.detectMultiScale(
            small,
            winStride=(8, 8),
            padding=(16, 16),
            scale=rules["hog_scale"],
            hitThreshold=rules["hog_hit_threshold"],
        )

        if len(rects) > 0:
            max_conf = float(max(weights)) if len(weights) > 0 else 0.5
            has_human = True
            method = "hog"
    except Exception:
        pass

    # 2. Haar 人脸检测
    try:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=rules["face_min_neighbors"],
            minSize=tuple(rules["face_min_size"]),
        )
        if len(faces) > 0:
            has_human = True
            method = f"{method}+haar_face" if has_human else "haar_face"
            max_conf = max(max_conf, 0.8)
    except Exception:
        pass

    return has_human, method, max_conf


def detect_human_in_clip(
    clip_path: str | Path,
    human_rules: dict | None = None,
    sample_frames: int = 16,
    sample_every_n: int = 2,
) -> Tuple[bool, str, float]:
    """
    对整个视频 clip 做抽样人物检测。

    策略:
        - 缓存帧数 <= 200（约25秒@8fps）→ 全帧逐帧检测，不遗漏
        - 缓存帧数 > 200 → 三阶段抽样:
            阶段1: 锚点检测（固定时间位置）
            阶段2: 均匀抽样
            阶段3: 弱信号区域稠密复查

    参数:
        clip_path: 视频文件路径
        human_rules: 检测规则，可选
        sample_frames: 均匀抽样帧数（不含锚点）
        sample_every_n: 读取时每隔 N 帧缓存一帧（加速大视频）

    返回:
        (has_human: bool, method: str, confidence: float)
    """
    cap = cv2.VideoCapture(str(clip_path))
    if not cap.isOpened():
        cap.release()
        return False, "none", 0.0

    # 第一遍：按间隔采样帧
    cached_frames = []
    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % sample_every_n == 0:
            cached_frames.append(frame)
        frame_idx += 1
    cap.release()

    n = len(cached_frames)
    if not cached_frames:
        return False, "none", 0.0

    best_method = "none"
    best_conf = 0.0
    weak_signal_indices = []

    def _check(idx: int) -> Tuple[bool, str, float]:
        """检测单帧"""
        nonlocal best_method, best_conf
        if idx >= n or idx < 0:
            return False, "none", 0.0
        found, method, conf = detect_human(cached_frames[idx], human_rules)
        if conf > best_conf:
            best_conf = conf
            best_method = method
        if conf > 0 and not found:
            weak_signal_indices.append(idx)
        return found, method, conf

    # === 短片段路径：缓存帧少 → 全量检测 ===
    FULL_SCAN_THRESHOLD = 200
    if n <= FULL_SCAN_THRESHOLD:
        for i in range(n):
            found, method, conf = _check(i)
            if found:
                return True, method, conf
        return False, best_method, best_conf

    # === 长片段路径：三阶段抽样 ===

    # 阶段1: 锚点检测
    anchor_fractions = [0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95]
    for frac in anchor_fractions:
        found, method, conf = _check(int(n * frac))
        if found:
            return True, method, conf

    # 阶段2: 均匀抽样
    uniform_indices = [int(n * i / (sample_frames - 1)) for i in range(sample_frames)]
    for idx in uniform_indices:
        found, method, conf = _check(idx)
        if found:
            return True, method, conf

    # 阶段3: 稠密复查弱信号区
    if weak_signal_indices:
        scan_start = max(0, min(weak_signal_indices) - 10)
        scan_end = min(n - 1, max(weak_signal_indices) + 10)
        for idx in range(scan_start, scan_end + 1):
            found, method, conf = _check(idx)
            if found:
                return True, method, conf

    return False, best_method, best_conf
