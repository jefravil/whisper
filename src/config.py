"""Configuration loader for Whisper Dictation App."""

from dataclasses import dataclass, field
from pathlib import Path

import tomli
import tomli_w


CONFIG_PATH = Path(__file__).parent.parent / "config.toml"

SUPPORTED_LANGUAGES = {
    "es": "Español",
    "en": "English",
    "fr": "Français",
    "de": "Deutsch",
    "pt": "Português",
    "it": "Italiano",
    "ja": "日本語",
    "zh": "中文",
    "ko": "한국어",
    "ru": "Русский",
    "ar": "العربية",
    "hi": "हिन्दी",
    "nl": "Nederlands",
    "pl": "Polski",
    "tr": "Türkçe",
    "ca": "Català",
}

SUPPORTED_MODELS = ("tiny", "base", "small", "medium", "large-v3")

COMPUTE_TYPES = ("int8", "float16", "float32")

# Default voice commands per language
DEFAULT_VOICE_COMMANDS: dict[str, list[dict]] = {
    "es": [
        {"trigger": "nueva línea", "action": "newline"},
        {"trigger": "punto", "action": "insert", "value": "."},
        {"trigger": "coma", "action": "insert", "value": ","},
        {"trigger": "signo de interrogación", "action": "insert", "value": "?"},
        {"trigger": "signo de exclamación", "action": "insert", "value": "!"},
        {"trigger": "dos puntos", "action": "insert", "value": ":"},
        {"trigger": "punto y coma", "action": "insert", "value": ";"},
        {"trigger": "borrar última palabra", "action": "delete_last_word"},
        {"trigger": "espacio", "action": "insert", "value": " "},
    ],
    "en": [
        {"trigger": "new line", "action": "newline"},
        {"trigger": "period", "action": "insert", "value": "."},
        {"trigger": "comma", "action": "insert", "value": ","},
        {"trigger": "question mark", "action": "insert", "value": "?"},
        {"trigger": "exclamation mark", "action": "insert", "value": "!"},
        {"trigger": "colon", "action": "insert", "value": ":"},
        {"trigger": "semicolon", "action": "insert", "value": ";"},
        {"trigger": "delete last word", "action": "delete_last_word"},
        {"trigger": "space", "action": "insert", "value": " "},
    ],
    "fr": [
        {"trigger": "nouvelle ligne", "action": "newline"},
        {"trigger": "point", "action": "insert", "value": "."},
        {"trigger": "virgule", "action": "insert", "value": ","},
        {"trigger": "point d'interrogation", "action": "insert", "value": "?"},
        {"trigger": "point d'exclamation", "action": "insert", "value": "!"},
        {"trigger": "supprimer dernier mot", "action": "delete_last_word"},
    ],
    "de": [
        {"trigger": "neue Zeile", "action": "newline"},
        {"trigger": "Punkt", "action": "insert", "value": "."},
        {"trigger": "Komma", "action": "insert", "value": ","},
        {"trigger": "Fragezeichen", "action": "insert", "value": "?"},
        {"trigger": "letztes Wort löschen", "action": "delete_last_word"},
    ],
    "pt": [
        {"trigger": "nova linha", "action": "newline"},
        {"trigger": "ponto", "action": "insert", "value": "."},
        {"trigger": "vírgula", "action": "insert", "value": ","},
        {"trigger": "apagar última palavra", "action": "delete_last_word"},
    ],
}


@dataclass
class VoiceCommand:
    trigger: str
    action: str  # "newline", "insert", "delete_last_word", "backspace"
    value: str = ""


@dataclass
class AppConfig:
    # General
    language: str = "es"
    model: str = "small"
    compute_type: str = "int8"
    device: str = "cpu"

    # Hotkey
    hotkey_combination: str = "<ctrl>+<shift>+space"

    # Audio ("auto" = auto-detect best device on startup)
    audio_device: str = "auto"
    sample_rate: int = 16000
    channels: int = 1

    # Clipboard mode
    clipboard_enabled: bool = False

    # Streaming
    streaming_enabled: bool = False

    # Noise gate
    noise_gate_enabled: bool = True
    silence_seconds: float = 10.0

    # Voice commands per language: dict[lang_code, list[VoiceCommand]]
    voice_commands_enabled: bool = True
    voice_commands: dict[str, list[VoiceCommand]] = field(default_factory=dict)

    # Output
    print_to_terminal: bool = False

    # Feedback
    audio_feedback: bool = True

    # Transcription quality
    hotwords: str = ""  # Comma-separated words to prioritize (names, terms)
    initial_prompt: str = ""  # Context prompt for style/punctuation
    hallucination_silence_threshold: float | None = 0.5  # Filter phantom text
    repetition_penalty: float = 1.1  # Penalize repeated tokens (1.0 = off)
    no_repeat_ngram_size: int = 3  # Block repeating N-grams (0 = off)

    def get_commands_for_language(self, lang: str | None = None) -> list[VoiceCommand]:
        """Get voice commands for a specific language (defaults to current)."""
        lang = lang or self.language
        return self.voice_commands.get(lang, [])


def _parse_commands_list(raw: list[dict]) -> list[VoiceCommand]:
    """Parse a list of command dicts into VoiceCommand objects."""
    return [
        VoiceCommand(
            trigger=cmd["trigger"],
            action=cmd["action"],
            value=cmd.get("value", ""),
        )
        for cmd in raw
    ]


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    """Load configuration from TOML file. Returns defaults if file missing."""
    if not path.exists():
        config = AppConfig()
        # Populate default commands for all supported languages
        for lang, cmds in DEFAULT_VOICE_COMMANDS.items():
            config.voice_commands[lang] = _parse_commands_list(cmds)
        save_config(config, path)
        return config

    with open(path, "rb") as f:
        data = tomli.load(f)

    general = data.get("general", {})
    hotkey = data.get("hotkey", {})
    audio = data.get("audio", {})
    clipboard = data.get("clipboard", {})
    streaming = data.get("streaming", {})
    noise_gate = data.get("noise_gate", {})
    voice_cmds_section = data.get("voice_commands", {})
    output = data.get("output", {})
    feedback = data.get("feedback", {})
    transcription = data.get("transcription", {})

    # Parse voice commands per language
    all_commands: dict[str, list[VoiceCommand]] = {}

    # Check for per-language structure: voice_commands.es, voice_commands.en, etc.
    for key, value in voice_cmds_section.items():
        if key == "enabled":
            continue
        if isinstance(value, dict) and "commands" in value:
            # Per-language: [voice_commands.es] commands = [...]
            all_commands[key] = _parse_commands_list(value["commands"])
        elif key == "commands" and isinstance(value, list):
            # Legacy flat format: voice_commands.commands = [...]
            # Assign to current language
            lang = general.get("language", "es")
            all_commands[lang] = _parse_commands_list(value)

    # Fill in defaults for languages not in config
    for lang, defaults in DEFAULT_VOICE_COMMANDS.items():
        if lang not in all_commands:
            all_commands[lang] = _parse_commands_list(defaults)

    return AppConfig(
        language=general.get("language", "es"),
        model=general.get("model", "small"),
        compute_type=general.get("compute_type", "int8"),
        device=general.get("device", "cpu"),
        hotkey_combination=hotkey.get("combination", "<ctrl>+<shift>+space"),
        audio_device=audio.get("device", "auto"),
        sample_rate=audio.get("sample_rate", 16000),
        channels=audio.get("channels", 1),
        clipboard_enabled=clipboard.get("enabled", False),
        streaming_enabled=streaming.get("enabled", False),
        noise_gate_enabled=noise_gate.get("enabled", True),
        silence_seconds=noise_gate.get("silence_seconds", 10.0),
        voice_commands_enabled=voice_cmds_section.get("enabled", True),
        voice_commands=all_commands,
        print_to_terminal=output.get("print_to_terminal", False),
        audio_feedback=feedback.get("audio_feedback", True),
        hotwords=transcription.get("hotwords", ""),
        initial_prompt=transcription.get("initial_prompt", ""),
        hallucination_silence_threshold=transcription.get("hallucination_silence_threshold", 0.5),
        repetition_penalty=transcription.get("repetition_penalty", 1.1),
        no_repeat_ngram_size=transcription.get("no_repeat_ngram_size", 3),
    )


def save_config(config: AppConfig, path: Path = CONFIG_PATH) -> None:
    """Persist current config back to TOML."""
    # Build voice commands section with per-language structure
    vc_section: dict = {"enabled": config.voice_commands_enabled}
    for lang, cmds in config.voice_commands.items():
        vc_section[lang] = {
            "commands": [
                {"trigger": c.trigger, "action": c.action,
                 **({"value": c.value} if c.value else {})}
                for c in cmds
            ],
        }

    data = {
        "general": {
            "language": config.language,
            "model": config.model,
            "compute_type": config.compute_type,
            "device": config.device,
        },
        "hotkey": {
            "combination": config.hotkey_combination,
        },
        "audio": {
            "device": config.audio_device,
            "sample_rate": config.sample_rate,
            "channels": config.channels,
        },
        "clipboard": {
            "enabled": config.clipboard_enabled,
        },
        "streaming": {
            "enabled": config.streaming_enabled,
        },
        "noise_gate": {
            "enabled": config.noise_gate_enabled,
            "silence_seconds": config.silence_seconds,
        },
        "voice_commands": vc_section,
        "output": {
            "print_to_terminal": config.print_to_terminal,
        },
        "feedback": {
            "audio_feedback": config.audio_feedback,
        },
        "transcription": {
            "hotwords": config.hotwords,
            "initial_prompt": config.initial_prompt,
            "hallucination_silence_threshold": config.hallucination_silence_threshold,
            "repetition_penalty": config.repetition_penalty,
            "no_repeat_ngram_size": config.no_repeat_ngram_size,
        },
    }
    with open(path, "wb") as f:
        tomli_w.dump(data, f)
