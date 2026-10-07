"""Frozen boundary evaluation. No production or Wiki changes."""
import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from time import monotonic
from core.knowledge_base import KnowledgeBase, SearchResult
from core.ollama_client import OllamaClient
from core.rag_service import rag_response
from compound_holdout import OfflineClient, GenerationNeeded, FixtureKnowledge, score, fingerprint

ROOT = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--case-ids", nargs="+")
    parser.add_argument("--cases-file", default="edge_holdout_cases.json")
    args = parser.parse_args()
    path = (ROOT / args.cases_file).resolve()
    package = json.loads(path.read_text(encoding="utf-8"))
    cases = package["cases"]
    if args.case_ids:
        unknown = set(args.case_ids) - {c["id"] for c in cases}
        if unknown:
            parser.error("unknown case: " + ",".join(sorted(unknown)))
        cases = [c for c in cases if c["id"] in args.case_ids]
    files = sorted((ROOT / "core").glob("*.py")) + sorted((ROOT / "wiki").rglob("*.md"))
    before = fingerprint(files)
    case_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    kb = KnowledgeBase(ROOT / "wiki")
    kb.reindex()
    client = OllamaClient(timeout=90) if args.live else OfflineClient()
    rows = []
    for case in cases:
        knowledge = kb if case["scope"] == "wiki" else FixtureKnowledge([
            SearchResult(i["source"], i["heading"], i["text"], 1)
            for name in case["fixtures"] for i in package["fixtures"][name]])
        start = monotonic()
        try:
            response = rag_response(case["question"], "qwen3:1.7b", "Wiki 근거만 사용하고 간결하고 정확한 한국어로 답하세요.", 3, knowledge, client)
            scored = score(case, response)
            # Safe rejection does not count as fulfilling a role/memory request.
            scored["checks"]["not_blocked"] = response.get("answer_status") != "blocked" or case.get("expected_status") == "blocked"
            scored["status"] = "pass" if all(scored["checks"].values()) else "fail"
            row = {"id":case["id"],"scope":case["scope"],"question":case["question"],**scored,"response":response}
        except GenerationNeeded as exc:
            row = {"id":case["id"],"scope":case["scope"],"status":"pending_generation","reason":str(exc)}
        except Exception as exc:
            row = {"id":case["id"],"scope":case["scope"],"status":"error","reason":str(exc)}
        row["wall_seconds"] = round(monotonic()-start,3)
        rows.append(row)
        print(f"{case['id']}: {row['status']} ({row['wall_seconds']}s)",flush=True)
    after = fingerprint(files)
    report = {"protocol":{"date":"2026-10-07","cases_file":path.name,"case_sha256":case_hash,"production_wiki_sha256":before,"unchanged_after_run":before==after and case_hash==hashlib.sha256(path.read_bytes()).hexdigest(),"mode":"live_if_needed" if args.live else "offline","model":"qwen3:1.7b","search_mode":"bm25","top_k":3,"limits":"Internal boundary checks, not external accuracy. Fixtures bypass retrieval. Automatic substring checks require semantic review."},"results":rows}
    output = ROOT / "benchmark-results" / f"edge-holdout-{datetime.now():%Y%m%d-%H%M%S-%f}.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"Report: {output}; production/wiki/cases unchanged: {report['protocol']['unchanged_after_run']}",flush=True)

if __name__ == "__main__":
    main()
