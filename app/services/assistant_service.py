from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Callable, Iterator

from app.core.config import Settings
from app.core.errors import ForbiddenError, NotFoundError
from app.integrations.base import PersonnelSystem
from app.models.domain import Escalation, NotificationType, Role, TaskStatus, User, utcnow
from app.models.schemas import AskOut, SourceOut
from app.services import irbi
from app.services.knowledge_base import KbHit, KnowledgeBase
from app.services.llm import NoAnswer
from app.services.notification_service import NotificationService

log = logging.getLogger(__name__)

NO_ANSWER = ("В базе знаний HR нет достоверного ответа на этот вопрос. Я не буду гадать, чтобы не ввести вас "
             "в заблуждение. Вы можете передать вопрос HR-специалисту — он ответит в центре уведомлений.")

_PERSONAL = re.compile(r"\b(у меня|меня|мне|мой|моя|моё|мое|моего|моей|мои|моих|я)\b", re.IGNORECASE)
_GREETING = re.compile(r"^\s*(привет|здравствуй|здравствуйте|добрый\s+(день|вечер|утро)|доброе\s+утро|салем|сәлем|"
                       r"салам|hello|hi)\b", re.IGNORECASE)
_THANKS = re.compile(r"^\s*(спасибо|благодарю|рахмет|спс|thanks)\b", re.IGNORECASE)
_HELP = re.compile(r"^\s*(что ты умеешь|помощь|help|что ты можешь|чем (ты )?можешь помочь)\s*\??\s*$", re.IGNORECASE)

PROFILE_SOURCE = SourceOut(document="Профиль сотрудника", section="Официальные данные 1С:ЗУП",
                           file="1c-zup", relevance=1.0)
WORK_SOURCE = SourceOut(document="Рабочее пространство", section="Задачи и учёт времени", file="tasks", relevance=1.0)

CAPABILITIES = ("Я Ирби — зайчик-помощник JanaMen. Отвечаю на вопросы по внутренним правилам: отпуск, аванс, больничный, "
                "командировки, обучение. Подскажу ваш остаток отпуска, задачи и отработанные часы, а ещё могу просто "
                "поболтать и поддержать. Если ответа нет в базе знаний, предложу передать вопрос HR.")


def _first_name(user: User | None) -> str:
    return user.full_name.split()[0] if user and user.full_name else ""


class AssistantService:
    def __init__(self, kb: KnowledgeBase | Callable[[], KnowledgeBase], settings: Settings, llm=None,
                 personnel: PersonnelSystem | None = None, users=None, tasks_repo=None, time_repo=None,
                 today: Callable[[], date] = date.today):
        self._kb = kb
        self._settings = settings
        self._llm = llm
        self._personnel = personnel
        self._users = users
        self._tasks = tasks_repo
        self._time = time_repo
        self._today = today

    @property
    def mode(self) -> str:
        return "qwen" if self._llm else "extractive"

    # Ответ целиком
    def ask(self, question: str, actor: User | None = None, history: list[str] | None = None) -> AskOut:
        direct = self._direct(question, actor)
        if direct:
            return direct
        reliable = self._retrieve(question, history)
        if not reliable:
            return self._conversation(question, actor, history)
        if self._llm:
            try:
                text = self._llm.answer(question, reliable, history)
                if text is None:
                    return self._not_found()
                return AskOut(answer=text, found=True, confidence=self._confidence(reliable), mode="qwen",
                              sources=[self._source(h) for h in reliable])
            except Exception as exc:
                log.warning("Нейросеть недоступна, отвечаю цитатой из базы знаний: %s", exc)
        return self._extractive(reliable)

    # Потоковый ответ
    def stream(self, question: str, actor: User | None = None, history: list[str] | None = None) -> Iterator[dict]:
        direct = self._direct(question, actor)
        reliable = [] if direct else self._retrieve(question, history)
        if not direct and not reliable and self._llm and self._can_chat(question):
            yield from self._chat_stream(question, actor, history)
            return
        if direct or not reliable or not self._llm:
            out = direct or (self._extractive(reliable) if reliable else self._conversation(question, actor, history,
                                                                                          use_llm=False))
            yield {"type": "meta", **out.model_dump(exclude={"answer"})}
            yield {"type": "token", "text": out.answer}
            yield {"type": "done"}
            return

        sources = [self._source(h).model_dump() for h in reliable]
        started = False
        try:
            for piece in self._llm.stream(question, reliable, history):
                if not started:
                    started = True
                    yield {"type": "meta", "found": True, "confidence": self._confidence(reliable), "mode": "qwen",
                           "sources": sources, "can_escalate": True,
                           "escalate_endpoint": "/api/v1/assistant/escalate"}
                yield {"type": "token", "text": piece}
        except NoAnswer:
            out = self._not_found()
            yield {"type": "meta", **out.model_dump(exclude={"answer"})}
            yield {"type": "token", "text": out.answer}
        except Exception as exc:
            log.warning("Ошибка нейросети: %s", exc)
            if started:
                yield {"type": "token", "text": "\n\n(ответ прерван, попробуйте ещё раз)"}
            else:
                out = self._extractive(reliable)
                yield {"type": "meta", **out.model_dump(exclude={"answer"})}
                yield {"type": "token", "text": out.answer}
        yield {"type": "done"}

    # Разговор
    @staticmethod
    def _can_chat(question: str) -> bool:
        kind = irbi.small_talk_kind(question)
        return kind != "crisis" and (not irbi.is_hr_topic(question) or kind in ("tired", "motivation", "advice"))

    def _conversation(self, question: str, actor: User | None, history: list[str] | None,
                      use_llm: bool = True) -> AskOut:
        kind = irbi.small_talk_kind(question)
        if use_llm and self._llm and self._can_chat(question):
            try:
                text = self._llm.chat(question, irbi.chat_system_prompt(actor), history)
                if text:
                    return self._chat(text)
            except Exception as exc:
                log.warning("Нейросеть недоступна для разговора: %s", exc)
        if kind and (kind != "advice" or not irbi.is_hr_topic(question)):
            return self._chat(irbi.canned_reply(kind, actor))
        return self._not_found()

    def _chat_stream(self, question: str, actor: User | None, history: list[str] | None) -> Iterator[dict]:
        started = False
        try:
            for piece in self._llm.chat_stream(question, irbi.chat_system_prompt(actor), history):
                if not started:
                    started = True
                    yield {"type": "meta", "found": True, "confidence": "high", "mode": "chat", "sources": [],
                           "can_escalate": False, "escalate_endpoint": "/api/v1/assistant/escalate"}
                yield {"type": "token", "text": piece}
        except Exception as exc:
            log.warning("Ошибка нейросети в разговоре: %s", exc)
            if started:
                yield {"type": "token", "text": "\n\n(ответ прерван, попробуйте ещё раз)"}
        if not started:
            out = self._conversation(question, actor, history, use_llm=False)
            yield {"type": "meta", **out.model_dump(exclude={"answer"})}
            yield {"type": "token", "text": out.answer}
        yield {"type": "done"}

    # Поиск
    def _retrieve(self, question: str, history: list[str] | None) -> list[KbHit]:
        kb = self._kb() if callable(self._kb) else self._kb
        reliable = self._reliable(kb.search(question, k=3))
        if not reliable and history:
            reliable = self._reliable(kb.search(f"{history[-1]} {question}", k=3))
        return reliable

    def _reliable(self, hits: list[KbHit]) -> list[KbHit]:
        return [h for h in hits if h.score >= self._settings.assistant_min_score
                and h.coverage >= self._settings.assistant_min_coverage]

    @staticmethod
    def _confidence(reliable: list[KbHit]) -> str:
        return "high" if reliable[0].coverage >= 0.75 else "medium"

    def _extractive(self, reliable: list[KbHit]) -> AskOut:
        top = reliable[0]
        used = [top] + [h for h in reliable[1:2] if h.score >= 0.8 * top.score]
        parts = [f"Согласно документу «{h.chunk.doc_title}», раздел «{h.chunk.section}»:\n{h.chunk.text}" for h in used]
        return AskOut(answer="\n\n".join(parts), found=True, confidence=self._confidence(reliable),
                      mode="extractive", sources=[self._source(h) for h in used])

    # Ответы без базы знаний
    def _direct(self, question: str, actor: User | None) -> AskOut | None:
        name = _first_name(actor)
        if irbi.small_talk_kind(question) == "crisis":
            return self._chat(irbi.canned_reply("crisis", actor))
        if _GREETING.search(question) and len(question.split()) <= 4:
            hello = f"Привет, {name}! " if name else "Привет! "
            return self._chat(hello + CAPABILITIES)
        if _THANKS.search(question) and len(question.split()) <= 4:
            return self._chat("Всегда пожалуйста! Я рядом, если понадоблюсь.")
        if _HELP.search(question):
            return self._chat(CAPABILITIES)
        return self._personal(question, actor)

    @staticmethod
    def _chat(text: str) -> AskOut:
        return AskOut(answer=text, found=True, confidence="high", mode="chat", sources=[], can_escalate=False)

    def _personal(self, question: str, actor: User | None) -> AskOut | None:
        if not (actor and self._personnel and _PERSONAL.search(question)):
            return None
        q = question.lower()
        if re.search(r"зарплат|оклад", q):
            return AskOut(answer="Размер заработной платы в портале не отображается. Уточните его у HR или в "
                                 "бухгалтерии — я могу передать ваш вопрос HR-специалисту.",
                          found=False, confidence="none", mode="profile", sources=[])
        if self._tasks is not None and re.search(r"задач|дедлайн", q):
            return self._tasks_answer(actor)
        if self._time is not None and re.search(r"\bчас(ов|ы|а)?\b|отработал", q):
            return self._hours_answer(actor)
        rec = self._personnel.get_employee(actor.id)
        if "отпуск" in q and re.search(r"остал|остат|сколько|дней", q):
            text = f"По данным 1С:ЗУП у вас осталось {rec.vacation_days_left} дн. ежегодного отпуска."
        elif re.search(r"руководител|начальник", q):
            mgr = self._users.get(rec.manager_id) if (rec.manager_id and self._users) else None
            text = (f"Ваш руководитель по данным 1С:ЗУП: {mgr.full_name}." if mgr
                    else "В 1С:ЗУП у вас не указан непосредственный руководитель.")
        elif re.search(r"дата при[её]ма|когда .*(принят|принял)|стаж", q):
            text = (f"Дата приёма на работу по данным 1С:ЗУП: {rec.hire_date.strftime('%d.%m.%Y')}."
                    if rec.hire_date else "Дата приёма в 1С:ЗУП не указана.")
        elif re.search(r"должност|отдел|подразделен", q):
            text = f"Ваша должность: {rec.position}, подразделение: {rec.department} (данные 1С:ЗУП)."
        else:
            return None
        return AskOut(answer=text, found=True, confidence="high", mode="profile", sources=[PROFILE_SOURCE])

    def _tasks_answer(self, actor: User) -> AskOut:
        today = self._today()
        open_tasks = sorted((t for t in self._tasks.for_users({actor.id}) if t.status != TaskStatus.DONE),
                            key=lambda t: t.due_date or date.max)
        if not open_tasks:
            text = "Открытых задач нет."
        else:
            lines = []
            for t in open_tasks[:5]:
                due = ""
                if t.due_date:
                    due = " — просрочена" if t.due_date < today else f" — до {t.due_date.strftime('%d.%m')}"
                lines.append(f"• {t.title}{due}")
            more = f"\nИ ещё {len(open_tasks) - 5}." if len(open_tasks) > 5 else ""
            text = f"Открытых задач: {len(open_tasks)}.\n" + "\n".join(lines) + more
        return AskOut(answer=text, found=True, confidence="high", mode="profile", sources=[WORK_SOURCE],
                      can_escalate=False)

    def _hours_answer(self, actor: User) -> AskOut:
        today = self._today()
        start = today - timedelta(days=today.weekday())
        hours = sum(e.hours for e in self._time.by_user(actor.id, start, today))
        text = f"С понедельника ({start.strftime('%d.%m')}) вы отметили {hours:g} ч."
        return AskOut(answer=text, found=True, confidence="high", mode="profile", sources=[WORK_SOURCE],
                      can_escalate=False)

    @staticmethod
    def _source(h: KbHit) -> SourceOut:
        return SourceOut(document=h.chunk.doc_title, section=h.chunk.section,
                         file=h.chunk.origin or f"{h.chunk.doc_id}.md", relevance=round(h.score, 2))

    @staticmethod
    def _not_found() -> AskOut:
        return AskOut(answer=NO_ANSWER, found=False, confidence="none", mode="extractive", sources=[])


class EscalationService:
    def __init__(self, repo, users, notifier: NotificationService):
        self._repo = repo
        self._users = users
        self._notifier = notifier

    def create(self, actor: User, question: str, context: str | None) -> Escalation:
        esc = self._repo.add(Escalation(id=self._repo.next_id(), user_id=actor.id, question=question, context=context))
        for hr in self._users.by_role(Role.HR):
            if hr.id != actor.id:
                self._notifier.notify(hr.id, NotificationType.ESCALATION_CREATED, "Вопрос к HR от ассистента",
                                      f"{actor.full_name}: {question[:120]}", link=f"/assistant/escalations/{esc.id}")
        return esc

    def list(self, actor: User, status: str | None = None) -> list[Escalation]:
        items = self._repo.list() if actor.role == Role.HR else self._repo.list(lambda e: e.user_id == actor.id)
        items = [e for e in items if status is None or e.status == status]
        return sorted(items, key=lambda e: e.created_at, reverse=True)

    def answer(self, actor: User, escalation_id: str, answer: str) -> Escalation:
        if actor.role != Role.HR:
            raise ForbiddenError("Отвечать на обращения может только HR")
        esc = self._repo.get(escalation_id)
        if not esc:
            raise NotFoundError("Обращение не найдено")
        esc.status, esc.answer, esc.answered_by, esc.answered_at = "answered", answer, actor.id, utcnow()
        self._repo.save(esc)
        self._notifier.notify(esc.user_id, NotificationType.ESCALATION_ANSWERED, "HR ответил на ваш вопрос",
                              answer[:200], link=f"/assistant/escalations/{esc.id}")
        return esc
