#!/usr/bin/env python3
"""
HuggingFace 模型下载脚本 —— 下载爬宠检测与行为识别所需的预训练模型。

这些模型可以：
  A) 本地推理：用 transformers 加载，GPU/CPU 本地跑
  B) 远程 API：上传到 HuggingFace Inference Endpoints 或其他模型服务调用
  C) 仅下载权重：用于后续在自己代码中加载

脚本依赖（独立于项目主依赖，按需安装）:
    uv pip install huggingface_hub transformers torch

模型列表:
    grounding-dino-tiny  — 零样本物体检测（用文字描述定位爬宠，如 "reptile", "snake", "lizard"）
    videomae-base         — 视频行为分类预训练模型（用于后续行为识别微调）

用法:
    # 列出可用模型
    python download_models.py --list

    # 预览要下载的内容
    python download_models.py --dry-run

    # 下载所有模型
    python download_models.py

    # 下载指定模型
    python download_models.py --model grounding-dino-tiny

    # 指定下载目录
    python download_models.py --models-dir /path/to/models
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODELS_DIR = PROJECT_ROOT / "models"


# ============================================================
# 模型注册表
# ============================================================

MODEL_REGISTRY = {
    "grounding-dino-tiny": {
        "repo_id": "IDEA-Research/grounding-dino-tiny",
        "description": "零样本物体检测 — 用文字提示定位爬宠位置（无需微调）",
        "size_estimate": "~700MB",
        "task": "object-detection",
        "remote_api": "https://huggingface.co/IDEA-Research/grounding-dino-tiny",
    },
    "videomae-base": {
        "repo_id": "MCG-NJU/videomae-base-finetuned-kinetics",
        "description": "视频行为分类 (VideoMAE) — Kinetics-400 预训练，可微调用于爬宠行为识别",
        "size_estimate": "~400MB",
        "task": "video-classification",
        "remote_api": "https://huggingface.co/MCG-NJU/videomae-base-finetuned-kinetics",
    },
}


def check_dependencies() -> bool:
    """检查脚本自身依赖（huggingface_hub），不包含 torch/transformers。"""
    missing = []
    for lib in ["huggingface_hub"]:
        try:
            __import__(lib)
        except ImportError:
            missing.append(lib)
    if missing:
        print(f"❌ 缺少下载工具: {', '.join(missing)}")
        print(f"   请运行: uv pip install {' '.join(missing)}")
        print(f"   注: torch/transformers 仅在本地推理时需要，下载模型不需要")
        return False
    return True


def list_models():
    """列出所有可用模型。"""
    print(f"\n{'='*60}")
    print(f"  可用模型列表")
    print(f"{'='*60}\n")
    for name, info in MODEL_REGISTRY.items():
        print(f"  📦 {name}")
        print(f"      HuggingFace: {info['repo_id']}")
        print(f"      用途: {info['description']}")
        print(f"      大小: {info['size_estimate']}")
        print(f"      任务: {info['task']}")
        print()


def download_model(name: str, info: dict, models_dir: Path, force: bool = False) -> bool:
    """
    下载单个模型到本地目录。

    Args:
        name: 模型简称
        info: 模型注册信息
        models_dir: 保存目录
        force: 是否强制重新下载

    Returns:
        是否成功
    """
    from huggingface_hub import snapshot_download

    local_dir = models_dir / name
    repo_id = info["repo_id"]

    # 检查是否已下载
    if local_dir.exists() and any(local_dir.iterdir()) and not force:
        model_files = (
            list(local_dir.glob("*.bin"))
            + list(local_dir.glob("*.safetensors"))
            + list(local_dir.glob("*.pt"))
        )
        if model_files:
            total_size = sum(
                f.stat().st_size for f in local_dir.rglob("*") if f.is_file()
            )
            size_mb = total_size / (1024 * 1024)
            print(f"  ✅ 已存在 ({size_mb:.0f}MB)，跳过。使用 --force 强制重新下载。")
            return True

    local_dir.mkdir(parents=True, exist_ok=True)

    print(f"  📥 下载: {repo_id}")
    print(f"  📁 保存到: {local_dir}")
    print(f"  📏 预计大小: {info['size_estimate']}")

    try:
        snapshot_download(
            repo_id=repo_id,
            local_dir=str(local_dir),
            local_dir_use_symlinks=False,
            resume_download=True,
            ignore_patterns=["*.msgpack", "*.h5", "*.pb", "*.ckpt"],
        )
        print(f"  ✅ 下载完成: {name}\n")
        return True

    except Exception as e:
        print(f"  ❌ 下载失败: {e}")
        print(f"  提示: 可以重试运行，支持断点续传。\n")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="下载 ReptiReplay 所需的 HuggingFace 预训练模型"
    )
    parser.add_argument(
        "--model", "-m", type=str, default=None,
        help="下载指定模型（不指定则下载全部）",
    )
    parser.add_argument(
        "--models-dir", type=str,
        default=str(DEFAULT_MODELS_DIR),
        help=f"模型保存目录（默认: {DEFAULT_MODELS_DIR}）",
    )
    parser.add_argument(
        "--list", "-l", action="store_true",
        help="列出所有可用模型",
    )
    parser.add_argument(
        "--force", "-f", action="store_true",
        help="强制重新下载（覆盖已有文件）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="仅显示将要下载的内容，不实际下载",
    )
    args = parser.parse_args()

    # 列出模型
    if args.list:
        list_models()
        return

    # 仅在真正下载时检查依赖
    if not args.dry_run and not check_dependencies():
        sys.exit(1)

    models_dir = Path(args.models_dir)

    # 确定要下载的模型
    if args.model:
        if args.model not in MODEL_REGISTRY:
            print(f"❌ 未知模型: {args.model}")
            print(f"   可用模型: {', '.join(MODEL_REGISTRY.keys())}")
            print(f"   使用 --list 查看详情")
            sys.exit(1)
        targets = {args.model: MODEL_REGISTRY[args.model]}
    else:
        targets = MODEL_REGISTRY

    print(f"\n{'='*60}")
    print(f"  ReptiReplay 模型下载")
    print(f"{'='*60}")
    print(f"  目标: {len(targets)} 个模型")
    print(f"  目录: {models_dir}")
    if args.dry_run:
        print(f"  模式: 预览 (--dry-run)")
    print()

    if args.dry_run:
        for name, info in targets.items():
            print(f"  📦 {name} → {info['repo_id']} ({info['size_estimate']})")
            print(f"     API: {info.get('remote_api', 'N/A')}")
        print("\n运行 `python download_models.py` 开始下载。")
        return

    # 下载
    success = 0
    failed = 0
    for name, info in targets.items():
        print(f"[{success + failed + 1}/{len(targets)}] {name}")
        if download_model(name, info, models_dir, args.force):
            success += 1
        else:
            failed += 1

    # 汇总
    print(f"{'='*60}")
    print(f"  下载完成: {success} 成功, {failed} 失败")
    print(f"  模型目录: {models_dir}")
    print()
    print(f"  使用方式:")
    print(f"  ──────────────────────────────────────────────")
    print(f"  A) 本地推理 (需要 torch + transformers):")
    print(f"     from transformers import AutoModelForObjectDetection")
    print(f"     model = AutoModelForObjectDetection.from_pretrained(")
    print(f"         '{models_dir}/grounding-dino-tiny'")
    print(f"     )")
    print()
    print(f"  B) 远程 API (无需本地 GPU):")
    print(f"     将模型部署到 HuggingFace Inference Endpoints")
    print(f"     或其他模型服务 (Triton/vLLM)，通过 HTTP/gRPC 调用")
    print()
    print(f"  C) 加载到项目代码:")
    print(f"     from backend.app.services.reptile_detector import ReptileDetector")
    print(f"     detector = ReptileDetector(model_dir='{models_dir}/grounding-dino-tiny')")
    print(f"  ──────────────────────────────────────────────")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
