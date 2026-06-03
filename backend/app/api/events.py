"""事件查询、复核、播放 API"""

import json
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from ..models.event import (
    EventListResponse, EventDetailResponse, ReviewRequest, EventItem, EventStatus
)
from ..services.video_processor import (
    get_events, get_event, review_event, export_annotations
)

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("/video/{video_id}", response_model=EventListResponse)
async def list_events(video_id: str):
    """获取视频的所有事件列表"""
    result = get_events(video_id)
    return result


@router.get("/{event_id}")
async def get_event_detail(event_id: str):
    """获取单个事件详情"""
    evt = get_event(event_id)
    if not evt:
        raise HTTPException(404, "事件不存在")

    clip_url = f"/api/events/{event_id}/clip" if evt.get("clip_path") else ""

    return {
        "event": evt,
        "clip_url": clip_url,
    }


@router.post("/{event_id}/review")
async def review_event_endpoint(event_id: str, body: ReviewRequest):
    """
    人工复核事件：
    - confirmed: 确认行为
    - rejected: 驳回（误报）
    - wrong_label: 标签错误
    """
    evt = review_event(event_id, body.status.value, body.label.value if body.label else None)
    if not evt:
        raise HTTPException(404, "事件不存在")
    return {"event": evt, "message": "复核完成"}


@router.get("/{event_id}/clip")
async def get_event_clip(event_id: str):
    """播放事件剪辑片段"""
    evt = get_event(event_id)
    if not evt:
        raise HTTPException(404, "事件不存在")

    clip_path = evt.get("clip_path", "")
    if not clip_path or not Path(clip_path).exists():
        raise HTTPException(404, "剪辑片段不存在")

    return FileResponse(
        clip_path,
        media_type="video/mp4",
        filename=f"{event_id}.mp4",
    )


@router.post("/{event_id}/thumbnail")
async def generate_thumbnail(event_id: str):
    """TODO: 生成事件缩略图"""
    return {"message": "缩略图功能将在后续版本实现"}


@router.get("/export/{video_id}")
async def export_video_annotations(video_id: str):
    """导出标注数据"""
    annotations = export_annotations(video_id)
    return {"video_id": video_id, "count": len(annotations), "annotations": annotations}


@router.get("/export/all")
async def export_all_annotations():
    """导出所有标注数据"""
    annotations = export_annotations()
    return {"count": len(annotations), "annotations": annotations}
