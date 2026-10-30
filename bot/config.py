import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    tg_token: str
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    llm_fallback_models: tuple[str, ...]
    llm_router_model: str
    llm_reasoning_effort: str
    archive_dir: Path
    db_path: Path
    timezone: str


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Змінна оточення {name} не задана (див. .env.example)")
    return value


def load_config() -> Config:
    return Config(
        tg_token=_required("TG_KEY"),
        llm_api_key=_required("GROQ_KEY"),
        llm_base_url=os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
        llm_model=os.getenv("LLM_MODEL", "openai/gpt-oss-120b"),
        llm_fallback_models=tuple(
            m.strip() for m in os.getenv("LLM_FALLBACK_MODEL", "qwen/qwen3.8-27b,openai/gpt-oss-20b").split(",")
            if m.strip()
        ),
        llm_router_model=os.getenv("LLM_ROUTER_MODEL", "qwen/qwen3.8-27b"),
        llm_reasoning_effort=os.getenv("LLM_REASONING_EFFORT", "low"),
        archive_dir=Path(os.getenv("ARCHIVE_DIR", "data/archive")),
        db_path=Path(os.getenv("DB_PATH", "storage/mishka.db")),
        timezone=os.getenv("TZ_NAME", "Europe/Kyiv"),
    )
