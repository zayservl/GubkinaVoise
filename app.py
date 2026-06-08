import os
import uuid
import threading
import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import whisper

app = Flask(__name__, static_folder='static')
CORS(app)
app.config['MAX_CONTENT_LENGTH'] = 3 * 1024 * 1024 * 1024  # 3 GB max

# Конфигурация Ollama
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "gemma4:31b-cloud"

# Глобальная модель (загружается один раз)
model = None
tasks = {}

def correct_with_llm(text):
    """Корректировка текста через Ollama"""
    print(f"[Ollama] Начало корректировки...")

    prompt = f"""Ты — профессиональный редактор русских текстов. Выполни глубокую вычитку и редактирование транскрипции.

ИСХОДНАЯ ТРАНСКРИПЦИЯ:
{text}

ЗАДАНИЕ:
1. Исправь ошибки автоматического распознавания речи: опечатки, искаженные термины, отсутствующую или неверную пунктуацию
2. Удали слова-паразиты, затрудняющие чтение
3. Структурируй текст по логическим блокам и диалогам для удобства чтения
4. Исправь специфические IT- и проектные термины (наряд-заказ, ЕДТ, ПСИ, ПМТ, бэкенд, фронтенд, тайм-энд-материал, инкрементно и др.) к общепринятому виду
5. Сохрани оригинальный смысл и стиль речи спикеров

ВЫВОД:
Сначала предоставь полный исправленный и отредактированный вариант транскрипции.
Затем, после разделителя "---КЛЮЧЕВЫЕ ИСПРАВЛЕНИЯ---", добавь список ключевых исправлений в формате:
- [оригинал] → [исправление] (причина)

Исправленный текст:"""

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.2,
                    "num_predict": 8192
                }
            },
            timeout=180
        )

        if response.status_code == 200:
            result = response.json()
            corrected = result.get('response', '').strip()
            print(f"[Ollama] Корректировка завершена")
            return corrected
        else:
            print(f"[Ollama] Ошибка: {response.status_code}")
            return None
    except Exception as e:
        print(f"[Ollama] Исключение: {e}")
        return None

def load_model():
    global model
    print("Загрузка модели Whisper small...")

    # Whisper на CPU стабильнее, MPS имеет ограничения
    device = "cpu"
    print("⚠ Используется CPU (MPS имеет ограничения в текущей версии PyTorch)")

    model = whisper.load_model("small", device=device)
    print(f"Модель загружена на устройстве: {device}")

def transcribe_task(task_id, file_path):
    try:
        tasks[task_id]['status'] = 'transcribing'
        tasks[task_id]['progress'] = 5

        print(f"[Whisper] Начало транскрибации файла: {file_path}")
        result = model.transcribe(
            file_path,
            language='ru',
            task='transcribe'
        )
        print(f"[Whisper] Транскрибация завершена, текст: {len(result['text'])} символов")
        tasks[task_id]['progress'] = 60

        text = result['text'].strip()
        segments = result.get('segments', [])

        # Формируем MD с таймкодами (сырой вариант)
        md_lines = ["# Транскрипция\n"]
        for seg in segments:
            start = format_time(seg['start'])
            end = format_time(seg['end'])
            md_lines.append(f"\n**[{start} - {end}]**")
            md_lines.append(seg['text'].strip())

        md_content = '\n'.join(md_lines)

        # Этап корректировки через Ollama
        tasks[task_id]['status'] = 'correcting'
        tasks[task_id]['progress'] = 70

        corrected_text = correct_with_llm(text)

        tasks[task_id]['progress'] = 95

        # Формируем исправленный MD
        md_corrected_lines = ["# Транскрипция (исправленная)\n"]
        for seg in segments:
            start = format_time(seg['start'])
            end = format_time(seg['end'])
            md_corrected_lines.append(f"\n**[{start} - {end}]**")
            md_corrected_lines.append(seg['text'].strip())

        md_corrected = '\n'.join(md_corrected_lines)

        tasks[task_id]['status'] = 'done'
        tasks[task_id]['progress'] = 100
        tasks[task_id]['result'] = {
            'raw_md': md_content,
            'raw_plain': text,
            'corrected_md': md_corrected if corrected_text else md_content,
            'corrected_plain': corrected_text if corrected_text else text,
            'corrected': bool(corrected_text)
        }

    except Exception as e:
        tasks[task_id]['status'] = 'error'
        tasks[task_id]['error'] = str(e)
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

def format_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/api/transcribe', methods=['POST'])
def transcribe():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    # Сохраняем файл временно
    task_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename)[1].lower()

    allowed_exts = {'.mov', '.mpeg', '.mp3', '.wav', '.mp4'}
    if ext not in allowed_exts:
        return jsonify({'error': f'Unsupported format. Allowed: {", ".join(allowed_exts)}'}), 400

    temp_path = os.path.join('uploads', f"{task_id}{ext}")
    os.makedirs('uploads', exist_ok=True)
    file.save(temp_path)

    # Инициализируем задачу
    tasks[task_id] = {
        'status': 'uploading',
        'progress': 0,
        'filename': file.filename
    }

    # Запускаем транскрибацию в отдельном потоке
    thread = threading.Thread(target=transcribe_task, args=(task_id, temp_path))
    thread.start()

    return jsonify({'task_id': task_id})

@app.route('/api/status/<task_id>')
def status(task_id):
    if task_id not in tasks:
        return jsonify({'error': 'Task not found'}), 404
    return jsonify(tasks[task_id])

@app.route('/api/result/<task_id>')
def result(task_id):
    if task_id not in tasks:
        return jsonify({'error': 'Task not found'}), 404
    task = tasks[task_id]
    if task['status'] != 'done':
        return jsonify({'error': 'Task not completed'}), 400
    return jsonify(task['result'])

if __name__ == '__main__':
    # Загружаем модель в основном потоке при старте
    load_model()
    from waitress import serve
    print("Сервер запущен на http://localhost:5001")
    serve(app, host='0.0.0.0', port=5001)