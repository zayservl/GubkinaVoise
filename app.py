import os
import uuid
import threading
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import whisper

app = Flask(__name__, static_folder='static')
CORS(app)

# Глобальная модель (загружается один раз)
model = None
tasks = {}

def load_model():
    global model
    print("Загрузка модели Whisper small...")
    model = whisper.load_model("small")
    print("Модель загружена!")

def transcribe_task(task_id, file_path):
    try:
        tasks[task_id]['status'] = 'transcribing'
        tasks[task_id]['progress'] = 10

        result = model.transcribe(
            file_path,
            language=None,  # auto-detect
            task='transcribe'
        )

        tasks[task_id]['progress'] = 90

        text = result['text'].strip()
        segments = result.get('segments', [])

        # Формируем MD с таймкодами
        md_lines = ["# Транскрипция\n"]
        for seg in segments:
            start = format_time(seg['start'])
            end = format_time(seg['end'])
            md_lines.append(f"\n**[{start} - {end}]**")
            md_lines.append(seg['text'].strip())

        md_content = '\n'.join(md_lines)
        plain_content = text

        tasks[task_id]['status'] = 'done'
        tasks[task_id]['progress'] = 100
        tasks[task_id]['result'] = {
            'md': md_content,
            'plain': plain_content
        }

    except Exception as e:
        tasks[task_id]['status'] = 'error'
        tasks[task_id]['error'] = str(e)
    finally:
        # Удаляем временный файл
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

    allowed_exts = {'.mov', '.mpeg', '.mp3', '.wav'}
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
    app.run(host='0.0.0.0', port=5000, debug=False)