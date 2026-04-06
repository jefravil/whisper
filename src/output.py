"""Text output module.

Handles two output modes:
1. Keyboard simulation: always uses clipboard+paste (avoids pynput char-drop bug)
2. Clipboard mode: copies text to system clipboard

On Linux: uses xclip (subprocess) + xdotool key ctrl+v for reliable paste.
  xclip owns the X selection independently — no tkinter event loop dependency.
  xdotool sends Ctrl+V as a single atomic action — no dropped characters.
On Windows: uses win32 clipboard API + pynput Ctrl+V.

pynput's Controller.type() has a confirmed unfixed bug on X11 (#437) that
randomly drops characters, especially around Unicode/accented chars.
"""

import ctypes
import logging
import platform
import shutil
import subprocess
import time

from pynput.keyboard import Controller, Key

from src.voice_commands import CommandAction

log = logging.getLogger(__name__)

_keyboard = Controller()
_IS_WINDOWS = platform.system() == "Windows"

# Cache tool availability
_xsel_ok: bool | None = None


def _has_xsel() -> bool:
    global _xsel_ok
    if _xsel_ok is None:
        _xsel_ok = shutil.which("xsel") is not None
    return _xsel_ok


def _set_clipboard_linux(text: str) -> bool:
    """Set clipboard via xsel (xclip has a UTF-8 bug that drops chars)."""
    if not _has_xsel():
        log.error("xsel not found. Install: sudo apt install xsel")
        return False

    proc = subprocess.run(
        ["xsel", "--clipboard", "--input"],
        input=text.encode("utf-8"),
        timeout=5,
    )
    return proc.returncode == 0


def _clipboard_paste_linux(text: str) -> bool:
    """Set clipboard via xsel, paste via xdotool to the focused window."""
    if not _set_clipboard_linux(text):
        return False

    # Capture target window BEFORE paste
    win_result = subprocess.run(
        ["xdotool", "getactivewindow"],
        capture_output=True, text=True, timeout=2,
    )
    target_window = win_result.stdout.strip() if win_result.returncode == 0 else None

    time.sleep(0.15)

    if target_window:
        subprocess.run(["xdotool", "windowfocus", "--sync", target_window], timeout=5)
        time.sleep(0.05)
        subprocess.run(["xdotool", "key", "--window", target_window, "ctrl+v"], timeout=5)
    else:
        subprocess.run(["xdotool", "key", "ctrl+v"], timeout=5)

    log.info("Clipboard paste: %d chars (window=%s)", len(text), target_window)
    return True


def _set_clipboard_windows(text: str) -> bool:
    """Set clipboard via Win32 API (64-bit safe)."""
    try:
        CF_UNICODETEXT = 13
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # Must set restype to c_void_p for 64-bit pointer safety.
        # Without this, pointers get truncated to 32 bits and the copy fails.
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalLock.restype = ctypes.c_void_p

        if not user32.OpenClipboard(0):
            log.warning("Failed to open clipboard")
            return False
        user32.EmptyClipboard()

        buf = ctypes.create_unicode_buffer(text)
        byte_len = ctypes.sizeof(buf)
        h_mem = kernel32.GlobalAlloc(0x0042, byte_len)  # GMEM_MOVEABLE | GMEM_ZEROINIT
        if not h_mem:
            user32.CloseClipboard()
            return False
        p_mem = kernel32.GlobalLock(h_mem)
        if not p_mem:
            user32.CloseClipboard()
            return False
        ctypes.memmove(p_mem, buf, byte_len)
        kernel32.GlobalUnlock(h_mem)
        user32.SetClipboardData(CF_UNICODETEXT, h_mem)
        user32.CloseClipboard()
        return True
    except Exception as e:
        log.warning("Windows clipboard set failed: %s", e)
        return False


def _clipboard_paste_windows(text: str) -> bool:
    """Set clipboard and paste via Ctrl+V."""
    if not _set_clipboard_windows(text):
        return False
    time.sleep(0.05)
    _keyboard.press(Key.ctrl_l)
    _keyboard.press('v')
    _keyboard.release('v')
    _keyboard.release(Key.ctrl_l)
    time.sleep(0.05)
    return True


def type_text(text: str) -> None:
    """Type text into the active application via clipboard+paste.

    Always uses clipboard+paste — pynput's Controller.type() has a confirmed
    unfixed bug on X11 (#437) that randomly drops characters.
    Linux: xclip + xdotool. Windows: win32 clipboard + pynput Ctrl+V.
    Falls back to pynput only if system tools are completely unavailable.
    """
    if not text:
        return

    if _IS_WINDOWS:
        if _clipboard_paste_windows(text):
            return
    else:
        if _clipboard_paste_linux(text):
            return

    # Last resort fallback (unreliable on Linux with Unicode)
    log.warning("Paste unavailable, using pynput fallback (may drop chars)")
    for char in text:
        _keyboard.type(char)
        time.sleep(0.015)


def copy_to_clipboard(text: str) -> None:
    """Copy text to system clipboard."""
    if _IS_WINDOWS:
        if _set_clipboard_windows(text):
            log.debug("Copied to clipboard")
        else:
            log.error("Failed to copy to clipboard")
    else:
        if _set_clipboard_linux(text):
            log.debug("Copied to clipboard via xsel")
            return
        log.error("No clipboard tool found. Install: sudo apt install xsel")


def execute_action(action: CommandAction) -> None:
    """Execute a non-text voice command action (delete_last_word, backspace)."""
    if action.action == "delete_last_word":
        _keyboard.press(Key.ctrl_l)
        _keyboard.press(Key.backspace)
        _keyboard.release(Key.backspace)
        _keyboard.release(Key.ctrl_l)

    elif action.action == "backspace":
        _keyboard.press(Key.backspace)
        _keyboard.release(Key.backspace)

    else:
        log.warning("Unknown action: %s", action.action)


def output_actions(actions: list[CommandAction], clipboard_mode: bool = False,
                   on_done=None) -> None:
    """Execute a list of command actions.

    Batches consecutive text/insert/newline actions into a single paste
    to avoid clipboard race conditions from multiple rapid pastes.
    Only breaks the batch when a non-text action (backspace, delete_word)
    requires a separate keystroke.
    """
    if clipboard_mode:
        parts = []
        for action in actions:
            if action.action == "text":
                parts.append(action.value)
            elif action.action == "insert":
                parts.append(action.value)
            elif action.action == "newline":
                parts.append("\n")
        if parts:
            copy_to_clipboard("".join(parts))
        if on_done:
            on_done()
        return

    # Batch consecutive text/insert/newline into a single string,
    # flush the batch before any non-text action
    batch: list[str] = []

    def _flush_batch():
        if batch:
            type_text("".join(batch))
            batch.clear()

    for action in actions:
        if action.action == "text":
            batch.append(action.value)
        elif action.action == "insert":
            batch.append(action.value)
        elif action.action == "newline":
            batch.append("\n")
        else:
            _flush_batch()
            execute_action(action)

    _flush_batch()

    if on_done:
        on_done()
