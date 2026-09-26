"""Load MedGemma weights and run text generation."""

from __future__ import annotations

import logging
import os
import platform
import resource
import threading
import warnings
from pathlib import Path
from typing import Any

# Quiet HF / transformers before those imports run.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

logger = logging.getLogger("prototyping.medgemma_chat")


def quiet_ml_logging() -> None:
    warnings.filterwarnings("ignore", category=UserWarning, module="torch")
    logging.getLogger("transformers").setLevel(logging.ERROR)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("mcp").setLevel(logging.WARNING)
    try:
        from transformers.utils import logging as hf_logging

        hf_logging.set_verbosity_error()
        hf_logging.disable_progress_bar()
    except Exception:
        pass


def require_ml():
    quiet_ml_logging()
    try:
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor
    except ImportError as exc:
        raise SystemExit(
            "Missing ML dependencies. Install with:\n"
            "  uv sync --extra mcp --group medgemma-chat\n"
            f"({exc})"
        ) from exc
    return torch, AutoModelForImageTextToText, AutoProcessor


def resolve_device(requested: str, torch_mod) -> Any:
    if requested == "auto":
        if torch_mod.backends.mps.is_available():
            return torch_mod.device("mps")
        if torch_mod.cuda.is_available():
            return torch_mod.device("cuda")
        return torch_mod.device("cpu")
    if requested == "mps" and not torch_mod.backends.mps.is_available():
        raise ValueError("MPS requested but not available on this machine")
    if requested == "cuda" and not torch_mod.cuda.is_available():
        raise ValueError("CUDA requested but not available on this machine")
    return torch_mod.device(requested)


def _compute_dtype(device, torch_mod) -> Any:
    use_bf16 = device.type in {"mps", "cuda"} or (
        device.type == "cpu" and platform.machine() in {"arm64", "aarch64"}
    )
    return torch_mod.bfloat16 if use_bf16 else torch_mod.float32


def _process_memory_detail(device, torch_mod) -> str:
    if device.type == "mps":
        mem_gb = torch_mod.mps.driver_allocated_memory() / (1024**3)
        return f"MPS memory {mem_gb:.2f} GB"
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_gb = rss / (1024**3) if platform.system() == "Darwin" else rss / (1024**2)
    return f"RSS {rss_gb:.2f} GB"


def _bitsandbytes_4bit_config(device, torch_mod):
    try:
        from transformers import BitsAndBytesConfig
    except ImportError as exc:
        raise SystemExit(
            "bitsandbytes is required for 4-bit MedGemma load.\n"
            "  uv sync --extra mcp --group medgemma-chat\n"
            f"({exc})"
        ) from exc
    return BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=_compute_dtype(device, torch_mod),
        bnb_4bit_use_double_quant=True,
    )


def load_medgemma(model_dir: Path, device, torch_mod, AutoModel, AutoProcessor):
    """Load local MedGemma weights (HF layout) in NF4 4-bit via bitsandbytes."""
    model_dir = model_dir.expanduser().resolve()
    if not model_dir.is_dir():
        raise SystemExit(f"Model dir not found: {model_dir}")
    try:
        processor = AutoProcessor.from_pretrained(
            str(model_dir),
            local_files_only=True,
            backend="torchvision",
        )
    except TypeError:
        processor = AutoProcessor.from_pretrained(
            str(model_dir), local_files_only=True, use_fast=True
        )
    except ValueError as exc:
        raise SystemExit(
            f"{exc}\nInstall image-processor deps:  uv sync --group medgemma-chat"
        ) from exc
    quantization_config = _bitsandbytes_4bit_config(device, torch_mod)
    compute_dtype = _compute_dtype(device, torch_mod)
    try:
        model = AutoModel.from_pretrained(
            str(model_dir),
            quantization_config=quantization_config,
            device_map={"": str(device)},
            local_files_only=True,
        )
    except ImportError as exc:
        raise SystemExit(
            "4-bit load needs bitsandbytes (+ accelerate). Install with:\n"
            "  uv sync --extra mcp --group medgemma-chat\n"
            f"({exc})"
        ) from exc
    model.eval()
    logger.info(
        "model_load %s quant=nf4-4bit compute_dtype=%s %s",
        model_dir.name,
        compute_dtype,
        _process_memory_detail(device, torch_mod),
    )
    return model, processor


def text_message(role: str, text: str) -> dict[str, Any]:
    return {"role": role, "content": [{"type": "text", "text": text}]}


def multimodal_user_message(text: str, image: Any) -> dict[str, Any]:
    """User turn with one PIL image + text (MedGemma chat template)."""
    return {
        "role": "user",
        "content": [
            {"type": "image", "image": image},
            {"type": "text", "text": text},
        ],
    }


def append_assistant(messages: list[dict[str, Any]], text: str) -> str:
    messages.append(text_message("assistant", text))
    return text


class TurnAborted(Exception):
    """User cancelled the current MedGemma / MCP turn."""


def raise_if_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise TurnAborted()


def _stopping_criteria(cancel_event: threading.Event | None):
    if cancel_event is None:
        return None
    try:
        from transformers import StoppingCriteria, StoppingCriteriaList
    except Exception:
        return None

    class _CancelStop(StoppingCriteria):
        def __call__(self, input_ids, scores, **kwargs):  # noqa: ANN001
            return bool(cancel_event.is_set())

    return StoppingCriteriaList([_CancelStop()])


def _ensure_user_then_assistant(messages: list[dict[str, Any]]) -> None:
    if len(messages) < 2:
        return
    last = messages[-1].get("role")
    prev = messages[-2].get("role")
    if last == "user" and prev == "user":
        messages.insert(-1, text_message("assistant", "(continuing)"))


def _images_from_messages(messages: list[dict[str, Any]]) -> list[Any]:
    images: list[Any] = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") == "image":
                img = part.get("image")
                if img is not None:
                    images.append(img)
    return images


def generate_text(
    *,
    model,
    processor,
    device,
    torch_mod,
    messages: list[dict[str, Any]],
    max_new_tokens: int,
    cancel_event: threading.Event | None = None,
) -> str:
    raise_if_cancelled(cancel_event)
    _ensure_user_then_assistant(messages)
    chat = processor.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )
    images = _images_from_messages(messages)
    proc_kwargs: dict[str, Any] = {"text": chat, "return_tensors": "pt"}
    if images:
        proc_kwargs["images"] = images
    inputs = processor(**proc_kwargs).to(device)
    input_len = inputs["input_ids"].shape[1]
    gen_kwargs: dict[str, Any] = {
        "max_new_tokens": max_new_tokens,
        "do_sample": False,
    }
    stop = _stopping_criteria(cancel_event)
    if stop is not None:
        gen_kwargs["stopping_criteria"] = stop
    with torch_mod.no_grad():
        outputs = model.generate(**inputs, **gen_kwargs)
    raise_if_cancelled(cancel_event)
    return processor.decode(outputs[0][input_len:], skip_special_tokens=True).strip()


def generate_cxr_report(
    *,
    model,
    processor,
    device,
    torch_mod,
    image_path: Path,
    max_new_tokens: int = 512,
) -> str:
    """One-shot CXR report from a local image file (PNG/JPEG)."""
    from PIL import Image

    image = Image.open(image_path).convert("RGB")
    messages = [
        multimodal_user_message(
            "Write a concise chest radiograph report: findings, "
            "impression, and any acute abnormalities.",
            image,
        )
    ]
    return generate_text(
        model=model,
        processor=processor,
        device=device,
        torch_mod=torch_mod,
        messages=messages,
        max_new_tokens=max_new_tokens,
    )