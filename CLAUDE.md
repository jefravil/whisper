# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Desktop voice dictation app. Captures audio via hotkey toggle, transcribes with faster-whisper (local, no cloud), and outputs text to the active application. Cross-platform: developed and working on Linux (X11/Wayland), currently being ported/tested on Windows 10+.

## Commands

```bash
# Activate virtual environment
# Linux:
source ../env_whisper/bin/activate
# Windows:
..\env_whisper\Scripts\activate
# Or use: activar_entorno.bat (from whisper_ws root on Windows)

# Install dependencies
pip install -r requirements.txt

# Run the app (from the whisper/ directory)
python -m src.main
```

## Architecture

**Entry point**: `src/main.py` — `WhisperDictationApp` is the central controller. It wires together all modules and manages the recording lifecycle:
1. Hotkey pressed → `_on_hotkey_activate()` → starts audio capture + noise gate + streaming timers
2. Hotkey pressed again (or silence timeout) → `_on_hotkey_deactivate()` → stops capture → transcribes → processes voice commands → outputs text

**Module responsibilities**:
- `src/ui.py` — Floating tkinter widget (72px draggable icon) with expandable settings panel. State-driven icon changes (idle/recording/processing/loading). All config changes go through the app controller back to `config.py`.
- `src/audio.py` — Audio capture via `sounddevice`. Uses a ring buffer (`deque` of numpy chunks, max 30 min). Lazy-imports sounddevice to avoid PortAudio errors in headless environments.
- `src/transcriber.py` — Wraps `faster-whisper` with INT8 quantization, Silero VAD, and model warm-up. Thread-safe via lock (critical for streaming mode where partial and final transcriptions can overlap). `try_transcribe()` is non-blocking for streaming ticks.
- `src/hotkey.py` — Global hotkey listener via `pynput`. Toggle mode: first press activates, second deactivates. Also handles hotkey capture for the settings panel.
- `src/output.py` — Text output with two strategies: Linux uses `xclip` + `xdotool` for reliable paste; Windows uses win32 clipboard API + pynput Ctrl+V. Avoids pynput's `type()` due to X11 character-drop bug.
- `src/voice_commands.py` — Post-transcription processing. Matches trigger phrases (accent-insensitive) and converts to actions (newline, insert punctuation, delete last word). Commands are per-language in `config.toml`.
- `src/config.py` — Loads/saves `config.toml` via `tomli`/`tomli-w`. Defines `AppConfig` dataclass and all defaults.

**Threading model**: UI runs on the main thread (tkinter mainloop). Model loading, hotkey listener, noise gate checks (every 0.5s), and streaming ticks (every 2s) each run on daemon threads. The transcriber lock serializes all inference calls.

**Config**: `config.toml` is the single source of truth for all settings. Voice commands are organized per-language (`[voice_commands.es]`, `[voice_commands.en]`, etc.). The settings panel reads/writes this file through `AppConfig`.

## Platform Differences

- **Audio feedback**: Linux uses `aplay` (ALSA); Windows support for sound playback may need an alternative.
- **Text output**: Linux uses `xclip` + `xdotool`; Windows uses win32 clipboard API via `ctypes` + pynput Ctrl+V.
- **Dependencies**: `python-xlib` and `evdev` are Linux-only (in requirements.txt); they will fail to install on Windows. `sounddevice` requires PortAudio on Linux (`libportaudio2`), bundled on Windows.

## Key Design Decisions

- **Clipboard-paste for output** (not `pynput.type()`): Works around a confirmed pynput bug (#437) that drops characters on X11.
- **Incremental streaming**: Transcribes only new audio each tick and accumulates parts, preventing text loss in long sessions.
- **Noise gate uses RMS energy** (threshold 0.015) checked every 0.5s, not VAD, for silence detection during recording. VAD is used only during transcription to filter silence segments.
- **Model warm-up**: Runs a dummy transcription on load to eliminate cold-start latency.

## Development Rules

- Each change or addition to the project MUST update README.md.
- Feature-first: each feature should work independently.
- No premature abstractions or speculative error handling — validate only at boundaries (user input, audio device, config file).
