import eventlet
eventlet.monkey_patch()

import cv2
import base64
import time
import os
import json
from datetime import datetime
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import random
import threading
import requests
import json
import threading
from datetime import datetime

# Variables globales para control de estado
auto_capture_timer = None
auto_capture_lock = threading.Lock()  # Para thread safety


app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret-key-for-socketio'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Variables globales
video_capture = None
is_streaming = False
is_auto_capturing = False
auto_capture_interval = 3  # segundos por defecto
auto_capture_prompt = "What is in this picture?"
connected_clients = 0
responses_history = []

def initialize_camera():
    """Inicializar la cámara con configuración de 672x672"""
    global video_capture
    try:
        video_capture = cv2.VideoCapture(0)
        if not video_capture.isOpened():
            return False
        video_capture.set(cv2.CAP_PROP_FRAME_WIDTH, 672)
        video_capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 672)
        return True
    except Exception as e:
        print(f"Error inicializando cámara: {e}")
        return False

def capture_and_stream():
    """Capturar frames y enviarlos SOLO a los clientes conectados para el video stream"""
    global is_streaming, video_capture, connected_clients
    
    while is_streaming:
        if video_capture is None or not video_capture.isOpened():
            eventlet.sleep(0.1)
            continue
            
        # Solo procesar frames si hay clientes conectados (optimización)
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
                print(f"Error codificando frame para stream: {e}")
        
        eventlet.sleep(0.03)  # ~30 FPS

import threading
from datetime import datetime, timedelta

# Variable global para el timer
auto_capture_timer = None

def auto_capture_task():
    """Inicializar sistema de autocaptura con scheduler preciso"""
    global is_auto_capturing, auto_capture_timer
    
    print("🤖 Iniciando autocaptura con scheduler preciso...")
    
    if is_auto_capturing:
        schedule_next_capture()

def schedule_next_capture():
    """Programar la próxima captura de forma precisa"""
    global auto_capture_timer, is_auto_capturing, auto_capture_interval
    
    if not is_auto_capturing:
        return
    
    # Cancelar timer anterior si existe
    if auto_capture_timer is not None:
        auto_capture_timer.cancel()
    
    # Programar próxima captura exactamente en N segundos
    auto_capture_timer = threading.Timer(auto_capture_interval, execute_capture)
    auto_capture_timer.start()
    
    print(f"⏰ Próxima captura programada en {auto_capture_interval} segundos exactos")

def execute_capture():
    """Ejecutar una sola captura y programar la siguiente"""
    global video_capture, responses_history, auto_capture_prompt, is_auto_capturing
    
    if not is_auto_capturing:
        return
    
    # IMPORTANTE: Programar la siguiente ANTES de procesar
    schedule_next_capture()
    
    if video_capture is None or not video_capture.isOpened():
        print("⚠️ Cámara no disponible para autocaptura")
        return
    
    try:
        ret, frame = video_capture.read()
        if not ret:
            print("⚠️ Error capturando frame")
            return
        
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"📸 Ejecutando captura automática: {timestamp}")
        
        # Guardar imagen localmente
        filename = f'captures/auto_capture_{int(time.time())}.jpg'
        os.makedirs('captures', exist_ok=True)
        cv2.imwrite(filename, frame)
        
        # Convertir a base64
        _, buffer = cv2.imencode('.jpg', frame)
        frame_base64 = base64.b64encode(buffer).decode('utf-8')
        
        # Llamada al API (sin afectar el timing)
        analysis_text = send_to_llm(frame_base64, auto_capture_prompt, "llava:7b")
        
        # Agregar al historial
        responses_history.append({
            'id': len(responses_history) + 1,
            'timestamp': timestamp,
            'prompt': auto_capture_prompt,
            'response': analysis_text,
            'image_base64': frame_base64,
            'auto_capture': True
        })
        
        # Emitir a clientes conectados
        socketio.emit('new_response', responses_history[-1])
        
        print(f"✅ Captura #{len(responses_history)} completada y programada siguiente")
        
    except Exception as e:
        print(f"❌ Error en captura automática: {e}")


def send_to_llm(image_base64, prompt, model="llava:7b"):
    """Enviar imagen al API real de LLaVA"""
    
    # Preparar payload según especificación
    payload = {
        "file": f"auto_capture_{int(time.time())}.jpg",
        "model": model,
        "prompt": prompt,
        "images": [image_base64]
    }
    
    try:
        print(f"🔄 Enviando al API LLaVA: {prompt[:50]}...")
        
        response = requests.post(
            "http://10.3.56.6:8000/llava",
            json=payload,
            timeout=30,  # 30 segundos timeout
            headers={'Content-Type': 'application/json'}
        )
        
        # Verificar status HTTP
        response.raise_for_status()
        
        # Parsear respuesta JSON
        data = response.json()
        
        if "response" not in data:
            print("⚠️ API respondió sin campo 'response'")
            return "Error: API response format invalid"
        
        print(f"✅ API respondió exitosamente")
        return data["response"]
        
    except requests.exceptions.Timeout:
        error_msg = "⏰ API request timeout (30s)"
        print(error_msg)
        return f"Error: {error_msg}"
        
    except requests.exceptions.ConnectionError:
        error_msg = "🔌 No se pudo conectar al API LLaVA"
        print(error_msg)
        return f"Error: {error_msg}"
        
    except requests.exceptions.HTTPError as e:
        error_msg = f"📡 API HTTP Error: {e.response.status_code}"
        print(error_msg)
        return f"Error: {error_msg}"
        
    except requests.exceptions.JSONDecodeError:
        error_msg = "📄 API response is not valid JSON"
        print(error_msg)
        return f"Error: {error_msg}"
        
    except Exception as e:
        error_msg = f"❌ Unexpected error: {str(e)}"
        print(error_msg)
        return f"Error: {error_msg}"


@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    global connected_clients
    connected_clients += 1
    print(f'👤 Cliente conectado. Total: {connected_clients}')
    emit('client_count', {'count': connected_clients}, broadcast=True)
    
    # Enviar historial completo al cliente que se conecta
    emit('responses_history', {'history': responses_history})
    
    # Enviar estado actual de autocaptura
    emit('auto_capture_state', {
        'is_running': is_auto_capturing,
        'interval': auto_capture_interval,
        'prompt': auto_capture_prompt
    })

@socketio.on('disconnect')
def handle_disconnect():
    global connected_clients
    connected_clients = max(0, connected_clients - 1)
    print(f'👤 Cliente desconectado. Total: {connected_clients}')
    emit('client_count', {'count': connected_clients}, broadcast=True)

@socketio.on('start_stream')
def handle_start_stream():
    global is_streaming
    if not is_streaming:
        if initialize_camera():
            is_streaming = True
            socketio.start_background_task(capture_and_stream)
            emit('stream_status', {'status': 'running'}, broadcast=True)
            print("📹 Stream de video iniciado")
        else:
            emit('server_message', {'message': 'Error: No se pudo inicializar la cámara'})

@socketio.on('stop_stream')
def handle_stop_stream():
    global is_streaming, video_capture
    is_streaming = False
    
    # AGREGAR: Liberar la cámara explícitamente
    if video_capture is not None:
        video_capture.release()
        video_capture = None
        print("📹 Cámara liberada - LED debería apagarse")
    
    emit('stream_status', {'status': 'stopped'}, broadcast=True)
    print("📹 Stream de video detenido")

@socketio.on('start_auto_capture')
def handle_start_auto_capture(data):
    global is_auto_capturing, auto_capture_interval, auto_capture_prompt
    
    is_auto_capturing = True
    auto_capture_interval = data.get('interval', 3)
    auto_capture_prompt = data.get('prompt', 'What is in this picture?')
    
    print(f"🚀 Iniciando autocaptura cada {auto_capture_interval} segundos")
    
    # Usar threading en lugar de eventlet para esta tarea
    threading.Thread(target=auto_capture_task, daemon=True).start()
    
    emit('auto_capture_started', {
        'interval': auto_capture_interval,
        'prompt': auto_capture_prompt
    }, broadcast=True)


@socketio.on('stop_auto_capture')
def handle_stop_auto_capture():
    global is_auto_capturing, auto_capture_timer
    
    is_auto_capturing = False
    
    # Cancelar timer pendiente
    if auto_capture_timer is not None:
        auto_capture_timer.cancel()
        auto_capture_timer = None
    
    emit('auto_capture_stopped', broadcast=True)
    print("🛑 Autocaptura detenida - Timer cancelado")


@socketio.on('capture_and_analyze')
def handle_capture_and_analyze(data):
    """Captura manual individual con API real"""
    global video_capture
    
    if video_capture is None or not video_capture.isOpened():
        emit('analysis_error', {'error': 'Cámara no disponible'})
        return
    
    def analyze_image():
        try:
            ret, frame = video_capture.read()
            if not ret:
                socketio.emit('analysis_error', {'error': 'Error capturando imagen'})
                return
            
            timestamp = datetime.now()
            timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S_%f")[:-3]
            
            # Guardar imagen
            folder_path = os.path.expanduser('~/Documents/photos')
            os.makedirs(folder_path, exist_ok=True)
            snapshot_path = os.path.join(folder_path, f"manual_{timestamp_str}.jpg")
            cv2.imwrite(snapshot_path, frame)
            
            # Convertir a base64
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            image_base64 = base64.b64encode(buffer).decode('utf-8')
            
            # Obtener parámetros
            prompt = data.get('prompt', 'What is in this picture?')
            model = data.get('model', 'llava:7b')
            
            socketio.emit('analysis_status', {'status': 'Analizando con API real...', 'prompt': prompt})
            
            # *** LLAMADA REAL AL API ***
            response = send_to_llm(image_base64, prompt, model)
            
            # Guardar en historial
            response_data = {
                'id': len(responses_history) + 1,
                'timestamp': timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                'prompt': prompt,
                'response': response,
                'model': model,
                'image_path': snapshot_path,
                'auto_capture': False  # Captura manual
            }
            
            responses_history.append(response_data)
            socketio.emit('new_response', response_data)
            socketio.emit('analysis_status', {'status': 'Análisis completado'})
            
        except Exception as e:
            socketio.emit('analysis_error', {'error': f'Error en análisis: {str(e)}'})
    
    socketio.start_background_task(analyze_image)


@socketio.on('clear_history')
def handle_clear_history():
    global responses_history
    responses_history = []
    emit('history_cleared', broadcast=True)
    print("🗑️ Historial limpiado")

if __name__ == '__main__':
    print("🚀 Iniciando servidor Flask-SocketIO...")
    print("📱 URL: http://127.0.0.1:5000")
    print("🎥 La autocaptura funcionará independientemente de conexiones de usuarios")
    
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
