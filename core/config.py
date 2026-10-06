from dataclasses import dataclass
import os


EMBEDDING_THRESHOLDS = {"embeddinggemma": 0.4395475, "nomic-embed-text": 0.754383}
DEFAULT_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "embeddinggemma:300m")


@dataclass(frozen=True)
class Settings:
    ollama_url: str = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    default_model: str = os.getenv("OLLAMA_MODEL", "qwen3:1.7b")
    num_ctx: int = int(os.getenv("OLLAMA_NUM_CTX", "2048"))
    num_predict: int = int(os.getenv("OLLAMA_NUM_PREDICT", "256"))
    temperature: float = float(os.getenv("OLLAMA_TEMPERATURE", "0.3"))
    embedding_model: str = DEFAULT_EMBED_MODEL
    semantic_threshold: float = float(os.getenv("SEMANTIC_THRESHOLD", str(EMBEDDING_THRESHOLDS.get(DEFAULT_EMBED_MODEL.split(":")[0], 0.65))))


settings = Settings()

