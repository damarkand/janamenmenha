from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import academy, assistant, auth, dashboard, integrations, notifications, requests, schedule, tasks, users
from app.container import Container
from app.core.config import BASE_DIR, Settings, settings as default_settings
from app.core.errors import AppError

logging.basicConfig(level=logging.INFO)

DESCRIPTION = """
MVP единой Digital-HR платформы **JanaMen**: профиль сотрудника (данные 1С:ЗУП), заявки на отпуск и аванс,
Jana Academy, центр уведомлений и HR-ассистент, отвечающий строго по базе знаний.

**Сайт:** http://localhost:8000 · **Как начать в Swagger:** выполните `POST /api/v1/auth/login` (пример тела уже подставлен), скопируйте `access_token`,
нажмите **Authorize** и вставьте токен.

Тестовые пользователи (пароль у всех `Passw0rd!`): `employee@janamen.kz`, `employee2@janamen.kz`,
`manager@janamen.kz`, `manager2@janamen.kz`, `sales@janamen.kz`, `hr@janamen.kz`.
"""

TAGS = [
    {"name": "Авторизация", "description": "Вход и текущий пользователь"},
    {"name": "Профили (только чтение, 1С:ЗУП)", "description": "Официальные кадровые данные; редактирование запрещено"},
    {"name": "Главная и графики", "description": "Сводка сотрудника и команды для графиков"},
    {"name": "Задачи", "description": "Личные задачи и поручения руководителя"},
    {"name": "График и учёт времени", "description": "Рабочий календарь, праздники, отпуска, отметка часов"},
    {"name": "Заявки", "description": "Отпуск, аванс, справки: создание, согласование, отмена, история"},
    {"name": "Jana Academy (обучение)", "description": "Каталог, назначение курсов, прогресс, тесты"},
    {"name": "Уведомления", "description": "Центр уведомлений"},
    {"name": "HR-ассистент (ИИ)", "description": "Ответы только по базе знаний, со ссылками на источники; эскалация в HR"},
    {"name": "Заглушки интеграций (1С:ЗУП, Documentolog)", "description": "Только для HR: что ушло во внешние системы"},
    {"name": "Система", "description": "Служебные эндпоинты"},
]

_VALIDATION_RU = {
    "missing": "Обязательное поле",
    "int_parsing": "Ожидается целое число",
    "int_type": "Ожидается целое число",
    "date_parsing": "Ожидается дата в формате ГГГГ-ММ-ДД",
    "date_from_datetime_parsing": "Ожидается дата в формате ГГГГ-ММ-ДД",
    "string_type": "Ожидается строка",
    "string_too_short": "Слишком короткое значение",
    "string_too_long": "Слишком длинное значение",
    "greater_than": "Значение должно быть больше {gt}",
    "greater_than_equal": "Значение должно быть не меньше {ge}",
    "less_than_equal": "Значение должно быть не больше {le}",
    "list_type": "Ожидается список",
    "literal_error": "Недопустимое значение, допустимо: {expected}",
    "enum": "Недопустимое значение, допустимо: {expected}",
    "json_invalid": "Некорректный JSON",
    "model_attributes_type": "Ожидается JSON-объект",
}


def _ru_validation_message(err: dict) -> str:
    template = _VALIDATION_RU.get(err.get("type", ""))
    if not template:
        return err.get("msg", "Некорректное значение")
    try:
        return template.format(**(err.get("ctx") or {}))
    except (KeyError, IndexError):
        return template


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or default_settings
    app = FastAPI(title=settings.app_name, version="0.1.0", description=DESCRIPTION, openapi_tags=TAGS)
    app.state.container = container or Container(settings)

    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.code, "message": exc.message})

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e.get("loc", []) if p != "body") or "body",
                    "message": _ru_validation_message(e)} for e in exc.errors()]
        return JSONResponse(status_code=422, content={
            "error": "validation_error", "message": "Ошибка в данных запроса", "details": details})

    @app.exception_handler(NotImplementedError)
    async def not_implemented_handler(_: Request, exc: NotImplementedError):
        return JSONResponse(status_code=501, content={"error": "not_implemented", "message": str(exc)})

    for r in (auth, users, dashboard, tasks, schedule, requests, academy, notifications, assistant, integrations):
        app.include_router(r.router, prefix=settings.api_prefix)

    @app.get("/health", tags=["Система"], summary="Проверка работоспособности")
    def health():
        c: Container = app.state.container
        return {"status": "ok", "storage": settings.storage,
                "database": settings.db_path.name if settings.storage == "sqlite" else None,
                "integration_mode": settings.integration_mode,
                "assistant_mode": c.assistant.mode,
                "ai_loaded": bool(c.ai and c.ai.loaded),
                "kb_sections": len(c.current_kb().chunks)}

    front = BASE_DIR / "front"
    if front.exists():
        app.mount("/", StaticFiles(directory=front, html=True), name="front")

    return app


app = create_app()
