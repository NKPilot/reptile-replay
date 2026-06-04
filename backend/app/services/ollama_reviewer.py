"""Ollama cloud review for model-clipped reptile behavior candidates."""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
OLLAMA_CHAT_URL = "https://ollama.com/api/chat"
DEFAULT_REVIEW_MODEL = "gemma3:12b"
LABELS = {
    "feeding_or_strike": "疑似进食/捕食",
    "shedding": "疑似蜕皮",
    "contact_mating_like": "疑似接触/交配",
    "drinking": "疑似饮水",
    "moving": "移动/探索",
    "resting": "静止/休息",
    "interaction": "外部互动",
    "unknown": "不确定",
}
ALLOWED_LABELS = set(LABELS)


def review_enabled() -> bool:
    return bool(os.environ.get("OLLAMA_API_KEY"))


def review_model_name() -> str:
    return os.environ.get("OLLAMA_REVIEW_MODEL", DEFAULT_REVIEW_MODEL)


def review_clip(clip: dict[str, Any], timeout_sec: int = 90) -> dict[str, Any]:
    api_key = os.environ.get("OLLAMA_API_KEY")
    if not api_key:
        return {"review_status": "skipped", "review_error": "OLLAMA_API_KEY 未配置"}

    images = _clip_preview_images(clip)
    if not images:
        return {"review_status": "skipped", "review_error": "没有可复核的关键帧预览图"}

    model = review_model_name()
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a reptile behavior verification model. "
                    "Return only compact JSON. Do not add markdown."
                ),
            },
            {
                "role": "user",
                "content": _review_prompt(clip),
                "images": images,
            },
        ],
        "options": {"temperature": 0},
    }
    request = urllib.request.Request(
        os.environ.get("OLLAMA_API_BASE", OLLAMA_CHAT_URL),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"review_status": "failed", "review_error": f"Ollama HTTP {exc.code}: {body[:300]}"}
    except Exception as exc:
        return {"review_status": "failed", "review_error": str(exc)}

    content = str(data.get("message", {}).get("content") or "")
    parsed = _parse_review_json(content)
    if not parsed:
        return {"review_status": "failed", "review_error": f"复核返回非 JSON: {content[:300]}"}

    label = _normalize_label(parsed.get("behavior"))
    confidence = _normalize_confidence(parsed.get("confidence"))
    has_reptile = bool(parsed.get("has_reptile", True))
    if not has_reptile:
        label = "unknown"
        confidence = min(confidence, 0.35)

    return {
        "review_status": "reviewed",
        "review_model": model,
        "llm_label": label,
        "llm_label_cn": LABELS.get(label, LABELS["unknown"]),
        "llm_confidence": confidence,
        "llm_reason": str(parsed.get("reason") or "").strip()[:500],
        "llm_has_reptile": has_reptile,
        "review_error": "",
    }


def apply_final_label(clip: dict[str, Any]) -> dict[str, Any]:
    auto_label = str(clip.get("auto_label") or "unknown")
    auto_confidence = _normalize_confidence(clip.get("confidence"))
    review_status = str(clip.get("review_status") or "")

    if review_status == "reviewed" and clip.get("llm_label"):
        final_label = _normalize_label(clip.get("llm_label"))
        final_confidence = _normalize_confidence(clip.get("llm_confidence"))
        final_source = "ollama"
    else:
        final_label = _normalize_label(auto_label)
        final_confidence = auto_confidence
        final_source = "locator"

    return {
        **clip,
        "final_label": final_label,
        "final_label_cn": LABELS.get(final_label, clip.get("label_cn") or final_label),
        "final_confidence": final_confidence,
        "final_source": final_source,
    }


def _clip_preview_images(clip: dict[str, Any], limit: int = 4) -> list[str]:
    frames = clip.get("frames") if isinstance(clip.get("frames"), list) else []
    selected = [
        frame
        for frame in frames
        if isinstance(frame, dict) and frame.get("preview") and frame.get("detections")
    ]
    if len(selected) < limit:
        selected.extend(
            frame
            for frame in frames
            if isinstance(frame, dict) and frame.get("preview") and frame not in selected
        )

    images = []
    for frame in selected[:limit]:
        path = _project_path(str(frame.get("preview")))
        if path.exists():
            images.append(base64.b64encode(path.read_bytes()).decode("ascii"))
    return images


def _project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _review_prompt(clip: dict[str, Any]) -> str:
    candidates = [
        {
            "label": item.get("label"),
            "label_cn": item.get("label_cn"),
            "confidence": item.get("confidence"),
        }
        for item in clip.get("behavior_candidates", [])
        if isinstance(item, dict)
    ]
    features = clip.get("behavior_features") if isinstance(clip.get("behavior_features"), dict) else {}
    labels = ", ".join(f"{key}={value}" for key, value in LABELS.items())
    return (
        "请根据这些带检测框的关键帧复核爬宠行为。"
        "只允许输出 JSON，字段为 has_reptile(boolean), behavior(string), "
        "confidence(number 0-1), reason(string)。"
        f"behavior 只能是这些枚举之一: {labels}。"
        "如果不能确定具体行为，behavior 用 unknown。"
        "重点区分: shed skin/白色脱落皮贴近身体 => shedding；"
        "猎物/食物被咬住或攻击动作 => feeding_or_strike；"
        "两只爬宠身体缠绕或持续接触 => contact_mating_like。"
        f"当前候选: {json.dumps(candidates, ensure_ascii=False)}。"
        f"检测特征: {json.dumps(features, ensure_ascii=False)}。"
    )


def _parse_review_json(content: str) -> dict[str, Any] | None:
    try:
        data = json.loads(content)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.S)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None


def _normalize_label(value: Any) -> str:
    label = str(value or "unknown").strip()
    return label if label in ALLOWED_LABELS else "unknown"


def _normalize_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    if confidence > 1.0:
        confidence = confidence / 100.0
    return round(max(0.0, min(confidence, 1.0)), 2)
