"""视频相关数据模型"""

from datetime import datetime
from enum import Enum
from pydantic import BaseModel
from typing import Optional


class VideoStatus(str, Enum):
    uploaded = "uploaded"
    processing = "processing"
    done = "done"
    failed = "failed"


class VideoInfo(BaseModel):
    video_id: str
    filename: str
    original_name: str
    duration: float = 0.0
    file_size: int = 0
    status: VideoStatus = VideoStatus.uploaded
    created_at: str = ""
    error: Optional[str] = None


class VideoUploadResponse(BaseModel):
    video_id: str
    filename: str
    status: str


class ProcessRequest(BaseModel):
    video_id: str
