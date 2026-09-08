from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox

from config import Config
from engine import TypingEngine
from windows_utils import get_open_windows, focus_window
import profiles as prof

APP_TITLE = "TypeSim - Windows Typing Simulator"

# Palette Copal
C = {
    "base":     "#0A1F44",
    "mantle":   "#0A1F44",
    "surface0": "#1E3A66",
    "surface1": "#2A4B7D",
    "crust":    "#051024",
    "overlay":  "#AFB4BA",
    "text":     "#E4E6E9",
    "subtext":  "#AFB4BA",
    "blue":     "#4ea8de",
    "green":    "#a6e3a1",
    "red":      "#f38ba8",
    "yellow":   "#f9e2af",
    "peach":    "#fab387",
}

class GradientCanvas(tk.Canvas):
    def __init__(self, parent, color1, color2, **kwargs):
        super().__init__(parent, highlightthickness=0, **kwargs)
        self.color1 = color1
        self.color2 = color2
        self.bind("<Configure>", self._draw_gradient)

    def _draw_gradient(self, event=None):
        self.delete("gradient")
        width = self.winfo_width()
        height = self.winfo_height()
        if width <= 1 or height <= 1: return
        (r1, g1, b1) = self.winfo_rgb(self.color1)
        (r2, g2, b2) = self.winfo_rgb(self.color2)
        r_ratio = float(r2 - r1) / height
        g_ratio = float(g2 - g1) / height
        b_ratio = float(b2 - b1) / height

        for i in range(height):
            nr = int(r1 + (r_ratio * i))
            ng = int(g1 + (g_ratio * i))
            nb = int(b1 + (b_ratio * i))
            color = f"#{nr>>8:02x}{ng>>8:02x}{nb>>8:02x}"
            self.create_line(0, i, width, i, tags=("gradient",), fill=color)
        self.lower("gradient")

class ScrollableFrame(ttk.Frame):
    def __init__(self, master, bg=C["base"], **kw):
        super().__init__(master, **kw)
        self._canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        self._scroll = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self.inner = tk.Frame(self._canvas, bg=bg)
        self._win_id = self._canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", lambda e: self._canvas.itemconfig(self._win_id, width=e.width))
        self._canvas.configure(yscrollcommand=self._scroll.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        self._scroll.pack(side="right", fill="y")
        self._canvas.bind_all("<MouseWheel>", lambda e: self._canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

class FloatingBar(tk.Toplevel):
    def __init__(self, app: "TypeSimApp"):
        super().__init__(app.root)
        self.app = app
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.95)
        sw = self.winfo_screenwidth()
        self.geometry(f"520x82+{sw - 530}+20")
        self._dx = self._dy = 0
        self._build()

    def _build(self):
        outer = tk.Frame(self, bg=C["blue"])
        outer.pack(fill="both", expand=True)
        inner = tk.Frame(outer, bg=C["surface0"])
        inner.pack(fill="both", expand=True, padx=2, pady=2)

        r1 = tk.Frame(inner, bg=C["surface0"])
        r1.pack(fill="x", padx=10, pady=(7, 2))

        tk.Label(r1, text="Ketik  TypeSim", font=("Montserrat", 9, "bold"),
                 bg=C["surface0"], fg=C["blue"]).pack(side="left")
        tk.Label(r1, text="  |  ", bg=C["surface0"], fg=C["overlay"],
                 font=("Poppins", 9)).pack(side="left")
        self._status_lbl = tk.Label(r1, text="Memulai...", font=("Poppins", 9),
                                     bg=C["surface0"], fg=C["text"])
        self._status_lbl.pack(side="left")

        btns = tk.Frame(r1, bg=C["surface0"])
        btns.pack(side="right")
        self._pause_btn = tk.Button(
            btns, text="Jeda", font=("Montserrat", 8, "bold"),
            bg=C["surface1"], fg=C["text"], activebackground=C["overlay"],
            relief="flat", padx=10, pady=3, cursor="hand2",
            command=self.app._cmd_pause)
        self._pause_btn.pack(side="left", padx=(0, 4))
        tk.Button(
            btns, text="Stop", font=("Montserrat", 8, "bold"),
            bg=C["red"], fg=C["crust"], activebackground=C["peach"],
            activeforeground=C["crust"], relief="flat", padx=10, pady=3,
            cursor="hand2", command=self.app._cmd_stop).pack(side="left")

        r2 = tk.Frame(inner, bg=C["surface0"])
        r2.pack(fill="x", padx=10, pady=(0, 7))
        self._prog_var = tk.DoubleVar(value=0)
        ttk.Progressbar(r2, variable=self._prog_var, maximum=100,
                        mode="determinate", length=360).pack(side="left")
        self._eta_lbl = tk.Label(r2, text="", font=("Poppins", 8),
                                  bg=C["surface0"], fg=C["subtext"],
                                  width=18, anchor="w")
        self._eta_lbl.pack(side="left", padx=(8, 0))

        for w in [outer, inner, r1, r2, self._status_lbl, self._eta_lbl]:
            w.bind("<Button-1>", self._drag_start, add="+")
            w.bind("<B1-Motion>", self._drag_move, add="+")

    def _drag_start(self, e):
        self._dx = e.x_root - self.winfo_x()
        self._dy = e.y_root - self.winfo_y()

    def _drag_move(self, e):
        self.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def set_status(self, msg, color=None):
        self._status_lbl.config(text=msg, fg=color or C["text"])

    def set_progress(self, pct, eta=""):
        self._prog_var.set(pct)
        self._eta_lbl.config(text=eta)

    def set_paused(self, paused):
        if paused:
            self._pause_btn.config(text="Lanjut", bg=C["yellow"], fg=C["crust"])
            self.set_status("Dijeda", color=C["yellow"])
        else:
            self._pause_btn.config(text="Jeda", bg=C["surface1"], fg=C["text"])
            self.set_status("Mengetik...", color=C["green"])

class TypeSimApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("760x600")
        self.root.minsize(640, 500)
        self.root.configure(bg=C["base"])
        self.config = Config.load()
        self.engine = TypingEngine(self.config)
        self.engine.on_progress = self._cb_progress
        self.engine.on_status   = self._cb_status
        self.engine.on_done     = self._cb_done
        self._is_running  = False
        self._is_paused   = False
        self._floating: FloatingBar | None = None
        self._hotkey_listener = None
        self._windows = []
        self._sv = {}
        self._apply_theme()
        self._build_ui()
        self._refresh_windows()
        self._start_hotkey_listener()

    def _apply_theme(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure(".", background=C["base"], foreground=C["text"], font=("Poppins", 10), borderwidth=0)
        s.configure("TFrame", background=C["base"])
        s.configure("TLabel", background=C["base"], foreground=C["text"])
        s.configure("TLabelframe", background=C["base"], bordercolor=C["surface1"], relief="solid", borderwidth=1)
        s.configure("TLabelframe.Label", background=C["base"], foreground=C["text"], font=("Montserrat", 9, "bold"))
        s.configure("TNotebook", background=C["mantle"], borderwidth=0)
        s.configure("TNotebook.Tab", background=C["surface0"], foreground=C["subtext"], font=("Montserrat", 9, "bold"), padding=(14, 7))
        s.map("TNotebook.Tab", background=[("selected", C["surface1"])], foreground=[("selected", C["text"])])
        s.configure("TButton", background=C["surface0"], foreground=C["text"], font=("Montserrat", 9), padding=(10, 6))
        s.map("TButton", background=[("active", C["surface1"]), ("disabled", C["mantle"])], foreground=[("disabled", C["overlay"])])
        s.configure("Header.TButton", background=C["surface0"], foreground=C["text"], font=("Montserrat", 9, "bold"), padding=(12, 4))
        s.map("Header.TButton", background=[("active", C["surface1"]), ("disabled", C["base"])], foreground=[("disabled", C["overlay"])])
        s.configure("TProgressbar", troughcolor=C["surface0"], background=C["blue"], borderwidth=0, thickness=8)
        s.configure("TCombobox", fieldbackground=C["surface0"], background=C["surface0"], foreground=C["text"], arrowcolor=C["text"], selectbackground=C["surface1"])
        s.map("TCombobox", fieldbackground=[("readonly", C["surface0"])])
        s.configure("TScale", background=C["base"], troughcolor=C["surface0"], sliderlength=18)
        s.configure("TCheckbutton", background=C["base"], foreground=C["text"])
        s.map("TCheckbutton", background=[("active", C["base"])], indicatorcolor=[("selected", C["blue"]), ("!selected", C["surface1"])])
        s.configure("TEntry", fieldbackground=C["surface0"], foreground=C["text"], insertcolor=C["blue"])
        s.configure("TScrollbar", background=C["surface0"], troughcolor=C["mantle"], arrowcolor=C["overlay"])

    def _build_ui(self):
        hdr = tk.Frame(self.root, bg=C["crust"], pady=8)
        hdr.pack(fill="x")
        tk.Label(hdr, text="TypeSim", font=("Montserrat", 13, "bold"), bg=C["crust"], fg=C["text"]).pack(side="left", padx=(16, 20))
        self._btn_start = ttk.Button(hdr, text="▶ START (F9)", style="Header.TButton", command=self._cmd_start)
        self._btn_start.pack(side="left")
        self._status_dot = tk.Label(hdr, text="Idle", font=("Montserrat", 9, "bold"), bg=C["crust"], fg=C["subtext"])
        self._status_dot.pack(side="right", padx=16)

        self._nb = ttk.Notebook(self.root)
        self._nb.pack(fill="both", expand=True, padx=10, pady=(8, 0))
        self._tab_main     = ttk.Frame(self._nb)
        self._tab_advanced = ttk.Frame(self._nb)
        self._tab_about    = ttk.Frame(self._nb)
        self._nb.add(self._tab_main,     text="  Main  ")
        self._nb.add(self._tab_advanced, text="  Advanced  ")
        self._nb.add(self._tab_about,    text="  About  ")
        self._build_main_tab()
        self._build_advanced_tab()
        self._build_about_tab()
        sbar = tk.Frame(self.root, bg=C["mantle"], pady=4)
        sbar.pack(fill="x", side="bottom")
        self._sbar_lbl = tk.Label(sbar, text="Ready  |  F9=Start   F10=Pause   F11=Stop",
                                   font=("Poppins", 8), bg=C["mantle"], fg=C["subtext"])
        self._sbar_lbl.pack(side="left", padx=10)

    def _build_main_tab(self):
        f = self._tab_main
        
        # Gradient border for Text Box
        gf = GradientCanvas(f, color1="#2A4B7D", color2="#0A1F44") 
        gf.pack(fill="both", expand=True, padx=8, pady=(12, 4))
        
        self._text = tk.Text(gf, font=("Poppins", 10), bg=C["surface0"], fg=C["text"],
                             insertbackground=C["text"], selectbackground=C["surface1"],
                             relief="flat", wrap="word", undo=True, maxundo=-1, autoseparators=True, padx=8, pady=8)
        sb = ttk.Scrollbar(gf, command=self._text.yview)
        sb.pack(side="right", fill="y", padx=(0, 2), pady=2)
        self._text.configure(yscrollcommand=sb.set)
        self._text.pack(side="left", fill="both", expand=True, padx=(2, 0), pady=2)
        self._text.bind("<KeyRelease>", self._update_stats)
        
        # --- WORD-LIKE EDITING SHORTCUTS ---
        self._text.bind("<Control-a>", lambda e: (self._text.tag_add("sel","1.0","end"), "break")[1])
        self._text.bind("<Control-A>", lambda e: (self._text.tag_add("sel","1.0","end"), "break")[1])
        self._text.bind("<Shift-Delete>", self._text_delete_line)
        self._text.bind("<Control-BackSpace>", self._text_ctrl_backspace)
        self._text.bind("<Control-Delete>", self._text_ctrl_delete)
        self._text.bind("<Control-y>", self._text_redo)
        self._text.bind("<Control-Y>", self._text_redo)
        self._text.bind("<Button-3>", self._show_context_menu) # Right-click menu

        # Stats row
        sr = tk.Frame(f, bg=C["base"])
        sr.pack(fill="x", padx=8, pady=1)
        self._stats_lbl = tk.Label(sr, text="0 chars  |  0 words  |  ETA: --",
                                    font=("Poppins", 8), bg=C["base"], fg=C["subtext"])
        self._stats_lbl.pack(side="left")
        tk.Button(sr, text="Clear", font=("Poppins", 8), bg=C["surface0"], fg=C["subtext"],
                  relief="flat", cursor="hand2", activebackground=C["surface1"],
                  command=lambda: (self._text.delete("1.0","end"), self._update_stats())).pack(side="right")
        # Window picker
        wf = ttk.LabelFrame(f, text=" Target Window ", padding=6)
        wf.pack(fill="x", padx=8, pady=4)
        wi = tk.Frame(wf, bg=C["base"])
        wi.pack(fill="x")
        self._win_var = tk.StringVar(value="<Active window when countdown ends>")
        self._win_combo = ttk.Combobox(wi, textvariable=self._win_var, state="readonly")
        self._win_combo.pack(side="left", fill="x", expand=True)
        ttk.Button(wi, text="Refresh", width=8, command=self._refresh_windows).pack(side="left", padx=(4,0))
        
        # Progress
        pf = tk.Frame(f, bg=C["base"])
        pf.pack(fill="x", padx=8, pady=(10, 4))
        self._progress_var = tk.DoubleVar(value=0)
        ttk.Progressbar(pf, variable=self._progress_var, maximum=100, mode="determinate").pack(fill="x")
        self._eta_lbl = tk.Label(f, text="", font=("Poppins", 8), bg=C["base"], fg=C["subtext"])
        self._eta_lbl.pack(anchor="e", padx=10, pady=(0, 4))

    # --- WORD-LIKE FUNCTIONS ---
    def _text_ctrl_backspace(self, event=None):
        try:
            if self._text.tag_ranges("sel"):
                self._text.delete("sel.first", "sel.last")
            else:
                self._text.delete("insert-1c wordstart", "insert")
            self._update_stats()
        except tk.TclError:
            pass
        return "break"

    def _text_ctrl_delete(self, event=None):
        try:
            if self._text.tag_ranges("sel"):
                self._text.delete("sel.first", "sel.last")
            else:
                self._text.delete("insert", "insert wordend")
            self._update_stats()
        except tk.TclError:
            pass
        return "break"

    def _text_redo(self, event=None):
        try:
            self._text.edit_redo()
            self._update_stats()
        except tk.TclError:
            pass
        return "break"

    def _show_context_menu(self, event):
        m = tk.Menu(self.root, tearoff=0, bg=C["surface0"], fg=C["text"], 
                    activebackground=C["surface1"], activeforeground=C["text"],
                    relief="flat", borderwidth=1, font=("Poppins", 9))
        m.add_command(label="Cut\tCtrl+X", command=lambda: self.root.focus_get().event_generate("<<Cut>>"))
        m.add_command(label="Copy\tCtrl+C", command=lambda: self.root.focus_get().event_generate("<<Copy>>"))
        m.add_command(label="Paste\tCtrl+V", command=lambda: self.root.focus_get().event_generate("<<Paste>>"))
        m.add_separator()
        m.add_command(label="Select All\tCtrl+A", command=lambda: self._text.tag_add("sel","1.0","end"))
        m.tk_popup(event.x_root, event.y_root)

    def _text_delete_line(self, event=None):
        start = self._text.index("insert linestart")
        end   = self._text.index("insert lineend+1c")
        self._text.delete(start, end)
        self._update_stats()
        return "break"

    def _build_advanced_tab(self):
        sf = ScrollableFrame(self._tab_advanced, bg=C["base"])
        sf.pack(fill="both", expand=True)
        p = sf.inner

        sp = ttk.LabelFrame(p, text="  Typing Speed ", padding=10)
        sp.pack(fill="x", padx=10, pady=(10, 5))
        self._sv["wpm"]       = self._add_slider(sp, "WPM (words per minute)", 10, 400, self.config.wpm, 0, "{:.0f} wpm", lambda v: self._set_cfg("wpm", int(v)))
        self._sv["variation"] = self._add_slider(sp, "Delay Variation (+/-%)", 0, 80, round(self.config.variation*100), 1, "{:.0f}%", lambda v: self._set_cfg("variation", v/100))

        hb = ttk.LabelFrame(p, text="  Human-like Behaviour ", padding=10)
        hb.pack(fill="x", padx=10, pady=5)
        self._sv["error_rate"]             = self._add_slider(hb, "Typo Rate (%)", 0, 25, round(self.config.error_rate*100,1), 0, "{:.1f}%", lambda v: self._set_cfg("error_rate", v/100))
        self._sv["error_correction_delay"] = self._add_slider(hb, "Typo Correction Delay (s)", 0.03, 1.0, self.config.error_correction_delay, 1, "{:.2f}s", lambda v: self._set_cfg("error_correction_delay", v))
        self._sv["thinking_pause_chance"]  = self._add_slider(hb, "Thinking Pause Chance (%)", 0, 20, round(self.config.thinking_pause_chance*100,1), 2, "{:.1f}%", lambda v: self._set_cfg("thinking_pause_chance", v/100))
        self._sv["thinking_pause_min"]     = self._add_slider(hb, "Thinking Pause Min (s)", 0.1, 5.0, self.config.thinking_pause_min, 3, "{:.1f}s", lambda v: self._set_cfg("thinking_pause_min", v))
        self._sv["thinking_pause_max"]     = self._add_slider(hb, "Thinking Pause Max (s)", 0.5, 10.0, self.config.thinking_pause_max, 4, "{:.1f}s", lambda v: self._set_cfg("thinking_pause_max", v))
        brow = tk.Frame(hb, bg=C["base"])
        brow.grid(row=5, column=0, columnspan=3, sticky="w", pady=(8,2))
        self._burst_var = tk.BooleanVar(value=self.config.burst_mode)
        ttk.Checkbutton(brow, text="Enable Burst Mode  (ketik N chars cepat, lalu jeda)",
                         variable=self._burst_var,
                         command=lambda: self._set_cfg("burst_mode", self._burst_var.get())).pack(side="left")
        self._sv["burst_chars"] = self._add_slider(hb, "Burst Length (chars)", 2, 40, self.config.burst_chars, 6, "{:.0f} chars", lambda v: self._set_cfg("burst_chars", int(v)))
        self._sv["burst_pause"] = self._add_slider(hb, "Burst Pause (s)", 0.1, 5.0, self.config.burst_pause, 7, "{:.2f}s", lambda v: self._set_cfg("burst_pause", v))

        uni = ttk.LabelFrame(p, text="  Unicode & Input Method ", padding=10)
        uni.pack(fill="x", padx=10, pady=5)
        mr = tk.Frame(uni, bg=C["base"])
        mr.pack(fill="x")
        tk.Label(mr, text="Input Method:", bg=C["base"], fg=C["text"], font=("Poppins", 9)).pack(side="left")
        self._method_var = tk.StringVar(value=self.config.unicode_method)
        mc = ttk.Combobox(mr, textvariable=self._method_var, values=["pynput","clipboard"], state="readonly", width=12)
        mc.pack(side="left", padx=8)
        mc.bind("<<ComboboxSelected>>", lambda _: self._set_cfg("unicode_method", self._method_var.get()))
        tk.Label(uni, text="pynput = cepat (BMP)   |   clipboard = reliable untuk emoji",
                 font=("Poppins",8), bg=C["base"], fg=C["subtext"], justify="left").pack(anchor="w", pady=(4,0))

        cdf = ttk.LabelFrame(p, text="  Countdown ", padding=10)
        cdf.pack(fill="x", padx=10, pady=5)
        self._sv["countdown"] = self._add_slider(cdf, "Detik sebelum mulai mengetik", 0, 10, self.config.countdown, 0, "{:.0f}s", lambda v: self._set_cfg("countdown", int(v)))

        hkf = ttk.LabelFrame(p, text="  Global Hotkeys ", padding=10)
        hkf.pack(fill="x", padx=10, pady=5)
        self._hk_vars = {}
        for i, (lbl, attr) in enumerate([("Start / Resume","hotkey_start"),("Pause","hotkey_pause"),("Stop / Abort","hotkey_stop")]):
            row = tk.Frame(hkf, bg=C["base"])
            row.grid(row=i, column=0, sticky="w", pady=4)
            tk.Label(row, text=f"{lbl}:", bg=C["base"], fg=C["text"], width=16, anchor="w", font=("Poppins", 9)).pack(side="left")
            var = tk.StringVar(value=getattr(self.config, attr).upper())
            self._hk_vars[attr] = var
            e = ttk.Entry(row, textvariable=var, width=8)
            e.pack(side="left", padx=4)
            e.bind("<FocusOut>", lambda _, a=attr, v=var: (self._set_cfg(a, v.get().lower()), self._start_hotkey_listener()))
        tk.Label(hkf, text="Contoh: f9  f10  f11  home  insert",
                 font=("Poppins",8), bg=C["base"], fg=C["subtext"]).grid(row=3, column=0, sticky="w", pady=(4,0))

        prf = ttk.LabelFrame(p, text="  Typing Profiles ", padding=10)
        prf.pack(fill="x", padx=10, pady=5)
        row1 = tk.Frame(prf, bg=C["base"])
        row1.pack(fill="x", pady=(0,6))
        tk.Label(row1, text="Nama profile:", bg=C["base"], fg=C["text"], font=("Poppins", 9)).pack(side="left")
        self._prof_name_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self._prof_name_var, width=18).pack(side="left", padx=(6,0))
        ttk.Button(row1, text="Simpan", command=self._save_profile).pack(side="left", padx=(6,0))
        row2 = tk.Frame(prf, bg=C["base"])
        row2.pack(fill="x")
        tk.Label(row2, text="Load profile:", bg=C["base"], fg=C["text"], font=("Poppins", 9)).pack(side="left")
        self._prof_select_var = tk.StringVar()
        self._prof_combo = ttk.Combobox(row2, textvariable=self._prof_select_var, state="readonly", width=18)
        self._prof_combo.pack(side="left", padx=(6,0))
        ttk.Button(row2, text="Load", command=self._load_profile).pack(side="left", padx=(6,0))
        ttk.Button(row2, text="Hapus", command=self._delete_profile).pack(side="left", padx=(4,0))
        self._refresh_profiles()

        ttk.Button(p, text="  Simpan Semua Settings  ", command=self._cmd_save).pack(pady=12)

    def _build_about_tab(self):
        f = self._tab_about
        tk.Label(f, text="TypeSim", font=("Montserrat",22,"bold"), bg=C["base"], fg=C["blue"]).pack(pady=(50,4))
        tk.Label(f, text="Windows Typing Simulator  v1.1", font=("Poppins",10), bg=C["base"], fg=C["text"]).pack()
        tk.Label(f, text="Mensimulasikan ketukan keyboard manusia ke aplikasi Windows manapun.", font=("Poppins",9), bg=C["base"], fg=C["subtext"]).pack(pady=(6,20))
        for label, val in [("Keyboard sim","pynput (Unicode)"),("Clipboard fallback","pyperclip (emoji/non-BMP)"),("Window target","pywin32"),("GUI","Tkinter + ttk")]:
            row = tk.Frame(f, bg=C["base"])
            row.pack(pady=2)
            tk.Label(row, text=f"{label}:", bg=C["base"], fg=C["subtext"], width=22, anchor="e", font=("Poppins", 9)).pack(side="left")
            tk.Label(row, text=val, bg=C["base"], fg=C["text"], font=("Poppins", 9)).pack(side="left", padx=6)
        tk.Label(f, text="\nF9 = Start     F10 = Pause     F11 = Stop", font=("Montserrat",9,"bold"), bg=C["base"], fg=C["blue"]).pack(pady=20)

    def _add_slider(self, parent, label, from_, to, initial, row, fmt, on_change):
        tk.Label(parent, text=label, bg=C["base"], fg=C["text"], width=36, anchor="w",
                 font=("Poppins",9)).grid(row=row, column=0, sticky="w", pady=3)
        var = tk.DoubleVar(value=initial)
        val_lbl = tk.Label(parent, text=fmt.format(initial), bg=C["base"], fg=C["text"],
                            width=10, anchor="w", font=("Poppins",9,"bold"))
        val_lbl.grid(row=row, column=2, sticky="w", padx=(4,0))
        def _upd(v): val_lbl.config(text=fmt.format(float(v))); on_change(float(v))
        ttk.Scale(parent, from_=from_, to=to, variable=var, orient="horizontal",
                  length=220, command=_upd).grid(row=row, column=1, sticky="ew", padx=(8,4), pady=3)
        parent.columnconfigure(1, weight=1)
        return var

    def _set_cfg(self, attr, value):
        setattr(self.config, attr, value)
        self.engine.config = self.config
        self._update_stats()

    def _sync_ui_from_config(self):
        mapping = {
            "wpm": self.config.wpm,
            "variation": self.config.variation * 100,
            "error_rate": self.config.error_rate * 100,
            "error_correction_delay": self.config.error_correction_delay,
            "thinking_pause_chance": self.config.thinking_pause_chance * 100,
            "thinking_pause_min": self.config.thinking_pause_min,
            "thinking_pause_max": self.config.thinking_pause_max,
            "burst_chars": self.config.burst_chars,
            "burst_pause": self.config.burst_pause,
            "countdown": self.config.countdown,
        }
        for k, v in mapping.items():
            if k in self._sv: self._sv[k].set(v)
        if hasattr(self, "_burst_var"):  self._burst_var.set(self.config.burst_mode)
        if hasattr(self, "_method_var"): self._method_var.set(self.config.unicode_method)
        for attr, var in getattr(self, "_hk_vars", {}).items():
            var.set(getattr(self.config, attr).upper())
        self._update_stats()

    def _cmd_save(self):
        self.config.save()
        self._set_sbar("Settings tersimpan!", timeout=3000, color=C["green"])

    def _refresh_profiles(self):
        names = prof.get_names()
        self._prof_combo["values"] = names
        if names and not self._prof_select_var.get():
            self._prof_select_var.set(names[0])

    def _save_profile(self):
        name = self._prof_name_var.get().strip()
        if not name:
            messagebox.showwarning("TypeSim", "Masukkan nama profile.")
            return
        prof.save_profile(name, self.config)
        self._refresh_profiles()
        self._prof_select_var.set(name)
        self._set_sbar(f"Profile '{name}' tersimpan.", timeout=3000, color=C["green"])

    def _load_profile(self):
        name = self._prof_select_var.get()
        if not name:
            messagebox.showwarning("TypeSim", "Pilih profile terlebih dahulu.")
            return
        prof.apply_profile(name, self.config)
        self.engine.config = self.config
        self._sync_ui_from_config()
        self._prof_name_var.set(name)
        self._set_sbar(f"Profile '{name}' dimuat.", timeout=3000, color=C["blue"])

    def _delete_profile(self):
        name = self._prof_select_var.get()
        if not name: return
        if not messagebox.askyesno("TypeSim", f"Hapus profile '{name}'?"): return
        prof.delete_profile(name)
        self._refresh_profiles()
        self._prof_select_var.set("")
        self._set_sbar(f"Profile '{name}' dihapus.", timeout=3000, color=C["red"])

    def _refresh_windows(self):
        self._windows = get_open_windows(exclude_title=APP_TITLE)
        titles = ["<Active window when countdown ends>"] + [t for _, t in self._windows]
        self._win_combo["values"] = titles
        if self._win_var.get() not in titles: self._win_var.set(titles[0])

    def _start_hotkey_listener(self):
        self._stop_hotkey_listener()
        try:
            from pynput import keyboard as pk
            hk_map = {
                f"<{self.config.hotkey_start}>": self._hk_start,
                f"<{self.config.hotkey_pause}>": self._hk_pause,
                f"<{self.config.hotkey_stop}>":  self._hk_stop,
            }
            self._hotkey_listener = pk.GlobalHotKeys(hk_map)
            self._hotkey_listener.start()
        except Exception as e:
            print(f"Hotkey error: {e}")

    def _stop_hotkey_listener(self):
        if self._hotkey_listener:
            try: self._hotkey_listener.stop()
            except: pass
            self._hotkey_listener = None

    def _hk_start(self):
        if self._is_running and self._is_paused: self.root.after(0, self._cmd_pause)
        elif not self._is_running: self.root.after(0, self._cmd_start)

    def _hk_pause(self):
        if self._is_running: self.root.after(0, self._cmd_pause)

    def _hk_stop(self):
        if self._is_running: self.root.after(0, self._cmd_stop)

    def _cmd_start(self):
        text = self._text.get("1.0", "end-1c")
        if not text.strip():
            messagebox.showwarning("TypeSim", "Masukkan teks terlebih dahulu.")
            return
        selected = self._win_var.get()
        if selected != "<Active window when countdown ends>":
            for hwnd, title in self._windows:
                if title == selected:
                    focus_window(hwnd); break
        self._is_running = True
        self._is_paused  = False
        self._btn_start.config(state="disabled")
        self._progress_var.set(0)
        self._eta_lbl.config(text="")
        
        self.root.withdraw()
        self._floating = FloatingBar(self)
        self.engine.config = self.config
        self.engine.start(text, countdown=self.config.countdown)

    def _cmd_pause(self):
        if not self._is_paused:
            self.engine.pause(); self._is_paused = True
            self._status_dot.config(text="Paused")
            if self._floating: self._floating.set_paused(True)
        else:
            self.engine.resume(); self._is_paused = False
            self._status_dot.config(text="Typing...")
            if self._floating: self._floating.set_paused(False)

    def _cmd_stop(self):
        self.engine.stop()
        self._close_floating()
        self.root.deiconify()
        self._reset_ui("Stopped")
        self._set_sbar("Stopped.")

    def _close_floating(self):
        if self._floating:
            try: self._floating.destroy()
            except: pass
            self._floating = None

    def _reset_ui(self, status="Idle"):
        self._is_running = False; self._is_paused = False
        self._btn_start.config(state="normal")
        self._status_dot.config(text=status)

    def _cb_progress(self, current, total):
        pct = (current/total*100) if total else 0
        rem_words = (total - current) / 5
        wpm = max(1, self.config.wpm)
        if rem_words > 0:
            sec = rem_words / wpm * 60
            eta = f"~{sec:.0f}s tersisa" if sec < 60 else f"~{sec/60:.1f}min tersisa"
        else:
            eta = "Hampir selesai..."
        def _upd():
            self._progress_var.set(pct)
            self._eta_lbl.config(text=eta)
            if self._floating: self._floating.set_progress(pct, eta)
        self.root.after(0, _upd)

    def _cb_status(self, msg):
        def _upd():
            self._status_dot.config(text=msg)
            if "Starting in" in msg:
                n = msg.split("Starting in ")[1].replace("...","").strip()
                if self._floating:
                    self._floating.set_status(f"Mulai dalam {n}s — klik jendela target sekarang!", color=C["yellow"])
            elif "Typing" in msg:
                if self._floating:
                    self._floating.set_status("Mengetik...", color=C["green"])
        self.root.after(0, _upd)

    def _cb_done(self):
        def _upd():
            self._progress_var.set(100)
            self._eta_lbl.config(text="Selesai!")
            self._close_floating()
            self.root.deiconify()
            self._reset_ui("Selesai!")
            self._set_sbar("Selesai! Siap untuk run berikutnya.", color=C["green"], timeout=5000)
        self.root.after(0, _upd)

    def _set_sbar(self, text, color=None, timeout=0):
        self._sbar_lbl.config(text=text, fg=color or C["subtext"])
        if timeout:
            self.root.after(timeout, lambda: self._sbar_lbl.config(
                text="Ready  |  F9=Start   F10=Pause   F11=Stop", fg=C["subtext"]))

    def _update_stats(self, *_):
        text = self._text.get("1.0", "end-1c")
        nc = len(text); nw = len(text.split()) if text.strip() else 0
        wpm = max(1, self.config.wpm)
        if nw:
            sec = nw/wpm*60
            eta = f"~{sec:.0f}s" if sec < 60 else f"~{sec/60:.1f} min"
        else:
            eta = "--"
        self._stats_lbl.config(text=f"{nc:,} chars  |  {nw:,} words  |  ETA: {eta}")

    def on_close(self):
        self.engine.stop()
        self._close_floating()
        self._stop_hotkey_listener()
        self.root.destroy()

def main():
    root = tk.Tk()
    app = TypeSimApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()

if __name__ == "__main__":
    main()
