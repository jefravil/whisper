"""Audio capture module using sounddevice with ring buffer.

Uses a pre-allocated numpy ring buffer for O(1) append and constant memory.
Audio is captured at 16kHz mono (Whisper's expected format).
"""

import threading
from collections import deque

import numpy as np

# Lazy import: sounddevice requires PortAudio system library.
# Deferring import avoids ImportError when running in environments
# without audio hardware (CI, headless servers).
sd = None

# 16-bit PCM → float32 range [-1.0, 1.0] is what sounddevice gives us
# Whisper expects float32 numpy array at 16kHz mono
DTYPE = np.float32


def _ensure_sounddevice():
    global sd
    if sd is None:
        import sounddevice as _sd
        sd = _sd

# Ring buffer stores chunks of audio. At 16kHz with 1024-sample chunks,
# each chunk is ~64ms. Max 30 min of audio = ~28125 chunks.
MAX_CHUNKS = 30000
CHUNK_SIZE = 1024


class AudioRecorder:
    """Records audio from microphone into a ring buffer.

    The ring buffer (deque with maxlen) guarantees:
    - O(1) append per chunk
    - Constant memory ceiling (MAX_CHUNKS * CHUNK_SIZE * 4 bytes)
    - Automatic eviction of oldest data when full
    """

    def __init__(self, sample_rate: int = 16000, channels: int = 1,
                 device: str | None = None):
        _ensure_sounddevice()
        self._sample_rate = sample_rate
        self._channels = channels
        self._device = None if device == "default" else device
        self._buffer: deque[np.ndarray] = deque(maxlen=MAX_CHUNKS)
        self._stream = None
        self._recording = False
        self._lock = threading.Lock()

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def _audio_callback(self, indata: np.ndarray, frames: int,
                        time_info, status) -> None:
        """Called by sounddevice from its own thread for each audio chunk."""
        if status:
            pass  # Drop status warnings silently in production
        # indata shape: (frames, channels). Squeeze to 1D for mono.
        self._buffer.append(indata[:, 0].copy())

    def start(self) -> None:
        """Start recording audio from microphone."""
        with self._lock:
            if self._recording:
                return
            self._buffer.clear()
            self._stream = sd.InputStream(
                samplerate=self._sample_rate,
                channels=self._channels,
                dtype=DTYPE,
                blocksize=CHUNK_SIZE,
                device=self._device,
                callback=self._audio_callback,
            )
            self._stream.start()
            self._recording = True

    def stop(self) -> np.ndarray:
        """Stop recording and return captured audio as a single float32 array.

        Returns:
            numpy array of shape (n_samples,) with float32 values in [-1, 1].
            Empty array if nothing was recorded.
        """
        with self._lock:
            if not self._recording:
                return np.array([], dtype=DTYPE)
            self._stream.stop()
            self._stream.close()
            self._stream = None
            self._recording = False

            if not self._buffer:
                return np.array([], dtype=DTYPE)

            # Concatenate all chunks into single contiguous array
            audio = np.concatenate(list(self._buffer))
            self._buffer.clear()
            return audio

    def get_current_audio(self) -> np.ndarray:
        """Get audio captured so far without stopping the recording.
        Used for streaming transcription.
        """
        if not self._buffer:
            return np.array([], dtype=DTYPE)
        return np.concatenate(list(self._buffer))

    def set_device(self, device_index: int | None) -> None:
        """Change the recording device. Takes effect on next start()."""
        self._device = device_index

    @staticmethod
    def list_devices() -> list[dict]:
        """List available audio input devices."""
        _ensure_sounddevice()
        devices = sd.query_devices()
        inputs = []
        for i, dev in enumerate(devices):
            if dev["max_input_channels"] > 0:
                inputs.append({
                    "index": i,
                    "name": dev["name"],
                    "channels": dev["max_input_channels"],
                    "sample_rate": dev["default_samplerate"],
                })
        return inputs

    @staticmethod
    def pick_best_device() -> dict | None:
        """Auto-select the best microphone based on heuristics.

        Priority order:
        1. PulseAudio/PipeWire "default" — routes to the user's selected mic
           AND handles sample rate conversion transparently (critical: Whisper
           needs 16kHz but hardware devices often only support 44.1/48kHz)
        2. PulseAudio/PipeWire named device — same resampling benefit
        3. Raw ALSA hw: devices — last resort, can fail with "Invalid sample
           rate" if the hardware doesn't support 16kHz natively

        Returns the best device dict, or None if no devices found.
        """
        devices = AudioRecorder.list_devices()
        if not devices:
            return None

        def _score(dev: dict) -> int:
            name = dev["name"].lower()
            # "default" is the PulseAudio/PipeWire default sink — best choice
            # because it follows the user's system audio settings and resamples
            if name == "default":
                return 100
            # PulseAudio/PipeWire also handles resampling
            if "pulse" in name or "pipewire" in name:
                return 90
            # Raw ALSA hw: devices do NOT resample — risky at 16kHz
            # Only use as last resort
            if "hw:" in name:
                return 10
            return 50

        devices.sort(key=_score, reverse=True)
        return devices[0]
