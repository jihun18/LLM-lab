import json

from flask import Flask, Response, jsonify, request, send_file

from core.config import settings
from core.ollama_client import OllamaClient, OllamaError


app = Flask(__name__)
client = OllamaClient()


@app.get("/")
def home():
    return send_file("privAI.html")


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

