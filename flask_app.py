import json
from pathlib import Path
from urllib.parse import unquote

from flask import Flask, Response, jsonify, request, send_file

from core.config import settings
from core.document_ingest import DocumentIngestError, DocumentIngestor, MAX_UPLOAD_BYTES
from core.knowledge_base import KnowledgeBase
from core.ollama_client import OllamaClient, OllamaError
from core.rag_service import rag_response, rag_stream_events


app = Flask(__name__)
client = OllamaClient()
ROOT = Path(__file__).resolve().parent
knowledge = KnowledgeBase(ROOT / "wiki")
knowledge.reindex()
documents = DocumentIngestor(ROOT / "wiki")


@app.get("/")
def home():
    response = send_file(ROOT / "privAI.html")
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@app.get("/health")
def health():
    try:
        return jsonify(**client.health(), framework="Flask")
    except Exception as exc:
        return jsonify(error=str(exc)), 503


@app.get("/models")
def models():
    try:
        return jsonify(models=client.list_models(), default=settings.default_model)
    except OllamaError as exc:
        return jsonify(error=str(exc)), 503


@app.get("/knowledge/status")
def knowledge_status():
    return jsonify(knowledge.status())


@app.post("/knowledge/reindex")
def knowledge_reindex():
    return jsonify(knowledge.reindex())


@app.get("/documents")
def document_list():
    return jsonify(documents=documents.list_documents())


@app.post("/documents/upload")
def document_upload():
    filename = unquote(request.headers.get("x-filename", ""))
    content_length = request.content_length
    if content_length and content_length > MAX_UPLOAD_BYTES:
        return jsonify(detail="파일은 최대 5MB까지 업로드할 수 있습니다."), 413
    try:
        document = documents.ingest(filename, request.get_data())
    except DocumentIngestError as exc:
        return jsonify(detail=str(exc)), 400
    return jsonify(document=document, knowledge=knowledge.reindex())


def validated_chat_data():
    data = request.get_json(silent=True) or {}
    prompt = str(data.get("prompt", "")).strip()
    if not prompt:
        return None, (jsonify(error="prompt는 필수입니다."), 400)
    return {
        "prompt": prompt,
        "model": data.get("model") or settings.default_model,
        "system": data.get("system"),
    }, None


def validated_rag_data():
    data, error = validated_chat_data()
    if error:
        return None, error
    raw_top_k = (request.get_json(silent=True) or {}).get("top_k", 3)
    try:
        data["top_k"] = min(max(int(raw_top_k), 1), 5)
    except (TypeError, ValueError):
        return None, (jsonify(error="top_k는 1부터 5까지의 정수여야 합니다."), 400)
    return data, None


@app.post("/chat")
def chat():
    data, error = validated_chat_data()
    if error:
        return error
    try:
        return jsonify(client.chat(**data))
    except OllamaError as exc:
        return jsonify(error=str(exc)), 502


@app.post("/chat/stream")
def chat_stream():
    data, error = validated_chat_data()
    if error:
        return error

    def generate():
        try:
            for chunk in client.stream_chat(**data):
                yield json.dumps(chunk, ensure_ascii=False) + "\n"
        except OllamaError as exc:
            yield json.dumps({"error": str(exc)}, ensure_ascii=False) + "\n"

    return Response(generate(), mimetype="application/x-ndjson")


@app.post("/rag/chat")
def rag_chat():
    data, error = validated_rag_data()
    if error:
        return error
    try:
        return jsonify(rag_response(**data, knowledge=knowledge, client=client))
    except OllamaError as exc:
        return jsonify(error=str(exc)), 502


@app.post("/rag/chat/stream")
def rag_chat_stream():
    data, error = validated_rag_data()
    if error:
        return error

    def generate():
        try:
            for event in rag_stream_events(**data, knowledge=knowledge, client=client):
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except OllamaError as exc:
            yield json.dumps({"error": str(exc)}, ensure_ascii=False) + "\n"

    return Response(generate(), mimetype="application/x-ndjson")


@app.post("/summarize")
def summarize():
    data = request.get_json(silent=True) or {}
    text = str(data.get("text", "")).strip()
    if not text:
        return jsonify(error="text는 필수입니다."), 400
    sentences = min(max(int(data.get("max_sentences", 3)), 1), 10)
    prompt = f"다음 글을 {sentences}문장 이내의 한국어로 요약하고 요약문만 출력하세요.\n\n{text}"
    try:
        return jsonify(client.chat(prompt, data.get("model")))
    except OllamaError as exc:
        return jsonify(error=str(exc)), 502


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
