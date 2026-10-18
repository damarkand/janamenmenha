@echo off
cd /d "%~dp0"
if not exist .venv (
  echo Создаю виртуальное окружение .venv
  python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -q --upgrade pip
pip install -q -r requirements.txt
python -c "import llama_cpp" 2>nul || pip install llama-cpp-python --prefer-binary --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
python -c "import llama_cpp" 2>nul && python scripts\download_model.py
echo.
echo   Сайт: http://localhost:8000    API: http://localhost:8000/docs
echo   Вход: employee@janamen.kz / Passw0rd!
start "" http://localhost:8000
uvicorn app.main:app --port 8000
