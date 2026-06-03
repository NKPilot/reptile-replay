#!/usr/bin/env python3
"""
自动筛选脚本 —— 对 clip 进行可用性自动筛选（usable / bad / unknown）。

检测项:
    1. 模糊检测 —— Laplacian 方差
    2. 运动检测 —— 帧差法判断是否有动物活动
    3. 文字/字幕检测 —— 边缘密度异常区域
    4. 场景切换检测 —— 直方图突变次数
    5. 综合评分 —— 加权判断 usable/bad/unknown

用法:
    # 筛选所有 clips
    python screen_clips.py --clips-dir data/clips

    # 筛选单个视频的 clips
    python screen_clips.py --video-id abc123

    # 预览模式（显示每帧检测信息）
    python screen_clips.py --clips-dir data/clips --verbose

输出:
    data/clips/screen_result.csv  # 筛选结果
    bad clips 被移动到 data/clips/bad/
    usable clips 被复制/软链接到 data/clips/usable/
"""

import argparse
import csv
import os
import sys
import json
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional

import cv2
import numpy as np
import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "configs" / "labels.yaml"


def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def detect_blur(frame: np.ndarray) -> float:
    """
    模糊检测 —— 使用 Laplacian 方差。
    返回值: 方差（越高越清晰）
    典型值:
        清晰图片: > 100
        轻微模糊: 50-100
        严重模糊: < 50
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    return laplacian.var()


def detect_motion(prev_frame: np.ndarray, curr_frame: np.ndarray) -> Tuple[float, float, int]:
    """
    运动检测 —— 帧差法。
    返回:
        motion_intensity: 运动像素占比 (0~1)
        motion_magnitude: 运动幅度均值
        num_regions: 独立运动区域数
    """
    prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
    curr_gray = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY)

    # 高斯模糊降噪
    prev_gray = cv2.GaussianBlur(prev_gray, (5, 5), 0)
    curr_gray = cv2.GaussianBlur(curr_gray, (5, 5), 0)

    # 帧差
    diff = cv2.absdiff(prev_gray, curr_gray)

    # 二值化
    _, thresh = cv2.threshold(diff, 15, 255, cv2.THRESH_BINARY)

    # 运动强度
    total_pixels = thresh.shape[0] * thresh.shape[1]
    motion_pixels = np.count_nonzero(thresh)
    intensity = motion_pixels / total_pixels

    # 运动幅度
    magnitude = np.mean(diff) / 255.0 if total_pixels > 0 else 0.0

    # 运动区域数（连通域分析）
    num_regions = 0
    if motion_pixels > 100:
        kernel = np.ones((3, 3), np.uint8)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
        num_labels, _ = cv2.connectedComponents(thresh)
        num_regions = max(0, num_labels - 1)  # 减去背景

    return intensity, magnitude, num_regions


def detect_text_area(frame: np.ndarray) -> float:
    """
    文字/字幕区域检测 —— 检测高对比度边缘密集区域。
    返回值: 疑似文字区域占比 (0~1)
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # Canny 边缘检测
    edges = cv2.Canny(gray, 50, 150)

    # 底部 1/4 区域通常有字幕
    h = edges.shape[0]
    bottom = edges[int(h * 0.75):, :]

    total_pixels = bottom.shape[0] * bottom.shape[1]
    if total_pixels == 0:
        return 0.0

    edge_pixels = np.count_nonzero(bottom)
    return edge_pixels / total_pixels


def detect_scene_cut(prev_hist: np.ndarray, curr_hist: np.ndarray, threshold: float = 0.45) -> bool:
    """
    场景切换检测 —— 直方图相关性。
    返回: True 表示发生了切镜
    """
    correlation = cv2.compareHist(prev_hist, curr_hist, cv2.HISTCMP_CORREL)
    return correlation < threshold


def get_histogram(frame: np.ndarray) -> np.ndarray:
    """计算 HSV 直方图"""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    return hist


def analyze_clip(clip_path: Path, config: dict, verbose: bool = False) -> dict:
    """
    分析单个 clip，返回指标字典。

    返回:
        {
            "clip_path": str,
            "is_usable": bool,
            "score": int,
            "reasons": [str],
            "metrics": {
                "avg_blur": float,
                "avg_motion": float,
                "peak_motion": float,
                "motion_frames": int,
                "max_text_area": float,
                "scene_cuts": int,
                "total_frames": int,
            }
        }
    """
    rules = config["screen_rules"]
    cap = cv2.VideoCapture(str(clip_path))

    if not cap.isOpened():
        return {
            "clip_path": str(clip_path),
            "is_usable": False,
            "score": 0,
            "reasons": ["无法打开视频"],
            "metrics": {},
        }

    blur_scores = []
    motion_intensities = []
    motion_magnitudes = []
    motion_region_counts = []
    text_area_ratios = []
    scene_cuts = 0
    motion_frame_count = 0

    prev_frame = None
    prev_hist = None
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # 1. 模糊检测
        blur = detect_blur(frame)
        blur_scores.append(blur)

        # 2. 运动检测
        if prev_frame is not None:
            intensity, magnitude, regions = detect_motion(prev_frame, frame)
            motion_intensities.append(intensity)
            motion_magnitudes.append(magnitude)
            motion_region_counts.append(regions)
            if intensity > 0.01:
                motion_frame_count += 1

        # 3. 文字检测（每 10 帧检测一次，节省计算）
        if frame_idx % 10 == 0:
            text_ratio = detect_text_area(frame)
            text_area_ratios.append(text_ratio)

        # 4. 场景切换检测
        curr_hist = get_histogram(frame)
        if prev_hist is not None:
            if detect_scene_cut(prev_hist, curr_hist):
                scene_cuts += 1

        prev_frame = frame
        prev_hist = curr_hist
        frame_idx += 1

    cap.release()
    total_frames = frame_idx

    if total_frames == 0:
        return {
            "clip_path": str(clip_path),
            "is_usable": False,
            "score": 0,
            "reasons": ["视频无帧"],
            "metrics": {"total_frames": 0},
        }

    # 汇总指标
    avg_blur = np.mean(blur_scores) if blur_scores else 0
    avg_motion = np.mean(motion_intensities) if motion_intensities else 0
    peak_motion = max(motion_intensities) if motion_intensities else 0
    max_text = max(text_area_ratios) if text_area_ratios else 0

    # 评分
    checks_passed = 0
    reasons = []

    # 检查 1: 不模糊
    if avg_blur >= rules["blur_threshold"]:
        checks_passed += 1
    else:
        reasons.append(f"画面模糊 (Laplacian={avg_blur:.1f})")

    # 检查 2: 有足够的运动帧
    if motion_frame_count >= rules["min_motion_frames"]:
        checks_passed += 1
    else:
        reasons.append(f"运动帧不足 ({motion_frame_count}/{total_frames})")

    # 检查 3: 文字/字幕区域不过大
    if max_text <= rules["max_text_area_ratio"]:
        checks_passed += 1
    else:
        reasons.append(f"字幕遮挡严重 ({max_text:.2%})")

    # 检查 4: 场景切换不过于频繁
    if scene_cuts <= rules["max_scene_cuts"]:
        checks_passed += 1
    else:
        reasons.append(f"镜头切换过多 ({scene_cuts}次/5s)")

    is_usable = checks_passed >= rules["min_usable_score"]

    metrics = {
        "avg_blur": round(avg_blur, 2),
        "avg_motion": round(avg_motion, 4),
        "peak_motion": round(peak_motion, 4),
        "motion_frames": motion_frame_count,
        "max_text_area": round(max_text, 4),
        "scene_cuts": scene_cuts,
        "total_frames": total_frames,
    }

    if verbose:
        print(f"  {'✓' if is_usable else '✗'} {clip_path.name}")
        print(f"    blur={avg_blur:.1f}  motion={avg_motion:.4f}  peak={peak_motion:.4f}")
        print(f"    motion_frames={motion_frame_count}/{total_frames}  text={max_text:.3f}  cuts={scene_cuts}")
        if reasons:
            print(f"    原因: {'; '.join(reasons)}")

    return {
        "clip_path": str(clip_path),
        "is_usable": is_usable,
        "score": checks_passed,
        "reasons": reasons,
        "metrics": metrics,
    }


def classify_clip(analysis: dict) -> str:
    """
    三分类: usable / bad / unknown
    - usable: 4/4 项通过
    - bad: 1/4 或 0/4 项通过
    - unknown: 2/4 或 3/4 项通过（需人工判断）
    """
    score = analysis["score"]
    if score >= 4:
        return "usable"
    elif score <= 1:
        return "bad"
    else:
        return "unknown"


def main():
    parser = argparse.ArgumentParser(description="Clip 自动可用性筛选")
    parser.add_argument("--clips-dir", type=str, default=str(PROJECT_ROOT / "data" / "clips"),
                        help="Clips 根目录")
    parser.add_argument("--video-id", type=str, help="仅处理指定视频的 clips")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    parser.add_argument("--move-bad", action="store_true", help="将 bad clips 移动到 bad/ 目录")
    parser.add_argument("--link-usable", action="store_true", help="将 usable clips 软链接到 usable/ 目录")
    args = parser.parse_args()

    config = load_config()

    clips_dir = Path(args.clips_dir)
    result_csv = clips_dir / "screen_result.csv"

    # 收集 clip 文件
    if args.video_id:
        clip_dirs = [clips_dir / args.video_id]
    else:
        clip_dirs = [
            d for d in clips_dir.iterdir()
            if d.is_dir() and d.name not in ("usable", "bad", "unknown")
        ]

    all_clips = []
    for d in clip_dirs:
        if d.exists():
            all_clips.extend(sorted(d.glob("*_*.mp4")))

    if not all_clips:
        print("未找到 clip 文件")
        sys.exit(0)

    print(f"待筛选: {len(all_clips)} 个 clips\n")

    # 写入结果
    with open(result_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "clip_path", "classification", "score",
            "avg_blur", "avg_motion", "peak_motion",
            "motion_frames", "total_frames", "max_text_area",
            "scene_cuts", "reasons"
        ])

        stats = {"usable": 0, "bad": 0, "unknown": 0}

        for i, clip in enumerate(all_clips):
            print(f"[{i+1}/{len(all_clips)}] ", end="")
            analysis = analyze_clip(clip, config, args.verbose)

            if not args.verbose:
                # 简洁模式也输出结果
                classification = classify_clip(analysis)
                symbol = {"usable": "✓", "bad": "✗", "unknown": "?"}[classification]
                print(f"{symbol} {clip.parent.name}/{clip.name} → {classification}")

            classification = classify_clip(analysis)
            stats[classification] += 1

            m = analysis.get("metrics", {})
            writer.writerow([
                analysis["clip_path"],
                classification,
                analysis["score"],
                m.get("avg_blur", ""),
                m.get("avg_motion", ""),
                m.get("peak_motion", ""),
                m.get("motion_frames", ""),
                m.get("total_frames", ""),
                m.get("max_text_area", ""),
                m.get("scene_cuts", ""),
                "; ".join(analysis["reasons"]),
            ])

            # 移动/链接文件
            if args.move_bad and classification == "bad":
                dest = clips_dir / "bad" / clip.name
                clip.rename(dest)
            if args.link_usable and classification == "usable":
                dest = clips_dir / "usable" / clip.name
                if not dest.exists():
                    os.symlink(clip.resolve(), dest)

    print(f"\n--- 筛选完成 ---")
    print(f"usable:  {stats['usable']}  ({stats['usable']/len(all_clips)*100:.1f}%)")
    print(f"bad:     {stats['bad']}  ({stats['bad']/len(all_clips)*100:.1f}%)")
    print(f"unknown: {stats['unknown']}  ({stats['unknown']/len(all_clips)*100:.1f}%)")
    print(f"结果: {result_csv}")


if __name__ == "__main__":
    main()
