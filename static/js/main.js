const socket = io();
const serverCamera = document.getElementById('serverCamera');
const cameraPlaceholder = document.getElementById('cameraPlaceholder');
const connectionStatus = document.getElementById('connectionStatus');
const clientCount = document.getElementById('clientCount');
const streamStatus = document.getElementById('streamStatus');
const startBtn = document.getElementById('startBtn');
const stopBtn = document.getElementById('stopBtn');
const captureBtn = document.getElementById('captureBtn');
const prompt = document.getElementById('prompt');
const response = document.getElementById('response');
const responsesTableBody = document.querySelector('#responsesTable tbody');
const clearHistoryBtn = document.getElementById('clearHistoryBtn');
const startAutoBtn = document.getElementById('startAutoBtn');
const stopAutoBtn = document.getElementById('stopAutoBtn');
const autoInterval = document.getElementById('autoInterval');

// Eventos de Socket.IO - LIMPIADOS Y SIN DUPLICADOS
socket.on('connect', () => {
    connectionStatus.textContent = 'Conectado';
    connectionStatus.className = 'status-connected';
    socket.emit('start_stream');
});

socket.on('disconnect', () => {
    connectionStatus.textContent = 'Desconectado';
    connectionStatus.className = 'status-disconnected';
});

socket.on('video_frame', (data) => {
    serverCamera.src = 'data:image/jpeg;base64,' + data.image;
    serverCamera.style.display = 'block';
    cameraPlaceholder.style.display = 'none';
});

socket.on('client_count', (data) => {
    clientCount.textContent = data.count;
});

socket.on('stream_status', (data) => {
    if (data.status === 'running') {
        streamStatus.textContent = '▶️ Stream activo';
        streamStatus.className = 'status running';
    } else {
        streamStatus.textContent = '⏸️ Stream pausado';
        streamStatus.className = 'status paused';
    }
});

socket.on('new_response', (data) => {
    addResponseToTable(data);
    response.value = data.response;
});

socket.on('responses_history', (data) => {
    data.history.forEach(response => addResponseToTable(response));
});

socket.on('history_cleared', () => {
    responsesTableBody.innerHTML = '';
    response.value = '';
});

socket.on('analysis_error', (data) => {
    response.value = 'Error: ' + data.error;
});

// Eventos de autocaptura del backend - SISTEMA LIMPIO
socket.on('auto_capture_started', (data) => {
    startAutoBtn.disabled = true;
    stopAutoBtn.disabled = false;
    autoInterval.disabled = true;
    streamStatus.textContent = `🤖 Auto-captura activa (cada ${data.interval}s)`;
    streamStatus.className = 'status running';
});

socket.on('auto_capture_stopped', () => {
    startAutoBtn.disabled = false;
    stopAutoBtn.disabled = true;
    autoInterval.disabled = false;
    streamStatus.textContent = '⏸️ Auto-captura detenida';
    streamStatus.className = 'status paused';
});

socket.on('auto_capture_state', (data) => {
    if (data.is_running) {
        startAutoBtn.disabled = true;
        stopAutoBtn.disabled = false;
        autoInterval.disabled = true;
        streamStatus.textContent = `🤖 Auto-captura activa (cada ${data.interval}s)`;
        streamStatus.className = 'status running';
    }
});

// Event listeners - SOLO SISTEMA BACKEND (SIN setInterval)
startBtn.addEventListener('click', () => {
    socket.emit('start_stream');
});

stopBtn.addEventListener('click', () => {
    socket.emit('stop_stream');
});

captureBtn.addEventListener('click', () => {
    const promptText = prompt.value.trim() || 'What is in this picture?';
    socket.emit('capture_and_analyze', { prompt: promptText });
});

clearHistoryBtn.addEventListener('click', () => {
    socket.emit('clear_history');
});

// AUTOCAPTURA - SOLO SISTEMA BACKEND (SIN setInterval local)
startAutoBtn.addEventListener('click', () => {
    const interval = parseInt(autoInterval.value);
    const promptText = prompt.value.trim() || 'What is in this picture?';
    socket.emit('start_auto_capture', { 
        interval: interval, 
        prompt: promptText 
    });
});

stopAutoBtn.addEventListener('click', () => {
    socket.emit('stop_auto_capture');
});

// Función auxiliar
function addResponseToTable(data) {
    const row = responsesTableBody.insertRow(0);
    row.innerHTML = `
        <td>${data.id}</td>
        <td>${data.timestamp}</td>
        <td>${data.prompt}</td>
        <td>${data.response}</td>
    `;
}