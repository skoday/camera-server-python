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

def auto_capture_task():
    """
    Tarea independiente de autocaptura que funciona SIN importar si hay usuarios conectados
    Esta función corre en background y sigue capturando aunque no haya clientes
    """
    global is_auto_capturing, video_capture, responses_history, auto_capture_interval, auto_capture_prompt
    
    print("🤖 Iniciando autocaptura independiente...")
    
    while is_auto_capturing:
        if video_capture is None or not video_capture.isOpened():
            print("⚠️ Cámara no disponible para autocaptura, reintentando...")
            eventlet.sleep(1)
            continue
            
        try:
            # Capturar frame actual
            ret, frame = video_capture.read()
            if not ret:
                print("⚠️ Error capturando frame, reintentando...")
                eventlet.sleep(1)
                continue
            
            # Guardar snapshot con timestamp
            timestamp = datetime.now()
            timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S_%f")[:-3]  # Incluir milisegundos
            folder_path = os.path.expanduser('~/Documents/photos')
            os.makedirs(folder_path, exist_ok=True)
            snapshot_path = os.path.join(folder_path, f"snapshot_{timestamp_str}.jpg")
            cv2.imwrite(snapshot_path, frame)
            
            print(f"📸 Snapshot guardado: {snapshot_path}")
            
            # Codificar imagen para LLM
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            image_base64 = base64.b64encode(buffer).decode('utf-8')
            
            print(f"🧠 Enviando al LLM: '{auto_capture_prompt}'")
            
            # Enviar al LLM (usando stub)
            response = send_to_llm(image_base64, auto_capture_prompt, "llava:7b")
            
            # Guardar en historial
            response_data = {
                'id': len(responses_history) + 1,
                'timestamp': timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                'prompt': auto_capture_prompt,
                'response': response,
                'model': 'llava:7b',
                'image_path': snapshot_path,
                'auto_capture': True  # Marca para identificar capturas automáticas
            }
            responses_history.append(response_data)
            
            print(f"✅ Respuesta #{response_data['id']}: {response[:50]}...")
            
            # Emitir respuesta a TODOS los clientes conectados (si los hay)
            # Si no hay clientes conectados, se almacena igual y lo verán cuando se conecten
            socketio.emit('new_response', response_data)
            socketio.emit('auto_capture_status', {
                'status': f'Captura automática #{response_data["id"]} completada',
                'next_in': auto_capture_interval
            })
            
        except Exception as e:
            print(f"❌ Error en autocaptura: {e}")
            socketio.emit('auto_capture_error', {'error': str(e)})
        
        # Esperar el intervalo configurado
        eventlet.sleep(auto_capture_interval)
    
    print("🛑 Autocaptura detenida")

def llm_stub(image_base64, prompt, model="llava:7b"):
    """Stub del LLM con respuestas más realistas"""
    eventlet.sleep(random.uniform(0.5, 2))  # Simular tiempo de procesamiento
    
    responses = [
        f"I can see various objects and activity in this image. The scene appears to be captured from a camera perspective showing an indoor environment.",
        f"The image shows what appears to be a workspace or living area with multiple items visible in the frame.",
        f"I observe a scene with furniture and personal belongings, suggesting this is a residential or office setting.",
        f"This appears to be a real-time camera feed showing movement and objects in what looks like an indoor space.",
        f"The captured image contains various elements including what might be electronics, furniture, and other household items."
    ]
    
    base_response = random.choice(responses)
    timestamp_info = f" [Analyzed at {datetime.now().strftime('%H:%M:%S')} by {model} stub]"
    
    return base_response + timestamp_info

def send_to_llm(image_base64, prompt, model="llava:7b"):
    """Enviar imagen al LLM"""
    return llm_stub(image_base64, prompt, model)

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
    global is_streaming
    is_streaming = False
    emit('stream_status', {'status': 'stopped'}, broadcast=True)
    print("📹 Stream de video detenido")

@socketio.on('start_auto_capture')
def handle_start_auto_capture(data):
    global is_auto_capturing, auto_capture_interval, auto_capture_prompt
    
    if not is_auto_capturing:
        # Configurar parámetros
        auto_capture_interval = data.get('interval', 3)
        auto_capture_prompt = data.get('prompt', 'What is in this picture?')
        
        # Asegurar que la cámara esté inicializada
        if not initialize_camera():
            emit('server_message', {'message': 'Error: No se pudo inicializar la cámara para autocaptura'})
            return
        
        is_auto_capturing = True
        
        # Iniciar tarea de autocaptura independiente
        socketio.start_background_task(auto_capture_task)
        
        emit('auto_capture_started', {
            'interval': auto_capture_interval,
            'prompt': auto_capture_prompt
        }, broadcast=True)
        
        print(f"🤖 Autocaptura iniciada: cada {auto_capture_interval}s con prompt: '{auto_capture_prompt}'")

@socketio.on('stop_auto_capture')
def handle_stop_auto_capture():
    global is_auto_capturing
    is_auto_capturing = False
    emit('auto_capture_stopped', broadcast=True)
    print("🤖 Autocaptura detenida por usuario")

@socketio.on('capture_and_analyze')
def handle_capture_and_analyze(data):
    """Captura manual individual"""
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
            folder_path = os.path.expanduser('~/Documents/photos')
            os.makedirs(folder_path, exist_ok=True)
            snapshot_path = os.path.join(folder_path, f"manual_{timestamp_str}.jpg")
            cv2.imwrite(snapshot_path, frame)
            
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            image_base64 = base64.b64encode(buffer).decode('utf-8')
            
            prompt = data.get('prompt', 'What is in this picture?')
            model = data.get('model', 'llava:7b')
            
            socketio.emit('analysis_status', {'status': 'Analizando imagen...', 'prompt': prompt})
            
            response = send_to_llm(image_base64, prompt, model)
            
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
    
    socketio.run(app, host='127.0.0.1', port=5000, debug=True)
