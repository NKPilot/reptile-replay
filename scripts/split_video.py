#!/usr/bin/env python3
"""
视频切片脚本 —— 将长视频统一切成 5 秒 clips。

用法:
    # 处理单个视频
    python split_video.py --input data/raw/abc123/abc123.mp4

    # 批量处理整个目录
    python split_video.py --input-dir data/raw

    # 自定义参数
    python split_video.py --input video.mp4 --width 640 --fps 8 --segment-time 5

输出规格:
    分辨率: 640 宽（等比缩放）
    帧率: 8 FPS
    片段长度: 5 秒
    音频: 去掉
    输出: data/clips/{video_id}/{video_id}_00001.mp4, ...
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import List


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CLIPS_DIR = PROJECT_ROOT / "data" / "clips"
SPLIT_LOG = PROJECT_ROOT / "data" / "clips" / "split_log.csv"


def ensure_dirs():
    DEFAULT_CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_CLIPS_DIR.joinpath("usable").mkdir(exist_ok=True)
    DEFAULT_CLIPS_DIR.joinpath("bad").mkdir(exist_ok=True)
    DEFAULT_CLIPS_DIR.joinpath("unknown").mkdir(exist_ok=True)
    if not SPLIT_LOG.exists():
        with open(SPLIT_LOG, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "source_video_id", "source_path", "clip_path", "clip_index",
                "start_sec", "end_sec", "duration_sec", "created_at"
            ])


def check_ffmpeg() -> bool:
    """检查 FFmpeg 是否可用"""
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_video_duration(video_path: Path) -> float:
    """获取视频时长（秒）"""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError):
        return 0.0


def find_video_files(input_dir: Path) -> List[Path]:
    """递归查找所有视频文件"""
    video_extensions = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".ts"}
    videos = []
    for ext in video_extensions:
        videos.extend(input_dir.rglob(f"*{ext}"))
    return sorted(videos)


def split_video(
    video_path: Path,
    output_dir: Path,
    width: int = 640,
    fps: int = 8,
    segment_time: int = 5,
) -> dict:
    """
    使用 FFmpeg 将视频切成固定长度片段。

    返回:
        {
            "video_id": str,
            "total_clips": int,
            "duration": float,
            "output_dir": str,
        }
    """
    # 从视频所在目录名提取 video_id
    video_id = video_path.parent.name
    clip_output_dir = output_dir / video_id
    clip_output_dir.mkdir(parents=True, exist_ok=True)

    # 构建输出模板
    output_template = str(clip_output_dir / f"{video_id}_%05d.mp4")

    duration = get_video_duration(video_path)
    if duration <= 0:
        print(f"  ✗ 无法获取视频时长: {video_path}")
        return {"video_id": video_id, "total_clips": 0, "duration": 0, "output_dir": str(clip_output_dir)}

    # FFmpeg 切片命令
    cmd = [
        "ffmpeg",
        "-y",                          # 覆盖已有文件
        "-i", str(video_path),
        "-vf", f"scale={width}:-2,fps={fps}",
        "-an",                         # 去掉音频
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "28",                  # 低码率（MVP 不需要高画质）
        "-f", "segment",
        "-segment_time", str(segment_time),
        "-reset_timestamps", "1",
        output_template,
    ]

    print(f"  输入: {video_path}")
    print(f"  时长: {duration:.1f}s")
    print(f"  规格: {width}w {fps}fps {segment_time}s/clip")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)

        if result.returncode != 0:
            print(f"  ✗ 切片失败:")
            print(f"    stderr: {result.stderr[-300:]}")
            return {"video_id": video_id, "total_clips": 0, "duration": duration, "output_dir": str(clip_output_dir)}

        # 统计生成的 clip 数量
        clip_files = sorted(clip_output_dir.glob(f"{video_id}_*.mp4"))
        num_clips = len(clip_files)

        # 记录到日志
        log_splits(video_id, str(video_path), clip_files, segment_time)

        print(f"  ✓ 生成 {num_clips} 个 clips → {clip_output_dir}")
        return {
            "video_id": video_id,
            "total_clips": num_clips,
            "duration": duration,
            "output_dir": str(clip_output_dir),
        }

    except subprocess.TimeoutExpired:
        print(f"  ✗ 切片超时 (>30分钟)")
        return {"video_id": video_id, "total_clips": 0, "duration": duration, "output_dir": str(clip_output_dir)}


def log_splits(video_id: str, source_path: str, clip_files: List[Path], segment_time: int):
    """记录切片到 CSV"""
    now = datetime.now().isoformat()
    with open(SPLIT_LOG, "a", newline="") as f:
        writer = csv.writer(f)
        for clip in clip_files:
            # 从文件名提取 index
            match = re.search(r"_(\d{5})\.mp4$", clip.name)
            idx = int(match.group(1)) if match else 0
            start = (idx - 1) * segment_time
            end = idx * segment_time
            writer.writerow([
                video_id, source_path, str(clip), idx, start, end,
                segment_time, now
            ])


def main():
    parser = argparse.ArgumentParser(description="视频切片 —— 切成 5s clips")
    parser.add_argument("--input", type=str, help="单个视频文件路径")
    parser.add_argument("--input-dir", type=str, help="批量处理目录")
    parser.add_argument("--output-dir", type=str, default=str(DEFAULT_CLIPS_DIR), help="输出目录")
    parser.add_argument("--width", type=int, default=640, help="输出宽度")
    parser.add_argument("--fps", type=int, default=8, help="输出帧率")
    parser.add_argument("--segment-time", type=int, default=5, help="每段时长(秒)")
    args = parser.parse_args()

    if not check_ffmpeg():
        print("错误: FFmpeg 未安装。请安装: apt install ffmpeg")
        sys.exit(1)

    ensure_dirs()
    output_dir = Path(args.output_dir)

    # 收集视频列表
    videos = []
    if args.input:
        p = Path(args.input)
        if not p.exists():
            print(f"错误: 文件不存在: {args.input}")
            sys.exit(1)
        videos = [p]
    elif args.input_dir:
        videos = find_video_files(Path(args.input_dir))
        if not videos:
            print(f"错误: 目录中没有找到视频文件: {args.input_dir}")
            sys.exit(1)
    else:
        print("请指定 --input 或 --input-dir")
        sys.exit(1)

    print(f"待处理: {len(videos)} 个视频\n")

    total_clips = 0
    for video in videos:
        print(f"[处理] {video.name}")
        result = split_video(video, output_dir, args.width, args.fps, args.segment_time)
        total_clips += result["total_clips"]
        print()

    print(f"--- 全部完成 ---")
    print(f"总计生成 {total_clips} 个 clips")
    print(f"输出目录: {output_dir}")


if __name__ == "__main__":
    main()
