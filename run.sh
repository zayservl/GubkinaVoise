#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Активация виртуального окружения
source "$SCRIPT_DIR/venv/bin/activate"

# Проверка Ollama
if ! pgrep -x "ollama" > /dev/null 2>&1; then
    echo "🚀 Запуск Ollama..."
    ollama serve &
    sleep 3

    # Проверяем модель
    if ! ollama list | grep -q "gemma4:31b-cloud"; then
        echo "📥 Загрузка модели gemma4:31b-cloud..."
        ollama pull gemma4:31b-cloud
    fi
else
    echo "✓ Ollama уже запущен"
fi

# Запуск приложения
echo "🎙️ Запуск Whisper Transcriber..."
cd "$SCRIPT_DIR"
python app.py