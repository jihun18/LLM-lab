import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import memory_launch
from core.memory_sampling import MeasurementError
from memory_benchmark import SUPPORTED_MODELS, select_protocol, validate_protocol, request_generation
from test_memory_launch import model_client


def base_protocol():
    return json.loads((Path(__file__).resolve().parents[1] / "memory_measurement_protocol.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("model", SUPPORTED_MODELS)
def test_selection_does_not_mutate_base_or_change_request_options(model):
    base = base_protocol()
    before = copy.deepcopy(base)
    selected = select_protocol(base, model)
    assert base == before and selected["model"] == model
    for key in ("num_ctx", "num_predict", "temperature", "prompt", "system", "rag", "stream", "think"):
        assert selected["request"][key] == base["request"][key]
    if model == SUPPORTED_MODELS[0]: assert selected == base
    else: assert "no /no_think suffix" in selected["request"]["note"]


def test_unsupported_model_rejected():
    with pytest.raises(MeasurementError): select_protocol(base_protocol(), "unknown:7b")


@pytest.mark.parametrize("key,value", [("measured_requests", 1), ("sampling_interval_ms", 50),
                                       ("concurrent_requests", 2)])
def test_model_selection_never_weakens_protocol(key, value):
    base = base_protocol()
    base[key] = value
    with pytest.raises(MeasurementError): select_protocol(base, SUPPORTED_MODELS[1])


@pytest.mark.parametrize("model", SUPPORTED_MODELS[1:])
def test_selected_installed_model_loads_only_on_explicit_choice(model):
    client, calls = model_client([], model=model)
    with client: memory_launch.check_model(client, True, model)
    assert calls.count(("POST", "/api/generate")) == 1


@pytest.mark.parametrize("model", SUPPORTED_MODELS[1:])
def test_existing_17b_prevents_automatic_model_switch(model):
    client, calls = model_client([{"name": SUPPORTED_MODELS[0], "digest": "abc"}], model=model)
    with client, pytest.raises(MeasurementError): memory_launch.check_model(client, True, model)
    assert calls == [("GET", "/api/ps")]


@pytest.mark.parametrize("model", SUPPORTED_MODELS)
def test_generation_requires_selected_response_model(model):
    protocol = select_protocol(base_protocol(), model)
    class Client:
        def post(self, path, json):
            assert json["model"] == model
            return SimpleNamespace(raise_for_status=lambda: None,
                                   json=lambda: {"answer": "답변", "eval_count": 12, "model": model})
    assert request_generation(Client(), protocol)["model"] == model


@pytest.mark.parametrize("model", SUPPORTED_MODELS[1:])
def test_launcher_passes_selected_model_to_preparation_and_collector(monkeypatch, model):
    prepared, commands = [], []
    monkeypatch.setattr("sys.argv", ["memory_launch.py", "--model", model])
    monkeypatch.setattr(memory_launch.psutil, "net_connections", lambda **kw: [])
    monkeypatch.setattr(memory_launch, "identify_services", lambda _: (10, 20, 110, 120))
    monkeypatch.setattr(memory_launch, "check_model", lambda client, prepare, selected: prepared.append(selected))
    monkeypatch.setattr(memory_launch.psutil, "Process", lambda _: SimpleNamespace())
    monkeypatch.setattr(memory_launch, "runner_pid", lambda _: 30)
    def collect(cmd, **kw):
        commands.append(cmd)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(memory_launch.subprocess, "run", collect)
    assert memory_launch.main() == 0
    assert prepared == [model]
    assert commands[0][-2:] == ["--model", model]
