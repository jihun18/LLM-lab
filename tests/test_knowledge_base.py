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
    assert "[근거 1:" in build_grounded_prompt("RAM은?", results)


def test_search_without_match_returns_empty(tmp_path: Path):
    (tmp_path / "note.md").write_text("# 사과\n\n빨간 과일", encoding="utf-8")
    knowledge = KnowledgeBase(tmp_path)
    knowledge.reindex()
    assert knowledge.search("양자컴퓨터") == []
    assert tokenize("FastAPI와 로컬 AI") == ["fastapi", "와", "로컬", "ai"]


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
