"""Speech-to-text pipeline using faster-whisper with Silero VAD.

Key optimizations:
- INT8 quantization via CTranslate2 for ~2x speed and ~50% memory vs FP32
- Silero VAD pre-filters silence segments before transcription
- Model warm-up with dummy audio eliminates cold-start latency
- Thread-safe: a lock prevents concurrent transcriptions (critical for streaming)
"""

import logging
import threading

import numpy as np
from faster_whisper import WhisperModel

log = logging.getLogger(__name__)

# Warm-up: 1 second of silence at 16kHz
_WARMUP_AUDIO = np.zeros(16000, dtype=np.float32)


class Transcriber:
    """Wraps faster-whisper with VAD and model lifecycle management.

    Thread-safety: a lock ensures only one transcription runs at a time.
    This is critical when streaming (partial transcriptions) is enabled,
    to prevent the streaming thread and the final transcription from
    corrupting each other's model state.
    """

    def __init__(self, model_size: str = "small", device: str = "cpu",
                 compute_type: str = "int8", language: str = "es",
                 hotwords: str = "", initial_prompt: str = "",
                 hallucination_silence_threshold: float | None = 0.5,
                 repetition_penalty: float = 1.1,
                 no_repeat_ngram_size: int = 3):
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._language = language
        self._hotwords = hotwords
        self._initial_prompt = initial_prompt
        self._hallucination_silence_threshold = hallucination_silence_threshold
        self._repetition_penalty = repetition_penalty
        self._no_repeat_ngram_size = no_repeat_ngram_size
        self._model: WhisperModel | None = None
        self._lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def language(self) -> str:
        return self._language

    @language.setter
    def language(self, value: str) -> None:
        self._language = value

    def load_model(self) -> None:
        """Load the Whisper model and warm it up with dummy audio."""
        log.info("Loading model '%s' (device=%s, compute=%s)...",
                 self._model_size, self._device, self._compute_type)

        self._model = WhisperModel(
            self._model_size,
            device=self._device,
            compute_type=self._compute_type,
        )

        log.info("Warming up model...")
        segments, _ = self._model.transcribe(
            _WARMUP_AUDIO,
            language=self._language,
            vad_filter=False,
        )
        for _ in segments:
            pass
        log.info("Model ready.")

    def transcribe(self, audio: np.ndarray, use_vad: bool = True) -> str:
        """Transcribe audio array to text. Thread-safe (blocking lock).

        Args:
            audio: float32 numpy array at 16kHz, shape (n_samples,).
            use_vad: Whether to use Silero VAD to filter silence.

        Returns:
            Transcribed text string. Empty string if no speech detected.
        """
        with self._lock:
            return self._transcribe_internal(audio, use_vad)

    def try_transcribe(self, audio: np.ndarray, use_vad: bool = True) -> str | None:
        """Non-blocking transcription. Returns None if the model is busy.

        Used by the streaming thread to avoid blocking when the final
        transcription is running. Uses lightweight mode for faster partials.
        """
        acquired = self._lock.acquire(blocking=False)
        if not acquired:
            return None
        try:
            return self._transcribe_internal(audio, use_vad, lightweight=True)
        finally:
            self._lock.release()

    def _transcribe_internal(self, audio: np.ndarray, use_vad: bool,
                             lightweight: bool = False) -> str:
        """Internal transcription logic. Must be called with lock held.

        Args:
            audio: float32 numpy array at 16kHz.
            use_vad: Whether to use Silero VAD to filter silence.
            lightweight: If True, skips heavy params (for streaming partials).
        """
        if self._model is None:
            self.load_model()

        if audio.size == 0:
            return ""

        vad_params = {
            "threshold": 0.5,
            "min_silence_duration_ms": 300,
            "speech_pad_ms": 400,
        }

        # Base transcription params
        params: dict = {
            "language": self._language,
            "vad_filter": use_vad,
            "vad_parameters": vad_params if use_vad else None,
            "beam_size": 5,
            "best_of": 5,
            "without_timestamps": not lightweight,
            # Temperature fallback: tries 0.0 first, retries with higher temps
            # if compression_ratio or log_prob thresholds fail
            "temperature": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
            "compression_ratio_threshold": 2.4,
            "log_prob_threshold": -1.0,
            # No-speech detection: skips segments with no voice
            "no_speech_threshold": 0.6,
            # Anti-repetition
            "repetition_penalty": self._repetition_penalty,
            "no_repeat_ngram_size": self._no_repeat_ngram_size,
        }

        # Hotwords bias the model toward specific vocabulary
        if self._hotwords:
            params["hotwords"] = self._hotwords

        # Initial prompt sets context/style for the decoder
        if self._initial_prompt:
            params["initial_prompt"] = self._initial_prompt

        # Hallucination filter (needs word timestamps, skip for streaming)
        if not lightweight and self._hallucination_silence_threshold:
            params["word_timestamps"] = True
            params["hallucination_silence_threshold"] = self._hallucination_silence_threshold
            params["without_timestamps"] = False

        segments, info = self._model.transcribe(audio, **params)

        parts = []
        for segment in segments:
            text = segment.text.strip()
            if text:
                parts.append(text)

        return " ".join(parts)

    def unload_model(self) -> None:
        """Release model from memory."""
        self._model = None
        log.info("Model unloaded.")
