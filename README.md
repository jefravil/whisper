# Whisper Dictation

App de escritorio para dictado por voz en Linux. Transcribe tu voz a texto con un atajo de teclado. **100% local** — no usa servicios en la nube.

## Características

- **Icono flotante**: Widget compacto y arrastrable, siempre visible. Cambia de icono según el estado (idle/grabando/procesando)
- **Toggle dictation**: Presiona el atajo una vez para grabar, otra vez para detener (o se detiene por silencio)
- **100% offline**: Usa faster-whisper (Whisper de OpenAI optimizado con CTranslate2 + cuantización INT8)
- **Panel de configuración**: Clic en el icono despliega un panel completo con todos los ajustes
- **Comandos por voz por idioma**: Cada idioma tiene su propio set de comandos configurables (ej: "nueva línea" en español, "new line" en inglés). Se pueden crear, modificar y eliminar desde el panel. Matching accent-insensitive
- **Noise gate inteligente**: Auto-detiene la grabación tras N segundos de silencio (default: 10s, configurable con decimales)
- **Auto-detección de micrófono**: Selecciona el mejor dispositivo automáticamente. Se puede cambiar desde el panel
- **Modo clipboard**: Copia al portapapeles en vez de escribir (default: off)
- **Salida en terminal**: Opción para imprimir la transcripción en la consola (default: off)
- **Streaming incremental**: Transcripción en tiempo real mientras hablas. Transcribe solo audio nuevo cada 2s y acumula resultados para no perder texto en sesiones largas (default: off)
- **Multi-idioma**: Combobox con 16+ idiomas (default: español)
- **Atajo configurable**: Captura de hotkey visual — clic en el campo y presiona tu combinación
- **Hotwords**: Palabras prioritarias para mejorar reconocimiento de nombres propios y términos técnicos
- **Temperature fallback**: Reintenta transcripción con temperaturas progresivas si la primera falla
- **Anti-alucinación**: Filtra texto fantasma generado durante silencios
- **Anti-repetición**: Penaliza tokens repetidos y bloquea N-grams duplicados
- **Output confiable**: Usa xclip+xdotool (Linux) o win32 API (Windows) para pegar texto sin pérdida de caracteres

## Requisitos

- Linux (X11 o Wayland) o Windows 10+
- Python 3.10+
- **Linux**: PortAudio, xclip, xdotool: `sudo apt install libportaudio2 xclip xdotool`
- **Windows**: No requiere herramientas adicionales (usa PowerShell para clipboard)
- aplay (Linux, para feedback sonoro, viene con ALSA)

## Instalación

```bash
# Clonar el repositorio
git clone git@github.com:jefravil/whisper.git
cd whisper

# Crear y activar entorno virtual
python3 -m venv ../env_whisper
source ../env_whisper/bin/activate

# Instalar dependencias (versiones exactas pineadas)
pip install -r requirements.txt
```

El modelo de Whisper se descarga automáticamente en la primera ejecución (~1GB para `small`).

## Uso

```bash
source ../activate_env.sh
python -m src.main
```

1. Aparece un icono flotante en la esquina superior derecha
2. El modelo se carga en background (el icono muestra estado "procesando")
3. Cuando esté listo, presiona `Ctrl+Shift+Space` para grabar
4. Habla al micrófono
5. Presiona el atajo de nuevo para detener, o espera el silencio automático (10s)
6. El texto se escribe en la aplicación activa

### Iconos de estado

| Icono | Estado |
|---|---|
| Azul (micrófono) | Listo / idle |
| Verde (engranaje) | Hover / configuración |
| Rojo (micrófono) | Grabando |
| Dorado (micrófono) | Procesando transcripción |

### Panel de configuración

Clic en el icono para abrir el panel. Desde ahí puedes:

- Cambiar idioma, micrófono y modelo de Whisper
- Activar/desactivar: clipboard, streaming, comandos de voz, salida en terminal
- Ajustar el tiempo de silencio del noise gate (valores decimales como 5.5 o 10.0)
- Cambiar el atajo de grabación (clic en el campo → presiona tu combinación)
- Agregar, ver o eliminar comandos de voz
- Clic derecho en el icono → Salir

## Configuración por archivo

También puedes editar `config.toml` directamente:

```toml
[general]
language = "es"
model = "small"
compute_type = "int8"
device = "cpu"

[hotkey]
combination = "<ctrl>+<shift>+space"

[audio]
device = "auto"         # "auto", "default", índice ("4"), o nombre ("USB")

[clipboard]
enabled = false

[streaming]
enabled = false

[noise_gate]
enabled = true
silence_seconds = 10.0  # Acepta decimales

[output]
print_to_terminal = false

[transcription]
hotwords = "Jeff, Quito, Guayaquil, UNESCO"  # Palabras prioritarias
initial_prompt = "Dictado en español con puntuación correcta."
hallucination_silence_threshold = 0.5  # Filtro anti-alucinación
repetition_penalty = 1.1               # Anti-repetición (1.0 = off)
no_repeat_ngram_size = 3               # Bloquea N-grams repetidos (0 = off)

[voice_commands]
enabled = true

[voice_commands.es]
commands = [
    { trigger = "nueva línea", action = "newline" },
    { trigger = "punto", action = "insert", value = "." },
    { trigger = "coma", action = "insert", value = "," },
]

[voice_commands.en]
commands = [
    { trigger = "new line", action = "newline" },
    { trigger = "period", action = "insert", value = "." },
    { trigger = "comma", action = "insert", value = "," },
]
```

### Modelos disponibles

| Modelo | RAM aprox. | Velocidad | Precisión |
|---|---|---|---|
| tiny | ~1 GB | Muy rápido | Baja |
| base | ~1 GB | Rápido | Media |
| small | ~2 GB | Balanceado | Buena |
| medium | ~5 GB | Lento | Alta |
| large-v3 | ~10 GB | Muy lento | Máxima |

## Estructura del Proyecto

```
whisper/
├── CLAUDE.md              # Guía de desarrollo para IA
├── README.md              # Este archivo
├── config.toml            # Configuración del usuario
├── requirements.txt       # Dependencias con versiones exactas
├── src/
│   ├── __init__.py
│   ├── main.py            # Entry point y controlador principal
│   ├── ui.py              # Icono flotante + panel de config (tkinter)
│   ├── audio.py           # Captura de audio (ring buffer)
│   ├── transcriber.py     # Pipeline STT (faster-whisper + VAD)
│   ├── hotkey.py          # Hotkey toggle + captura de atajo
│   ├── output.py          # Escritura de texto / clipboard
│   ├── config.py          # Carga/validación de config TOML
│   └── voice_commands.py  # Procesador de comandos por voz
└── assets/
    ├── icons/
    │   ├── default_whisper_icon.png
    │   ├── recording_whisper_icon.png
    │   ├── processing_whisper_icon.png
    │   └── settings_whisper_icon.png
    └── sounds/
        ├── start.wav
        └── stop.wav
```

## Licencia

MIT
