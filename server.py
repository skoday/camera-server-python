import cv2
import base64
import time
import os
from flask import Flask, render_template
from flask_socketio import SocketIO
import eventlet

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# Variables globales
video_capture = None
is_streaming = False

def initialize_camera():
    """Inicializar la cámara con configuración de 672x672"""
    global video_capture
    video_capture = cv2.VideoCapture(0)
    video_capture.set(cv2.CAP_PROP_FRAME_WIDTH, 672)
    video_capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 672)
    return video_capture.isOpened()

def capture_and_stream():
    """Capturar frames y enviarlos a todos los clientes conectados"""
    global is_streaming, video_capture
    
    # Crear carpeta para snapshots
    folder_path = os.path.expanduser('~/Documents/photos')
    os.makedirs(folder_path, exist_ok=True)
    
    start_time = time.time()
    snapshot_count = 0
    
    while is_streaming:
        if video_capture is None or not video_capture.isOpened():
            break
            
        ret, frame = video_capture.read()
        if not ret:
            continue
        
        # Guardar snapshot cada 2 segundos
        current_time = time.time()
        if current_time - start_time >= 2:
            snapshot_path = os.path.join(folder_path, f"snapshot_{snapshot_count}.jpg")
            cv2.imwrite(snapshot_path, frame)
            print(f"Snapshot guardado: {snapshot_path}")
            snapshot_count += 1
            start_time = current_time
        
        # Codificar frame para transmisión
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        jpg_as_text = base64.b64encode(buffer).decode('utf-8')
        
        # Enviar frame a todos los clientes conectados
        socketio.emit('video_frame', {'image': jpg_as_text})
        
        eventlet.sleep(0.03)  # ~30 FPS

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    print('Cliente conectado')
    socketio.emit('status', {'message': 'Conectado al stream de cámara'})

@socketio.on('disconnect')
def handle_disconnect():
    print('Cliente desconectado')

@socketio.on('start_stream')
def handle_start_stream():
    global is_streaming
    if not is_streaming and initialize_camera():
        is_streaming = True
        socketio.start_background_task(capture_and_stream)
        socketio.emit('status', {'message': 'Stream iniciado'})
    else:
        socketio.emit('status', {'message': 'Error al iniciar la cámara'})

@socketio.on('stop_stream')
def handle_stop_stream():
    global is_streaming, video_capture
    is_streaming = False
    if video_capture:
        video_capture.release()
        video_capture = None
    socketio.emit('status', {'message': 'Stream detenido'})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
