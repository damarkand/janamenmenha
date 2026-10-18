import json
from typing import Literal

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse

from app.api.deps import get_container, get_current_user
from app.api.presenters import escalation_out
from app.container import Container
from app.models.domain import User
from app.models.schemas import AskIn, AskOut, EscalateIn, EscalationAnswerIn, EscalationOut

router = APIRouter(prefix="/assistant", tags=["HR-ассистент (ИИ)"])


@router.post("/ask", response_model=AskOut,
             summary="Вопрос HR-ассистенту: ответ только из базы знаний, с источниками")
def ask(body: AskIn, user: User = Depends(get_current_user), c: Container = Depends(get_container)):
    return c.assistant.ask(body.question, user, body.history)


@router.post("/ask/stream", summary="Тот же вопрос, но ответ печатается по мере генерации (Server-Sent Events)")
def ask_stream(body: AskIn, user: User = Depends(get_current_user), c: Container = Depends(get_container)):
    def events():
        for event in c.assistant.stream(body.question, user, body.history):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/status", summary="Состояние нейросети: скачана ли модель, загружена ли в память")
def ai_status(_: User = Depends(get_current_user), c: Container = Depends(get_container)):
    engine = c.ai
    return {"mode": c.assistant.mode, "setting": c.settings.ai_mode,
            **(engine.status() if engine else {"model": c.settings.ai_model_path.name,
                                               "model_file": c.settings.ai_model_path.exists(),
                                               "loaded": False})}


@router.post("/escalate", response_model=EscalationOut, status_code=status.HTTP_201_CREATED,
             summary="Передать вопрос живому HR-специалисту")
def escalate(body: EscalateIn, user: User = Depends(get_current_user), c: Container = Depends(get_container)):
    return escalation_out(c, c.escalations.create(user, body.question, body.context))


@router.get("/escalations", response_model=list[EscalationOut], summary="Обращения: свои (или все — для HR)")
def list_escalations(status: Literal["open", "answered"] | None = None, user: User = Depends(get_current_user),
                     c: Container = Depends(get_container)):
    return [escalation_out(c, e) for e in c.escalations.list(user, status)]


@router.post("/escalations/{escalation_id}/answer", response_model=EscalationOut, summary="Ответ HR на обращение")
def answer(escalation_id: str, body: EscalationAnswerIn, user: User = Depends(get_current_user),
           c: Container = Depends(get_container)):
    return escalation_out(c, c.escalations.answer(user, escalation_id, body.answer))
