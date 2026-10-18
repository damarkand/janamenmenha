from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

_WORD = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)
_STOP = set("""
и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее мне было вот от меня
еще нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был него до вас нибудь опять уж вам ведь
там потом себя ничего ей может они тут где есть надо ней для мы тебя их чем была сам чтоб без будто чего раз
тоже себе под будет ж тогда кто этот того потому этого какой совсем ним здесь этом один почти мой тем чтобы
нее сейчас были куда зачем всех никогда можно при наконец два об другой хоть после над больше тот через эти
нас про всего них какая много разве три эту моя впрочем хорошо свою этой перед иногда лучше чуть том нельзя
такой им более всегда конечно всю между это мне меня мои мой моё сколько какие каких каким как ли нужно положен положено положена
полагается
the a an is are of to in for on and or what how do does can i my me when where which who
""".split())


def tokenize(text: str) -> list[str]:
    out = []
    for w in _WORD.findall(text.lower().replace("ё", "е")):
        if w in _STOP or len(w) < 2:
            continue
        out.append(w[:5] if len(w) > 5 else w)
    return out


@dataclass
class KbChunk:
    doc_id: str
    doc_title: str
    section: str
    text: str
    tokens: list[str] = field(default_factory=list)
    origin: str = ""


@dataclass
class KbHit:
    chunk: KbChunk
    score: float
    coverage: float


class KnowledgeBase:
    K1, B = 1.5, 0.75

    def __init__(self, chunks: list[KbChunk]):
        self.chunks = chunks
        self._tf = [Counter(c.tokens) for c in chunks]
        self._avgdl = (sum(len(c.tokens) for c in chunks) / len(chunks)) if chunks else 0
        df: Counter = Counter()
        for tf in self._tf:
            df.update(tf.keys())
        n = len(chunks)
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    @classmethod
    def from_dir(cls, path: Path) -> "KnowledgeBase":
        chunks: list[KbChunk] = []
        for md in sorted(Path(path).glob("*.md")):
            chunks.extend(cls._parse(md))
        return cls(chunks)

    @staticmethod
    def _parse(md: Path) -> list[KbChunk]:
        title, section, buf, keywords, chunks = md.stem, "Общие положения", [], [], []

        def flush():
            body = "\n".join(buf).strip()
            if body:
                toks = tokenize(f"{section} {section}") + tokenize(body) + tokenize(" ".join(keywords))
                chunks.append(KbChunk(md.stem, title, section, body, toks, origin=md.name))

        for line in md.read_text(encoding="utf-8").splitlines():
            if line.startswith(">"):
                continue
            if line.lower().startswith("ключевые слова:"):
                keywords.append(line.split(":", 1)[1])
                continue
            if line.startswith("# "):
                title = line[2:].strip()
            elif line.startswith("## "):
                flush()
                section, buf, keywords = line[3:].strip(), [], []
            else:
                buf.append(line)
        flush()
        return chunks

    @staticmethod
    def chunks_from_qa(rows) -> list[KbChunk]:
        chunks = []
        for r in rows:
            question, answer = r["question"].strip(), r["answer"].strip()
            toks = tokenize(f"{question} {question}") + tokenize(answer)
            chunks.append(KbChunk(f"kb-{r['id']}", r["source"].strip(), question, answer, toks,
                                  origin=f"knowledge_base#{r['id']}"))
        return chunks

    def search(self, query: str, k: int = 3) -> list[KbHit]:
        q_terms = set(tokenize(query))
        if not q_terms or not self.chunks:
            return []
        hits = []
        for chunk, tf in zip(self.chunks, self._tf):
            dl = len(chunk.tokens)
            score, matched = 0.0, 0
            for t in q_terms:
                f = tf.get(t, 0)
                if not f:
                    continue
                matched += 1
                score += self._idf[t] * f * (self.K1 + 1) / (f + self.K1 * (1 - self.B + self.B * dl / self._avgdl))
            if score > 0:
                hits.append(KbHit(chunk, score, matched / len(q_terms)))
        return sorted(hits, key=lambda h: h.score, reverse=True)[:k]
