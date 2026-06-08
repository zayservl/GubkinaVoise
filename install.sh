#!/bin/bash
set -e

echo "Создание виртуального окружения..."
python3 -m venv venv

echo "Активация и установка зависимостей..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "Готово! Для запуска: ./run.sh"