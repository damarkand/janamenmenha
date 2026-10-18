#!/usr/bin/env bash
# Запуск всех автотестов с отчётом о покрытии. Использование: ./run_tests.sh [аргументы pytest]
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "Создаю виртуальное окружение .venv..."
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt
pytest --cov=app --cov-report=term-missing --cov-report=html "$@"
echo ""
echo "HTML-отчёт о покрытии: htmlcov/index.html  (открыть: open htmlcov/index.html)"
