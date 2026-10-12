"""Explicit local runtime diagnostic: no model loading or benchmark answering."""

import importlib
import json
import sys


def probe() -> dict:
    torch = importlib.import_module("torch")
    cuda = torch.cuda.is_available()
    return {
        "available": True,
        "torch_version": torch.__version__,
        "cuda_build": torch.version.cuda,
        "cuda_available": cuda,
        "devices": [
            {
                "name": torch.cuda.get_device_name(i),
                "total_vram_bytes": torch.cuda.get_device_properties(i).total_memory,
            }
            for i in range(torch.cuda.device_count() if cuda else 0)
        ],
        "reason": "CUDAランタイム利用可能（モデル推論は未検証）"
        if cuda
        else "CPU利用可能。CUDAは利用できません",
        "live_model_verified": False,
    }


def main():
    try:
        print(json.dumps(probe(), ensure_ascii=True))
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
