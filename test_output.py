"""Test script for Windows clipboard + paste output.

Runs a series of tests to validate that text output works correctly:
1. Clipboard set/get roundtrip (no paste)
2. Clipboard with Unicode/accented characters
3. Clipboard with long text
4. Paste simulation timing
5. Full pipeline: transcriber → voice commands → output

Results are written to test_results.txt
"""

import ctypes
import platform
import sys
import time

_IS_WINDOWS = platform.system() == "Windows"


# ── Test helpers ──────────────────────────────────────────────────────────

def get_clipboard_windows() -> str:
    """Read current clipboard text via Win32 API."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalSize.restype = ctypes.c_size_t

    CF_UNICODETEXT = 13
    if not user32.OpenClipboard(0):
        return "<ERROR: OpenClipboard failed>"
    try:
        h_data = user32.GetClipboardData(CF_UNICODETEXT)
        if not h_data:
            return "<ERROR: GetClipboardData returned NULL>"
        p_data = kernel32.GlobalLock(h_data)
        if not p_data:
            return "<ERROR: GlobalLock returned NULL>"
        try:
            return ctypes.wstring_at(p_data)
        finally:
            kernel32.GlobalUnlock(h_data)
    finally:
        user32.CloseClipboard()


def get_clipboard_linux() -> str:
    """Read clipboard via xsel."""
    import subprocess
    result = subprocess.run(
        ["xsel", "--clipboard", "--output"],
        capture_output=True, text=True, timeout=5,
    )
    return result.stdout if result.returncode == 0 else f"<ERROR: xsel rc={result.returncode}>"


def get_clipboard() -> str:
    if _IS_WINDOWS:
        return get_clipboard_windows()
    return get_clipboard_linux()


# ── Import app modules ───────────────────────────────────────────────────

sys.path.insert(0, ".")
from src.output import _set_clipboard_windows, _set_clipboard_linux, copy_to_clipboard, type_text
from src.voice_commands import CommandAction, process_text
from src.config import VoiceCommand


# ── Tests ─────────────────────────────────────────────────────────────────

results = []


def log_result(test_name: str, sent: str, received: str):
    passed = sent == received
    status = "PASS" if passed else "FAIL"
    results.append(f"[{status}] {test_name}")
    results.append(f"  Sent:     {repr(sent)}")
    results.append(f"  Received: {repr(received)}")
    if not passed:
        # Show diff details
        for i, (a, b) in enumerate(zip(sent, received)):
            if a != b:
                results.append(f"  First diff at index {i}: sent={repr(a)} received={repr(b)}")
                break
        if len(sent) != len(received):
            results.append(f"  Length diff: sent={len(sent)} received={len(received)}")
    results.append("")
    print(f"  {status}: {test_name}")


def test_clipboard_roundtrip(label: str, text: str):
    """Set clipboard, read it back, compare."""
    if _IS_WINDOWS:
        ok = _set_clipboard_windows(text)
    else:
        ok = _set_clipboard_linux(text)

    if not ok:
        results.append(f"[FAIL] {label} - clipboard set returned False")
        results.append("")
        print(f"  FAIL: {label} - clipboard set returned False")
        return

    time.sleep(0.05)  # Small delay for clipboard to settle
    got = get_clipboard()
    log_result(label, text, got)


def run_tests():
    print("=" * 60)
    print("Whisper Dictation - Output Test Suite")
    print(f"Platform: {platform.system()} {platform.architecture()[0]}")
    print(f"Python: {sys.version}")
    print("=" * 60)
    results.append("=" * 60)
    results.append("Whisper Dictation - Output Test Suite")
    results.append(f"Platform: {platform.system()} {platform.architecture()[0]}")
    results.append(f"Python: {sys.version}")
    results.append(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    results.append("=" * 60)
    results.append("")

    # ── 1. Basic clipboard roundtrip ─────────────────────────────────
    print("\n--- Test 1: Basic clipboard roundtrip ---")
    results.append("--- Test 1: Basic clipboard roundtrip ---")
    test_clipboard_roundtrip("ASCII simple", "Hello, World!")
    test_clipboard_roundtrip("Empty string", "")
    test_clipboard_roundtrip("Single char", "A")

    # ── 2. Unicode & accented characters ─────────────────────────────
    print("\n--- Test 2: Unicode & accented characters ---")
    results.append("--- Test 2: Unicode & accented characters ---")
    test_clipboard_roundtrip("Spanish accents", "Él está aquí, ¿cómo estás? ¡Bien!")
    test_clipboard_roundtrip("French accents", "Ça fait plaisir, même très bien. Où êtes-vous?")
    test_clipboard_roundtrip("German umlauts", "Ärger über Übungen, straße Grüße")
    test_clipboard_roundtrip("Portuguese", "Ação e coração, não é?")
    test_clipboard_roundtrip("Japanese", "こんにちは世界")
    test_clipboard_roundtrip("Chinese", "你好世界")
    test_clipboard_roundtrip("Korean", "안녕하세요")
    test_clipboard_roundtrip("Mixed Unicode", "Hello 你好 مرحبا Привет こんにちは")
    test_clipboard_roundtrip("Emoji", "Hello 🎤🎧 World 🌍")

    # ── 3. Punctuation & special characters ──────────────────────────
    print("\n--- Test 3: Punctuation & special characters ---")
    results.append("--- Test 3: Punctuation & special characters ---")
    test_clipboard_roundtrip("Punctuation", "Hello. World, test! Right? Yes: no; maybe...")
    test_clipboard_roundtrip("Quotes & brackets", 'She said "hello" and (walked) [away] {quickly}')
    test_clipboard_roundtrip("Special symbols", "email@test.com $100 50% 3+4=7 a&b ~tilde `backtick`")
    test_clipboard_roundtrip("Newlines", "Line 1\nLine 2\nLine 3")
    test_clipboard_roundtrip("Tabs", "Col1\tCol2\tCol3")
    test_clipboard_roundtrip("Mixed whitespace", "  spaces  \ttab\n\nnewlines  ")

    # ── 4. Long text ─────────────────────────────────────────────────
    print("\n--- Test 4: Long text ---")
    results.append("--- Test 4: Long text ---")
    medium_text = "Esta es una prueba de dictado por voz. " * 20
    test_clipboard_roundtrip("Medium text (800 chars)", medium_text)
    long_text = "Transcripción de audio larga con múltiples oraciones. " * 100
    test_clipboard_roundtrip(f"Long text ({len(long_text)} chars)", long_text)

    # ── 5. Voice commands pipeline ───────────────────────────────────
    print("\n--- Test 5: Voice commands pipeline ---")
    results.append("--- Test 5: Voice commands pipeline ---")

    commands = [
        VoiceCommand(trigger="nueva línea", action="newline"),
        VoiceCommand(trigger="punto", action="insert", value="."),
        VoiceCommand(trigger="coma", action="insert", value=","),
        VoiceCommand(trigger="punto y coma", action="insert", value=";"),
    ]

    test_cases = [
        ("Hola mundo", "Hola mundo"),
        ("Hola nueva línea mundo", "Hola\nmundo"),
        ("Hola punto mundo", "Hola.mundo"),
        ("Hola coma mundo", "Hola,mundo"),
        ("Primero punto y coma segundo", "Primero;segundo"),
    ]

    for input_text, expected in test_cases:
        actions = process_text(input_text, commands)
        # Reconstruct text from actions
        parts = []
        for action in actions:
            if action.action == "text":
                parts.append(action.value)
            elif action.action == "insert":
                parts.append(action.value)
            elif action.action == "newline":
                parts.append("\n")
        got = "".join(parts)
        log_result(f"VoiceCmd: '{input_text}'", expected, got)

    # ── 6. copy_to_clipboard function ────────────────────────────────
    print("\n--- Test 6: copy_to_clipboard function ---")
    results.append("--- Test 6: copy_to_clipboard (high-level) ---")

    test_text = "Prueba de clipboard con acentos: á é í ó ú ñ ¿? ¡!"
    copy_to_clipboard(test_text)
    time.sleep(0.05)
    got = get_clipboard()
    log_result("copy_to_clipboard Spanish", test_text, got)

    test_text2 = "The quick brown fox jumps over the lazy dog. 0123456789"
    copy_to_clipboard(test_text2)
    time.sleep(0.05)
    got2 = get_clipboard()
    log_result("copy_to_clipboard English", test_text2, got2)

    # ── 7. Rapid successive clipboard operations ─────────────────────
    print("\n--- Test 7: Rapid successive clipboard operations ---")
    results.append("--- Test 7: Rapid successive clipboard operations ---")

    rapid_texts = [
        "First text",
        "Second text with ñ",
        "Third text with 你好",
        "Fourth text final",
    ]
    for i, text in enumerate(rapid_texts):
        copy_to_clipboard(text)
        time.sleep(0.02)
        got = get_clipboard()
        log_result(f"Rapid #{i+1}: '{text}'", text, got)

    # ── Summary ──────────────────────────────────────────────────────
    pass_count = sum(1 for r in results if r.startswith("[PASS]"))
    fail_count = sum(1 for r in results if r.startswith("[FAIL]"))
    total = pass_count + fail_count

    summary = f"\n{'=' * 60}\nSUMMARY: {pass_count}/{total} passed, {fail_count} failed\n{'=' * 60}"
    results.append(summary)
    print(summary)

    # Write results to file
    output_path = "test_results.txt"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(results))
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    run_tests()
