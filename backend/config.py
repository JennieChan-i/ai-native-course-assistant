from pathlib import Path
import os
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MODEL = ROOT / "models" / "bge-small-zh-v1.5"
SAMPLE_CSV = ROOT / "examples" / "course_chunks_sample.csv"
EVAL_QUESTIONS = ROOT / "evals" / "retrieval_sample.csv"
HISTORICAL_SUMMARY = ROOT / "evals" / "historical_full_summary.json"


def settings():
    local = dotenv_values(ROOT / ".env")
    def read(name, default=""):
        return str(local.get(name) or os.environ.get(name) or default)
    model_path = Path(read("EMBEDDING_MODEL_PATH", str(MODEL)))
    if not model_path.is_absolute():
        model_path = ROOT / model_path
    return {
        "api_key": read("DASHSCOPE_API_KEY"),
        "base_url": read("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "model": read("QWEN_MODEL", "qwen3.8-flash"),
        "enable_thinking": read("ENABLE_THINKING", "false").lower() == "true",
        "embedding_path": model_path,
    }
