"""事件相关数据模型"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel


class EventStatus(str, Enum):
    pending = "pending"
    confirmed = "confirmed"
    rejected = "rejected"
    wrong_label = "wrong_label"


class EventType(str, Enum):
    resting = "resting"
    moving = "moving"
    feeding_or_strike = "feeding_or_strike"
    shedding = "shedding"
    contact_mating_like = "contact_mating_like"
    unknown = "unknown"


LABEL_CN = {
    "resting": "静止/休息",
    "moving": "普通移动",
    "feeding_or_strike": "疑似进食/捕食",
    "shedding": "疑似蜕皮",
    "contact_mating_like": "疑似交配/接触",
    "unknown": "未知",
}


class EventItem(BaseModel):
    event_id: str
    video_id: str
    type: EventType
    label: str          # 中文标签
    label_en: str       # 英文标签
    start: float        # 开始秒数
    end: float          # 结束秒数
    confidence: float
    clip_path: str      # 剪辑片段路径
    status: EventStatus = EventStatus.pending
    thumbnail_path: str = ""


class EventListResponse(BaseModel):
    video_id: str
    total: int
    events: list[EventItem]


class ReviewRequest(BaseModel):
    status: EventStatus
    label: Optional[EventType] = None


class EventDetailResponse(BaseModel):
    event: EventItem
    clip_url: str
