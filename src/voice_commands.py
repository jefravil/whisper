"""Voice command processor.

Scans transcribed text for trigger phrases and replaces them with actions.
Commands are processed in order of trigger length (longest first) to avoid
partial matches — e.g., "punto y coma" matches before "punto".

Matching is accent-insensitive: "línea" matches "linea" and vice versa.
This is critical because Whisper sometimes omits or adds accents.
"""

import unicodedata
from dataclasses import dataclass

from src.config import VoiceCommand


@dataclass
class CommandAction:
    """Represents a processed action to execute."""
    action: str       # "newline", "insert", "delete_last_word", "backspace", "text"
    value: str = ""   # For "insert" and "text" actions


def _normalize(text: str) -> str:
    """Normalize text for accent-insensitive comparison.

    Decomposes Unicode characters (NFD), strips combining diacritical marks
    (accents), then lowercases. This way "línea" → "linea", "más" → "mas".
    """
    nfkd = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return stripped.lower()


def build_command_index(commands: list[VoiceCommand]) -> list[tuple[str, str, VoiceCommand]]:
    """Build sorted index of (normalized_trigger, original_trigger, command).

    Sorted by trigger length (longest first) to ensure "punto y coma"
    matches before "punto".
    """
    indexed = []
    for cmd in commands:
        normalized = _normalize(cmd.trigger)
        indexed.append((normalized, cmd.trigger.lower(), cmd))
    indexed.sort(key=lambda x: len(x[0]), reverse=True)
    return indexed


def process_text(text: str, commands: list[VoiceCommand]) -> list[CommandAction]:
    """Process transcribed text, replacing trigger phrases with actions.

    Uses accent-insensitive matching: both the text and triggers are
    normalized (accents removed) before comparison, so "nueva línea"
    matches "nueva linea" regardless of Whisper's accent output.

    Returns list of CommandAction objects to execute in order.
    """
    if not commands:
        return [CommandAction(action="text", value=text)] if text else []

    index = build_command_index(commands)
    text_normalized = _normalize(text)
    actions: list[CommandAction] = []
    current_text = []
    pos = 0

    # We walk through the ORIGINAL text by position, but compare
    # against the normalized version. Since _normalize only removes
    # combining characters, positions may shift. To handle this correctly,
    # we build a mapping from normalized position → original position.
    norm_to_orig = []
    orig_idx = 0
    for ch in unicodedata.normalize("NFKD", text):
        if not unicodedata.combining(ch):
            norm_to_orig.append(orig_idx)
        orig_idx += 1
    # Sentinel for end
    norm_to_orig.append(len(text))

    while pos < len(text_normalized):
        matched = False

        for norm_trigger, _orig_trigger, cmd in index:
            end = pos + len(norm_trigger)
            if end > len(text_normalized):
                continue

            if text_normalized[pos:end] == norm_trigger:
                # Check word boundaries on the normalized text
                before_ok = (pos == 0 or not text_normalized[pos - 1].isalnum())
                after_ok = (end >= len(text_normalized)
                            or not text_normalized[end].isalnum())

                if before_ok and after_ok:
                    # Flush accumulated text (using original positions)
                    if current_text:
                        actions.append(CommandAction(
                            action="text",
                            value="".join(current_text),
                        ))
                        current_text = []

                    actions.append(CommandAction(
                        action=cmd.action,
                        value=cmd.value,
                    ))
                    pos = end
                    # Skip trailing space
                    if pos < len(text_normalized) and text_normalized[pos] == " ":
                        pos += 1
                    matched = True
                    break

        if not matched:
            # Append original character at this normalized position
            orig_pos = norm_to_orig[pos] if pos < len(norm_to_orig) else pos
            if orig_pos < len(text):
                current_text.append(text[orig_pos])
            pos += 1

    if current_text:
        actions.append(CommandAction(
            action="text",
            value="".join(current_text),
        ))

    return actions
