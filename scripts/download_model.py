import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import Settings

HF = "https://huggingface.co"


def find_file(repo: str, wanted: str) -> str:
    try:
        with urllib.request.urlopen(f"{HF}/api/models/{repo}", timeout=30) as r:
            files = [s["rfilename"] for s in json.loads(r.read()).get("siblings", [])]
    except Exception:
        return wanted
    if wanted in files:
        return wanted
    tag = "q4_k_m"
    for f in files:
        if f.lower().endswith(".gguf") and tag in f.lower() and "-of-" not in f.lower():
            return f
    return wanted


def download(url: str, target: Path) -> None:
    part = target.with_suffix(target.suffix + ".part")
    have = part.stat().st_size if part.exists() else 0
    req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
    with urllib.request.urlopen(req, timeout=60) as r:
        if have and r.status != 206:
            have = 0
        total = have + int(r.headers.get("Content-Length") or 0)
        mode = "ab" if have else "wb"
        done, t0 = have, time.time()
        with open(part, mode) as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    speed = (done - have) / max(time.time() - t0, 0.1) / 1e6
                    sys.stdout.write(f"\r  {done / 1e9:.2f} / {total / 1e9:.2f} ГБ  ({done * 100 // total}%)  {speed:.1f} МБ/с ")
                    sys.stdout.flush()
    print()
    part.rename(target)


def main() -> int:
    s = Settings()
    target = Path(s.ai_model_path)
    if target.exists() and target.stat().st_size > 100_000_000:
        print(f"Модель уже скачана: {target}")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    name = find_file(s.ai_model_repo, s.ai_model_file)
    url = f"{HF}/{s.ai_model_repo}/resolve/main/{name}"
    print(f"Скачиваю {name} (~2 ГБ) из {s.ai_model_repo}")
    print("Если связь оборвётся — запустите команду ещё раз, загрузка продолжится.")
    try:
        download(url, target)
    except KeyboardInterrupt:
        print("\nОстановлено. Повторный запуск продолжит загрузку.")
        return 1
    except Exception as exc:
        print(f"\nНе удалось скачать модель: {exc}")
        print(f"Можно скачать вручную по ссылке:\n  {url}\nи положить файл сюда:\n  {target}")
        return 1
    print(f"Готово: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
