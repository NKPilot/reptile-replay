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
DEFAULT_PROMPTS = ["reptile", "snake", "lizard", "gecko", "turtle"]


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
    ) -> dict[str, Any]:
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
    detected_frames = sum(1 for frame in frame_results if frame["detections"])
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
        clips.append(
            {
                "clip_path": str(clip_path.relative_to(PROJECT_ROOT)),
                "video_meta": video_meta,
                "elapsed_sec": time.perf_counter() - clip_started,
                **summary,
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
