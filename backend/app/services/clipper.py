"""
视频剪辑器 —— 用 FFmpeg 从原视频中剪出事件片段。
"""

import subprocess
from pathlib import Path


def clip_event(
    source_path: Path,
    output_path: Path,
    start_sec: float,
    end_sec: float,
    width: int = 640,
    fps: int = 8,
) -> bool:
    """
    从原视频中剪辑片段。

    参数:
        source_path: 源视频路径
        output_path: 输出路径
        start_sec: 起始秒数
        end_sec: 结束秒数
        width: 输出宽度
        fps: 输出帧率

    返回: 成功 True / 失败 False
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    duration = end_sec - start_sec
    if duration <= 0:
        return False

    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(start_sec),
        "-i", str(source_path),
        "-t", str(duration),
        "-vf", f"scale={width}:-2,fps={fps}",
        "-an",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "28",
        str(output_path),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return result.returncode == 0 and output_path.exists()
    except subprocess.TimeoutExpired:
        return False


def clip_all_events(
    source_path: Path,
    events_dir: Path,
    events: list[dict],
) -> list[dict]:
    """
    批量剪辑所有事件片段。

    返回: 更新后的 events 列表（含 clip_path）
    """
    for evt in events:
        clip_filename = f"{evt['event_id']}.mp4"
        clip_path = events_dir / evt["video_id"] / clip_filename
        clip_path.parent.mkdir(parents=True, exist_ok=True)

        success = clip_event(
            source_path,
            clip_path,
            evt["clip_start"],
            evt["clip_end"],
        )

        evt["clip_path"] = str(clip_path) if success else ""
        evt["clip_success"] = success

    return events
