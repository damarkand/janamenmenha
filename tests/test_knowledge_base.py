from app.services.knowledge_base import KnowledgeBase, tokenize

DOC = """# Тестовый документ
> служебная пометка про секрет
Вступление про офис.

## Парковка
Ключевые слова: автомобиль машина
Парковка для сотрудников бесплатная.

## Обед
Обед с 13 до 14.
"""


def test_tokenize_drops_stopwords_and_stems():
    assert tokenize("Сколько дней отпуска положено?") == ["дней", "отпус"]
    assert tokenize("Ёлка") == ["елка"]
    assert tokenize("и в на") == []


def test_parse_sections_ignores_notes_and_hides_keywords(tmp_path):
    (tmp_path / "doc.md").write_text(DOC, encoding="utf-8")
    kb = KnowledgeBase.from_dir(tmp_path)
    assert [c.section for c in kb.chunks] == ["Общие положения", "Парковка", "Обед"]
    assert all(c.doc_title == "Тестовый документ" and c.doc_id == "doc" for c in kb.chunks)
    parking = kb.chunks[1]
    assert "Ключевые" not in parking.text and "автомобиль" not in parking.text
    assert all("секрет" not in c.text for c in kb.chunks)


def test_search_uses_keywords_and_ranks(tmp_path):
    (tmp_path / "doc.md").write_text(DOC, encoding="utf-8")
    kb = KnowledgeBase.from_dir(tmp_path)
    hits = kb.search("где поставить машину")
    assert hits and hits[0].chunk.section == "Парковка" and hits[0].coverage > 0
    assert kb.search("секрет") == []
    assert kb.search("") == []
    assert KnowledgeBase([]).search("обед") == []


def test_real_knowledge_base_loads(settings):
    kb = KnowledgeBase.from_dir(settings.kb_dir)
    assert {c.doc_id for c in kb.chunks} == {
        "vacation_policy", "advance_payment", "sick_leave", "business_trips", "academy_rules"}
    assert all(c.text.strip() for c in kb.chunks)
