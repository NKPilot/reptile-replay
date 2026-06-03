#!/usr/bin/env python3
"""
自动标注脚本 —— 基于运动分析对 usable clips 进行初步行为分类。

分类逻辑:
    resting          → 运动强度极低
    moving           → 持续中等强度运动
    feeding_or_strike_candidate  → 短时间剧烈运动峰值
    contact_mating_like_candidate → 多运动区域重叠
    shedding_candidate → 低速长时间运动（误报率高，仅供参考）
    unknown          → 不满足以上条件

用法:
    # 对筛选后的 usable clips 进行标注
    python auto_label.py --clips-dir data/clips/usable

    # 输出标注 CSV
    python auto_label.py --clips-dir data/clips/usable --output data/annotations/auto_labels.csv

    # 同时生成可视化摘要
    python auto_label.py --clips-dir data/clips --verbose

输出:
    data/annotations/auto_labels.csv
"""

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np
import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "configs" / "labels.yaml"


def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def extract_motion_profile(clip_path: Path) -> dict:
    """
    提取 clip 的完整运动特征。

    返回:
        {
            "total_frames": int,
            "motion_curve": [float],          # 每帧的运动强度
            "magnitude_curve": [float],       # 每帧的运动幅度
            "region_counts": [int],           # 每帧的独立运动区域数
            "avg_intensity": float,
            "peak_intensity": float,
            "peak_sustained_ratio": float,    # 峰值持续时间占比
            "motion_frame_ratio": float,      # 有运动帧的占比
            "max_regions": int,
            "overlap_frames": int,            # 多区域重叠帧数
        }
    """
    cap = cv2.VideoCapture(str(clip_path))
    if not cap.isOpened():
        return {"total_frames": 0}

    motion_curve = []
    magnitude_curve = []
    region_counts = []
    prev_frame = None

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if prev_frame is not None:
            prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
            curr_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            prev_gray = cv2.GaussianBlur(prev_gray, (5, 5), 0)
            curr_gray = cv2.GaussianBlur(curr_gray, (5, 5), 0)

            diff = cv2.absdiff(prev_gray, curr_gray)
            _, thresh = cv2.threshold(diff, 15, 255, cv2.THRESH_BINARY)

            total_pixels = thresh.shape[0] * thresh.shape[1]
            motion_pixels = np.count_nonzero(thresh)
            intensity = motion_pixels / total_pixels
            magnitude = np.mean(diff) / 255.0

            # 连通域分析
            num_regions = 0
            if motion_pixels > 100:
                kernel = np.ones((3, 3), np.uint8)
                cleaned = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
                num_labels, _ = cv2.connectedComponents(cleaned)
                num_regions = max(0, num_labels - 1)

            motion_curve.append(intensity)
            magnitude_curve.append(magnitude)
            region_counts.append(num_regions)

        prev_frame = frame

    cap.release()

    total_frames = len(motion_curve)
    if total_frames == 0:
        return {"total_frames": 0}

    avg_intensity = np.mean(motion_curve)
    peak_intensity = max(motion_curve)

    # 峰值持续时间占比
    peak_threshold = max(avg_intensity * 2.0, 0.3)
    peak_frames = sum(1 for v in motion_curve if v > peak_threshold)
    peak_ratio = peak_frames / total_frames

    # 有运动帧占比
    motion_frames = sum(1 for v in motion_curve if v > 0.01)
    motion_ratio = motion_frames / total_frames

    # 多区域重叠帧数
    overlap_frames = sum(1 for r in region_counts if r >= 2)

    return {
        "total_frames": total_frames,
        "motion_curve": motion_curve,
        "magnitude_curve": magnitude_curve,
        "region_counts": region_counts,
        "avg_intensity": round(avg_intensity, 6),
        "peak_intensity": round(peak_intensity, 6),
        "peak_sustained_ratio": round(peak_ratio, 4),
        "motion_frame_ratio": round(motion_ratio, 4),
        "max_regions": max(region_counts) if region_counts else 0,
        "overlap_frames": overlap_frames,
    }


def classify_behavior(profile: dict, rules: dict) -> tuple:
    """
    根据运动特征进行行为分类。

    返回: (label, confidence, reason)
    """
    if profile.get("total_frames", 0) == 0:
        return "unknown", 0.0, "无法读取视频"

    avg = profile["avg_intensity"]
    peak = profile["peak_intensity"]
    peak_ratio = profile["peak_sustained_ratio"]
    motion_ratio = profile["motion_frame_ratio"]
    max_regions = profile["max_regions"]
    overlap_frames = profile["overlap_frames"]
    total = profile["total_frames"]
    peak_to_avg = peak / max(avg, 0.001)

    r = rules

    # 1. resting: 几乎无运动
    if avg <= r["resting"]["max_motion"] and motion_ratio < 0.3:
        conf = 1.0 - (avg / r["resting"]["max_motion"])
        return "resting", round(min(conf, 0.95), 2), f"平均运动={avg:.4f}, 运动帧占比={motion_ratio:.2f}"

    # 2. feeding_or_strike_candidate: 短时间剧烈运动
    if (peak > r["feeding_or_strike_candidate"]["min_peak_motion"] and
        peak_to_avg > r["feeding_or_strike_candidate"]["peak_ratio"] and
        peak_ratio < r["feeding_or_strike_candidate"]["max_peak_duration"]):
        conf = min((peak - 0.3) / 0.3, 0.9)
        return "feeding_or_strike", round(conf, 2), f"峰值={peak:.4f}, 峰值/均值={peak_to_avg:.1f}"

    # 3. contact_mating_like_candidate: 多运动区域重叠
    if (max_regions >= r["contact_mating_like_candidate"]["min_motion_regions"] and
        overlap_frames / max(total, 1) > 0.2):
        conf = min(overlap_frames / total, 0.85)
        return "contact_mating_like", round(conf, 2), f"运动区域={max_regions}, 重叠帧={overlap_frames}"

    # 4. shedding_candidate: 低速长时间运动（不可靠，置信度标低）
    if (r["shedding_candidate"]["min_motion"] <= avg <= r["shedding_candidate"]["max_motion"] and
        motion_ratio > r["shedding_candidate"]["min_sustained_ratio"]):
        conf = min(motion_ratio * 0.5, 0.5)  # 置信度不超过 0.5
        return "shedding", round(conf, 2), f"低速持续: avg={avg:.4f}, 持续比={motion_ratio:.2f} (注意: 纯运动检测不可靠)"

    # 5. moving: 持续中等强度运动
    if (r["moving"]["min_motion"] <= avg <= r["moving"]["max_motion"] and
        motion_ratio > r["moving"]["min_duration_ratio"]):
        conf = min(motion_ratio, 0.85)
        return "moving", round(conf, 2), f"中等运动: avg={avg:.4f}, 持续比={motion_ratio:.2f}"

    # 6. unknown: 不满足以上条件
    return "unknown", 0.3, f"无法确定: avg={avg:.4f}, peak={peak:.4f}"


def main():
    parser = argparse.ArgumentParser(description="基于运动分析的 Clip 自动标注")
    parser.add_argument("--clips-dir", type=str,
                        default=str(PROJECT_ROOT / "data" / "clips" / "usable"),
                        help="Usable clips 目录")
    parser.add_argument("--output", type=str,
                        default=str(PROJECT_ROOT / "data" / "annotations" / "auto_labels.csv"),
                        help="输出 CSV 路径")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    args = parser.parse_args()

    config = load_config()
    rules = config["auto_label_rules"]
    label_cn = config["label_cn"]

    clips_dir = Path(args.clips_dir)
    if not clips_dir.exists():
        print(f"错误: 目录不存在: {clips_dir}")
        print("请先运行 screen_clips.py 筛选出 usable clips")
        sys.exit(1)

    clip_files = sorted(clips_dir.glob("*.mp4"))
    if not clip_files:
        # 也尝试查找软链接
        clip_files = sorted([p for p in clips_dir.iterdir() if p.suffix == ".mp4"])

    if not clip_files:
        print(f"未找到 clip 文件在: {clips_dir}")
        sys.exit(0)

    print(f"待标注: {len(clip_files)} 个 clips\n")

    # 准备输出
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "clip_path", "auto_label", "label_cn", "confidence",
            "avg_intensity", "peak_intensity", "motion_frame_ratio",
            "max_regions", "overlap_frames", "reason"
        ])

        stats = {}
        for label in config["labels"].values():
            stats[label] = 0

        for i, clip in enumerate(clip_files):
            print(f"[{i+1}/{len(clip_files)}] {clip.name} ", end="")

            profile = extract_motion_profile(clip)
            label, confidence, reason = classify_behavior(profile, rules)

            stats[label] = stats.get(label, 0) + 1

            cn = label_cn.get(label, label)
            print(f"→ {cn} ({confidence:.2f})")

            if args.verbose:
                print(f"    avg={profile['avg_intensity']:.4f}, peak={profile['peak_intensity']:.4f}")
                print(f"    motion_ratio={profile['motion_frame_ratio']:.2f}, regions={profile['max_regions']}")
                print(f"    reason: {reason}")

            writer.writerow([
                str(clip.resolve()),
                label,
                cn,
                confidence,
                profile["avg_intensity"],
                profile["peak_intensity"],
                profile["motion_frame_ratio"],
                profile["max_regions"],
                profile["overlap_frames"],
                reason,
            ])

    # 统计摘要
    print(f"\n--- 标注统计 ---")
    for label, count in sorted(stats.items(), key=lambda x: -x[1]):
        if count > 0:
            cn = label_cn.get(label, label)
            bar = "█" * max(1, count)
            print(f"  {cn:<12} {count:>4}  {bar}")
    print(f"\n结果: {output_path}")


if __name__ == "__main__":
    main()
