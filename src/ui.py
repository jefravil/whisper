"""Floating dictation widget UI using tkinter.

Design:
- A small floating icon (80x80) that stays on top of all windows
- Icon changes based on app state: default → recording → processing
- On hover: shows settings icon
- On click: expands a settings panel below with all configuration options
- Draggable anywhere on screen

Settings panel includes:
- Language selector (combobox)
- Microphone selector (combobox)
- Toggles: clipboard, streaming, voice commands, noise gate, CMD output
- Noise gate seconds (decimal spinbox)
- Hotkey capture (click to set)
- Voice commands CRUD (add/edit/delete)
"""

import logging
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from typing import Callable

from PIL import Image, ImageTk

from src.config import SUPPORTED_LANGUAGES, SUPPORTED_MODELS, VoiceCommand

log = logging.getLogger(__name__)

ICONS_DIR = Path(__file__).parent.parent / "assets" / "icons"
ICON_SIZE = 72

# Dark modern color palette
C = {
    "bg": "#1e1e2e",
    "bg_panel": "#252536",
    "bg_input": "#2e2e42",
    "bg_hover": "#35354a",
    "fg": "#e0e0ef",
    "fg_dim": "#8888aa",
    "fg_label": "#aaaacc",
    "accent": "#4a9eff",
    "red": "#e04050",
    "green": "#40c070",
    "yellow": "#e0b040",
    "border": "#3a3a55",
    "toggle_on": "#4a9eff",
    "toggle_off": "#444460",
    "btn_hover": "#5ab0ff",
    "danger": "#c03040",
    "separator": "#333350",
}


class DictationWidget:
    """Floating icon widget with expandable settings panel."""

    def __init__(self, app_controller):
        self._app = app_controller
        self._root: tk.Tk | None = None
        self._panel_visible = False
        self._panel_frame: tk.Frame | None = None
        self._icon_label: tk.Label | None = None
        self._hovering = False

        # Icon images (loaded once, kept in memory)
        self._icons: dict[str, ImageTk.PhotoImage] = {}

        # Widget references for dynamic updates
        self._lang_var: tk.StringVar | None = None
        self._device_var: tk.StringVar | None = None
        self._silence_var: tk.StringVar | None = None
        self._hotkey_var: tk.StringVar | None = None
        self._hotkey_capturing = False
        self._commands_title: tk.Label | None = None

        # Streaming overlay
        self._stream_window: tk.Toplevel | None = None
        self._stream_label: tk.Label | None = None

        # Drag state
        self._drag_x = 0
        self._drag_y = 0
        self._dragged = False

        # Current visual state
        self._current_state = "idle"

    def _load_icons(self) -> None:
        """Load and resize all icon PNGs."""
        icon_map = {
            "idle": "default_whisper_icon.png",
            "settings": "settings_whisper_icon.png",
            "recording": "recording_whisper_icon.png",
            "processing": "processing_whisper_icon.png",
        }
        for state, filename in icon_map.items():
            path = ICONS_DIR / filename
            if path.exists():
                img = Image.open(path).resize(
                    (ICON_SIZE, ICON_SIZE), Image.LANCZOS,
                )
                self._icons[state] = ImageTk.PhotoImage(img)
            else:
                log.warning("Icon not found: %s", path)

    def build(self) -> tk.Tk:
        """Build the tkinter UI and return the root window."""
        root = tk.Tk()
        self._root = root
        root.title("Whisper Dictation")
        root.configure(bg=C["bg"])
        root.attributes("-topmost", True)
        root.overrideredirect(True)

        # Load icons
        self._load_icons()

        # Position at top-right corner
        root.update_idletasks()
        screen_w = root.winfo_screenwidth()
        x = screen_w - ICON_SIZE - 30
        y = 30
        root.geometry(f"{ICON_SIZE}x{ICON_SIZE}+{x}+{y}")

        # Main icon
        default_icon = self._icons.get("idle")
        self._icon_label = tk.Label(
            root, image=default_icon, bg=C["bg"],
            cursor="hand2", bd=0,
        )
        self._icon_label.pack()

        # Bind events — differentiate click vs drag:
        # A click = press + release without significant mouse movement
        # A drag = press + motion
        self._icon_label.bind("<Enter>", self._on_icon_enter)
        self._icon_label.bind("<Leave>", self._on_icon_leave)
        self._icon_label.bind("<ButtonPress-1>", self._on_press)
        self._icon_label.bind("<B1-Motion>", self._on_drag_motion)
        self._icon_label.bind("<ButtonRelease-1>", self._on_release)
        self._icon_label.bind("<Button-3>", self._on_right_click)

        # Style comboboxes
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Dark.TCombobox",
                        fieldbackground=C["bg_input"],
                        background=C["bg_hover"],
                        foreground=C["fg"],
                        arrowcolor=C["fg_dim"],
                        borderwidth=1, relief="flat")
        style.map("Dark.TCombobox",
                  fieldbackground=[("readonly", C["bg_input"])],
                  foreground=[("readonly", C["fg"])])
        style.configure("Dark.TSpinbox",
                        fieldbackground=C["bg_input"],
                        background=C["bg_hover"],
                        foreground=C["fg"],
                        arrowcolor=C["fg_dim"],
                        borderwidth=1)
        style.map("Dark.TSpinbox",
                  fieldbackground=[("readonly", C["bg_input"])],
                  foreground=[("readonly", C["fg"])])

        return root

    # === Icon state management ===

    def _on_icon_enter(self, event) -> None:
        self._hovering = True
        if self._current_state == "idle" and not self._panel_visible:
            self._show_icon("settings")

    def _on_icon_leave(self, event) -> None:
        self._hovering = False
        if self._current_state == "idle" and not self._panel_visible:
            self._show_icon("idle")

    def _show_icon(self, state: str) -> None:
        icon = self._icons.get(state)
        if icon and self._icon_label:
            self._icon_label.configure(image=icon)

    def set_status(self, status: str) -> None:
        """Update the icon based on app state. Thread-safe."""
        if self._root is None:
            return

        def _update():
            self._current_state = status
            if status == "recording":
                self._show_icon("recording")
            elif status == "processing":
                self._show_icon("processing")
            elif status == "loading":
                self._show_icon("processing")
            else:
                if self._hovering and not self._panel_visible:
                    self._show_icon("settings")
                else:
                    self._show_icon("idle")

        self._root.after(0, _update)

    # === Streaming overlay ===

    def show_streaming_text(self, text: str) -> None:
        """Show or update the streaming transcription overlay. Thread-safe."""
        if self._root is None:
            return

        def _update():
            if not text:
                return

            if self._stream_window is None or not self._stream_window.winfo_exists():
                self._stream_window = tk.Toplevel(self._root)
                self._stream_window.overrideredirect(True)
                self._stream_window.attributes("-topmost", True)
                self._stream_window.configure(bg=C["bg"])

                self._stream_label = tk.Label(
                    self._stream_window, text=text,
                    bg=C["bg"], fg=C["fg"],
                    font=("Sans", 10), wraplength=400,
                    justify="left", padx=12, pady=8,
                )
                self._stream_label.pack()
            else:
                self._stream_label.config(text=text)

            # Position below the main icon
            ix = self._root.winfo_x()
            iy = self._root.winfo_y() + ICON_SIZE + 4
            self._stream_window.update_idletasks()
            sw = self._stream_window.winfo_reqwidth()
            # Align right edge with icon
            sx = ix + ICON_SIZE - sw
            if sx < 0:
                sx = 0
            self._stream_window.geometry(f"+{sx}+{iy}")

        self._root.after(0, _update)

    def hide_streaming_text(self) -> None:
        """Hide the streaming overlay. Thread-safe."""
        if self._root is None:
            return

        def _hide():
            if self._stream_window and self._stream_window.winfo_exists():
                self._stream_window.destroy()
                self._stream_window = None
                self._stream_label = None

        self._root.after(0, _hide)

    # === Click vs Drag handling ===
    # Press records start position. If the mouse moves >5px, it's a drag.
    # If released without moving, it's a click.

    def _on_press(self, event) -> None:
        self._drag_x = event.x
        self._drag_y = event.y
        self._dragged = False

    def _on_drag_motion(self, event) -> None:
        dx = abs(event.x - self._drag_x)
        dy = abs(event.y - self._drag_y)
        if dx > 5 or dy > 5:
            self._dragged = True
        if self._dragged:
            x = self._root.winfo_x() + (event.x - self._drag_x)
            y = self._root.winfo_y() + (event.y - self._drag_y)
            self._root.geometry(f"+{x}+{y}")

    def _on_release(self, event) -> None:
        if not self._dragged:
            # It was a click, not a drag
            if self._panel_visible:
                self._hide_panel()
            else:
                self._show_panel()

    def _on_right_click(self, event) -> None:
        menu = tk.Menu(self._root, tearoff=0, bg=C["bg_panel"],
                       fg=C["fg"], activebackground=C["accent"])
        menu.add_command(label="Salir", command=self._on_quit)
        menu.tk_popup(event.x_root, event.y_root)

    # === Settings panel ===

    def _show_panel(self) -> None:
        """Create and show the settings panel below the icon."""
        if self._panel_visible:
            return
        self._panel_visible = True
        self._show_icon("settings")

        panel_w = 340
        panel_h = 600

        # Position panel below and to the left of the icon
        ix = self._root.winfo_x()
        iy = self._root.winfo_y()

        # Resize window to fit icon + panel
        total_h = ICON_SIZE + panel_h + 4
        new_x = ix - (panel_w - ICON_SIZE)
        if new_x < 0:
            new_x = 0
        self._root.geometry(f"{panel_w}x{total_h}+{new_x}+{iy}")

        # Re-pack icon to right side
        self._icon_label.pack_configure(anchor="ne")

        # Panel frame
        self._panel_frame = tk.Frame(self._root, bg=C["bg_panel"])
        self._panel_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=(0, 2))

        # Scrollable canvas
        canvas = tk.Canvas(self._panel_frame, bg=C["bg_panel"],
                           highlightthickness=0)
        scrollbar = ttk.Scrollbar(self._panel_frame, orient="vertical",
                                  command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=C["bg_panel"])

        scroll_frame.bind("<Configure>",
                          lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw",
                             width=panel_w - 20)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Enable mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _on_button4(event):
            canvas.yview_scroll(-3, "units")

        def _on_button5(event):
            canvas.yview_scroll(3, "units")

        canvas.bind_all("<Button-4>", _on_button4)
        canvas.bind_all("<Button-5>", _on_button5)

        # Build settings content
        self._build_panel_content(scroll_frame)

    def _hide_panel(self) -> None:
        """Hide the settings panel."""
        if not self._panel_visible:
            return
        self._panel_visible = False

        # Unbind scroll events
        self._root.unbind_all("<Button-4>")
        self._root.unbind_all("<Button-5>")

        if self._panel_frame:
            self._panel_frame.destroy()
            self._panel_frame = None

        # Resize back to icon only
        ix = self._root.winfo_x()
        iy = self._root.winfo_y()
        # Restore position accounting for panel offset
        self._root.geometry(f"{ICON_SIZE}x{ICON_SIZE}+{ix + 340 - ICON_SIZE}+{iy}")
        self._icon_label.pack_configure(anchor="center")

        if self._current_state == "idle":
            self._show_icon("idle")

    def _build_panel_content(self, parent: tk.Frame) -> None:
        """Build all settings controls inside the panel."""
        config = self._app._config
        pad = {"padx": 10, "pady": 3}

        # === Title ===
        tk.Label(parent, text="Configuración", bg=C["bg_panel"],
                 fg=C["accent"], font=("Sans", 11, "bold")).pack(**pad, anchor="w")
        self._separator(parent)

        # === Language ===
        self._section_label(parent, "Idioma de Salida")
        lang_names = list(SUPPORTED_LANGUAGES.values())
        lang_codes = list(SUPPORTED_LANGUAGES.keys())
        current_lang = SUPPORTED_LANGUAGES.get(config.language, "Español")
        self._lang_var = tk.StringVar(value=current_lang)
        lang_combo = ttk.Combobox(
            parent, textvariable=self._lang_var, values=lang_names,
            state="readonly", style="Dark.TCombobox", width=28,
        )
        lang_combo.pack(**pad, anchor="w")
        lang_combo.bind("<<ComboboxSelected>>", lambda e: self._on_language_change(
            lang_codes[lang_names.index(self._lang_var.get())],
        ))

        # === Microphone ===
        self._section_label(parent, "Micrófono")
        devices = self._app._available_devices
        device_names = [d["name"] for d in devices]
        current_dev_name = ""
        if self._app._current_device_index is not None:
            match = next(
                (d for d in devices if d["index"] == self._app._current_device_index),
                None,
            )
            if match:
                current_dev_name = match["name"]

        self._device_var = tk.StringVar(value=current_dev_name)
        dev_combo = ttk.Combobox(
            parent, textvariable=self._device_var, values=device_names,
            state="readonly", style="Dark.TCombobox", width=28,
        )
        dev_combo.pack(**pad, anchor="w")
        dev_combo.bind("<<ComboboxSelected>>", lambda e: self._on_device_change(
            self._device_var.get(),
        ))

        # === Model ===
        self._section_label(parent, "Modelo")
        self._model_var = tk.StringVar(value=config.model)
        model_combo = ttk.Combobox(
            parent, textvariable=self._model_var,
            values=list(SUPPORTED_MODELS),
            state="readonly", style="Dark.TCombobox", width=28,
        )
        model_combo.pack(**pad, anchor="w")
        model_combo.bind("<<ComboboxSelected>>", lambda e: self._on_model_change(
            self._model_var.get(),
        ))

        self._separator(parent)

        # === Toggles ===
        self._section_label(parent, "Opciones")

        self._clipboard_toggle = self._make_toggle_row(
            parent, "Modo Clipboard", config.clipboard_enabled,
            self._on_toggle_clipboard,
        )
        self._streaming_toggle = self._make_toggle_row(
            parent, "Streaming", config.streaming_enabled,
            self._on_toggle_streaming,
        )
        self._voice_cmd_toggle = self._make_toggle_row(
            parent, "Comandos de Voz", config.voice_commands_enabled,
            self._on_toggle_voice_commands,
        )
        self._terminal_toggle = self._make_toggle_row(
            parent, "Salida en Terminal", config.print_to_terminal,
            self._on_toggle_terminal,
        )

        self._separator(parent)

        # === Noise Gate ===
        self._section_label(parent, "Noise Gate (segundos de silencio)")
        gate_frame = tk.Frame(parent, bg=C["bg_panel"])
        gate_frame.pack(**pad, anchor="w", fill=tk.X)

        self._noise_gate_toggle = self._make_toggle_btn(
            gate_frame, config.noise_gate_enabled, self._on_toggle_noise_gate,
        )
        self._noise_gate_toggle.pack(side=tk.LEFT, padx=(0, 8))

        self._silence_var = tk.StringVar(value=str(config.silence_seconds))
        silence_spin = ttk.Spinbox(
            gate_frame, textvariable=self._silence_var,
            from_=1.0, to=60.0, increment=0.5,
            style="Dark.TSpinbox", width=8,
        )
        silence_spin.pack(side=tk.LEFT)
        silence_spin.bind("<FocusOut>", lambda e: self._on_silence_change())
        silence_spin.bind("<Return>", lambda e: self._on_silence_change())

        tk.Label(gate_frame, text="seg", bg=C["bg_panel"],
                 fg=C["fg_dim"], font=("Sans", 9)).pack(side=tk.LEFT, padx=4)

        self._separator(parent)

        # === Hotkey ===
        self._section_label(parent, "Atajo de Grabación")
        hotkey_frame = tk.Frame(parent, bg=C["bg_panel"])
        hotkey_frame.pack(**pad, anchor="w", fill=tk.X)

        self._hotkey_var = tk.StringVar(value=config.hotkey_combination)
        self._hotkey_btn = tk.Label(
            hotkey_frame, textvariable=self._hotkey_var,
            bg=C["bg_input"], fg=C["accent"],
            font=("Sans", 10, "bold"), padx=12, pady=6,
            cursor="hand2", relief="flat",
        )
        self._hotkey_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._hotkey_btn.bind("<Button-1>", self._on_hotkey_capture_start)

        tk.Label(hotkey_frame, text="(clic para cambiar)", bg=C["bg_panel"],
                 fg=C["fg_dim"], font=("Sans", 8)).pack(side=tk.LEFT, padx=6)

        self._separator(parent)

        # === Voice Commands (per current language) ===
        lang_name = SUPPORTED_LANGUAGES.get(config.language, config.language)
        self._commands_title = tk.Label(
            parent, text=f"Comandos de Voz ({lang_name})",
            bg=C["bg_panel"], fg=C["fg_label"], font=("Sans", 9, "bold"),
        )
        self._commands_title.pack(padx=10, pady=(8, 2), anchor="w")
        self._commands_frame = tk.Frame(parent, bg=C["bg_panel"])
        self._commands_frame.pack(**pad, anchor="w", fill=tk.X)
        self._rebuild_commands_list()

        # Add command button
        add_btn = tk.Label(
            parent, text="+ Agregar comando", bg=C["accent"], fg="#ffffff",
            font=("Sans", 9, "bold"), padx=10, pady=4, cursor="hand2",
        )
        add_btn.pack(padx=10, pady=6, anchor="w")
        add_btn.bind("<Button-1>", lambda e: self._on_add_command())
        add_btn.bind("<Enter>", lambda e: add_btn.config(bg=C["btn_hover"]))
        add_btn.bind("<Leave>", lambda e: add_btn.config(bg=C["accent"]))

        self._separator(parent)

        # === Quit ===
        quit_btn = tk.Label(
            parent, text="Salir", bg=C["danger"], fg="#ffffff",
            font=("Sans", 9, "bold"), padx=10, pady=6, cursor="hand2",
        )
        quit_btn.pack(padx=10, pady=(4, 12), anchor="w")
        quit_btn.bind("<Button-1>", lambda e: self._on_quit())
        quit_btn.bind("<Enter>", lambda e: quit_btn.config(bg="#e04050"))
        quit_btn.bind("<Leave>", lambda e: quit_btn.config(bg=C["danger"]))

    # === Helper widgets ===

    def _section_label(self, parent: tk.Frame, text: str) -> None:
        tk.Label(parent, text=text, bg=C["bg_panel"], fg=C["fg_label"],
                 font=("Sans", 9, "bold")).pack(padx=10, pady=(8, 2), anchor="w")

    def _separator(self, parent: tk.Frame) -> None:
        tk.Frame(parent, bg=C["separator"], height=1).pack(
            fill=tk.X, padx=10, pady=6,
        )

    def _make_toggle_row(self, parent: tk.Frame, text: str,
                         initial: bool, callback: Callable) -> tk.Label:
        """Create a row with label + toggle button."""
        row = tk.Frame(parent, bg=C["bg_panel"])
        row.pack(padx=10, pady=2, anchor="w", fill=tk.X)

        tk.Label(row, text=text, bg=C["bg_panel"], fg=C["fg"],
                 font=("Sans", 9)).pack(side=tk.LEFT)

        toggle = self._make_toggle_btn(row, initial, callback)
        toggle.pack(side=tk.RIGHT)
        return toggle

    def _make_toggle_btn(self, parent: tk.Frame, initial: bool,
                         callback: Callable) -> tk.Label:
        """Create a toggle switch button."""
        color = C["toggle_on"] if initial else C["toggle_off"]
        text = "  ON " if initial else " OFF "
        btn = tk.Label(
            parent, text=text, bg=color, fg="#ffffff",
            font=("Sans", 8, "bold"), padx=4, pady=1, cursor="hand2",
        )
        btn._toggled = initial

        def _toggle(e):
            btn._toggled = not btn._toggled
            btn.config(
                bg=C["toggle_on"] if btn._toggled else C["toggle_off"],
                text="  ON " if btn._toggled else " OFF ",
            )
            callback(btn._toggled)

        btn.bind("<Button-1>", _toggle)
        return btn

    # === Voice Commands CRUD ===

    def _rebuild_commands_list(self) -> None:
        """Rebuild the voice commands list for the current language."""
        for widget in self._commands_frame.winfo_children():
            widget.destroy()

        cmds = self._app._config.get_commands_for_language()
        for i, cmd in enumerate(cmds):
            row = tk.Frame(self._commands_frame, bg=C["bg_input"])
            row.pack(fill=tk.X, pady=1)

            # Trigger
            tk.Label(row, text=f'"{cmd.trigger}"', bg=C["bg_input"],
                     fg=C["fg"], font=("Sans", 8), width=18,
                     anchor="w").pack(side=tk.LEFT, padx=4)

            # Arrow
            tk.Label(row, text="→", bg=C["bg_input"],
                     fg=C["fg_dim"], font=("Sans", 8)).pack(side=tk.LEFT)

            # Action display
            action_text = cmd.action
            if cmd.value:
                action_text = f'{cmd.action} "{cmd.value}"'
            tk.Label(row, text=action_text, bg=C["bg_input"],
                     fg=C["accent"], font=("Sans", 8),
                     anchor="w").pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)

            # Delete button
            del_btn = tk.Label(
                row, text="✕", bg=C["bg_input"], fg=C["danger"],
                font=("Sans", 9, "bold"), cursor="hand2", padx=4,
            )
            del_btn.pack(side=tk.RIGHT)
            del_btn.bind("<Button-1>", lambda e, idx=i: self._on_delete_command(idx))

    def _on_add_command(self) -> None:
        """Show dialog to add a new voice command."""
        dialog = tk.Toplevel(self._root)
        dialog.title("Nuevo Comando de Voz")
        dialog.configure(bg=C["bg_panel"])
        dialog.attributes("-topmost", True)
        dialog.geometry("320x220")
        dialog.resizable(False, False)

        pad = {"padx": 12, "pady": 4}

        tk.Label(dialog, text="Palabra/frase trigger:", bg=C["bg_panel"],
                 fg=C["fg_label"], font=("Sans", 9)).pack(**pad, anchor="w")
        trigger_entry = tk.Entry(dialog, bg=C["bg_input"], fg=C["fg"],
                                 font=("Sans", 10), insertbackground=C["fg"])
        trigger_entry.pack(**pad, fill=tk.X)

        tk.Label(dialog, text="Acción:", bg=C["bg_panel"],
                 fg=C["fg_label"], font=("Sans", 9)).pack(**pad, anchor="w")
        action_var = tk.StringVar(value="insert")
        action_combo = ttk.Combobox(
            dialog, textvariable=action_var,
            values=["insert", "newline", "delete_last_word", "backspace"],
            state="readonly", style="Dark.TCombobox",
        )
        action_combo.pack(**pad, fill=tk.X)

        tk.Label(dialog, text='Valor (para "insert"):', bg=C["bg_panel"],
                 fg=C["fg_label"], font=("Sans", 9)).pack(**pad, anchor="w")
        value_entry = tk.Entry(dialog, bg=C["bg_input"], fg=C["fg"],
                               font=("Sans", 10), insertbackground=C["fg"])
        value_entry.pack(**pad, fill=tk.X)

        def _save():
            trigger = trigger_entry.get().strip()
            action = action_var.get()
            value = value_entry.get().strip()
            if not trigger:
                return
            new_cmd = VoiceCommand(trigger=trigger, action=action, value=value)
            lang = self._app._config.language
            if lang not in self._app._config.voice_commands:
                self._app._config.voice_commands[lang] = []
            self._app._config.voice_commands[lang].append(new_cmd)
            self._save_config()
            self._rebuild_commands_list()
            dialog.destroy()

        save_btn = tk.Label(
            dialog, text="Guardar", bg=C["accent"], fg="#ffffff",
            font=("Sans", 10, "bold"), padx=12, pady=6, cursor="hand2",
        )
        save_btn.pack(pady=10)
        save_btn.bind("<Button-1>", lambda e: _save())

    def _on_delete_command(self, index: int) -> None:
        """Delete a voice command by index for the current language."""
        lang = self._app._config.language
        cmds = self._app._config.voice_commands.get(lang, [])
        if 0 <= index < len(cmds):
            del cmds[index]
            self._save_config()
            self._rebuild_commands_list()

    # === Hotkey capture ===

    def _on_hotkey_capture_start(self, event) -> None:
        """Start listening for a new hotkey combination."""
        if self._hotkey_capturing:
            return
        self._hotkey_capturing = True
        self._hotkey_btn.config(bg=C["red"], fg="#ffffff")
        self._hotkey_var.set("Presiona tu atajo...")

        self._captured_keys = set()

        from pynput import keyboard

        def _on_press(key):
            # Normalize
            if key == keyboard.Key.ctrl_r:
                key = keyboard.Key.ctrl_l
            if key == keyboard.Key.shift_r:
                key = keyboard.Key.shift_l
            if key == keyboard.Key.alt_r:
                key = keyboard.Key.alt_l
            self._captured_keys.add(key)

        def _on_release(key):
            if len(self._captured_keys) >= 1:
                # Build the combination string
                from src.hotkey import format_hotkey
                combo_str = self._keys_to_config_string(self._captured_keys)
                self._capture_listener.stop()
                self._hotkey_capturing = False
                self._root.after(0, lambda: self._apply_new_hotkey(combo_str))

        self._capture_listener = keyboard.Listener(
            on_press=_on_press, on_release=_on_release,
        )
        self._capture_listener.daemon = True
        self._capture_listener.start()

    def _keys_to_config_string(self, keys: set) -> str:
        """Convert captured keys to config string format."""
        from pynput import keyboard
        parts = []
        key_map = {
            keyboard.Key.ctrl_l: "<ctrl>",
            keyboard.Key.shift_l: "<shift>",
            keyboard.Key.alt_l: "<alt>",
            keyboard.Key.cmd: "<cmd>",
            keyboard.Key.space: "space",
            keyboard.Key.tab: "<tab>",
            keyboard.Key.esc: "<esc>",
        }
        for i in range(1, 13):
            key_map[getattr(keyboard.Key, f"f{i}")] = f"<f{i}>"

        # Modifiers first
        modifier_order = [keyboard.Key.ctrl_l, keyboard.Key.shift_l,
                          keyboard.Key.alt_l, keyboard.Key.cmd]
        for mod in modifier_order:
            if mod in keys:
                parts.append(key_map[mod])

        for key in keys:
            if key in modifier_order:
                continue
            if key in key_map:
                parts.append(key_map[key])
            elif isinstance(key, keyboard.KeyCode) and key.char:
                parts.append(key.char.lower())

        return "+".join(parts) if parts else "<ctrl>+<shift>+space"

    def _apply_new_hotkey(self, combo_str: str) -> None:
        """Apply the newly captured hotkey."""
        self._hotkey_var.set(combo_str)
        self._hotkey_btn.config(bg=C["bg_input"], fg=C["accent"])
        self._app._config.hotkey_combination = combo_str
        self._save_config()

        # Update the hotkey listener
        if self._app._hotkey:
            self._app._hotkey.update_combination(combo_str)
        log.info("Hotkey changed to: %s", combo_str)

    # === Callbacks ===

    def _save_config(self) -> None:
        from src.config import save_config
        save_config(self._app._config)

    def _on_language_change(self, lang_code: str) -> None:
        self._app._config.language = lang_code
        self._app._transcriber.language = lang_code
        self._save_config()
        log.info("Language changed to: %s", lang_code)
        # Update commands title and list for the new language
        if self._commands_title:
            lang_name = SUPPORTED_LANGUAGES.get(lang_code, lang_code)
            self._commands_title.config(text=f"Comandos de Voz ({lang_name})")
        if self._commands_frame:
            self._rebuild_commands_list()

    def _on_device_change(self, device_name: str) -> None:
        devices = self._app._available_devices
        match = next((d for d in devices if d["name"] == device_name), None)
        if match:
            self._app._current_device_index = match["index"]
            self._app._recorder.set_device(match["index"])
            self._app._config.audio_device = str(match["index"])
            self._save_config()
            log.info("Audio device changed to: [%d] %s",
                     match["index"], match["name"])

    def _on_model_change(self, model: str) -> None:
        self._app._config.model = model
        self._save_config()
        log.info("Model changed to: %s (restart needed to apply)", model)

    def _on_toggle_clipboard(self, enabled: bool) -> None:
        self._app._config.clipboard_enabled = enabled
        self._save_config()
        log.info("Clipboard mode: %s", enabled)

    def _on_toggle_streaming(self, enabled: bool) -> None:
        self._app._config.streaming_enabled = enabled
        self._save_config()
        log.info("Streaming mode: %s", enabled)

    def _on_toggle_voice_commands(self, enabled: bool) -> None:
        self._app._config.voice_commands_enabled = enabled
        self._save_config()
        log.info("Voice commands: %s", enabled)

    def _on_toggle_terminal(self, enabled: bool) -> None:
        self._app._config.print_to_terminal = enabled
        self._save_config()
        log.info("Terminal output: %s", enabled)

    def _on_toggle_noise_gate(self, enabled: bool) -> None:
        self._app._config.noise_gate_enabled = enabled
        self._save_config()
        log.info("Noise gate: %s", enabled)

    def _on_silence_change(self) -> None:
        try:
            value = float(self._silence_var.get())
            if value < 1.0:
                value = 1.0
            self._app._config.silence_seconds = value
            self._save_config()
            log.info("Silence threshold: %.1f seconds", value)
        except ValueError:
            pass

    def _on_quit(self) -> None:
        self._app.shutdown()
        self._root.destroy()

    # === Public ===

    def run(self) -> None:
        """Start the tkinter main loop (blocks)."""
        self._root.protocol("WM_DELETE_WINDOW", self._on_quit)
        self._root.mainloop()

    def destroy(self) -> None:
        if self._root:
            self._root.after(0, self._root.destroy)
