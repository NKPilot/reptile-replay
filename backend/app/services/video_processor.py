"""
视频处理服务 —— 统一的处理编排层。
    抽帧 → 运动分析 → 事件生成 → 剪辑
"""

import json
import os
import uuid
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from .event_aggregator import generate_events
from .clipper import clip_all_events

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
UPLOADS_DIR = PROJECT_ROOT / "data" / "uploads"
EVENTS_DIR = PROJECT_ROOT / "data" / "events"
RESULTS_DIR = PROJECT_ROOT / "data" / "results"
RAW_DIR = PROJECT_ROOT / "data" / "raw"

# 内存中的状态存储（MVP 阶段，不引入数据库）
_video_store: dict[str, dict] = {}
_event_store: dict[str, dict] = {}


def init_storage():
    """初始化存储目录"""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def import_source_video(source_video_id: str) -> str:
    """
    将 data/raw/{source_video_id}/ 中的预下载视频导入上传目录并注册到视频存储。
    返回新生成的 video_id，失败抛出异常。
    """
    init_storage()

    raw_video_dir = RAW_DIR / source_video_id
    if not raw_video_dir.exists():
        raise FileNotFoundError(f"素材视频不存在: {source_video_id}")

    # 找到视频文件
    video_files = list(raw_video_dir.glob("*.mp4")) + \
                  list(raw_video_dir.glob("*.webm")) + \
                  list(raw_video_dir.glob("*.mkv"))
    if not video_files:
        raise FileNotFoundError(f"素材目录下没有视频文件: {raw_video_dir}")

    raw_path = video_files[0]

    # 读取 info.json 获取元数据
    title = source_video_id
    info_files = list(raw_video_dir.glob("*.info.json"))
    if info_files:
        import json
        try:
            with open(info_files[0]) as f:
                info = json.load(f)
            title = info.get("title", source_video_id)
        except (json.JSONDecodeError, KeyError):
            pass

    # 生成新 video_id 并拷贝到 uploads
    new_video_id = uuid.uuid4().hex[:12]
    ext = raw_path.suffix
    safe_name = f"{new_video_id}{ext}"
    dest = UPLOADS_DIR / safe_name

    shutil.copy2(raw_path, dest)

    file_size = dest.stat().st_size
    _video_store[new_video_id] = {
        "video_id": new_video_id,
        "filename": safe_name,
        "original_name": title,
        "file_path": str(dest),
        "file_size": file_size,
        "duration": 0,
        "status": "uploaded",
        "created_at": datetime.now().isoformat(),
        "error": None,
        "source_video_id": source_video_id,
    }

    return new_video_id


def save_upload(file_data: bytes, filename: str) -> str:
    """保存上传的视频文件，返回 video_id"""
    init_storage()
    video_id = uuid.uuid4().hex[:12]
    safe_name = f"{video_id}_{filename}"
    dest = UPLOADS_DIR / safe_name

    with open(dest, "wb") as f:
        f.write(file_data)

    file_size = dest.stat().st_size
    _video_store[video_id] = {
        "video_id": video_id,
        "filename": safe_name,
        "original_name": filename,
        "file_path": str(dest),
        "file_size": file_size,
        "duration": 0,
        "status": "uploaded",
        "created_at": datetime.now().isoformat(),
        "error": None,
    }

    return video_id


def get_video(video_id: str) -> Optional[dict]:
    """获取视频信息"""
    return _video_store.get(video_id)


def get_all_videos() -> list[dict]:
    """获取所有视频"""
    return list(_video_store.values())


def process_video(video_id: str) -> dict:
    """处理视频：运动分析 → 事件生成 → 剪辑"""
    video = _video_store.get(video_id)
    if not video:
        return {"error": "视频不存在"}

    video_path = Path(video["file_path"])
    if not video_path.exists():
        video["status"] = "failed"
        video["error"] = "文件丢失"
        return {"error": "文件丢失"}

    # 更新状态
    video["status"] = "processing"

    try:
        # 1. 运动分析 + 事件生成
        result = generate_events(
            video_path,
            window_size=5.0,
            step_size=2.0,
            min_conf=0.45,
            min_consecutive=2,
            merge_gap=10.0,
            pre_buffer=10.0,
            post_buffer=20.0,
        )

        if "error" in result:
            video["status"] = "failed"
            video["error"] = result["error"]
            return result

        events = result.get("events", [])
        video["duration"] = result.get("video_duration", 0)

        # 2. 剪辑事件片段
        if events:
            events = clip_all_events(video_path, EVENTS_DIR, events)

        # 3. 保存事件到内存
        for evt in events:
            _event_store[evt["event_id"]] = evt

        # 4. 保存结果 JSON
        result_path = RESULTS_DIR / f"{video_id}.json"
        with open(result_path, "w") as f:
            json.dump({
                "video_id": video_id,
                "events": events,
                "motion_summary": result.get("motion_summary", {}),
                "processed_at": datetime.now().isoformat(),
            }, f, ensure_ascii=False, indent=2)

        video["status"] = "done"
        video["event_count"] = len(events)
        video["result_path"] = str(result_path)

        return {"video_id": video_id, "event_count": len(events), "events": events}

    except Exception as e:
        video["status"] = "failed"
        video["error"] = str(e)
        return {"error": str(e)}


def get_events(video_id: str) -> dict:
    """获取视频的所有事件"""
    events = [
        evt for evt in _event_store.values()
        if evt["video_id"] == video_id
    ]
    return {
        "video_id": video_id,
        "total": len(events),
        "events": events,
    }


def get_event(event_id: str) -> Optional[dict]:
    """获取单个事件"""
    return _event_store.get(event_id)


def review_event(event_id: str, status: str, new_label: Optional[str] = None) -> Optional[dict]:
    """复核事件"""
    evt = _event_store.get(event_id)
    if not evt:
        return None

    evt["status"] = status
    if new_label:
        evt["type"] = new_label
        evt["label_en"] = new_label
        from ..models.event import LABEL_CN
        evt["label"] = LABEL_CN.get(new_label, new_label)

    return evt


def export_annotations(video_id: Optional[str] = None) -> list[dict]:
    """导出标注数据"""
    events = list(_event_store.values())
    if video_id:
        events = [e for e in events if e["video_id"] == video_id]
    return events
