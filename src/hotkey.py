"""Global hotkey listener using pynput.

Supports two modes:
- Toggle: press once to start, press again to stop
- The hotkey combination is configurable (e.g., "<ctrl>+<shift>+space")

Runs in a dedicated daemon thread to avoid blocking the main thread.
"""

import logging
import threading
import time
from typing import Callable

from pynput import keyboard

log = logging.getLogger(__name__)

# Minimum time between toggle events to avoid double-triggers
_DEBOUNCE_SECONDS = 0.4


def parse_hotkey(combination: str) -> frozenset:
    """Parse a hotkey string like '<ctrl>+<shift>+space' into a frozenset of keys."""
    keys = set()
    parts = combination.lower().split("+")

    for part in parts:
        part = part.strip()
        if part in ("<ctrl>", "ctrl"):
            keys.add(keyboard.Key.ctrl_l)
        elif part in ("<shift>", "shift"):
            keys.add(keyboard.Key.shift_l)
        elif part in ("<alt>", "alt"):
            keys.add(keyboard.Key.alt_l)
        elif part in ("<cmd>", "cmd", "super"):
            keys.add(keyboard.Key.cmd)
        elif part == "space":
            keys.add(keyboard.Key.space)
        elif part in ("<tab>", "tab"):
            keys.add(keyboard.Key.tab)
        elif part in ("<esc>", "esc"):
            keys.add(keyboard.Key.esc)
        elif part in ("<f1>", "f1"):
            keys.add(keyboard.Key.f1)
        elif part in ("<f2>", "f2"):
            keys.add(keyboard.Key.f2)
        elif part in ("<f3>", "f3"):
            keys.add(keyboard.Key.f3)
        elif part in ("<f4>", "f4"):
            keys.add(keyboard.Key.f4)
        elif part in ("<f5>", "f5"):
            keys.add(keyboard.Key.f5)
        elif part in ("<f6>", "f6"):
            keys.add(keyboard.Key.f6)
        elif part in ("<f7>", "f7"):
            keys.add(keyboard.Key.f7)
        elif part in ("<f8>", "f8"):
            keys.add(keyboard.Key.f8)
        elif part in ("<f9>", "f9"):
            keys.add(keyboard.Key.f9)
        elif part in ("<f10>", "f10"):
            keys.add(keyboard.Key.f10)
        elif part in ("<f11>", "f11"):
            keys.add(keyboard.Key.f11)
        elif part in ("<f12>", "f12"):
            keys.add(keyboard.Key.f12)
        elif len(part) == 1:
            keys.add(keyboard.KeyCode.from_char(part))
        else:
            log.warning("Unknown key in hotkey: '%s'", part)

    return frozenset(keys)


def format_hotkey(keys: frozenset) -> str:
    """Convert a frozenset of keys back to a human-readable string."""
    parts = []
    key_names = {
        keyboard.Key.ctrl_l: "Ctrl",
        keyboard.Key.shift_l: "Shift",
        keyboard.Key.alt_l: "Alt",
        keyboard.Key.cmd: "Super",
        keyboard.Key.space: "Space",
        keyboard.Key.tab: "Tab",
        keyboard.Key.esc: "Esc",
    }
    # Add F-keys
    for i in range(1, 13):
        key_names[getattr(keyboard.Key, f"f{i}")] = f"F{i}"

    # Modifiers first, then other keys
    modifier_order = [keyboard.Key.ctrl_l, keyboard.Key.shift_l,
                      keyboard.Key.alt_l, keyboard.Key.cmd]
    for mod in modifier_order:
        if mod in keys:
            parts.append(key_names[mod])

    for key in keys:
        if key not in modifier_order:
            if key in key_names:
                parts.append(key_names[key])
            elif isinstance(key, keyboard.KeyCode) and key.char:
                parts.append(key.char.upper())

    return " + ".join(parts)


class HotkeyListener:
    """Toggle-mode hotkey listener.

    Press the hotkey once → on_activate fires
    Press the hotkey again → on_deactivate fires
    Uses debouncing to prevent double-triggers from key repeat.
    """

    def __init__(self, combination: str,
                 on_activate: Callable[[], None],
                 on_deactivate: Callable[[], None]):
        self._target_keys = parse_hotkey(combination)
        self._on_activate = on_activate
        self._on_deactivate = on_deactivate
        self._pressed: set = set()
        self._recording = False
        self._listener: keyboard.Listener | None = None
        self._lock = threading.Lock()
        self._last_toggle_time = 0.0

    def _normalize_key(self, key):
        """Normalize key variants (left/right modifiers → left)."""
        if key == keyboard.Key.ctrl_r:
            return keyboard.Key.ctrl_l
        if key == keyboard.Key.shift_r:
            return keyboard.Key.shift_l
        if key == keyboard.Key.alt_r:
            return keyboard.Key.alt_l
        return key

    def _on_press(self, key) -> None:
        key = self._normalize_key(key)
        with self._lock:
            self._pressed.add(key)
            if self._target_keys.issubset(self._pressed):
                now = time.monotonic()
                if now - self._last_toggle_time < _DEBOUNCE_SECONDS:
                    return
                self._last_toggle_time = now

                if not self._recording:
                    self._recording = True
                    log.debug("Hotkey toggle: recording ON")
                    threading.Thread(
                        target=self._on_activate, daemon=True,
                    ).start()
                else:
                    self._recording = False
                    log.debug("Hotkey toggle: recording OFF")
                    threading.Thread(
                        target=self._on_deactivate, daemon=True,
                    ).start()

    def _on_release(self, key) -> None:
        key = self._normalize_key(key)
        with self._lock:
            self._pressed.discard(key)

    def notify_stopped(self) -> None:
        """Called externally when recording stops (e.g., noise gate).
        Resets internal toggle state so next press starts recording again.
        """
        with self._lock:
            self._recording = False

    def start(self) -> None:
        """Start listening for the hotkey in a daemon thread."""
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.daemon = True
        self._listener.start()
        log.info("Hotkey listener started (toggle mode): %s",
                 format_hotkey(self._target_keys))

    def stop(self) -> None:
        """Stop the hotkey listener."""
        if self._listener:
            self._listener.stop()
            self._listener = None

    def update_combination(self, combination: str) -> None:
        """Update the hotkey combination. Restarts the listener."""
        was_running = self._listener is not None
        if was_running:
            self.stop()
        self._target_keys = parse_hotkey(combination)
        self._recording = False
        self._pressed.clear()
        if was_running:
            self.start()
