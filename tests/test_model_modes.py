from core.model_modes import build_model_modes


def test_known_models_are_ordered_by_user_mode():
    modes = build_model_modes(
        [
            {"name": "qwen2.5:7b-instruct"},
            {"name": "qwen3:1.7b"},
            {"name": "qwen3:4b-instruct"},
        ]
    )
    assert [item["mode"] for item in modes] == ["fast", "balanced", "precision"]
    assert modes[0]["recommended"] is True


def test_unknown_installed_model_remains_selectable():
    modes = build_model_modes([{"name": "custom:latest"}])
    assert modes == [
        {
            "model": "custom:latest",
            "mode": "custom",
            "label": "추가 모델",
            "description": "Ollama에 설치된 모델 · 측정된 권장값 없음",
            "recommended": False,
        }
    ]
