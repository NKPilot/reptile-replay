#!/usr/bin/env python3
"""
数据管线总控脚本 —— 一键跑通：下载 → 切片 → 筛选 → 标注。

用法（务必通过 uv run 执行）:
    # 完整流程：从 URL 列表开始
    uv run python scripts/pipeline.py --urls urls.txt

    # 跳过下载，从已有视频开始
    uv run python scripts/pipeline.py --input-dir data/raw

    # 只做切片+筛选+标注
    uv run python scripts/pipeline.py --input video.mp4

    # 预览模式（不实际下载）
    uv run python scripts/pipeline.py --urls urls.txt --dry-run

流程:
    Step 1: yt-dlp 下载视频              → data/raw/{video_id}/
    Step 2: FFmpeg 切片 (5s, 640p, 8fps) → data/clips/{video_id}/
    Step 3: 自动筛选 (usable/bad/unknown) → data/clips/screen_result.csv
    Step 4: 运动分析自动标注              → data/annotations/auto_labels.csv
"""

import argparse
import csv
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

# 确保 ffmpeg/yt-dlp 等工具在 PATH 中
os.environ["PATH"] = os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")

# 使用 uv run 方式调用子脚本：确保在 venv 环境中运行
_PYTHON_RUN = [sys.executable]  # uv venv 中的 python


def run_step(name: str, cmd: list) -> bool:
    """运行一个步骤并报告结果"""
    print(f"\n{'='*60}")
    print(f"  Step: {name}")
    print(f"{'='*60}")

    start = time.time()
    result = subprocess.run(cmd)
    elapsed = time.time() - start

    if result.returncode == 0:
        print(f"\n  ✓ {name} 完成 ({elapsed:.1f}s)")
        return True
    else:
        print(f"\n  ✗ {name} 失败 (exit code: {result.returncode})")
        return False


def count_clips() -> int:
    """统计已生成的 clip 数量"""
    clips_dir = PROJECT_ROOT / "data" / "clips"
    count = 0
    for d in clips_dir.iterdir():
        if d.is_dir() and d.name not in ("usable", "bad", "unknown"):
            count += len(list(d.glob("*_*.mp4")))
    return count


def show_summary():
    """显示管线结果摘要"""
    print(f"\n{'='*60}")
    print(f"  管线执行摘要")
    print(f"{'='*60}")

    # 下载统计
    download_log = PROJECT_ROOT / "data" / "downloads" / "download_log.csv"
    if download_log.exists():
        with open(download_log) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        success = sum(1 for r in rows if r["status"] == "success")
        print(f"\n  下载: {success}/{len(rows)} 成功")

    # 切片统计
    total_clips = count_clips()
    print(f"  Clips: {total_clips} 个")

    # 筛选统计
    screen_csv = PROJECT_ROOT / "data" / "clips" / "screen_result.csv"
    if screen_csv.exists():
        with open(screen_csv) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        usable = sum(1 for r in rows if r["classification"] == "usable")
        bad = sum(1 for r in rows if r["classification"] == "bad")
        unknown = sum(1 for r in rows if r["classification"] == "unknown")
        print(f"  筛选: {usable} usable / {bad} bad / {unknown} unknown")

    # 标注统计
    labels_csv = PROJECT_ROOT / "data" / "annotations" / "auto_labels.csv"
    if labels_csv.exists():
        with open(labels_csv) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        print(f"  标注: {len(rows)} 个 clips 已标注")
        from collections import Counter
        labels = Counter(r["auto_label"] for r in rows)
        for label, count in labels.most_common():
            print(f"    - {label}: {count}")

    print(f"\n  输出文件:")
    print(f"    筛选结果: {screen_csv}")
    print(f"    标注结果: {labels_csv}")
    print(f"    Clips:    {PROJECT_ROOT / 'data' / 'clips'}")


def main():
    parser = argparse.ArgumentParser(
        description="爬宠视频数据管线 —— 一键自动化处理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 完整流程
  python pipeline.py --urls urls.txt

  # 从已有视频开始
  python pipeline.py --input-dir data/raw

  # 单视频快速测试
  python pipeline.py --input my_video.mp4

  # 预览（不下载）
  python pipeline.py --urls urls.txt --dry-run

  # 跳过筛选，直接做标注
  python pipeline.py --input-dir data/raw --skip-screen
        """
    )
    parser.add_argument("--urls", type=str, help="URL 列表文件")
    parser.add_argument("--input", type=str, help="单个视频文件")
    parser.add_argument("--input-dir", type=str, help="视频目录")
    parser.add_argument("--dry-run", action="store_true", help="预览模式（不实际下载）")
    parser.add_argument("--skip-download", action="store_true", help="跳过下载步骤")
    parser.add_argument("--skip-screen", action="store_true", help="跳过自动筛选步骤")
    parser.add_argument("--width", type=int, default=640, help="切片宽度")
    parser.add_argument("--fps", type=int, default=8, help="切片帧率")
    parser.add_argument("--segment-time", type=int, default=5, help="切片时长(秒)")
    args = parser.parse_args()

    started_at = datetime.now()
    print(f"爬宠数据管线启动: {started_at.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"项目目录: {PROJECT_ROOT}")

    # ============================================================
    # Step 1: 下载
    # ============================================================
    if not args.skip_download and args.urls:
        if args.dry_run:
            print("\n[预览] 将下载 URL 列表中的视频")
            with open(args.urls) as f:
                urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
            print(f"  共 {len(urls)} 个 URL")
        else:
            cmd = [*_PYTHON_RUN, str(SCRIPTS_DIR / "download_videos.py"), "--urls", args.urls]
            if not run_step("下载视频", cmd):
                print("下载步骤失败，终止管线")
                sys.exit(1)

    # ============================================================
    # Step 2: 切片
    # ============================================================
    if args.input:
        if args.dry_run:
            print(f"\n[预览] 将对 {args.input} 进行切片")
        else:
            cmd = [
                *_PYTHON_RUN, str(SCRIPTS_DIR / "split_video.py"),
                "--input", args.input,
                "--width", str(args.width),
                "--fps", str(args.fps),
                "--segment-time", str(args.segment_time),
            ]
            if not run_step("视频切片", cmd):
                print("切片步骤失败，终止管线")
                sys.exit(1)
    elif args.input_dir:
        if args.dry_run:
            print(f"\n[预览] 将对 {args.input_dir} 中所有视频进行切片")
        else:
            cmd = [
                *_PYTHON_RUN, str(SCRIPTS_DIR / "split_video.py"),
                "--input-dir", args.input_dir,
                "--width", str(args.width),
                "--fps", str(args.fps),
                "--segment-time", str(args.segment_time),
            ]
            if not run_step("批量视频切片", cmd):
                print("切片步骤失败，终止管线")
                sys.exit(1)
    elif not args.dry_run:
        # 如果没指定输入，且完成了下载，自动使用 data/raw
        raw_dir = PROJECT_ROOT / "data" / "raw"
        if raw_dir.exists() and any(raw_dir.iterdir()):
            cmd = [
                *_PYTHON_RUN, str(SCRIPTS_DIR / "split_video.py"),
                "--input-dir", str(raw_dir),
                "--width", str(args.width),
                "--fps", str(args.fps),
                "--segment-time", str(args.segment_time),
            ]
            if not run_step("视频切片 (自动检测 data/raw)", cmd):
                print("切片步骤失败，终止管线")
                sys.exit(1)
        else:
            print("\n提示: 未指定输入且 data/raw 为空，跳过切片步骤")

    # ============================================================
    # Step 3: 自动筛选
    # ============================================================
    if not args.skip_screen:
        if args.dry_run:
            print(f"\n[预览] 将对所有 clips 进行自动筛选")
        else:
            cmd = [
                *_PYTHON_RUN, str(SCRIPTS_DIR / "screen_clips.py"),
                "--clips-dir", str(PROJECT_ROOT / "data" / "clips"),
            ]
            if not run_step("自动筛选 (模糊/字幕/切镜检测)", cmd):
                print("筛选步骤失败，但继续标注步骤")

    # ============================================================
    # Step 4: 自动标注
    # ============================================================
    if args.dry_run:
        print(f"\n[预览] 将对 usable clips 进行自动标注")
    else:
        # 标注 usable clips
        usable_dir = PROJECT_ROOT / "data" / "clips" / "usable"
        clips_to_label = usable_dir

        # 如果 usable 目录为空，尝试标注全部 clips
        if not clips_to_label.exists() or not list(clips_to_label.glob("*.mp4")):
            print("\n提示: usable 目录为空，将标注所有 clips")
            clips_to_label = PROJECT_ROOT / "data" / "clips"

        cmd = [
            *_PYTHON_RUN, str(SCRIPTS_DIR / "auto_label.py"),
            "--clips-dir", str(clips_to_label),
            "--output", str(PROJECT_ROOT / "data" / "annotations" / "auto_labels.csv"),
        ]
        run_step("运动分析自动标注", cmd)

    # ============================================================
    # 完成
    # ============================================================
    elapsed = (datetime.now() - started_at).total_seconds()
    print(f"\n{'='*60}")
    print(f"  管线执行完毕，总耗时: {elapsed:.0f}s ({elapsed/60:.1f}min)")
    print(f"{'='*60}")

    if not args.dry_run:
        show_summary()


if __name__ == "__main__":
    main()
