"""Whisper Dictation App - Entry point.

Connects all modules: hotkey listener (toggle mode), audio recorder,
transcriber, voice commands, output, and floating widget UI.
"""

import logging
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

from src.audio import AudioRecorder
from src.config import (
    AppConfig,
    load_config,
    save_config,
)
from src.hotkey import HotkeyListener
from src.output import output_actions
from src.transcriber import Transcriber
from src.ui import DictationWidget
from src.voice_commands import CommandAction, process_text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("whisper-dictation")

SOUNDS_DIR = Path(__file__).parent.parent / "assets" / "sounds"


def _play_sound(name: str) -> None:
    """Play a feedback sound asynchronously using aplay (ALSA)."""
    path = SOUNDS_DIR / f"{name}.wav"
    if path.exists():
        try:
            subprocess.Popen(
                ["aplay", "-q", str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            pass


class WhisperDictationApp:
    """Main application controller.

    Recording flow (toggle mode):
    - User presses hotkey → start recording (icon turns red)
    - User presses hotkey again OR silence timeout → stop → transcribe → output
    """

    def __init__(self):
        self._config: AppConfig = load_config()
        self._available_devices = AudioRecorder.list_devices()
        resolved_device = self._resolve_audio_device()

        self._recorder = AudioRecorder(
            sample_rate=self._config.sample_rate,
            channels=self._config.channels,
            device=resolved_device,
        )
        self._transcriber = Transcriber(
            model_size=self._config.model,
            device=self._config.device,
            compute_type=self._config.compute_type,
            language=self._config.language,
            hotwords=self._config.hotwords,
            initial_prompt=self._config.initial_prompt,
            hallucination_silence_threshold=self._config.hallucination_silence_threshold,
            repetition_penalty=self._config.repetition_penalty,
            no_repeat_ngram_size=self._config.no_repeat_ngram_size,
        )
        self._hotkey: HotkeyListener | None = None
        self._widget: DictationWidget | None = None
        self._noise_gate_timer: threading.Timer | None = None
        self._streaming_timer: threading.Timer | None = None
        self._stream_parts: list[str] = []
        self._stream_last_pos = 0
        self._processing = False
        self._current_device_index: int | None = resolved_device

    def _resolve_audio_device(self) -> int | None:
        """Resolve the configured audio device to a sounddevice index."""
        setting = self._config.audio_device

        if setting == "auto":
            best = AudioRecorder.pick_best_device()
            if best:
                log.info("Auto-selected audio device: [%d] %s",
                         best["index"], best["name"])
                return best["index"]
            log.warning("No input devices found, using system default")
            return None

        if setting == "default":
            return None

        try:
            idx = int(setting)
            if any(d["index"] == idx for d in self._available_devices):
                return idx
            log.warning("Device index %d not found, auto-detecting", idx)
        except ValueError:
            for dev in self._available_devices:
                if setting.lower() in dev["name"].lower():
                    log.info("Matched device by name: [%d] %s",
                             dev["index"], dev["name"])
                    return dev["index"]
            log.warning("Device '%s' not found, auto-detecting", setting)

        best = AudioRecorder.pick_best_device()
        return best["index"] if best else None

    def _on_hotkey_activate(self) -> None:
        """Toggle ON — start recording."""
        if self._processing:
            return

        log.info("Recording started")
        if self._config.audio_feedback:
            _play_sound("start")

        self._recorder.start()
        if self._widget:
            self._widget.set_status("recording")

        if self._config.noise_gate_enabled:
            self._start_noise_gate()

        if self._config.streaming_enabled:
            self._start_streaming()

    def _on_hotkey_deactivate(self) -> None:
        """Toggle OFF — stop recording and transcribe."""
        if not self._recorder.is_recording:
            return

        self._cancel_noise_gate()
        self._cancel_streaming()
        self._processing = True
        if self._widget:
            self._widget.set_status("processing")

        if self._config.audio_feedback:
            _play_sound("stop")

        audio = self._recorder.stop()
        duration = len(audio) / self._config.sample_rate
        log.info("Recording stopped: %.1f seconds of audio", duration)

        # Notify hotkey listener that recording stopped
        # (important for noise gate triggered stops)
        if self._hotkey:
            self._hotkey.notify_stopped()

        if audio.size == 0:
            log.warning("No audio captured")
            self._processing = False
            if self._widget:
                self._widget.set_status("idle")
            return

        text = self._transcriber.transcribe(
            audio, use_vad=self._config.noise_gate_enabled,
        )
        log.info("Transcription: '%s'", text)

        if text:
            # Print to terminal if enabled
            if self._config.print_to_terminal:
                print(f"\n>>> {text}\n", flush=True)

            cmds = self._config.get_commands_for_language()
            if self._config.voice_commands_enabled and cmds:
                actions = process_text(text, cmds)
            else:
                actions = [CommandAction(action="text", value=text)]

            output_actions(actions, clipboard_mode=self._config.clipboard_enabled)

        self._processing = False
        if self._widget:
            self._widget.hide_streaming_text()
            self._widget.set_status("idle")

    def _start_noise_gate(self) -> None:
        """Monitor audio and auto-stop after continuous silence >= threshold.

        Checks every 0.5s. Tracks when silence began and only triggers
        when silence has lasted >= silence_seconds continuously.
        Speech resets the silence counter.
        """
        self._silence_since: float | None = None

        def check_silence():
            if not self._recorder.is_recording:
                return

            audio = self._recorder.get_current_audio()
            if audio.size > self._config.sample_rate:
                # Check the last 0.5s of audio for energy
                check_samples = int(self._config.sample_rate * 0.5)
                last_chunk = audio[-check_samples:]
                rms = np.sqrt(np.mean(last_chunk ** 2))

                if rms < 0.015:
                    # Silence detected — start or continue tracking
                    if self._silence_since is None:
                        self._silence_since = time.monotonic()
                    elapsed = time.monotonic() - self._silence_since
                    if elapsed >= self._config.silence_seconds:
                        log.info("Noise gate: %.1fs of continuous silence",
                                 elapsed)
                        self._on_hotkey_deactivate()
                        return
                else:
                    # Speech detected — reset silence counter
                    self._silence_since = None

            # Re-check every 500ms
            self._noise_gate_timer = threading.Timer(0.5, check_silence)
            self._noise_gate_timer.daemon = True
            self._noise_gate_timer.start()

        # Start checking 1s after recording begins (startup buffer)
        self._noise_gate_timer = threading.Timer(1.0, check_silence)
        self._noise_gate_timer.daemon = True
        self._noise_gate_timer.start()

    def _cancel_noise_gate(self) -> None:
        if self._noise_gate_timer:
            self._noise_gate_timer.cancel()
            self._noise_gate_timer = None

    # === Streaming (real-time partial transcription) ===

    def _start_streaming(self) -> None:
        """Periodically transcribe only NEW audio and accumulate partial results.

        Every 2 seconds, takes only the audio captured since the last tick,
        transcribes that chunk, appends the result to accumulated parts,
        and shows the full accumulated text in the floating overlay.
        This prevents earlier content from being lost as audio grows.
        """
        self._stream_parts: list[str] = []
        self._stream_last_pos = 0

        def _stream_tick():
            if not self._recorder.is_recording:
                return

            audio = self._recorder.get_current_audio()
            new_samples = audio.size - self._stream_last_pos
            # Need at least 2s of new audio for a meaningful transcription
            min_new = self._config.sample_rate * 2
            if new_samples >= min_new:
                new_audio = audio[self._stream_last_pos:]
                # Non-blocking: skip if the model is busy (final transcription)
                text = self._transcriber.try_transcribe(new_audio, use_vad=True)
                if text is not None and text.strip():
                    self._stream_parts.append(text.strip())
                    self._stream_last_pos = audio.size
                    full_text = " ".join(self._stream_parts)
                    if self._widget:
                        self._widget.show_streaming_text(full_text)

            # Schedule next tick
            self._streaming_timer = threading.Timer(2.0, _stream_tick)
            self._streaming_timer.daemon = True
            self._streaming_timer.start()

        # First partial transcription after 2 seconds
        self._streaming_timer = threading.Timer(2.0, _stream_tick)
        self._streaming_timer.daemon = True
        self._streaming_timer.start()

    def _cancel_streaming(self) -> None:
        if self._streaming_timer:
            self._streaming_timer.cancel()
            self._streaming_timer = None
        self._stream_parts = []
        self._stream_last_pos = 0

    def shutdown(self) -> None:
        """Clean shutdown of all components."""
        log.info("Shutting down...")
        self._cancel_noise_gate()
        self._cancel_streaming()
        if self._recorder.is_recording:
            self._recorder.stop()
        if self._hotkey:
            self._hotkey.stop()
        self._transcriber.unload_model()

    def run(self) -> None:
        """Start the application."""
        log.info("=" * 50)
        log.info("Whisper Dictation App")
        log.info("=" * 50)
        log.info("Language: %s", self._config.language)
        log.info("Model: %s (%s on %s)", self._config.model,
                 self._config.compute_type, self._config.device)
        log.info("Hotkey: %s (toggle mode)", self._config.hotkey_combination)
        log.info("Clipboard: %s | Streaming: %s | Terminal: %s",
                 self._config.clipboard_enabled,
                 self._config.streaming_enabled,
                 self._config.print_to_terminal)
        log.info("Noise gate: %s (%.1fs)",
                 self._config.noise_gate_enabled, self._config.silence_seconds)
        log.info("Voice commands: %s (%d commands)",
                 self._config.voice_commands_enabled,
                 len(self._config.voice_commands))

        dev_name = "System default"
        if self._current_device_index is not None:
            match = next(
                (d for d in self._available_devices
                 if d["index"] == self._current_device_index), None,
            )
            if match:
                dev_name = f"[{match['index']}] {match['name']}"
        log.info("Audio device: %s", dev_name)
        log.info("=" * 50)

        # Build the floating widget
        self._widget = DictationWidget(self)
        root = self._widget.build()

        # Show "loading" while model loads
        self._widget.set_status("loading")

        def _load_and_start():
            log.info("Loading STT model (first run downloads ~1GB)...")
            self._transcriber.load_model()

            self._hotkey = HotkeyListener(
                combination=self._config.hotkey_combination,
                on_activate=self._on_hotkey_activate,
                on_deactivate=self._on_hotkey_deactivate,
            )
            self._hotkey.start()

            log.info("Ready! Press %s to start/stop dictation.",
                     self._config.hotkey_combination)
            self._widget.set_status("idle")

        # Load in background so UI appears immediately
        threading.Thread(target=_load_and_start, daemon=True).start()

        # Run UI (blocks)
        self._widget.run()


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = WhisperDictationApp()
    app.run()


if __name__ == "__main__":
    main()
