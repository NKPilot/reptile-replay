#!/usr/bin/env python3
"""
⚠ 已废弃: 人物检测已集成到 screen_clips.py（第 5 项检查，使用 HOG+Haar 双保险）。

该脚本仅作为独立工具保留，如需对已有 screen_result.csv 做补充扫描可手动运行。

用法:
    uv run python scripts/detect_humans.py
"""

import csv
import sys
from pathlib import Path

import cv2

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLIPS_DIR = PROJECT_ROOT / "data" / "clips"
SCREEN_CSV = CLIPS_DIR / "screen_result.csv"

# OpenCV 预训练 Haar 分类器
CASCADE_PATH = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
face_cascade = cv2.CascadeClassifier(CASCADE_PATH)


def has_human_face(clip_path: Path, sample_count: int = 3) -> bool:
    """抽样检测 clip 中间几帧是否含人脸"""
    cap = cv2.VideoCapture(str(clip_path))
    if not cap.isOpened():
        return False

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames < 1:
        cap.release()
        return False

    # 在 20%-80% 区间均匀抽样
    indices = [
        int(total_frames * (0.2 + 0.3 * i / max(sample_count - 1, 1)))
        for i in range(sample_count)
    ]

    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if not ret:
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(40, 40))

        if len(faces) > 0:
            cap.release()
            return True

    cap.release()
    return False


def main():
    if not SCREEN_CSV.exists():
        print("错误: screen_result.csv 不存在，请先运行筛选管线")
        sys.exit(1)

    # 读取现有结果
    rows = []
    with open(SCREEN_CSV, newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        has_human_field = "has_human" in (fieldnames or [])
        for row in reader:
            rows.append(row)

    if not has_human_field:
        fieldnames = list(fieldnames) + ["has_human"]

    # 扫描每个 clip
    total = len(rows)
    human_count = 0
    reclassified = 0

    for i, row in enumerate(rows):
        clip_rel = row["clip_path"].removeprefix("data/clips/").lstrip("/")
        clip_abs = CLIPS_DIR / clip_rel

        if not clip_abs.exists():
            print(f"[{i+1}/{total}] ⚠ 文件不存在: {clip_rel}")
            continue

        # 跳过已标记的
        if row.get("has_human") == "true":
            human_count += 1
            continue

        print(f"[{i+1}/{total}] 检测: {clip_rel[:55]}...", end=" ", flush=True)

        if has_human_face(clip_abs):
            print("👤 人脸!")
            row["has_human"] = "true"
            if row.get("classification") not in ("bad",):
                row["classification"] = "bad"
                if not row.get("reasons"):
                    row["reasons"] = "检测到人脸"
                else:
                    row["reasons"] = row["reasons"] + "; 检测到人脸"
                reclassified += 1
            human_count += 1
        else:
            row["has_human"] = "false"
            print("✓")

    # 写回 CSV
    with open(SCREEN_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n--- 完成 ---")
    print(f"总计: {total} clips")
    print(f"含人脸: {human_count}")
    print(f"重新标记为 bad: {reclassified}")
    print(f"结果已写回: {SCREEN_CSV}")


if __name__ == "__main__":
    main()
