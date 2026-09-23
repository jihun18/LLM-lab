from __future__ import annotations

from typing import Any


MODEL_MODE_PROFILES = (
    {
        "model": "qwen3:1.7b",
        "mode": "fast",
        "label": "빠른 모드",
        "description": "기본 데모 · 평균 7.959초 · 13.99 token/s",
        "recommended": True,
    },
    {
        "model": "qwen3:4b-instruct",
        "mode": "balanced",
        "label": "균형 모드",
        "description": "속도와 품질 비교 · 평균 16.034초 · 6.80 token/s",
        "recommended": False,
    },
    {
        "model": "qwen2.5:7b-instruct",
        "mode": "precision",
        "label": "정밀 모드",
        "description": "시간이 허용되는 작업 · 평균 28.539초 · 3.80 token/s",
        "recommended": False,
    },
)


def build_model_modes(installed_models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    installed_names = [str(item.get("name", "")) for item in installed_models]
    profiles = {profile["model"]: profile for profile in MODEL_MODE_PROFILES}
    modes = [dict(profile) for profile in MODEL_MODE_PROFILES if profile["model"] in installed_names]
    modes.extend(
        {
            "model": name,
            "mode": "custom",
            "label": "추가 모델",
            "description": "Ollama에 설치된 모델 · 측정된 권장값 없음",
            "recommended": False,
        }
        for name in installed_names
        if name and name not in profiles
    )
    return modes
