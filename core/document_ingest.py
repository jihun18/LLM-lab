from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
import unicodedata


MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = {".md", ".txt", ".pdf"}


class DocumentIngestError(ValueError):
    pass


class DocumentIngestor:
    def __init__(self, wiki_root: Path, max_bytes: int = MAX_UPLOAD_BYTES) -> None:
        self.wiki_root = wiki_root.resolve()
        self.upload_root = self.wiki_root / "Uploads"
        self.max_bytes = max_bytes

    def _validated_filename(self, filename: str) -> tuple[str, str, str]:
        normalized = unicodedata.normalize("NFKC", filename).strip()
        if not normalized or normalized in {".", ".."}:
            raise DocumentIngestError("파일명이 없습니다.")
        if Path(normalized).name != normalized or "/" in normalized or "\\" in normalized:
            raise DocumentIngestError("폴더 경로가 포함된 파일명은 허용되지 않습니다.")
        extension = Path(normalized).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise DocumentIngestError("지원 형식은 .md, .txt, .pdf입니다.")
        stem = Path(normalized).stem
        safe_stem = re.sub(r"[^0-9A-Za-z가-힣._-]+", "-", stem).strip("-._")
        if not safe_stem:
            safe_stem = "document"
        return normalized, safe_stem[:80], extension

    def _decode_text(self, data: bytes) -> str:
        for encoding in ("utf-8-sig", "cp949"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise DocumentIngestError("텍스트 인코딩은 UTF-8 또는 CP949여야 합니다.")

    def _extract_pdf(self, data: bytes) -> tuple[str, int]:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise DocumentIngestError(
                "PDF 처리를 위해 'python -m pip install pypdf'를 실행하세요."
            ) from exc
        try:
            reader = PdfReader(BytesIO(data))
            if reader.is_encrypted and not reader.decrypt(""):
                raise DocumentIngestError("암호화된 PDF는 처리할 수 없습니다.")
            if len(reader.pages) > 100:
                raise DocumentIngestError("PDF는 최대 100페이지만 처리할 수 있습니다.")
            pages = []
            for number, page in enumerate(reader.pages, start=1):
                page_text = (page.extract_text() or "").strip()
                if page_text:
                    pages.append(f"## PDF {number}페이지\n\n{page_text}")
        except DocumentIngestError:
            raise
        except Exception as exc:
            raise DocumentIngestError(f"PDF를 읽을 수 없습니다: {exc}") from exc
        if not pages:
            raise DocumentIngestError(
                "PDF에서 텍스트를 찾지 못했습니다. 스캔 PDF는 OCR 단계가 필요합니다."
            )
        return "\n\n".join(pages), len(reader.pages)

    def ingest(self, filename: str, data: bytes) -> dict:
        original_name, safe_stem, extension = self._validated_filename(filename)
        if not data:
            raise DocumentIngestError("빈 파일은 업로드할 수 없습니다.")
        if len(data) > self.max_bytes:
            raise DocumentIngestError(
                f"파일은 최대 {self.max_bytes // 1024 // 1024}MB까지 업로드할 수 있습니다."
            )

        pages = None
        if extension == ".pdf":
            extracted, pages = self._extract_pdf(data)
        else:
            extracted = self._decode_text(data).strip()
            if not extracted:
                raise DocumentIngestError("문서에서 텍스트를 찾지 못했습니다.")

        digest = sha256(data).hexdigest()[:10]
        target_name = f"{safe_stem}-{digest}.md"
        self.upload_root.mkdir(parents=True, exist_ok=True)
        target = (self.upload_root / target_name).resolve()
        if self.upload_root.resolve() not in target.parents:
            raise DocumentIngestError("안전하지 않은 저장 경로입니다.")

        metadata = [
            f"# {safe_stem}",
            "",
            f"> 원본 파일: `{original_name}`  ",
            f"> 가져온 시각: {datetime.now():%Y-%m-%d %H:%M:%S}  ",
            f"> 원본 형식: {extension}",
        ]
        if pages is not None:
            metadata[-1] += f" · {pages}페이지"
        content = "\n".join(metadata) + "\n\n## 문서 내용\n\n" + extracted + "\n"
        target.write_text(content, encoding="utf-8-sig")
        return {
            "original_name": original_name,
            "wiki_file": target.relative_to(self.wiki_root).as_posix(),
            "bytes": len(data),
            "characters": len(extracted),
            "pages": pages,
            "sha256": sha256(data).hexdigest(),
        }

    def list_documents(self) -> list[dict]:
        if not self.upload_root.exists():
            return []
        return [
            {
                "wiki_file": path.relative_to(self.wiki_root).as_posix(),
                "bytes": path.stat().st_size,
                "modified_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(
                    timespec="seconds"
                ),
            }
            for path in sorted(self.upload_root.glob("*.md"))
            if path.is_file()
        ]

