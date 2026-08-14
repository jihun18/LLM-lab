from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    ollama_url: str = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    default_model: str = os.getenv("OLLAMA_MODEL", "qwen3:1.7b")
    num_ctx: int = int(os.getenv("OLLAMA_NUM_CTX", "2048"))
    num_predict: int = int(os.getenv("OLLAMA_NUM_PREDICT", "256"))
    temperature: float = float(os.getenv("OLLAMA_TEMPERATURE", "0.3"))


settings = Settings()

