# Whisper Dictation App - CLAUDE.md

## Proyecto
App de escritorio local para dictado por voz en Linux. Sin dependencias de nube. Push-to-talk con atajo de teclado configurable.

## Stack Tecnológico
- **Python 3.10** (venv en `../env_whisper/`)
- **STT Engine**: `faster-whisper` con CTranslate2 (cuantización INT8)
- **VAD**: Silero VAD (integrado en faster-whisper)
- **Audio Capture**: `sounddevice` (PortAudio)
- **Hotkey Global**: `pynput`
- **Output de Texto**: `pynput` keyboard controller + `xdotool` fallback
- **System Tray**: `pystray` + `Pillow`
- **Config**: TOML (`tomli` para leer, `tomli-w` para escribir)
- **Streaming** (opcional): `whisper-streaming` wrapper

## Estructura del Proyecto
```
whisper/
├── CLAUDE.md
├── README.md
├── config.toml              # Configuración del usuario
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── main.py              # Entry point + system tray
│   ├── audio.py             # Captura de audio (ring buffer)
│   ├── transcriber.py       # Pipeline STT (faster-whisper + VAD)
│   ├── hotkey.py            # Listener de atajos globales
│   ├── output.py            # Escritura de texto / clipboard
│   ├── config.py            # Carga/validación de config TOML
│   └── voice_commands.py    # Procesador de comandos por voz
└── assets/
    ├── icon_idle.png
    ├── icon_recording.png
    ├── icon_processing.png
    └── sounds/
        ├── start.wav
        └── stop.wav
```

## Features (orden de implementación - Feature First)

### F1: Core Dictation (MVP)
- Hotkey presionado → captura audio → transcribe → escribe texto en app activa
- Ring buffer para captura de audio (memoria constante, sin allocations)
- Model warm-up al iniciar la app (elimina lag en primera transcripción)
- Thread pool: hotkey listener, audio capture, inferencia STT (sin bloqueo de UI)

### F2: Sistema de Configuración
- Archivo `config.toml` con todas las opciones
- Hotkey configurable
- Modelo de Whisper seleccionable (tiny, base, small, medium, large)
- Idioma seleccionable via Combobox (default: español). NO auto-detección.
- Dispositivo de audio configurable

### F3: Comandos por Voz
- Palabras de comando configurables por el usuario en `config.toml`
- Defaults: "nueva línea" → Enter, "punto" → ".", "coma" → ","
- Se procesan post-transcripción antes de output

### F4: System Tray + Feedback
- Icono que cambia: idle → grabando → procesando
- Sonido corto al iniciar/detener grabación
- Menú contextual: configuración, idioma, quit

### F5: Modo Clipboard
- **Default: DESACTIVADO**
- Toggle en config y system tray
- Cuando activo: texto va al portapapeles en vez de escribirse

### F6: Noise Gate Inteligente
- Silero VAD + timeout configurable por el usuario (N segundos de silencio)
- Auto-detiene grabación tras N segundos sin voz
- N configurable en `config.toml`

### F7: Streaming en Tiempo Real
- **Default: DESACTIVADO**
- Toggle en config y system tray
- Muestra texto mientras el usuario habla (whisper-streaming wrapper)

## Principios de Desarrollo

### Algoritmos y Optimización
- **Cuantización INT8** en faster-whisper → mitad de latencia y memoria vs FP32
- **Silero VAD** pre-filtro → recorta silencio antes de transcribir, mejora velocidad y accuracy
- **Ring buffer** (collections.deque con maxlen) para audio → O(1) append, memoria constante
- **Model warm-up** con audio dummy al iniciar → primera transcripción sin cold start
- **Lazy loading** de modelos → solo carga el modelo seleccionado
- **Thread dedicado** para cada subsistema → sin contención

### Buenas Prácticas
- Feature-first: cada feature debe funcionar independientemente
- No crear abstracciones prematuras ni helpers innecesarios
- No agregar error handling especulativo — solo validar en boundaries (input de usuario, audio device, archivo de config)
- Código directo y legible, sin sobre-ingeniería
- Tests solo donde agreguen valor real (pipeline STT, voice commands parsing)
- Cada cambio o adición al proyecto DEBE actualizar el README.md

### Config TOML - Estructura esperada
```toml
[general]
language = "es"           # Idioma por defecto: español
model = "small"           # tiny, base, small, medium, large
hotkey = "<ctrl>+<shift>+space"

[audio]
device = "default"
sample_rate = 16000

[clipboard]
enabled = false           # Default: desactivado

[streaming]
enabled = false           # Default: desactivado

[noise_gate]
enabled = true
silence_seconds = 3       # Configurable por el usuario

[voice_commands]
enabled = true
commands = [
    { trigger = "nueva línea", action = "newline" },
    { trigger = "punto", action = "insert", value = "." },
    { trigger = "coma", action = "insert", value = "," },
    { trigger = "borrar última palabra", action = "delete_last_word" },
    { trigger = "signo de interrogación", action = "insert", value = "?" },
    { trigger = "signo de exclamación", action = "insert", value = "!" },
]
```

## Comandos Útiles
```bash
# Activar entorno virtual
source /home/jeff/whisper_ws/activate_env.sh

# Instalar dependencias
pip install -r requirements.txt

# Ejecutar la app
python -m src.main

# Descargar modelo de Whisper (se hace automáticamente en primer uso)
# Los modelos se guardan en ~/.cache/huggingface/
```
