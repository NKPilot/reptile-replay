#!/usr/bin/env python3
"""
视频下载脚本 —— 基于 yt-dlp 自动批量下载爬宠公开视频。

用法:
    # 从 URL 列表文件下载
    python download_videos.py --urls urls.txt

    # 下载单个视频
    python download_videos.py --url "https://www.youtube.com/watch?v=xxxx"

    # 指定输出目录
    python download_videos.py --urls urls.txt --outdir data/raw

    # 限制分辨率
    python download_videos.py --urls urls.txt --max-height 720

输出:
    data/raw/{video_id}/
        {video_id}.mp4          # 视频文件
        {video_id}.info.json    # yt-dlp 元数据
        {video_id}.jpg          # 缩略图
    data/downloads/download_log.csv  # 下载记录
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTDIR = PROJECT_ROOT / "data" / "raw"
DOWNLOAD_ARCHIVE = PROJECT_ROOT / "data" / "downloads" / "downloaded.txt"
DOWNLOAD_LOG = PROJECT_ROOT / "data" / "downloads" / "download_log.csv"


def ensure_dirs():
    DEFAULT_OUTDIR.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_LOG.parent.mkdir(parents=True, exist_ok=True)
    if not DOWNLOAD_LOG.exists():
        with open(DOWNLOAD_LOG, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "video_id", "url", "title", "duration", "platform",
                "animal_type", "behavior_candidate", "downloaded_at",
                "status", "file_path", "notes"
            ])


def check_yt_dlp() -> bool:
    """检查 yt-dlp 是否可用"""
    try:
        subprocess.run(["yt-dlp", "--version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def build_yt_dlp_cmd(url: str, outdir: Path, max_height: int = 720) -> list:
    """构建 yt-dlp 命令"""
    cmd = [
        "yt-dlp",
        "--write-info-json",
        "--write-thumbnail",
        "--restrict-filenames",
        "--download-archive", str(DOWNLOAD_ARCHIVE),
        "-f", f"bv*[height<={max_height}]+ba/b[height<={max_height}]/bv*+ba/b",
        "-o", str(outdir / "%(id)s" / "%(id)s.%(ext)s"),
        "--no-playlist",
        "--no-overwrites",
    ]

    # 尝试使用 cookies（如果存在）
    cookies_file = PROJECT_ROOT / "cookies.txt"
    if cookies_file.exists():
        cmd.extend(["--cookies", str(cookies_file)])

    cmd.append(url)
    return cmd


def download_single(url: str, outdir: Path, max_height: int = 720) -> Optional[dict]:
    """下载单个视频，返回元数据"""
    cmd = build_yt_dlp_cmd(url, outdir, max_height)
    print(f"[下载] {url}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        if result.returncode != 0:
            # 检查是否是已下载过的
            if "has already been recorded in the archive" in result.stderr:
                print(f"  ⏭ 已下载过，跳过")
                return {"status": "skipped", "reason": "already_downloaded"}

            print(f"  ✗ 下载失败: {result.stderr[-200:]}")
            return {"status": "failed", "error": result.stderr[-500:]}

        # 从输出中提取 video_id
        video_id = None
        for line in result.stdout.split("\n") + result.stderr.split("\n"):
            if "[download] Destination:" in line:
                # 尝试从路径提取 ID
                pass

        # 查找 info.json 获取元数据
        info_files = list(outdir.glob("*/*.info.json"))
        if info_files:
            latest_info = max(info_files, key=lambda p: p.stat().st_mtime)
            with open(latest_info) as f:
                info = json.load(f)
            video_id = info.get("id", "unknown")

            # 查找对应的视频文件
            video_files = list(latest_info.parent.glob("*.mp4")) + \
                          list(latest_info.parent.glob("*.mkv")) + \
                          list(latest_info.parent.glob("*.webm"))
            file_path = str(video_files[0]) if video_files else ""

            return {
                "status": "success",
                "video_id": video_id,
                "title": info.get("title", ""),
                "duration": info.get("duration", 0),
                "platform": info.get("extractor", ""),
                "file_path": file_path,
            }

        return {"status": "success", "video_id": "unknown", "title": "", "duration": 0, "platform": "", "file_path": ""}

    except subprocess.TimeoutExpired:
        print(f"  ✗ 下载超时 (>10分钟)")
        return {"status": "failed", "error": "timeout"}


def log_download(result: dict, url: str, animal_type: str = "", behavior: str = ""):
    """记录下载到 CSV"""
    with open(DOWNLOAD_LOG, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            result.get("video_id", ""),
            url,
            result.get("title", ""),
            result.get("duration", 0),
            result.get("platform", ""),
            animal_type,
            behavior,
            datetime.now().isoformat(),
            result.get("status", "unknown"),
            result.get("file_path", ""),
            result.get("error", "") or result.get("reason", ""),
        ])


def main():
    parser = argparse.ArgumentParser(description="爬宠视频批量下载")
    parser.add_argument("--urls", type=str, help="URL 列表文件（每行一个 URL）")
    parser.add_argument("--url", type=str, help="下载单个 URL")
    parser.add_argument("--outdir", type=str, default=str(DEFAULT_OUTDIR), help="输出目录")
    parser.add_argument("--max-height", type=int, default=720, help="最大分辨率高度")
    parser.add_argument("--animal", type=str, default="", help="动物类型标注")
    parser.add_argument("--behavior", type=str, default="", help="预期行为标注")
    args = parser.parse_args()

    if not check_yt_dlp():
        print("错误: yt-dlp 未安装。请运行: pip install yt-dlp")
        sys.exit(1)

    ensure_dirs()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # 收集 URL 列表
    urls = []
    if args.url:
        urls = [args.url]
    elif args.urls:
        urls_path = Path(args.urls)
        if not urls_path.exists():
            print(f"错误: URL 文件不存在: {args.urls}")
            sys.exit(1)
        with open(urls_path) as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    else:
        print("请指定 --url 或 --urls")
        sys.exit(1)

    print(f"共 {len(urls)} 个视频待下载\n")

    stats = {"success": 0, "skipped": 0, "failed": 0}

    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] ", end="")
        result = download_single(url, outdir, args.max_height)
        log_download(result, url, args.animal, args.behavior)

        if result["status"] == "success":
            stats["success"] += 1
            title = result.get("title", "")[:60]
            duration = result.get("duration", 0)
            print(f"  ✓ {title} ({duration}s)")
        elif result["status"] == "skipped":
            stats["skipped"] += 1
        else:
            stats["failed"] += 1

    print(f"\n--- 下载完成 ---")
    print(f"成功: {stats['success']}  跳过: {stats['skipped']}  失败: {stats['failed']}")
    print(f"日志: {DOWNLOAD_LOG}")


if __name__ == "__main__":
    main()
