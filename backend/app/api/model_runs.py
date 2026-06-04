"""Single-video model clipping task API."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from ..services.model_run_processor import (
    create_model_run,
    execute_model_run,
    list_model_runs,
    load_model_run_detail,
)

router = APIRouter(prefix="/api/model-runs", tags=["model-runs"])


class CreateModelRunRequest(BaseModel):
    video_id: Optional[str] = None
    source_video_id: Optional[str] = None


@router.post("")
async def create_run(body: CreateModelRunRequest, background_tasks: BackgroundTasks):
    try:
        record = create_model_run(body.video_id, body.source_video_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    background_tasks.add_task(execute_model_run, record["run_id"])
    return {
        "run_id": record["run_id"],
        "video_id": record["video_id"],
        "source_video_id": record.get("source_video_id", ""),
        "status": record["status"],
    }


@router.get("")
async def list_runs(video_id: Optional[str] = Query(None)):
    return {"runs": list_model_runs(video_id)}


@router.get("/{run_id}")
async def get_run(run_id: str):
    detail = load_model_run_detail(run_id)
    if not detail:
        raise HTTPException(404, "模型剪辑任务不存在")
    return detail
