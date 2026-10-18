#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

WITH_AI=1
for arg in "$@"; do
  [ "$arg" = "--no-ai" ] && WITH_AI=0
done

if ! command -v python3 >/dev/null 2>&1; then
  echo "Не найден python3. Установите Python 3.10+ с https://www.python.org/downloads/"
  exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "Нужен Python 3.10 или новее, сейчас: $(python3 --version)"
  exit 1
fi

if [ ! -d .venv ]; then
  echo "▸ Создаю виртуальное окружение .venv"
  python3 -m venv .venv
fi
source .venv/bin/activate

echo "▸ Устанавливаю зависимости"
python -m pip install -q --upgrade pip
pip install -q -r requirements.txt

if [ "$WITH_AI" = "1" ]; then
  if ! python -c "import llama_cpp" >/dev/null 2>&1; then
    echo "▸ Устанавливаю движок нейросети llama-cpp-python (первый раз собирается 5–15 минут)"
    if [ "$(uname)" = "Darwin" ] && ! xcode-select -p >/dev/null 2>&1; then
      echo "  Нужны инструменты разработчика Apple. Выполните: xcode-select --install, затем снова ./start.sh"
      echo "  Пока запускаю без нейросети."
    else
      if [ "$(uname)" = "Darwin" ] && [ "$(uname -m)" = "x86_64" ]; then
        export CMAKE_ARGS="-DGGML_METAL=OFF"
      fi
      pip install -r requirements-ai.txt || echo "  Не удалось установить llama-cpp-python — ассистент будет отвечать цитатами из базы знаний."
    fi
  fi
  if python -c "import llama_cpp" >/dev/null 2>&1; then
    python scripts/download_model.py || echo "  Модель не скачана — ассистент будет отвечать цитатами из базы знаний."
  fi
else
  export AI_MODE=off
fi

PORT="${PORT:-8000}"
echo ""
echo "════════════════════════════════════════════"
echo "  Сайт:     http://localhost:$PORT"
echo "  API:      http://localhost:$PORT/docs"
echo "  Вход:     employee@janamen.kz / Passw0rd!"
echo "  Стоп:     Ctrl+C"
echo "════════════════════════════════════════════"
( sleep 3; (command -v open >/dev/null && open "http://localhost:$PORT") || (command -v xdg-open >/dev/null && xdg-open "http://localhost:$PORT") ) >/dev/null 2>&1 &
exec uvicorn app.main:app --port "$PORT"
