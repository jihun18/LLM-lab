import json
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from core.config import settings
from core.document_ingest import DocumentIngestError, DocumentIngestor, MAX_UPLOAD_BYTES
from core.grounding import deterministic_metric_answer, verify_grounded_answer
from core.knowledge_base import KnowledgeBase, build_grounded_prompt
from core.ollama_client import OllamaClient, OllamaError
from core.schemas import ChatRequest, RagRequest, SummarizeRequest


app = FastAPI(
    title="privAI Local LLM API",
    description="Ollama 기반 저사양 PC용 로컬 LLM REST API",
    version="0.1.0",
)
client = OllamaClient()
ROOT = Path(__file__).resolve().parent
knowledge = KnowledgeBase(ROOT / "wiki")
knowledge.reindex()
documents = DocumentIngestor(ROOT / "wiki")


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(ROOT / "privAI.html")


@app.get("/health")
def health() -> dict:
    try:
        return {**client.health(), "framework": "FastAPI"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/models")
def models() -> dict:
    try:
        return {"models": client.list_models(), "default": settings.default_model}
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/chat")
def chat(request: ChatRequest) -> dict:
    try:
        return client.chat(request.prompt, request.model, request.system)
    except OllamaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    def generate():
        try:
            for chunk in client.stream_chat(request.prompt, request.model, request.system):
                yield json.dumps(chunk, ensure_ascii=False) + "\n"
        except OllamaError as exc:
            yield json.dumps({"error": str(exc)}, ensure_ascii=False) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.get("/knowledge/status")
def knowledge_status() -> dict:
    return knowledge.status()


@app.post("/knowledge/reindex")
def knowledge_reindex() -> dict:
    return knowledge.reindex()


@app.get("/documents")
def document_list() -> dict:
    return {"documents": documents.list_documents()}


@app.post("/documents/upload")
async def document_upload(request: Request) -> dict:
    encoded_filename = request.headers.get("x-filename", "")
    filename = unquote(encoded_filename)
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="파일은 최대 5MB까지 업로드할 수 있습니다.")
    data = await request.body()
    try:
        document = documents.ingest(filename, data)
    except DocumentIngestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"document": document, "knowledge": knowledge.reindex()}


def source_payload(results) -> list[dict]:
    return [
        {
            "source": result.source,
            "heading": result.heading,
            "score": result.score,
            "excerpt": result.text[:240],
        }
        for result in results
    ]


def grounded_response(request: RagRequest, results) -> dict:
    deterministic = deterministic_metric_answer(request.prompt, results)
    if deterministic:
        answer, verification = deterministic
        return {
            "model": "deterministic-table",
            "answer": answer,
            "elapsed_seconds": 0,
            "tokens_per_second": None,
            "eval_count": 0,
            "verification": verification,
        }

    grounded_prompt = build_grounded_prompt(request.prompt, results)
    response = client.chat(grounded_prompt, request.model, request.system)
    verification = verify_grounded_answer(request.prompt, response["answer"], results)
    return {**response, "verification": verification}


@app.post("/rag/chat")
def rag_chat(request: RagRequest) -> dict:
    results = knowledge.search(request.prompt, request.top_k)
    sources = source_payload(results)
    if not results:
        return {
            "model": request.model,
            "answer": "Wiki에서 관련 근거를 찾지 못했습니다.",
            "sources": [],
            "elapsed_seconds": 0,
            "tokens_per_second": None,
            "eval_count": 0,
        }
    try:
        response = grounded_response(request, results)
        return {**response, "sources": sources}
    except OllamaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/rag/chat/stream")
def rag_chat_stream(request: RagRequest) -> StreamingResponse:
    results = knowledge.search(request.prompt, request.top_k)
    sources = source_payload(results)

    def generate():
        yield json.dumps({"sources": sources}, ensure_ascii=False) + "\n"
        if not results:
            yield json.dumps(
                {"done": False, "content": "Wiki에서 관련 근거를 찾지 못했습니다."},
                ensure_ascii=False,
            ) + "\n"
            yield json.dumps(
                {
                    "done": True,
                    "elapsed_seconds": 0,
                    "tokens_per_second": None,
                    "eval_count": 0,
                },
                ensure_ascii=False,
            ) + "\n"
            return
        try:
            response = grounded_response(request, results)
            yield json.dumps(
                {
                    "done": False,
                    "content": response["answer"],
                    "verification": response["verification"],
                },
                ensure_ascii=False,
            ) + "\n"
            yield json.dumps(
                {
                    "done": True,
                    "elapsed_seconds": response["elapsed_seconds"],
                    "tokens_per_second": response["tokens_per_second"],
                    "eval_count": response["eval_count"],
                    "verification": response["verification"],
                },
                ensure_ascii=False,
            ) + "\n"
        except OllamaError as exc:
            yield json.dumps({"error": str(exc)}, ensure_ascii=False) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.post("/summarize")
def summarize(request: SummarizeRequest) -> dict:
    prompt = (
        f"다음 글을 핵심 사실을 유지하면서 {request.max_sentences}문장 이내의 한국어로 "
        f"요약하세요. 요약문만 출력하세요.\n\n{request.text}"
    )
    try:
        return client.chat(prompt, request.model)
    except OllamaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
