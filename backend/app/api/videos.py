"""视频上传与处理 API"""

import os
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse

from ..models.video import VideoUploadResponse, VideoInfo, VideoStatus
from ..services.video_processor import (
    save_upload, get_video, get_all_videos, process_video, import_source_video
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

router = APIRouter(prefix="/api/videos", tags=["videos"])


@router.post("/upload", response_model=VideoUploadResponse)
async def upload_video(file: UploadFile = File(...)):
    """上传 MP4 视频"""
    if not file.filename:
        raise HTTPException(400, "文件名不能为空")

    filename = file.filename
    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".mp4", ".mov", ".avi", ".mkv", ".webm"):
        raise HTTPException(400, f"不支持的格式: {ext}，请上传 mp4/mov/avi/mkv/webm")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(400, "文件为空")

    video_id = save_upload(content, filename)

    return VideoUploadResponse(
        video_id=video_id,
        filename=filename,
        status="uploaded",
    )


@router.get("/", response_model=list[VideoInfo])
async def list_videos():
    """列出所有已上传的视频"""
    return get_all_videos()


@router.get("/{video_id}", response_model=VideoInfo)
async def get_video_info(video_id: str):
    """获取单个视频信息"""
    video = get_video(video_id)
    if not video:
        raise HTTPException(404, "视频不存在")
    return video


@router.post("/{video_id}/process")
async def process_video_endpoint(video_id: str, background_tasks: BackgroundTasks):
    """
    开始处理视频：运动分析 → 事件生成 → 自动剪辑。
    同步返回结果，前端可以轮询事件列表。
    """
    video = get_video(video_id)
    if not video:
        raise HTTPException(404, "视频不存在")

    # 同步处理（MVP 阶段视频不会太长）
    result = process_video(video_id)

    if "error" in result:
        raise HTTPException(500, result["error"])

    return {
        "video_id": video_id,
        "status": "done",
        "event_count": result.get("event_count", 0),
        "message": f"处理完成，发现 {result.get('event_count', 0)} 个疑似关键行为",
    }


@router.post("/import-source/{source_video_id}")
async def import_source(source_video_id: str):
    """
    将素材库中的预下载视频导入并自动分析。
    拖拽素材卡到上传区时调用此接口。
    """
    try:
        video_id = import_source_video(source_video_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))

    # 自动触发分析处理
    result = process_video(video_id)

    if "error" in result:
        raise HTTPException(500, result["error"])

    return {
        "video_id": video_id,
        "source_video_id": source_video_id,
        "status": "done",
        "event_count": result.get("event_count", 0),
        "message": f"素材导入完成，发现 {result.get('event_count', 0)} 个疑似关键行为",
    }
