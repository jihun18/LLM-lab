from types import SimpleNamespace
import pytest
import psutil
from core.memory_sampling import summarize, ProcessScopes, MeasurementError, scope_summaries
from memory_benchmark import capture, validate_protocol, request_generation
import json
from pathlib import Path

def points(values, times=None):
    return [{"time":t,"rss_bytes":v} for t,v in zip(times or range(len(values)),values)]

def test_irregular_samples_use_left_held_time_weighted_average():
    r = summarize(points([100,400,900],[0,1,4]))
    assert r["time_weighted_mean_bytes"] == 325
    assert r["sampled_min_bytes"] == 100 and r["sampled_max_bytes"] == 900
    assert r["sampling_delayed"]

def test_zero_rss_is_valid_not_missing():
    assert summarize(points([0,0]))["valid"]

@pytest.mark.parametrize("samples", [[],points([1]),points([1,None]),points([-1,2]),points([True,2]),
    points([1,2],[0,0]),points([1,2],[1,0]),points([1,2],[0,float('nan')]),points([1.5,2])])
def test_missing_or_invalid_values_do_not_become_zero(samples):
    r = summarize(samples)
    assert not r["valid"] and "time_weighted_mean_bytes" not in r

def test_error_invalidates_whole_scope_summary():
    s = points([10,20]); s[1]["error"]="AccessDenied"
    assert not summarize(s)["valid"]

class FakeProcess:
    def __init__(self,pid,created,rss):
        self.pid=pid; self.created=created; self.rss=rss; self.descendants=[]; self.denied=False
    def create_time(self): return self.created
    def children(self,recursive): return self.descendants
    def memory_info(self):
        if self.denied: raise psutil.AccessDenied(self.pid)
        return SimpleNamespace(rss=self.rss)

def fixture():
    procs={i:FakeProcess(i,10+i,100*i) for i in (1,2,3,4)}
    procs[2].descendants=[procs[3]]
    return procs

def test_service_runner_web_are_separate_not_double_counted():
    p=fixture(); p[3].descendants=[p[4]]; p[2].descendants=[p[3],p[4]]
    r=ProcessScopes(1,2,3,p.__getitem__).snapshot()
    assert r["scopes"]["service"]["rss_bytes"] == 200
    assert r["scopes"]["runner"]["rss_bytes"] == 700
    assert r["scopes"]["web"]["rss_bytes"] == 100

@pytest.mark.parametrize("kind", ["same","overlap","missing_runner","unknown_service_child"])
def test_ambiguous_scope_is_rejected(kind):
    p=fixture(); ids=(1,2,3)
    if kind=="same": ids=(1,2,2)
    if kind=="overlap": p[1].descendants=[p[3]]
    if kind=="missing_runner": p[2].descendants=[]
    if kind=="unknown_service_child": p[2].descendants.append(p[4])
    with pytest.raises(MeasurementError): ProcessScopes(*ids,p.__getitem__)

@pytest.mark.parametrize("kind", ["reused","denied"])
def test_read_error_or_pid_reuse_yields_null_and_error(kind):
    p=fixture(); roots=ProcessScopes(1,2,3,p.__getitem__)
    if kind=="reused": p[3].created+=1
    else: p[1].denied=True
    r=roots.snapshot()
    assert r["error"]
    assert all(v["rss_bytes"] is None for v in r["scopes"].values())

def test_capture_preserves_action_failure_and_samples():
    p=fixture(); roots=ProcessScopes(1,2,3,p.__getitem__)
    def fail(): raise ValueError("request failed")
    r=capture(roots,0.01,fail)
    assert not r["valid"] and "ValueError" in r["outcome"]["error"]
    assert len(r["samples"])>=2

def test_partial_raw_reads_are_retained_but_not_used_as_valid_statistics():
    p=fixture(); roots=ProcessScopes(1,2,3,p.__getitem__); p[2].denied=True
    r=roots.snapshot()
    assert r["scopes"]["web"]["rss_bytes"]==100
    assert r["scopes"]["service"]["rss_bytes"] is None
    assert r["error"]
    assert not scope_summaries([r,r])["web"]["valid"]

def test_capture_endpoint_and_response_are_retained():
    p=fixture(); roots=ProcessScopes(1,2,3,p.__getitem__)
    r=capture(roots,0.01,lambda:{"eval_count":10})
    assert r["valid"]
    assert r["outcome"]["action_start"] <= r["outcome"]["action_end"]
    assert r["summary"]["web"]["sampled_max_bytes"]==100

def test_frozen_protocol_is_valid_and_modified_scope_rejected():
    p=json.loads((Path(__file__).resolve().parents[1]/"memory_measurement_protocol.json").read_text(encoding="utf-8"))
    validate_protocol(p)
    p["request"]["rag"]=True
    with pytest.raises(MeasurementError): validate_protocol(p)

@pytest.mark.parametrize("data", [{"answer":"","eval_count":10,"model":"qwen3:1.7b"},
    {"answer":"copy","eval_count":0,"model":"qwen3:1.7b"},
    {"answer":"ok","eval_count":10,"model":"other"}])
def test_non_generation_is_not_a_valid_measurement(data):
    class Client:
        def post(self,path,json):
            return SimpleNamespace(raise_for_status=lambda:None,json=lambda:data)
    p={"model":"qwen3:1.7b","request":{"prompt":"question","system":"system"}}
    with pytest.raises(MeasurementError): request_generation(Client(),p)
