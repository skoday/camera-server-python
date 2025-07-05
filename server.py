import eventlet
eventlet.monkey_patch()

import cv2
import base64
import time
import os
from datetime import datetime
from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import requests

# --- Globals ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret-key-for-socketio'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

video_capture = None
camera_lock = eventlet.semaphore.Semaphore(1)
is_streaming = False
is_auto_capturing = False
auto_capture_interval = 3
auto_capture_prompt = "What is in this picture?"
connected_clients = 0
responses_history = []
auto_capture_timer = None

# --- Camera Management ---

def initialize_camera():
    global video_capture
    with camera_lock:
        if video_capture is not None:
            video_capture.release()
        video_capture = cv2.VideoCapture(0)
        if not video_capture.isOpened():
            video_capture = None
            print("❌ Could not open camera.")
            return False
        video_capture.set(cv2.CAP_PROP_FRAME_WIDTH, 672)
        video_capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 672)
        print("✅ Camera initialized.")
        return True

def release_camera():
    global video_capture
    with camera_lock:
        if video_capture is not None:
            video_capture.release()
            video_capture = None
            print("📹 Camera released.")

# --- Streaming ---

def capture_and_stream():
    global is_streaming, video_capture, connected_clients
    print("🎬 Starting video stream loop...")
    while is_streaming:
        with camera_lock:
            if video_capture is None or not video_capture.isOpened():
                eventlet.sleep(0.1)
                continue
            if connected_clients > 0:
                ret, frame = video_capture.read()
                if not ret:
                    eventlet.sleep(0.1)
                    continue
                try:
                    _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    jpg_as_text = base64.b64encode(buffer).decode('utf-8')
                    socketio.emit('video_frame', {'image': jpg_as_text})
                except Exception as e:
                    print(f"Error encoding frame: {e}")
        eventlet.sleep(0.03)  # ~30 FPS
    print("🎬 Video stream loop ended.")

# --- Auto Capture ---

def auto_capture_loop():
    global is_auto_capturing, auto_capture_interval
    print("🤖 Auto-capture loop started.")
    while is_auto_capturing:
        # 1. Capture and encode frame
        with camera_lock:
            if video_capture is None or not video_capture.isOpened():
                print("⚠️ Camera not available for auto-capture.")
                eventlet.sleep(auto_capture_interval)
                continue
            ret, frame = video_capture.read()
            if not ret:
                print("⚠️ Error capturing frame.")
                eventlet.sleep(auto_capture_interval)
                continue
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            filename = f'captures/auto_capture_{int(time.time())}.jpg'
            os.makedirs('captures', exist_ok=True)
            cv2.imwrite(filename, frame)
            _, buffer = cv2.imencode('.jpg', frame)
            frame_base64 = base64.b64encode(buffer).decode('utf-8')
        
        # 2. Launch API call in background, don't wait
        socketio.start_background_task(
            analyze_and_emit_auto_capture, frame_base64, timestamp
        )

        # 3. Wait for the next scheduled capture (fixed interval, not API time)
        eventlet.sleep(auto_capture_interval)
    print("🛑 Auto-capture loop stopped.")

def analyze_and_emit_auto_capture(frame_base64, timestamp):
    global responses_history, auto_capture_prompt
    analysis_text = send_to_llm(frame_base64, auto_capture_prompt, "llava:7b")
    response_data = {
        'id': len(responses_history) + 1,
        'timestamp': timestamp,
        'prompt': auto_capture_prompt,
        'response': analysis_text,
        'image_base64': frame_base64,
        'auto_capture': True
    }
    responses_history.append(response_data)
    socketio.emit('new_response', response_data)
    print(f"✅ Auto-capture #{len(responses_history)} complete.")


def execute_capture():
    global video_capture, responses_history, auto_capture_prompt
    with camera_lock:
        if video_capture is None or not video_capture.isOpened():
            print("⚠️ Camera not available for auto-capture.")
            return
        ret, frame = video_capture.read()
        if not ret:
            print("⚠️ Error capturing frame.")
            return
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        filename = f'captures/auto_capture_{int(time.time())}.jpg'
        os.makedirs('captures', exist_ok=True)
        cv2.imwrite(filename, frame)
        _, buffer = cv2.imencode('.jpg', frame)
        frame_base64 = base64.b64encode(buffer).decode('utf-8')
    analysis_text = send_to_llm(frame_base64, auto_capture_prompt, "llava:7b")
    response_data = {
        'id': len(responses_history) + 1,
        'timestamp': timestamp,
        'prompt': auto_capture_prompt,
        'response': analysis_text,
        'image_base64': frame_base64,
        'auto_capture': True
    }
    responses_history.append(response_data)
    socketio.emit('new_response', response_data)
    print(f"✅ Auto-capture #{len(responses_history)} complete.")

# --- API Call ---

def send_to_llm(image_base64, prompt, model="llava:7b"):
    payload = {
        "file": f"auto_capture_{int(time.time())}.jpg",
        "model": model,
        "prompt": prompt,
        "images": [image_base64]
    }
    try:
        print(f"🔄 Sending to LLaVA API: {prompt[:50]}...")
        response = requests.post(
            "http://localhost:8000/llava",
            json=payload,
            timeout=30,
            headers={'Content-Type': 'application/json'}
        )
        response.raise_for_status()
        data = response.json()
        if "response" not in data:
            print("⚠️ API missing 'response' field")
            return "Error: API response format invalid"
        print(f"✅ API responded successfully")
        return data["response"]
    except requests.exceptions.Timeout:
        print("⏰ API request timeout (30s)")
        return "Error: API timeout"
    except requests.exceptions.ConnectionError:
        print("🔌 Could not connect to LLaVA API")
        return "Error: API connection error"
    except requests.exceptions.HTTPError as e:
        print(f"📡 API HTTP Error: {e.response.status_code}")
        return f"Error: HTTP {e.response.status_code}"
    except Exception as e:
        print(f"❌ Unexpected error: {str(e)}")
        return f"Error: {str(e)}"

# --- Flask Routes ---

@app.route('/')
def index():
    return render_template('index.html')

# --- SocketIO Events ---

@socketio.on('connect')
def handle_connect():
    global connected_clients
    connected_clients += 1
    print(f'👤 Client connected. Total: {connected_clients}')
    emit('client_count', {'count': connected_clients}, broadcast=True)
    emit('responses_history', {'history': responses_history})
    emit('auto_capture_state', {
        'is_running': is_auto_capturing,
        'interval': auto_capture_interval,
        'prompt': auto_capture_prompt
    })

@socketio.on('disconnect')
def handle_disconnect():
    global connected_clients
    connected_clients = max(0, connected_clients - 1)
    print(f'👤 Client disconnected. Total: {connected_clients}')
    emit('client_count', {'count': connected_clients}, broadcast=True)

@socketio.on('start_stream')
def handle_start_stream():
    global is_streaming
    if not is_streaming:
        if initialize_camera():
            is_streaming = True
            socketio.start_background_task(capture_and_stream)
            emit('stream_status', {'status': 'running'}, broadcast=True)
            print("📹 Video stream started.")
        else:
            emit('server_message', {'message': 'Error: Could not initialize camera'})

@socketio.on('stop_stream')
def handle_stop_stream():
    global is_streaming
    is_streaming = False
    release_camera()
    emit('stream_status', {'status': 'stopped'}, broadcast=True)
    print("📹 Video stream stopped.")

@socketio.on('start_auto_capture')
def handle_start_auto_capture(data):
    global is_auto_capturing, auto_capture_interval, auto_capture_prompt
    is_auto_capturing = True
    auto_capture_interval = data.get('interval', 3)
    auto_capture_prompt = data.get('prompt', 'What is in this picture?')
    print(f"🚀 Auto-capture every {auto_capture_interval} seconds.")
    socketio.start_background_task(auto_capture_loop)
    emit('auto_capture_started', {
        'interval': auto_capture_interval,
        'prompt': auto_capture_prompt
    }, broadcast=True)

@socketio.on('stop_auto_capture')
def handle_stop_auto_capture():
    global is_auto_capturing
    is_auto_capturing = False
    emit('auto_capture_stopped', broadcast=True)
    print("🛑 Auto-capture stopped.")

@socketio.on('capture_and_analyze')
def handle_capture_and_analyze(data):
    global video_capture
    def analyze_image():
        with camera_lock:
            if video_capture is None or not video_capture.isOpened():
                socketio.emit('analysis_error', {'error': 'Camera not available'})
                return
            ret, frame = video_capture.read()
            if not ret:
                socketio.emit('analysis_error', {'error': 'Error capturing image'})
                return
            timestamp = datetime.now()
            timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S_%f")[:-3]
            folder_path = os.path.expanduser('~/Documents/photos')
            os.makedirs(folder_path, exist_ok=True)
            snapshot_path = os.path.join(folder_path, f"manual_{timestamp_str}.jpg")
            cv2.imwrite(snapshot_path, frame)
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            image_base64 = base64.b64encode(buffer).decode('utf-8')
        prompt = data.get('prompt', 'What is in this picture?')
        model = data.get('model', 'llava:7b')
        socketio.emit('analysis_status', {'status': 'Analyzing with real API...', 'prompt': prompt})
        response = send_to_llm(image_base64, prompt, model)
        response_data = {
            'id': len(responses_history) + 1,
            'timestamp': timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            'prompt': prompt,
            'response': response,
            'model': model,
            'image_path': snapshot_path,
            'auto_capture': False
        }
        responses_history.append(response_data)
        socketio.emit('new_response', response_data)
        socketio.emit('analysis_status', {'status': 'Analysis complete'})
    socketio.start_background_task(analyze_image)

@socketio.on('clear_history')
def handle_clear_history():
    global responses_history
    responses_history = []
    emit('history_cleared', broadcast=True)
    print("🗑️ History cleared.")

if __name__ == '__main__':
    print("🚀 Flask-SocketIO server starting...")
    print("📱 URL: http://127.0.0.1:5000")
    print("🎥 Auto-capture will run independently of user connections.")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
