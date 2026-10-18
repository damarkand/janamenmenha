import sys
import types

import pytest

from app.container import Container
from app.core.errors import ForbiddenError, NotFoundError
from app.models.domain import NotificationType
from app.services.assistant_service import AssistantService
from app.services.knowledge_base import KnowledgeBase
from app.services.llm import NoAnswer, QwenEngine, build_engine


class FakeLlm:
    def __init__(self, result=None, exc=None, pieces=None):
        self.result, self.exc, self.pieces, self.calls = result, exc, pieces, []

    def answer(self, question, hits, history=None):
        self.calls.append((question, hits, history))
        if self.exc:
            raise self.exc
        return self.result

    def stream(self, question, hits, history=None):
        self.calls.append((question, hits, history))
        if self.exc:
            raise self.exc
        if self.result is None:
            raise NoAnswer()
        yield from (self.pieces or [self.result])

    def chat(self, question, system, history=None):
        self.calls.append(("chat", question, system, history))
        if self.exc:
            raise self.exc
        return self.result

    def chat_stream(self, question, system, history=None):
        self.calls.append(("chat", question, system, history))
        if self.exc:
            raise self.exc
        yield from (self.pieces or ([self.result] if self.result else []))


def make_assistant(settings, llm=None):
    return AssistantService(KnowledgeBase.from_dir(settings.kb_dir), settings, llm)


def collect(events):
    events = list(events)
    meta = next(e for e in events if e["type"] == "meta")
    text = "".join(e["text"] for e in events if e["type"] == "token")
    assert events[-1]["type"] == "done"
    return meta, text


# Личные вопросы
@pytest.mark.parametrize("question,expected", [
    ("Сколько у меня осталось дней отпуска?", "21"),
    ("Кто мой руководитель?", "Ерлан Тулеуов"),
    ("Какая у меня дата приёма?", "14.02.2022"),
    ("Когда меня приняли на работу?", "14.02.2022"),
    ("Какая моя должность?", "Backend-разработчик"),
    ("Какие у меня задачи?", "Открытых задач: 3"),
    ("Сколько часов я отработал?", "30 ч"),
])
def test_personal_questions_answered_from_own_data(container, question, expected):
    out = container.assistant.ask(question, container.users.get("u-3"))
    assert out.mode == "profile" and out.found and expected in out.answer


def test_personal_question_for_user_without_manager(container):
    out = container.assistant.ask("Кто мой руководитель?", container.users.get("u-2"))
    assert "не указан" in out.answer


def test_personal_question_without_actor_goes_to_kb(container):
    assert container.assistant.ask("Сколько у меня осталось дней отпуска?").mode != "profile"


def test_unknown_personal_question_is_not_guessed(container):
    out = container.assistant.ask("Какая у меня зарплата?", container.users.get("u-3"))
    assert not out.found and out.sources == []


@pytest.mark.parametrize("question", ["Привет", "Добрый день!", "Спасибо", "Что ты умеешь?"])
def test_small_talk_does_not_hit_knowledge_base(container, question):
    out = container.assistant.ask(question, container.users.get("u-3"))
    assert out.mode == "chat" and out.found and not out.can_escalate and out.sources == []


def test_greeting_uses_first_name(container):
    assert "Данияр" in container.assistant.ask("Привет", container.users.get("u-3")).answer


def test_word_now_is_not_treated_as_hours(container):
    out = container.assistant.ask("Что мне делать сейчас с отпуском?", container.users.get("u-3"))
    assert out.mode != "profile" or "ч." not in out.answer


# Ответы нейросети
def test_llm_answer_is_used_with_sources(settings):
    llm = FakeLlm("Перенос согласуется с руководителем [1]")
    out = make_assistant(settings, llm).ask("Как перенести отпуск?")
    assert out.mode == "qwen" and out.found and out.answer.endswith("[1]")
    assert out.sources and llm.calls and llm.calls[0][1]


def test_llm_receives_history(settings):
    llm = FakeLlm("Ответ [1]")
    make_assistant(settings, llm).ask("Как перенести отпуск?", history=["Сколько дней отпуска?"])
    assert llm.calls[0][2] == ["Сколько дней отпуска?"]


def test_follow_up_question_uses_history_for_search(settings):
    a = make_assistant(settings)
    out = a.ask("а частями можно?", history=["Можно ли разделить отпуск?"])
    assert out.found and out.sources[0].section == "Разделение отпуска на части"


def test_llm_no_answer_becomes_not_found(settings):
    out = make_assistant(settings, FakeLlm(None)).ask("Как перенести отпуск?")
    assert not out.found and out.sources == []


def test_llm_failure_falls_back_to_extractive(settings):
    out = make_assistant(settings, FakeLlm(exc=TimeoutError("timeout"))).ask("Как перенести отпуск?")
    assert out.found and out.mode == "extractive"


def test_llm_is_not_called_for_irrelevant_question(settings):
    llm = FakeLlm("выдумка")
    out = make_assistant(settings, llm).ask("Какой дресс-код в офисе?")
    assert not out.found and llm.calls == []


# Потоковые ответы
def test_stream_with_llm(settings):
    llm = FakeLlm("Перенос [1]", pieces=["Пере", "нос", " [1]"])
    meta, text = collect(make_assistant(settings, llm).stream("Как перенести отпуск?"))
    assert meta["mode"] == "qwen" and meta["found"] and meta["sources"] and text == "Перенос [1]"


def test_stream_no_answer_from_llm(settings):
    meta, text = collect(make_assistant(settings, FakeLlm(None)).stream("Как перенести отпуск?"))
    assert not meta["found"] and "нет достоверного ответа" in text


def test_stream_llm_failure_before_first_token_falls_back(settings):
    meta, text = collect(make_assistant(settings, FakeLlm(exc=RuntimeError("boom"))).stream("Как перенести отпуск?"))
    assert meta["mode"] == "extractive" and "Согласно документу" in text


def test_stream_without_llm_and_not_found(settings):
    meta, text = collect(make_assistant(settings).stream("Какой дресс-код в офисе?"))
    assert not meta["found"] and meta["can_escalate"]


def test_stream_small_talk(container):
    meta, text = collect(container.assistant.stream("Привет", container.users.get("u-3")))
    assert meta["mode"] == "chat" and "Данияр" in text


# Ирби
@pytest.mark.parametrize("question", ["Как прошёл твой день?", "Как дела?", "Кто ты?", "Расскажи анекдот"])
def test_irbi_small_talk_without_llm(container, question):
    out = container.assistant.ask(question, container.users.get("u-3"))
    assert out.mode == "chat" and out.found and not out.can_escalate and out.sources == []


def test_irbi_support_mentions_position(container):
    user = container.users.get("u-3")
    out = container.assistant.ask("Я так устал сегодня", user)
    assert out.mode == "chat" and user.position in out.answer and "Данияр" in out.answer


def test_irbi_name_in_intro(container):
    assert "Ирби" in container.assistant.ask("Как тебя зовут?", container.users.get("u-3")).answer


def test_irbi_crisis_reply_is_canned(settings):
    llm = FakeLlm("болтовня")
    out = make_assistant(settings, llm).ask("Не хочу жить")
    assert "112" in out.answer and llm.calls == []


def test_irbi_uses_llm_for_free_talk(container, settings):
    llm = FakeLlm("Мой день прошёл отлично!")
    user = container.users.get("u-3")
    out = make_assistant(settings, llm).ask("Какая сегодня погода?", user)
    assert out.mode == "chat" and out.answer == "Мой день прошёл отлично!"
    _, _, system, _ = llm.calls[0]
    assert "Ирби" in system and user.position in system


def test_irbi_hr_question_is_not_chatted(settings):
    llm = FakeLlm("выдумка")
    out = make_assistant(settings, llm).ask("Какая политика по ипотеке?")
    assert not out.found and llm.calls == []


def test_irbi_llm_failure_falls_back_to_canned(settings):
    out = make_assistant(settings, FakeLlm(exc=TimeoutError())).ask("Как дела?")
    assert out.mode == "chat" and out.found


def test_irbi_stream_chat(settings):
    llm = FakeLlm("Привет-привет", pieces=["При", "вет"])
    meta, text = collect(make_assistant(settings, llm).stream("Как погода?"))
    assert meta["mode"] == "chat" and not meta["can_escalate"] and text == "Привет"


def test_irbi_stream_chat_falls_back_without_tokens(settings):
    meta, text = collect(make_assistant(settings, FakeLlm(None)).stream("Как прошёл твой день?"))
    assert meta["mode"] == "chat" and text


class FakeLlama:
    answer = "Ответ по источникам [1]."

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []

    def create_chat_completion(self, messages, stream=False, **kw):
        self.calls.append((messages, stream, kw))
        text = FakeLlama.answer
        if stream:
            def gen():
                yield {"choices": [{"delta": {"role": "assistant"}}]}
                for i in range(0, len(text), 3):
                    yield {"choices": [{"delta": {"content": text[i:i + 3]}}]}
            return gen()
        return {"choices": [{"message": {"content": text}}]}


@pytest.fixture
def qwen_settings(settings, tmp_path, monkeypatch):
    model = tmp_path / "qwen.gguf"
    model.write_bytes(b"fake")
    settings.ai_mode, settings.ai_model_path, settings.ai_preload = "auto", model, False
    monkeypatch.setitem(sys.modules, "llama_cpp", types.SimpleNamespace(Llama=FakeLlama))
    monkeypatch.setattr(QwenEngine, "library_available", staticmethod(lambda: True))
    FakeLlama.answer = "Ответ по источникам [1]."
    return settings


def test_engine_answer_and_prompt(qwen_settings):
    engine = QwenEngine(qwen_settings)
    hits = KnowledgeBase.from_dir(qwen_settings.kb_dir).search("Как перенести отпуск?")
    assert engine.answer("Как перенести отпуск?", hits, ["Сколько дней отпуска?"]) == "Ответ по источникам [1]."
    messages, _, params = engine._llm.calls[0]
    assert "ТОЛЬКО" in messages[0]["content"] and "NO_ANSWER" in messages[0]["content"]
    assert hits[0].chunk.section in messages[1]["content"] and "Сколько дней отпуска?" in messages[1]["content"]
    assert params["temperature"] <= 0.2 and engine.loaded and engine._llm.kwargs["n_gpu_layers"] == 0


def test_engine_chat(qwen_settings):
    FakeLlama.answer = "  Отлично, спасибо!"
    engine = QwenEngine(qwen_settings)
    assert engine.chat("Как дела?", "Ты Ирби", ["Привет"]) == "Отлично, спасибо!"
    messages, _, params = engine._llm.calls[0]
    assert messages[0]["content"] == "Ты Ирби" and "Привет" in messages[1]["content"]
    assert params["temperature"] > 0.5 and params["max_tokens"] <= 220
    assert "".join(engine.chat_stream("Как дела?", "Ты Ирби")) == "Отлично, спасибо!"


def test_engine_stream(qwen_settings):
    engine = QwenEngine(qwen_settings)
    assert "".join(engine.stream("вопрос", [])) == "Ответ по источникам [1]."


@pytest.mark.parametrize("text", ["NO_ANSWER", "  NO_ANSWER.", ""])
def test_engine_no_answer(qwen_settings, text):
    FakeLlama.answer = text
    engine = QwenEngine(qwen_settings)
    assert engine.answer("вопрос", []) is None
    with pytest.raises(NoAnswer):
        list(engine.stream("вопрос", []))


def test_build_engine_modes(qwen_settings, tmp_path):
    assert isinstance(build_engine(qwen_settings), QwenEngine)
    qwen_settings.ai_mode = "off"
    assert build_engine(qwen_settings) is None
    qwen_settings.ai_mode, qwen_settings.ai_model_path = "auto", tmp_path / "missing.gguf"
    assert build_engine(qwen_settings) is None


def test_container_uses_qwen_when_model_present(qwen_settings):
    c = Container(qwen_settings)
    assert c.assistant.mode == "qwen"
    out = c.assistant.ask("Как перенести отпуск?", c.users.get("u-3"))
    assert out.mode == "qwen" and out.answer == "Ответ по источникам [1]."


def test_engine_status(qwen_settings):
    st = QwenEngine(qwen_settings).status()
    assert st["model_file"] and st["library"] and not st["loaded"] and st["threads"] >= 1


# Обращения к HR
def test_escalation_lifecycle(container):
    emp, hr = container.users.get("u-3"), container.users.get("u-1")
    esc = container.escalations.create(emp, "Компенсация спортзала?", "контекст")
    assert esc.status == "open"
    assert any(n.type == NotificationType.ESCALATION_CREATED for n in container.notifications.list_for(hr))
    assert [e.id for e in container.escalations.list(hr, "open")] == [esc.id]
    assert container.escalations.list(container.users.get("u-4")) == []

    with pytest.raises(ForbiddenError):
        container.escalations.answer(emp, esc.id, "сам себе отвечу")
    with pytest.raises(NotFoundError):
        container.escalations.answer(hr, "esc-404", "ответ")

    container.escalations.answer(hr, esc.id, "Да, до 15 000 ₸ в месяц")
    assert container.escalations.list(emp, "answered")[0].answered_by == hr.id
    assert container.escalations.list(hr, "open") == []
    assert any(n.type == NotificationType.ESCALATION_ANSWERED for n in container.notifications.list_for(emp))


def test_hr_escalation_does_not_notify_self(container):
    hr = container.users.get("u-1")
    before = len(container.notifications.list_for(hr))
    container.escalations.create(hr, "Вопрос от HR", None)
    assert len(container.notifications.list_for(hr)) == before
