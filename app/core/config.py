from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


@dataclass
class Settings:
    app_name: str = "JanaMen — API платформы Digital-HR"
    api_prefix: str = "/api/v1"

    # Авторизация
    jwt_secret: str = field(default_factory=lambda: _env("JWT_SECRET", "dev-only-secret-change-me-in-production-32b+"))
    jwt_algorithm: str = "HS256"
    jwt_ttl_minutes: int = field(default_factory=lambda: int(_env("JWT_TTL_MINUTES", "480")))

    storage: str = field(default_factory=lambda: _env("STORAGE", "sqlite"))
    db_path: Path = field(default_factory=lambda: Path(_env("DIGITAL_HR_DB", str(BASE_DIR / "digital_hr.db"))))
    demo_password: str = field(default_factory=lambda: _env("DEMO_PASSWORD", "Passw0rd!"))
    # Хранилище и контент
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", str(BASE_DIR / "data"))))
    kb_dir: Path = field(default_factory=lambda: Path(_env("KB_DIR", str(BASE_DIR / "knowledge_base"))))

    integration_mode: str = field(default_factory=lambda: _env("INTEGRATION_MODE", "mock"))
    zup_base_url: str = field(default_factory=lambda: _env("ZUP_BASE_URL", ""))
    documentolog_base_url: str = field(default_factory=lambda: _env("DOCUMENTOLOG_BASE_URL", ""))

    # Бизнес-правила
    advance_max_percent: int = field(default_factory=lambda: int(_env("ADVANCE_MAX_PERCENT", "50")))
    default_salary: int = field(default_factory=lambda: int(_env("DEFAULT_SALARY", "500000")))

    # HR-ассистент
    assistant_min_score: float = field(default_factory=lambda: float(_env("ASSISTANT_MIN_SCORE", "2.0")))
    assistant_min_coverage: float = field(default_factory=lambda: float(_env("ASSISTANT_MIN_COVERAGE", "0.6")))
    ai_mode: str = field(default_factory=lambda: _env("AI_MODE", "auto"))
    ai_model_repo: str = field(default_factory=lambda: _env("AI_MODEL_REPO", "Qwen/Qwen2.5-3B-Instruct-GGUF"))
    ai_model_file: str = field(default_factory=lambda: _env("AI_MODEL_FILE", "qwen2.5-3b-instruct-q4_k_m.gguf"))
    ai_model_path: Path = field(default_factory=lambda: Path(_env(
        "AI_MODEL_PATH", str(BASE_DIR / "models" / _env("AI_MODEL_FILE", "qwen2.5-3b-instruct-q4_k_m.gguf")))))
    ai_threads: int = field(default_factory=lambda: int(_env("AI_THREADS", "0")))
    ai_ctx: int = field(default_factory=lambda: int(_env("AI_CTX", "2048")))
    ai_max_tokens: int = field(default_factory=lambda: int(_env("AI_MAX_TOKENS", "256")))
    ai_preload: bool = field(default_factory=lambda: _env("AI_PRELOAD", "1") == "1")


settings = Settings()
