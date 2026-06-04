#!/usr/bin/env python3
"""
Run an open-vocabulary locator model on sampled video frames.

Examples:
    uv run --group locateanything python scripts/locate_clips.py \
      --clips-dir data/events \
      --limit 20

    uv run --group locateanything python scripts/locate_clips.py \
      --model-dir models/grounding-dino-tiny \
      --backend grounding-dino \
      --clips-dir data/clips/usable

Output:
    data/results/locateanything_test.json
    data/results/locateanything_preview/*.jpg
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODELS_DIR = PROJECT_ROOT / "models"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "results" / "locateanything_test.json"
DEFAULT_PREVIEW_DIR = PROJECT_ROOT / "data" / "results" / "locateanything_preview"
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".ts"}
DEFAULT_PROMPTS = [
    "reptile",
    "snake",
    "lizard",
    "gecko",
    "turtle",
    "food",
    "prey",
    "shed skin",
    "water bowl",
    "human hand",
]

REPTILE_LABELS = {"reptile", "snake", "lizard", "gecko", "turtle", "locateanything"}
FOOD_LABELS = {"food", "prey", "insect", "mouse", "worm"}
SHED_LABELS = {"shed skin", "skin", "shedding skin"}
WATER_LABELS = {"water bowl", "water", "bowl"}
HUMAN_LABELS = {"human hand", "hand", "person", "human"}

BEHAVIOR_LABEL_CN = {
    "feeding_or_strike": "疑似进食/捕食",
    "shedding": "疑似蜕皮",
    "moving": "移动/探索",
    "resting": "静止/休息",
    "drinking": "疑似饮水",
    "interaction": "外部互动",
    "contact_mating_like": "疑似接触/交配",
    "unknown": "不确定",
}


@dataclass
class SampledFrame:
    image: Image.Image
    frame_index: int
    timestamp_sec: float


def _project_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def discover_model_dir(models_dir: Path) -> Path:
    candidates = [
        models_dir / "locateanything-3b",
        models_dir / "LocateAnything-3B",
        models_dir / "grounding-dino-tiny",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    existing = [p for p in models_dir.iterdir() if p.is_dir()] if models_dir.exists() else []
    if len(existing) == 1:
        return existing[0]

    names = ", ".join(p.name for p in existing) or "none"
    raise FileNotFoundError(
        f"Could not auto-detect a model under {models_dir}. "
        f"Found: {names}. Pass --model-dir explicitly."
    )


def detect_backend(model_dir: Path, requested: str) -> str:
    if requested != "auto":
        return requested

    name = model_dir.name.lower()
    if "grounding" in name or "dino" in name:
        return "grounding-dino"
    if "locate" in name:
        return "locateanything"

    config_path = model_dir / "config.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
        except json.JSONDecodeError:
            config = {}
        model_type = str(config.get("model_type", "")).lower()
        architectures = " ".join(config.get("architectures", [])).lower()
        if "grounding" in model_type or "dino" in architectures:
            return "grounding-dino"
        if "locate" in model_type or "locate" in architectures:
            return "locateanything"

    raise ValueError(
        f"Could not infer backend for {model_dir}. "
        "Pass --backend locateanything or --backend grounding-dino."
    )


def resolve_device(device: str) -> str:
    if device != "auto":
        return device
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def resolve_torch_dtype(dtype: str, device: str):
    import torch

    if dtype == "auto":
        if device.startswith("cuda"):
            return torch.float16
        return torch.float32
    mapping = {
        "fp16": torch.float16,
        "float16": torch.float16,
        "bf16": torch.bfloat16,
        "bfloat16": torch.bfloat16,
        "fp32": torch.float32,
        "float32": torch.float32,
    }
    if dtype not in mapping:
        raise ValueError(f"Unsupported dtype: {dtype}")
    return mapping[dtype]


def list_video_files(root: Path, recursive: bool = True) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix.lower() in VIDEO_EXTENSIONS else []

    iterator = root.rglob("*") if recursive else root.glob("*")
    files = [p for p in iterator if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS]
    return sorted(files)


def sample_video_frames(clip_path: Path, sample_frames: int) -> tuple[list[SampledFrame], dict[str, Any]]:
    cap = cv2.VideoCapture(str(clip_path))
    if not cap.isOpened():
        return [], {"error": "could_not_open_video"}

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    duration = total_frames / fps if fps > 0 else 0.0
    if total_frames <= 0:
        cap.release()
        return [], {"error": "video_has_no_frames", "total_frames": total_frames, "fps": fps}

    count = max(1, min(sample_frames, total_frames))
    indices = np.linspace(0, total_frames - 1, count, dtype=int)
    samples: list[SampledFrame] = []

    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ok, frame = cap.read()
        if not ok:
            continue
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        ts = float(idx / fps) if fps > 0 else 0.0
        samples.append(SampledFrame(Image.fromarray(rgb), int(idx), ts))

    cap.release()
    return samples, {"total_frames": total_frames, "fps": fps, "duration_sec": duration}


class LocateAnythingWorker:
    def __init__(self, model_dir: Path, device: str, dtype: str):
        import torch
        from transformers import AutoModel, AutoProcessor, AutoTokenizer

        torch_dtype = resolve_torch_dtype(dtype, device)
        self.device = device
        self.dtype = torch_dtype
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)
        self.processor = AutoProcessor.from_pretrained(model_dir, trust_remote_code=True)
        self.model = AutoModel.from_pretrained(
            model_dir,
            torch_dtype=torch_dtype,
            trust_remote_code=True,
        ).to(device).eval()

    def detect(
        self,
        image: Image.Image,
        categories: list[str],
        generation_mode: str,
        max_new_tokens: int,
        temperature: float,
        verbose: bool,
        combined_prompts: bool,
    ) -> dict[str, Any]:
        if not combined_prompts:
            answers = []
            boxes = []
            for category in categories:
                prompt = f"Locate all the instances that matches the following description: {category}."
                result = self.predict(
                    image,
                    prompt,
                    generation_mode=generation_mode,
                    max_new_tokens=max_new_tokens,
                    temperature=temperature,
                    verbose=verbose,
                )
                answers.append(f"[{category}] {result.get('answer', '')}")
                for box in result["boxes"]:
                    boxes.append({**box, "label": category})
            return {"answer": "\n".join(answers), "boxes": boxes}

        cats = "</c>".join(categories)
        prompt = f"Locate all the instances that matches the following description: {cats}."
        return self.predict(
            image,
            prompt,
            generation_mode=generation_mode,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            verbose=verbose,
        )

    def predict(
        self,
        image: Image.Image,
        question: str,
        generation_mode: str,
        max_new_tokens: int,
        temperature: float,
        verbose: bool,
    ) -> dict[str, Any]:
        import torch

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": question},
                ],
            }
        ]
        text = self.processor.py_apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        images, videos = self.processor.process_vision_info(messages)
        inputs = self.processor(text=[text], images=images, videos=videos, return_tensors="pt")
        inputs = inputs.to(self.device)

        with torch.no_grad():
            response = self.model.generate(
                pixel_values=inputs["pixel_values"].to(self.dtype),
                input_ids=inputs["input_ids"],
                attention_mask=inputs["attention_mask"],
                image_grid_hws=inputs.get("image_grid_hws", None),
                tokenizer=self.tokenizer,
                max_new_tokens=max_new_tokens,
                use_cache=True,
                generation_mode=generation_mode,
                temperature=temperature,
                do_sample=temperature > 0,
                top_p=0.9,
                repetition_penalty=1.1,
                verbose=verbose,
            )

        answer = response[0] if isinstance(response, tuple) else response
        return {"answer": answer, "boxes": parse_locateanything_boxes(answer, image.size)}


class GroundingDinoWorker:
    def __init__(self, model_dir: Path, device: str, dtype: str, box_threshold: float, text_threshold: float):
        import torch
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

        torch_dtype = resolve_torch_dtype(dtype, device)
        self.device = device
        self.box_threshold = box_threshold
        self.text_threshold = text_threshold
        self.processor = AutoProcessor.from_pretrained(model_dir)
        self.model = AutoModelForZeroShotObjectDetection.from_pretrained(
            model_dir,
            torch_dtype=torch_dtype if device.startswith("cuda") else None,
        ).to(device).eval()

    def detect(self, image: Image.Image, categories: list[str]) -> dict[str, Any]:
        import torch

        text = ". ".join(categories)
        if not text.endswith("."):
            text += "."

        inputs = self.processor(images=image, text=text, return_tensors="pt")
        inputs = {k: v.to(self.device) if hasattr(v, "to") else v for k, v in inputs.items()}
        with torch.no_grad():
            outputs = self.model(**inputs)

        target_sizes = torch.tensor([image.size[::-1]], device=self.device)
        try:
            processed = self.processor.post_process_grounded_object_detection(
                outputs,
                input_ids=inputs.get("input_ids"),
                box_threshold=self.box_threshold,
                text_threshold=self.text_threshold,
                target_sizes=target_sizes,
            )[0]
        except TypeError:
            processed = self.processor.post_process_grounded_object_detection(
                outputs,
                inputs.get("input_ids"),
                box_threshold=self.box_threshold,
                text_threshold=self.text_threshold,
                target_sizes=target_sizes,
            )[0]

        boxes = []
        for box, score, label in zip(
            processed.get("boxes", []),
            processed.get("scores", []),
            processed.get("labels", []),
        ):
            x1, y1, x2, y2 = [float(v) for v in box.detach().cpu().tolist()]
            boxes.append(
                {
                    "label": str(label),
                    "score": float(score.detach().cpu().item()),
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                }
            )

        return {"answer": "", "boxes": boxes}


def parse_locateanything_boxes(answer: str, image_size: tuple[int, int]) -> list[dict[str, Any]]:
    width, height = image_size
    boxes = []
    patterns = [
        r"<box><(\d+)><(\d+)><(\d+)><(\d+)></box>",
        r"<box>\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*</box>",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, answer):
            x1, y1, x2, y2 = [int(g) for g in match.groups()]
            boxes.append(
                {
                    "label": "locateanything",
                    "score": None,
                    "x1": x1 / 1000 * width,
                    "y1": y1 / 1000 * height,
                    "x2": x2 / 1000 * width,
                    "y2": y2 / 1000 * height,
                }
            )
    return boxes


def clamp_box(box: dict[str, Any], width: int, height: int) -> dict[str, float]:
    x1 = max(0.0, min(float(box["x1"]), float(width)))
    y1 = max(0.0, min(float(box["y1"]), float(height)))
    x2 = max(0.0, min(float(box["x2"]), float(width)))
    y2 = max(0.0, min(float(box["y2"]), float(height)))
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    return {**box, "x1": x1, "y1": y1, "x2": x2, "y2": y2}


def normalize_label(label: Any) -> str:
    return re.sub(r"\s+", " ", str(label or "").strip().lower())


def detection_group(det: dict[str, Any]) -> str:
    label = normalize_label(det.get("label"))
    if label in REPTILE_LABELS or any(token in label for token in ("reptile", "snake", "lizard", "gecko", "turtle")):
        return "reptile"
    if label in FOOD_LABELS or any(token in label for token in ("food", "prey", "insect", "mouse", "worm")):
        return "food"
    if label in SHED_LABELS or "shed" in label:
        return "shed"
    if label in WATER_LABELS or ("water" in label and "bowl" in label):
        return "water"
    if label in HUMAN_LABELS or "hand" in label or "human" in label or "person" in label:
        return "human"
    return "other"


def box_area(box: dict[str, Any]) -> float:
    return max(0.0, float(box["x2"]) - float(box["x1"])) * max(0.0, float(box["y2"]) - float(box["y1"]))


def box_distance(a: dict[str, Any], b: dict[str, Any]) -> float:
    ax = (float(a["x1"]) + float(a["x2"])) / 2
    ay = (float(a["y1"]) + float(a["y2"])) / 2
    bx = (float(b["x1"]) + float(b["x2"])) / 2
    by = (float(b["y1"]) + float(b["y2"])) / 2
    aw = max(1.0, float(a["x2"]) - float(a["x1"]))
    ah = max(1.0, float(a["y2"]) - float(a["y1"]))
    scale = max(aw, ah, 1.0)
    return float(((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5 / scale)


def has_near_object(
    frame_results: list[dict[str, Any]],
    object_group: str,
    max_distance: float = 1.8,
) -> bool:
    for frame in frame_results:
        reptile_boxes = [d for d in frame["detections"] if detection_group(d) == "reptile"]
        object_boxes = [d for d in frame["detections"] if detection_group(d) == object_group]
        if reptile_boxes and object_boxes:
            if min(box_distance(r, o) for r in reptile_boxes for o in object_boxes) <= max_distance:
                return True
    return False


def count_multi_reptile_frames(frame_results: list[dict[str, Any]]) -> int:
    return sum(
        1
        for frame in frame_results
        if sum(1 for det in frame["detections"] if detection_group(det) == "reptile") >= 2
    )


def has_near_reptile_pair(frame_results: list[dict[str, Any]], max_distance: float = 1.4) -> bool:
    for frame in frame_results:
        reptile_boxes = [d for d in frame["detections"] if detection_group(d) == "reptile"]
        for index, box in enumerate(reptile_boxes):
            for other in reptile_boxes[index + 1:]:
                if box_distance(box, other) <= max_distance:
                    return True
    return False


def reptile_frame_flags(frame_results: list[dict[str, Any]]) -> list[bool]:
    return [
        any(detection_group(det) == "reptile" for det in frame["detections"])
        for frame in frame_results
    ]


def continuous_segments(flags: list[bool], timestamps: list[float]) -> list[dict[str, Any]]:
    segments = []
    start: int | None = None
    for index, flag in enumerate(flags + [False]):
        if flag and start is None:
            start = index
        if not flag and start is not None:
            end = index - 1
            segments.append(
                {
                    "start_frame": start,
                    "end_frame": end,
                    "start_sec": timestamps[start] if start < len(timestamps) else 0.0,
                    "end_sec": timestamps[end] if end < len(timestamps) else 0.0,
                    "length": end - start + 1,
                }
            )
            start = None
    return segments


def motion_profile(samples: list[SampledFrame], frame_results: list[dict[str, Any]]) -> dict[str, float]:
    if len(samples) < 2:
        return {
            "avg_motion": 0.0,
            "peak_motion": 0.0,
            "motion_ratio": 0.0,
            "roi_motion_ratio": 0.0,
            "texture_change": 0.0,
        }

    grays = []
    for sample in samples:
        arr = cv2.cvtColor(np.array(sample.image), cv2.COLOR_RGB2GRAY)
        width = 160
        height = max(1, int(arr.shape[0] * width / max(arr.shape[1], 1)))
        grays.append(cv2.resize(arr, (width, height), interpolation=cv2.INTER_AREA))

    motions = []
    roi_ratios = []
    texture_changes = []
    for index in range(1, len(grays)):
        diff = cv2.absdiff(grays[index - 1], grays[index])
        motion = float(np.mean(diff) / 255.0)
        motions.append(motion)

        prev_lap = cv2.Laplacian(grays[index - 1], cv2.CV_32F)
        curr_lap = cv2.Laplacian(grays[index], cv2.CV_32F)
        texture_changes.append(float(np.mean(np.abs(curr_lap - prev_lap)) / 255.0))

        source_width, source_height = samples[index].image.size
        mask = np.zeros_like(diff, dtype=np.uint8)
        for det in frame_results[index].get("detections", []):
            if detection_group(det) != "reptile":
                continue
            x1 = int(float(det["x1"]) / max(source_width, 1) * mask.shape[1])
            x2 = int(float(det["x2"]) / max(source_width, 1) * mask.shape[1])
            y1 = int(float(det["y1"]) / max(source_height, 1) * mask.shape[0])
            y2 = int(float(det["y2"]) / max(source_height, 1) * mask.shape[0])
            mask[max(0, y1):max(0, y2), max(0, x1):max(0, x2)] = 1

        total_energy = float(np.sum(diff))
        if total_energy > 0 and np.any(mask):
            roi_ratios.append(float(np.sum(diff * mask) / total_energy))

    avg_motion = float(np.mean(motions)) if motions else 0.0
    peak_motion = float(max(motions)) if motions else 0.0
    active_threshold = max(0.015, avg_motion * 1.4)
    return {
        "avg_motion": round(avg_motion, 4),
        "peak_motion": round(peak_motion, 4),
        "motion_ratio": round(sum(1 for m in motions if m >= active_threshold) / max(len(motions), 1), 4),
        "roi_motion_ratio": round(float(np.mean(roi_ratios)) if roi_ratios else 0.0, 4),
        "texture_change": round(float(np.mean(texture_changes)) if texture_changes else 0.0, 4),
    }


def behavior_candidates(
    frame_results: list[dict[str, Any]],
    motion: dict[str, float],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sampled_frames = max(len(frame_results), 1)
    flags = reptile_frame_flags(frame_results)
    detected_frames = sum(1 for flag in flags if flag)
    continuity = detected_frames / sampled_frames
    segments = continuous_segments(flags, [float(frame.get("timestamp_sec") or 0.0) for frame in frame_results])
    longest_segment = max((segment["length"] for segment in segments), default=0)
    longest_ratio = longest_segment / sampled_frames

    reptile_boxes = [
        det
        for frame in frame_results
        for det in frame["detections"]
        if detection_group(det) == "reptile"
    ]
    avg_box_area = 0.0
    if reptile_boxes:
        first_frame = next((frame for frame in frame_results if frame["detections"]), None)
        frame_area = 1.0
        if first_frame:
            all_boxes = first_frame["detections"]
            max_x = max(float(det["x2"]) for det in all_boxes)
            max_y = max(float(det["y2"]) for det in all_boxes)
            frame_area = max(max_x * max_y, 1.0)
        avg_box_area = min(float(np.mean([box_area(box) / frame_area for box in reptile_boxes])), 1.0)

    near_food = has_near_object(frame_results, "food")
    near_shed = has_near_object(frame_results, "shed", max_distance=2.4)
    near_water = has_near_object(frame_results, "water")
    near_human = has_near_object(frame_results, "human", max_distance=2.2)
    multi_reptile_ratio = count_multi_reptile_frames(frame_results) / sampled_frames
    near_reptile_pair = has_near_reptile_pair(frame_results)
    objects = sorted({detection_group(det) for frame in frame_results for det in frame["detections"]})

    roi_motion = motion["roi_motion_ratio"]
    peak_motion = motion["peak_motion"]
    avg_motion = motion["avg_motion"]
    texture_change = motion["texture_change"]

    scores = {
        "feeding_or_strike": 0.10 + continuity * 0.18 + roi_motion * 0.25 + min(peak_motion / 0.08, 1.0) * 0.20,
        "shedding": 0.08 + continuity * 0.24 + longest_ratio * 0.16 + min(texture_change / 0.08, 1.0) * 0.18,
        "moving": 0.12 + continuity * 0.22 + roi_motion * 0.20 + min(avg_motion / 0.05, 1.0) * 0.18,
        "resting": 0.08 + continuity * 0.28 + max(0.0, 1.0 - min(avg_motion / 0.025, 1.0)) * 0.22,
        "drinking": 0.06 + continuity * 0.16 + roi_motion * 0.14,
        "interaction": 0.06 + continuity * 0.14 + min(peak_motion / 0.08, 1.0) * 0.12,
        "contact_mating_like": 0.07 + continuity * 0.18 + multi_reptile_ratio * 0.24 + roi_motion * 0.16,
    }

    if near_food:
        scores["feeding_or_strike"] += 0.28
        scores["shedding"] -= 0.18
    if near_shed:
        shed_bonus = 0.26
        if peak_motion >= 0.06:
            shed_bonus -= 0.12
        if near_food:
            shed_bonus -= 0.10
        scores["shedding"] += max(0.0, shed_bonus)
    if near_water:
        scores["drinking"] += 0.30
    if near_human:
        scores["interaction"] += 0.26
        scores["feeding_or_strike"] -= 0.10
        scores["contact_mating_like"] -= 0.08
        scores["shedding"] -= 0.08
    if near_food and peak_motion >= 0.06 and roi_motion >= 0.35:
        scores["feeding_or_strike"] += 0.14
    if peak_motion >= 0.075:
        scores["shedding"] -= 0.08
    if near_reptile_pair:
        scores["contact_mating_like"] += 0.22
    if multi_reptile_ratio > 0 and peak_motion < 0.08:
        scores["contact_mating_like"] += 0.10
    if avg_box_area > 0:
        scores["moving"] += min(avg_box_area * 0.25, 0.08)
        scores["resting"] += min(avg_box_area * 0.20, 0.06)

    if detected_frames == 0:
        scores = {"unknown": 0.35}
    else:
        scores["unknown"] = max(0.05, 0.32 - continuity * 0.18)
        if near_food and peak_motion >= 0.06:
            scores["shedding"] = min(scores["shedding"], scores["feeding_or_strike"] - 0.05)
        elif peak_motion >= 0.075:
            scores["shedding"] = min(scores["shedding"], 0.68)
        elif not near_shed:
            scores["shedding"] = min(scores["shedding"], 0.62)

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:3]
    candidates = [
        {
            "label": label,
            "label_cn": BEHAVIOR_LABEL_CN.get(label, label),
            "confidence": round(max(0.0, min(score, 0.95)), 2),
        }
        for label, score in ranked
    ]
    features = {
        **motion,
        "reptile_continuity": round(continuity, 4),
        "longest_reptile_segment_ratio": round(longest_ratio, 4),
        "multi_reptile_frame_ratio": round(multi_reptile_ratio, 4),
        "near_reptile_pair": near_reptile_pair,
        "reptile_segments": segments,
        "objects": objects,
    }
    return candidates, features


def draw_preview(image: Image.Image, detections: list[dict[str, Any]], title: str, output_path: Path):
    preview = image.copy()
    draw = ImageDraw.Draw(preview)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 16)
    except OSError:
        font = ImageFont.load_default()

    width, height = preview.size
    for det in detections:
        box = clamp_box(det, width, height)
        x1, y1, x2, y2 = box["x1"], box["y1"], box["x2"], box["y2"]
        label = str(box.get("label") or "object")
        score = box.get("score")
        text = f"{label} {score:.2f}" if isinstance(score, float) else label
        draw.rectangle((x1, y1, x2, y2), outline=(255, 66, 66), width=3)
        text_box = draw.textbbox((x1, y1), text, font=font)
        label_h = text_box[3] - text_box[1] + 4
        label_w = text_box[2] - text_box[0] + 6
        y_text = max(0, y1 - label_h)
        draw.rectangle((x1, y_text, x1 + label_w, y_text + label_h), fill=(255, 66, 66))
        draw.text((x1 + 3, y_text + 2), text, fill=(255, 255, 255), font=font)

    draw.rectangle((0, 0, width, 24), fill=(0, 0, 0))
    draw.text((6, 4), title[:120], fill=(255, 255, 255), font=font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    preview.save(output_path, quality=92)


def summarize_clip(frame_results: list[dict[str, Any]]) -> dict[str, Any]:
    detected_frames = sum(
        1
        for frame in frame_results
        if any(detection_group(det) == "reptile" for det in frame["detections"])
    )
    detections = sum(len(frame["detections"]) for frame in frame_results)
    labels = sorted(
        {
            str(det.get("label"))
            for frame in frame_results
            for det in frame["detections"]
            if det.get("label")
        }
    )
    return {
        "sampled_frames": len(frame_results),
        "detected_frames": detected_frames,
        "total_detections": detections,
        "has_reptile": detected_frames > 0,
        "labels": labels,
    }


def normalize_prompts(values: Iterable[str]) -> list[str]:
    prompts: list[str] = []
    for value in values:
        for piece in value.split(","):
            piece = piece.strip()
            if piece:
                prompts.append(piece)
    return prompts or DEFAULT_PROMPTS


def run(args: argparse.Namespace) -> dict[str, Any]:
    model_dir = _project_path(args.model_dir) if args.model_dir else discover_model_dir(DEFAULT_MODELS_DIR)
    backend = detect_backend(model_dir, args.backend)
    clips_dir = _project_path(args.clips_dir)
    output = _project_path(args.output)
    preview_dir = _project_path(args.preview_dir)
    prompts = normalize_prompts(args.prompt)
    device = resolve_device(args.device)

    if backend == "locateanything":
        worker = LocateAnythingWorker(model_dir, device, args.dtype)
    elif backend == "grounding-dino":
        worker = GroundingDinoWorker(
            model_dir,
            device,
            args.dtype,
            args.box_threshold,
            args.text_threshold,
        )
    else:
        raise ValueError(f"Unsupported backend: {backend}")

    clip_paths = list_video_files(clips_dir, recursive=not args.no_recursive)
    if args.limit:
        clip_paths = clip_paths[: args.limit]
    if not clip_paths:
        raise FileNotFoundError(f"No video clips found under {clips_dir}")

    output.parent.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    clips = []
    print(f"Model: {model_dir}")
    print(f"Backend: {backend}, device: {device}, dtype: {args.dtype}")
    print(f"Prompts: {', '.join(prompts)}")
    print(f"Clips: {len(clip_paths)}")

    for clip_number, clip_path in enumerate(clip_paths, start=1):
        clip_started = time.perf_counter()
        samples, video_meta = sample_video_frames(clip_path, args.sample_frames)
        frame_results = []
        print(f"[{clip_number}/{len(clip_paths)}] {clip_path.relative_to(PROJECT_ROOT)}")

        for frame_number, sample in enumerate(samples, start=1):
            frame_started = time.perf_counter()
            if backend == "locateanything":
                result = worker.detect(
                    sample.image,
                    prompts,
                    generation_mode=args.generation_mode,
                    max_new_tokens=args.max_new_tokens,
                    temperature=args.temperature,
                    verbose=args.model_verbose,
                    combined_prompts=args.locateanything_combined_prompts,
                )
            else:
                result = worker.detect(sample.image, prompts)

            width, height = sample.image.size
            detections = [clamp_box(det, width, height) for det in result["boxes"]]
            frame_elapsed = time.perf_counter() - frame_started
            preview_name = (
                f"{clip_path.stem}_f{sample.frame_index:06d}"
                f"_{frame_number:02d}.jpg"
            )
            if detections or args.save_empty_preview:
                draw_preview(
                    sample.image,
                    detections,
                    f"{clip_path.name} @ {sample.timestamp_sec:.2f}s",
                    preview_dir / preview_name,
                )

            frame_results.append(
                {
                    "frame_index": sample.frame_index,
                    "timestamp_sec": sample.timestamp_sec,
                    "elapsed_sec": frame_elapsed,
                    "preview": str((preview_dir / preview_name).relative_to(PROJECT_ROOT))
                    if detections or args.save_empty_preview
                    else None,
                    "detections": detections,
                    "raw_answer": result.get("answer") if args.include_raw_answer else None,
                }
            )

        summary = summarize_clip(frame_results)
        candidates, behavior_features = behavior_candidates(frame_results, motion_profile(samples, frame_results))
        best_candidate = candidates[0] if candidates else {
            "label": "unknown",
            "label_cn": BEHAVIOR_LABEL_CN["unknown"],
            "confidence": 0.0,
        }
        clips.append(
            {
                "clip_path": str(clip_path.relative_to(PROJECT_ROOT)),
                "video_meta": video_meta,
                "elapsed_sec": time.perf_counter() - clip_started,
                **summary,
                "auto_label": best_candidate["label"],
                "label_cn": best_candidate["label_cn"],
                "confidence": best_candidate["confidence"],
                "candidate_labels": [candidate["label"] for candidate in candidates],
                "behavior_candidates": candidates,
                "behavior_features": behavior_features,
                "frames": frame_results,
            }
        )

    result = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "model_dir": str(model_dir),
        "backend": backend,
        "device": device,
        "dtype": args.dtype,
        "prompts": prompts,
        "sample_frames": args.sample_frames,
        "elapsed_sec": time.perf_counter() - started,
        "clip_count": len(clips),
        "detected_clip_count": sum(1 for clip in clips if clip["has_reptile"]),
        "clips": clips,
    }

    output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nWrote JSON: {output}")
    print(f"Wrote previews: {preview_dir}")
    print(f"Detected clips: {result['detected_clip_count']}/{result['clip_count']}")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sample video frames and run a locator model for quick visual QA."
    )
    parser.add_argument("--clips-dir", default="data/events", help="Video file or directory to scan")
    parser.add_argument("--model-dir", default="", help="Local model directory; auto-detects models/* when omitted")
    parser.add_argument(
        "--backend",
        default="auto",
        choices=["auto", "locateanything", "grounding-dino"],
        help="Model backend",
    )
    parser.add_argument("--prompt", action="append", default=[], help="Object prompt(s), comma-separated or repeated")
    parser.add_argument("--limit", type=int, default=20, help="Max clips to process")
    parser.add_argument("--sample-frames", type=int, default=3, help="Frames to sample per clip")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="JSON output path")
    parser.add_argument("--preview-dir", default=str(DEFAULT_PREVIEW_DIR), help="Annotated preview image directory")
    parser.add_argument("--device", default="auto", help="auto, cuda, cuda:0, or cpu")
    parser.add_argument("--dtype", default="auto", help="auto, fp16, bf16, or fp32")
    parser.add_argument("--no-recursive", action="store_true", help="Only scan direct children of --clips-dir")
    parser.add_argument("--save-empty-preview", action="store_true", help="Save preview frames even with no boxes")
    parser.add_argument("--include-raw-answer", action="store_true", help="Store raw model text in JSON")

    parser.add_argument("--box-threshold", type=float, default=0.25, help="GroundingDINO box threshold")
    parser.add_argument("--text-threshold", type=float, default=0.25, help="GroundingDINO text threshold")

    parser.add_argument(
        "--generation-mode",
        default="hybrid",
        choices=["fast", "slow", "hybrid"],
        help="LocateAnything generation mode",
    )
    parser.add_argument("--max-new-tokens", type=int, default=2048, help="LocateAnything generation budget")
    parser.add_argument("--temperature", type=float, default=0.0, help="LocateAnything sampling temperature")
    parser.add_argument("--model-verbose", action="store_true", help="Pass verbose=True into LocateAnything generate")
    parser.add_argument(
        "--locateanything-combined-prompts",
        action="store_true",
        help="Run LocateAnything once with all prompts. Faster, but boxes use a generic label.",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        run(args)
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
