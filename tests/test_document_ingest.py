from pathlib import Path

import pytest

from core.document_ingest import DocumentIngestError, DocumentIngestor


def test_ingests_utf8_text_as_wiki_markdown(tmp_path: Path):
    ingestor = DocumentIngestor(tmp_path)
    result = ingestor.ingest("지원 정책.txt", "청년 지원금은 월 10만원입니다.".encode())
    target = tmp_path / result["wiki_file"]
    assert target.exists()
    assert "청년 지원금" in target.read_text(encoding="utf-8-sig")
    assert result["original_name"] == "지원 정책.txt"


def test_same_document_is_idempotent(tmp_path: Path):
    ingestor = DocumentIngestor(tmp_path)
    first = ingestor.ingest("note.md", b"# Note\n\nLocal fact")
    second = ingestor.ingest("note.md", b"# Note\n\nLocal fact")
    assert first["wiki_file"] == second["wiki_file"]
    assert len(ingestor.list_documents()) == 1


@pytest.mark.parametrize("filename", ["../secret.txt", "folder/note.md", "malware.exe"])
def test_rejects_unsafe_or_unsupported_names(tmp_path: Path, filename: str):
    with pytest.raises(DocumentIngestError):
        DocumentIngestor(tmp_path).ingest(filename, b"content")


def test_rejects_oversized_file(tmp_path: Path):
    with pytest.raises(DocumentIngestError, match="최대"):
        DocumentIngestor(tmp_path, max_bytes=3).ingest("note.txt", b"1234")


def test_pdf_extraction_path(monkeypatch, tmp_path: Path):
    ingestor = DocumentIngestor(tmp_path)
    monkeypatch.setattr(ingestor, "_extract_pdf", lambda data: ("PDF에서 추출한 내용", 2))
    result = ingestor.ingest("guide.pdf", b"fake-pdf")
    text = (tmp_path / result["wiki_file"]).read_text(encoding="utf-8-sig")
    assert "PDF에서 추출한 내용" in text
    assert result["pages"] == 2

