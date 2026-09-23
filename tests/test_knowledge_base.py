from pathlib import Path

from core.knowledge_base import KnowledgeBase, build_grounded_prompt, tokenize


def test_markdown_index_and_search(tmp_path: Path):
    (tmp_path / "system.md").write_text(
        "# 시스템 사양\n\nCPU는 Intel i3-7100이고 RAM은 8GB입니다.\n\n"
        "## 모델\n\n기본 모델은 qwen3:1.7b입니다.",
        encoding="utf-8",
    )
    knowledge = KnowledgeBase(tmp_path)
    status = knowledge.reindex()
    results = knowledge.search("CPU와 RAM 사양", top_k=2)

    assert status["files_indexed"] == 1
    assert status["chunks_indexed"] == 2
    assert results[0].heading == "시스템 사양"
    assert "8GB" in results[0].text
    prompt = build_grounded_prompt("RAM은?", results)
    assert "[근거 1:" in prompt
    assert "[출처: system.md#시스템 사양]" in prompt
    assert "[출처: 파일명#제목]" not in prompt


def test_search_without_match_returns_empty(tmp_path: Path):
    (tmp_path / "note.md").write_text("# 사과\n\n빨간 과일", encoding="utf-8")
    knowledge = KnowledgeBase(tmp_path)
    knowledge.reindex()
    assert knowledge.search("양자컴퓨터") == []
    assert tokenize("FastAPI와 로컬 AI") == ["fastapi", "로컬", "ai"]


def test_korean_particles_share_a_search_term(tmp_path: Path):
    (tmp_path / "model.md").write_text(
        "# 7B를 PrivAI 기본 모델로 사용하지 않는 이유\n\n"
        "7B 모델은 평균 응답시간이 길어 기본 모델로 사용하지 않는다.",
        encoding="utf-8",
    )
    (tmp_path / "noise.md").write_text(
        "# 로컬 RAG\n\nWiki 근거와 사용자 질문을 연결한다.",
        encoding="utf-8",
    )
    knowledge = KnowledgeBase(tmp_path)
    knowledge.reindex()

    results = knowledge.search(
        "7B 모델을 PrivAI 기본 모델로 사용하지 않는 이유를 근거와 함께 설명해줘."
    )

    assert results[0].source == "model.md"
    assert "모델" in tokenize("모델을 모델로 모델은")


def test_code_block_examples_are_not_indexed(tmp_path: Path):
    (tmp_path / "guide.md").write_text(
        "# 사용법\n\n예시 질문\n\n```text\n비밀테스트검색어\n```",
        encoding="utf-8",
    )
    knowledge = KnowledgeBase(tmp_path)
    knowledge.reindex()
    assert knowledge.search("비밀테스트검색어") == []


def test_low_relative_score_results_are_pruned(tmp_path: Path):
    (tmp_path / "answer.md").write_text(
        "# 청년 AI 지원금 신청 마감일\n\n청년 AI 지원금 신청 마감일은 9월 30일입니다.",
        encoding="utf-8",
    )
    (tmp_path / "noise.md").write_text(
        "# 일반 지원\n\n이 문서는 일반적인 지원 내용을 설명합니다.", encoding="utf-8"
    )
    knowledge = KnowledgeBase(tmp_path)
    knowledge.reindex()
    results = knowledge.search("청년 AI 지원금 신청 마감일", top_k=5)
    assert [result.source for result in results] == ["answer.md"]
