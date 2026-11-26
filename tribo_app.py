"""
TriboAnalyzer v1.0 — Анализ трибоиспытаний.
Main application entry point.
"""

import os
import json
import math
import csv
import shutil
import tempfile
import zipfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Optional

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import matplotlib.ticker as mticker
import numpy as np

# Drag-and-drop support (tkinterdnd2)
try:
    from tkinterdnd2 import TkinterDnD
    TKDND_AVAILABLE = True
except ImportError:
    TKDND_AVAILABLE = False

# Clipboard support for paste fallback
try:
    import pyperclip
    PYPERCLIP_AVAILABLE = True
except ImportError:
    PYPERCLIP_AVAILABLE = False

from data_model import (
    TribSample, TestParams, parse_tribology_file,
    compute_friction_path, apply_smoothing, SMOOTH_METHODS,
    compute_tribology_wear,
)
from tribology import detect_friction_regimes
from wear_calc import (
    calc_wear_depth, calc_wear_area, calc_wear_volume,
    calc_wear_volume_edge_radius, calc_wear_errors, calc_gravimetric,
    compute_wear_metrics_and_errors,
    INSTRUMENT_SPECS,
)
from wear_scar_window import WearScarWindow
from export import export_graph, export_table_dialog, export_table_docx, export_table_xlsx, DOCX_AVAILABLE, XLSX_AVAILABLE


# ======================================================================
# Default formatting config for results table
# ======================================================================

DEFAULT_FORMAT_CONFIG = {
    "mu_avg":        {"decimals": 2, "err_decimals": 2, "units": {"": 1},                                      "selected_unit": "",        "header": "μ ср.", "show_err": True},
    "mu_std":        {"decimals": 2, "err_decimals": 2, "units": {"": 1},                                      "selected_unit": "",        "header": "σ(μ)", "show_err": True},
    "L_mm":          {"decimals": 2, "err_decimals": 2, "units": {"мм": 1, "мкм": 1e3},                        "selected_unit": "мм",      "header": "L", "show_err": True},
    "W_mm":          {"decimals": 2, "err_decimals": 2, "units": {"мм": 1, "мкм": 1e3},                        "selected_unit": "мм",      "header": "W", "show_err": True},
    "h_mm":          {"decimals": 4, "err_decimals": 4, "units": {"мм": 1, "мкм": 1e3},                        "selected_unit": "мм",      "header": "h", "show_err": True},
    "S_mm2":         {"decimals": 4, "err_decimals": 4, "units": {"мм²": 1, "мкм²": 1e6},                      "selected_unit": "мкм²",    "header": "S", "show_err": True},
    "V_mm3":         {"decimals": 4, "err_decimals": 4, "units": {"мм³": 1, "мкм³": 1e9},                      "selected_unit": "мкм³",    "header": "V", "show_err": True},
    "D_m":           {"decimals": 4, "err_decimals": 4, "units": {"м": 1, "мм": 1e3, "мкм": 1e6},              "selected_unit": "мкм",     "header": "D", "show_err": True},
    "I_h":           {"decimals": 2, "err_decimals": 2, "units": {"мкм/м": 1, "мм/м": 1e-3},                   "selected_unit": "мкм/м",   "header": "Iₕ", "show_err": True},
    "I_A":           {"decimals": 2, "err_decimals": 2, "units": {"мкм/Дж": 1},                                "selected_unit": "мкм/Дж",  "header": "Iₐ", "show_err": True},
    "eps":           {"decimals": 2, "err_decimals": 2, "units": {"м/мкм": 1},                                 "selected_unit": "м/мкм",   "header": "ε", "show_err": True},
    "k":             {"decimals": 2, "err_decimals": 2, "units": {"мм³/Н·м": 1, "10⁻⁶·мм³/Н·м": 1e6, "мм³/мН·м": 1e-3, "мкм³/Н·м": 1e9, "мкм³/мН·м": 1e6}, "selected_unit": "мм³/Н·м", "header": "k", "show_err": True},
    "V_D":           {"decimals": 2, "err_decimals": 2, "units": {"мм³/м": 1, "мкм³/м": 1e9},                  "selected_unit": "мм³/м",   "header": "V/D", "show_err": True},
    "eps_V":         {"decimals": 2, "err_decimals": 2, "units": {"м/мкм³": 1, "м/мм³": 1e9},                    "selected_unit": "м/мм³",   "header": "ε_V", "show_err": True},
    "A_J":           {"decimals": 2, "err_decimals": 2, "units": {"Дж": 1, "мДж": 1e3, "кДж": 1e-3},           "selected_unit": "Дж",      "header": "A", "show_err": True},
    "P_W":           {"decimals": 2, "err_decimals": 2, "units": {"Вт": 1, "мВт": 1e3},                        "selected_unit": "Вт",      "header": "P", "show_err": True},
    "p_MPa":         {"decimals": 2, "err_decimals": 2, "units": {"МПа": 1, "ГПа": 1e-3, "кПа": 1e3, "Па": 1e6}, "selected_unit": "МПа",     "header": "p", "show_err": True},
    "t_steady_s":    {"decimals": 0, "err_decimals": 1, "units": {"с": 1, "мс": 1e3},                          "selected_unit": "с",       "header": "t стаб.", "show_err": True},
    "mu_amplitude":  {"decimals": 2, "err_decimals": 2, "units": {"": 1},                                      "selected_unit": "",        "header": "Δμ ампл.", "show_err": True},
    "mu_cov":        {"decimals": 2, "err_decimals": 2, "units": {"": 1},                                      "selected_unit": "",        "header": "COV(μ)", "show_err": True},
    "grav_delta_m":  {"decimals": 2, "err_decimals": 2, "units": {"мг": 1, "мкг": 1e3},                        "selected_unit": "мг",      "header": "Δm", "show_err": True},
    "grav_V":        {"decimals": 4, "err_decimals": 4, "units": {"мм³": 1, "мкм³": 1e9},                      "selected_unit": "мм³",     "header": "Vвзв", "show_err": True},
    "grav_delta_V":  {"decimals": 4, "err_decimals": 4, "units": {"мм³": 1, "мкм³": 1e9},                      "selected_unit": "мм³",     "header": "±ΔV", "show_err": True},
    "grav_k":        {"decimals": 2, "err_decimals": 2, "units": {"мм³/Н·м": 1, "10⁻⁶·мм³/Н·м": 1e6, "мм³/мН·м": 1e-3, "мкм³/Н·м": 1e9, "мкм³/мН·м": 1e6}, "selected_unit": "мм³/Н·м", "header": "kвзв", "show_err": True},
    "grav_delta_k":  {"decimals": 2, "err_decimals": 2, "units": {"": 1},                                      "selected_unit": "",        "header": "±kвзв", "show_err": True},
}


# ======================================================================
# Tooltip helper
# ======================================================================

class ToolTip:
    """Tooltip for tkinter widgets."""

    def __init__(self, widget: tk.Widget, text: str):
        self.widget = widget
        self.text = text
        self.tip_window = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, event=None):
        if self.tip_window:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw, text=self.text, justify=tk.LEFT,
            background="#ffffe0", relief=tk.SOLID, borderwidth=1,
            font=("Segoe UI", 9), wraplength=350, padx=6, pady=4,
        )
        label.pack()

    def _hide(self, event=None):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None


# ======================================================================
# Tooltip descriptions for table columns
# ======================================================================

COLUMN_TOOLTIPS = {
    "name": "Образец — название файла испытания",
    "num_pts": "Количество точек данных в файле",
    "date": "Дата проведения испытания",
    "duration_s": "Общее время испытания (с)",
    "mu_avg": "Среднее значение коэффициента трения за всё испытание",
    "mu_std": "Стандартное отклонение коэффициента трения (стабильность процесса)",
    "mu_min": "Минимальное значение коэффициента трения",
    "mu_max": "Максимальное значение коэффициента трения",
    "path_m": "Общий путь трения (м) = ω·R·t",
    "L_mm": "Длина лунки износа (мм) — по оси трения",
    "W_mm": "Ширина лунки износа (мм) — перпендикулярно оси трения",
    "h_mm": "Максимальная глубина лунки (мм) = R − √(R²−L²/4)",
    "S_mm2": "Площадь поперечного сечения трека S_BCD (мм²)",
    "V_mm3": "Объём износа V = S·W (мм³)",
    "D_m": "Путь трения D (м) — нормализация для Archard",
    "I_h": "Интенсивность износа по пути Iₕ = h/D (мкм/м)",
    "I_A": "Интенсивность износа по работе Iₐ = h/A (мкм/Дж)",
    "eps": "Сопротивление износа ε = 1/Iₕ (м/мкм)",
    "k": "Коэффициент износа Арчарда k = V/(F_N·D) (мм³/Н·м)",
    "V_D": "Объём износа на единицу пути V/D (мм³/м)",
    "eps_V": "Объёмное сопротивление износу ε_V = D/V (м/мкм³)",
    "A_J": "Работа трения A = ∫ F_N·μ·ds (Дж)",
    "P_W": "Мощность трения P = A/t (Вт)",
    "p_MPa": "Контактное давление p = F_N/(πR²) (МПа)",
    "t_steady_s": "Время выхода на стационарный режим (с)",
    "mu_amplitude": "Амплитуда флуктуаций μ (95-й перцентиль − 5-й перцентиль)",
    "stick_slip": "Эффект «скольжение-скачок» (Да/Нет)",
    "mu_cov": "Коэффициент вариации COV = σ/μ (стабильность трения)",
    "grav_delta_m": "Потеря массы Δm = m₁ − m₂ (мг)",
    "grav_V": "Объём износа по взвешиванию V = Δm/ρ (мм³)",
    "grav_delta_V": "Погрешность объёма ±ΔV = δm/ρ (мм³)",
    "grav_k": "Удельный износ k = V/(F_N·D) (мм³/Н·м)",
    "grav_delta_k": "Погрешность удельного износа ±k",
}


class TriboApp:
    """Main GUI application."""

    BG = "#f0f0f0"
    FONT = ("Segoe UI", 10)
    FONT_BOLD = ("Segoe UI", 10, "bold")
    FONT_TITLE = ("Segoe UI", 12, "bold")

    SAMPLE_COLORS = [
        "#e63946", "#457b9d", "#2a9d8f", "#e9c46a",
        "#f4a261", "#264653", "#a8dadc", "#6d6875",
        "#b5838d", "#ffb4a2", "#023e8a", "#48cae4",
    ]

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("TriboAnalyzer v1.0")
        self.root.geometry("1400x900")
        self.root.minsize(900, 600)
        self.root.configure(bg=self.BG)
        self._set_app_icon()

        self.samples: list[TribSample] = []
        self.params = TestParams()
        self.color_idx = 0

        # Per-sample curve colors (index -> hex color)
        self._curve_colors: dict[int, str] = {}

        # Curve visibility toggles
        self.show_curve_var: dict[str, tk.BooleanVar] = {}

        # Show friction regimes on graph
        self.show_regimes_var = tk.BooleanVar(value=True)

        # Project path
        self._project_path: Optional[str] = None

        # Wear analyzer windows registry
        self._analyzer_windows: list = []

        # Default calibration from analyzer
        self._project_default_calib: dict = {"calib_px": 100.0, "calib_mm": 1.0}

        # Relative calibration error for L/W
        self.calib_rel_error: float = 0.01

        # Table formatting config (per-column decimals + unit multiplier)
        self.format_config: dict = {k: {kk: vv for kk, vv in v.items()} for k, v in DEFAULT_FORMAT_CONFIG.items()}

        # Build menu bar
        self._build_menu()

        self._build_ui()

        # Drag-and-drop & file paste
        self._enable_dnd()
        self.file_listbox.bind("<Button-3>", self._on_listbox_right_click)

    def _set_app_icon(self):
        """Generate and set a tribology-themed app icon (pin on disc)."""
        try:
            from PIL import Image, ImageDraw
            size = 64
            img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            cx, cy = size // 2, size // 2
            # Disc (circle)
            r_disc = 26
            draw.ellipse([cx - r_disc, cy - r_disc, cx + r_disc, cy + r_disc],
                         fill="#457b9d", outline="#1d3557", width=2)
            # Pin (vertical rectangle)
            pin_w, pin_h = 6, 20
            draw.rectangle([cx - pin_w // 2, cy - r_disc - pin_h + 6,
                            cx + pin_w // 2, cy - r_disc + 6],
                           fill="#e63946", outline="#a80000", width=1)
            # Friction arrow (→)
            arrow_y = cy + r_disc + 8
            draw.line([cx - 14, arrow_y, cx + 14, arrow_y], fill="#1d3557", width=2)
            draw.polygon([(cx + 14, arrow_y), (cx + 8, arrow_y - 4), (cx + 8, arrow_y + 4)],
                         fill="#1d3557")
            # Contact point glow
            draw.ellipse([cx - 4, cy - r_disc + 2, cx + 4, cy - r_disc + 10],
                         fill="#e9c46a")
            icon_path = os.path.join(tempfile.gettempdir(), "tribo_icon.ico")
            img.save(icon_path, format="ICO", sizes=[(64, 64), (32, 32), (16, 16)])
            self.root.iconbitmap(icon_path)
        except Exception:
            pass

    # ==================================================================
    # Menu bar
    # ==================================================================

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Новый проект", command=self._new_project, accelerator="Ctrl+N")
        file_menu.add_command(label="Открыть проект...", command=self._open_project, accelerator="Ctrl+O")
        file_menu.add_command(label="Сохранить проект", command=self._save_project, accelerator="Ctrl+S")
        file_menu.add_command(label="Сохранить проект как...", command=self._save_project_as)
        file_menu.add_separator()
        file_menu.add_command(label="Выход", command=self.root.quit)
        menubar.add_cascade(label="Файл", menu=file_menu)

        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Формат таблицы результатов...", command=self._format_settings_dialog)
        menubar.add_cascade(label="Настройки", menu=settings_menu)

        self.root.bind("<Control-n>", lambda e: self._new_project())
        self.root.bind("<Control-o>", lambda e: self._open_project())
        self.root.bind("<Control-s>", lambda e: self._save_project())

    # ==================================================================
    # UI
    # ==================================================================

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=self.BG)
        style.configure("TLabel", background=self.BG, font=self.FONT)
        style.configure("TButton", font=self.FONT)
        style.configure("Title.TLabel", font=self.FONT_TITLE, background=self.BG)
        style.configure("Treeview", font=("Consolas", 9), rowheight=22)
        style.configure("Treeview.Heading", font=self.FONT_BOLD)
        style.configure("TNotebook", background=self.BG)
        style.configure("TNotebook.Tab", font=self.FONT, padding=[12, 4])

        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        left = ttk.Frame(paned, width=320)
        paned.add(left, weight=0)
        self._build_left_panel(left)

        right = ttk.Frame(paned)
        paned.add(right, weight=1)

        self.notebook = ttk.Notebook(right)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        graph_tab = ttk.Frame(self.notebook)
        self.notebook.add(graph_tab, text="  График  ")
        self._build_graph(graph_tab)

        table_tab = ttk.Frame(self.notebook)
        self.notebook.add(table_tab, text="  Таблица  ")
        self._build_right_panel(table_tab)

        analyzer_tab = ttk.Frame(self.notebook)
        self.notebook.add(analyzer_tab, text="  Анализатор лунок  ")
        self._analyzer = WearScarWindow(self.root, self.params, self.samples,
                                         app=self, parent=analyzer_tab)
        self._analyzer_windows.append(self._analyzer)

    # ----- Left panel --------------------------------------------------------

    def _build_left_panel(self, parent: ttk.Frame):
        ttk.Label(parent, text="Файлы испытаний", style="Title.TLabel").pack(
            anchor=tk.W, padx=5, pady=(5, 2)
        )

        bf = ttk.Frame(parent)
        bf.pack(fill=tk.X, padx=5, pady=2)
        ttk.Button(bf, text="+ Добавить", command=self._add_files).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text="Папка", command=self._add_folder).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text="Удалить", command=self._remove_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text="Очистить", command=self._clear_files).pack(side=tk.LEFT, padx=2)

        lf = ttk.Frame(parent)
        lf.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)
        self.file_listbox = tk.Listbox(lf, selectmode=tk.EXTENDED, font=("Consolas", 9), height=12)
        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.file_listbox.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.file_listbox.configure(yscrollcommand=scroll.set)

        # --- Smoothing ---
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=5, pady=6)
        ttk.Label(parent, text="Сглаживание", style="Title.TLabel").pack(anchor=tk.W, padx=5, pady=(0, 2))

        sf0 = ttk.Frame(parent)
        sf0.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(sf0, text="Образец:").pack(side=tk.LEFT)
        self.smooth_sample_var = tk.StringVar()
        self.smooth_sample_combo = ttk.Combobox(sf0, textvariable=self.smooth_sample_var, state="readonly", width=22)
        self.smooth_sample_combo.pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)
        self.smooth_sample_combo.bind("<<ComboboxSelected>>", self._on_smooth_combo_select)

        sf = ttk.Frame(parent)
        sf.pack(fill=tk.X, padx=5, pady=2)
        self.smooth_enabled_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(sf, text="Вкл", variable=self.smooth_enabled_var).grid(row=0, column=0, padx=2)
        ttk.Label(sf, text="Метод:").grid(row=0, column=1, padx=(6, 2))
        self.smooth_method_var = tk.StringVar(value="savgol")
        self.smooth_method_combo = ttk.Combobox(
            sf, textvariable=self.smooth_method_var, width=14,
            values=list(SMOOTH_METHODS.values()), state="readonly"
        )
        self.smooth_method_combo.grid(row=0, column=2, padx=2)

        sf2 = ttk.Frame(parent)
        sf2.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(sf2, text="Окно:").grid(row=0, column=0, padx=2)
        self.smooth_window_var = tk.StringVar(value="21")
        ttk.Spinbox(sf2, from_=3, to=501, increment=2, width=5, textvariable=self.smooth_window_var).grid(row=0, column=1, padx=2)
        ttk.Label(sf2, text="Полином:").grid(row=0, column=2, padx=(8, 2))
        self.smooth_poly_var = tk.StringVar(value="3")
        ttk.Spinbox(sf2, from_=1, to=10, width=3, textvariable=self.smooth_poly_var).grid(row=0, column=3, padx=2)
        ttk.Button(sf2, text="К образцу", command=self._apply_smooth_to_selected).grid(row=0, column=4, padx=(8, 2))
        ttk.Button(sf2, text="Ко всем", command=self._apply_smooth_to_all).grid(row=0, column=5, padx=2)

        # --- Test params ---
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=5, pady=6)
        ttk.Label(parent, text="Параметры испытания", style="Title.TLabel").pack(anchor=tk.W, padx=5, pady=(0, 4))

        pf = ttk.Frame(parent)
        pf.pack(fill=tk.X, padx=5)
        self.param_vars: dict[str, tk.StringVar] = {}
        for i, (lbl, key, default) in enumerate([
            ("Диаметр диска, мм", "disk_diameter_mm", "60"),
            ("Нагрузка, мН", "load_mN", "200"),
            ("Время испыт., с", "test_time_s", "1500"),
            ("Скорость об/с", "rotation_speed_rev_s", "0.5"),
            ("Радиус скругл. диска, мм", "edge_radius_mm", "0.0"),
            ("Относит. погрешн. размеров, %", "calib_rel_error", "1"),
        ]):
            ttk.Label(pf, text=lbl).grid(row=i, column=0, sticky=tk.W, pady=1)
            var = tk.StringVar(value=default)
            self.param_vars[key] = var
            ttk.Entry(pf, textvariable=var, width=10).grid(row=i, column=1, sticky=tk.E, pady=1, padx=(4, 0))
        ttk.Button(parent, text="Применить", command=self._apply_params).pack(fill=tk.X, padx=5, pady=4)

        # --- Mode switcher ---
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=5, pady=6)
        ttk.Label(parent, text="Режим анализа износа", style="Title.TLabel").pack(anchor=tk.W, padx=5, pady=(0, 4))
        mf = ttk.Frame(parent)
        mf.pack(fill=tk.X, padx=5, pady=2)
        self.wear_mode_var = tk.StringVar(value="geometry")
        for val, txt in [("geometry", "Геометрия"), ("gravimetric", "Взвешивание"), ("both", "Оба")]:
            ttk.Radiobutton(mf, text=txt, variable=self.wear_mode_var, value=val, command=self._on_wear_mode_change).pack(side=tk.LEFT, padx=4)

        # --- Recalculate button ---
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=5, pady=6)
        ttk.Button(parent, text="Пересчитать все", command=self._recalc_all_metrics).pack(fill=tk.X, padx=5, pady=2)

        # --- Analyzer button ---
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=5, pady=6)
        ttk.Button(parent, text="Анализатор лунок (фото)", command=lambda: self.notebook.select(2) if hasattr(self, 'notebook') else None).pack(fill=tk.X, padx=5, pady=2)

        # --- Gravimetric wear ---
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=5, pady=6)
        self.grav_frame = ttk.LabelFrame(parent, text="Метод взвешивания")
        self.grav_frame.pack(fill=tk.X, padx=5, pady=2)

        # Sample selector
        sf = ttk.Frame(self.grav_frame)
        sf.pack(fill=tk.X, padx=4, pady=2)
        ttk.Label(sf, text="Образец:").pack(side=tk.LEFT)
        self.grav_sample_var = tk.StringVar()
        self.grav_sample_combo = ttk.Combobox(sf, textvariable=self.grav_sample_var, state="readonly", width=22)
        self.grav_sample_combo.pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)
        self.grav_sample_combo.bind("<<ComboboxSelected>>", self._on_grav_combo_select)

        gf = ttk.Frame(self.grav_frame)
        gf.pack(fill=tk.X, padx=4)
        self.grav_vars: dict[str, tk.StringVar] = {}
        for i, (lbl, key, default) in enumerate([
            ("Масса до, мг", "m_before_mg", "0"),
            ("Масса после, мг", "m_after_mg", "0"),
            ("Плотность, г/см³", "density_g_cm3", "0"),
            ("Погрешность весов, мг", "error_mg", "0.1"),
        ]):
            ttk.Label(gf, text=lbl).grid(row=i, column=0, sticky=tk.W, pady=1)
            var = tk.StringVar(value=default)
            self.grav_vars[key] = var
            ttk.Entry(gf, textvariable=var, width=10).grid(row=i, column=1, sticky=tk.E, pady=1, padx=(4, 0))

        gf2 = ttk.Frame(self.grav_frame)
        gf2.pack(fill=tk.X, padx=4, pady=2)
        ttk.Button(gf2, text="Рассчитать", command=self._calc_gravimetric).pack(side=tk.LEFT, padx=2)
        ttk.Button(gf2, text="К образцу", command=self._apply_grav_to_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(gf2, text="Ко всем", command=self._apply_grav_to_all).pack(side=tk.LEFT, padx=2)
        self.grav_result_var = tk.StringVar(value="")
        ttk.Label(self.grav_frame, textvariable=self.grav_result_var, wraplength=300, justify=tk.LEFT).pack(fill=tk.X, padx=4, pady=2)

        # --- Export ---
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=5, pady=6)
        ttk.Button(parent, text="Экспорт графика (PNG)", command=self._export_graph).pack(fill=tk.X, padx=5, pady=2)
        ttk.Button(parent, text="Экспорт таблицы", command=self._export_table).pack(fill=tk.X, padx=5, pady=2)

    # ----- Analyzer tab --------------------------------------------------------

    def _open_wear_analyzer(self):
        """Open analyzer in new tab (if not already embedded)."""
        if hasattr(self, '_analyzer') and self._analyzer:
            self.notebook.select(2)
            return
        analyzer_tab = ttk.Frame(self.notebook)
        self.notebook.add(analyzer_tab, text="  Анализатор лунок  ")
        self._analyzer = WearScarWindow(self.root, self.params, self.samples,
                                         app=self, parent=analyzer_tab)
        self._analyzer_windows.append(self._analyzer)
        self.notebook.select(analyzer_tab)

    # ----- Graph -------------------------------------------------------------

    def _build_graph(self, parent: ttk.Frame):
        gf = ttk.Frame(parent)
        gf.pack(fill=tk.BOTH, expand=True)

        self.fig = Figure(figsize=(8, 5), dpi=100, facecolor="white")
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=gf)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        tb = ttk.Frame(gf)
        tb.pack(fill=tk.X)
        self.toolbar = NavigationToolbar2Tk(self.canvas, tb)
        self.toolbar.update()

        self.ax.set_xlabel("Путь трения, м", fontsize=11)
        self.ax.set_ylabel("Коэффициент трения", fontsize=11)
        self.ax.grid(True, alpha=0.3)

        # Line settings
        sf = ttk.Frame(gf)
        sf.pack(fill=tk.X, padx=4, pady=2)
        ttk.Label(sf, text="Линия:").pack(side=tk.LEFT, padx=2)
        self.linestyle_var = tk.StringVar(value="-")
        ttk.Combobox(sf, textvariable=self.linestyle_var, width=5, values=["-", "--", "-.", ":"], state="readonly").pack(side=tk.LEFT)
        ttk.Label(sf, text="Толщина:").pack(side=tk.LEFT, padx=(8, 2))
        self.linewidth_var = tk.StringVar(value="1.5")
        ttk.Spinbox(sf, from_=0.5, to=5.0, increment=0.5, width=4, textvariable=self.linewidth_var).pack(side=tk.LEFT)
        ttk.Label(sf, text="Точки:").pack(side=tk.LEFT, padx=(8, 2))
        self.markersize_var = tk.StringVar(value="0")
        ttk.Spinbox(sf, from_=0, to=10, width=4, textvariable=self.markersize_var).pack(side=tk.LEFT)
        ttk.Button(sf, text="Обновить", command=self._update_graph).pack(side=tk.LEFT, padx=8)

        # Title
        sf2 = ttk.Frame(gf)
        sf2.pack(fill=tk.X, padx=4, pady=2)
        ttk.Label(sf2, text="Заголовок:").pack(side=tk.LEFT, padx=4)
        self.title_var = tk.StringVar(value="Зависимость коэффициента трения от пути трения")
        ttk.Entry(sf2, textvariable=self.title_var, width=60).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Axis labels
        sf3 = ttk.Frame(gf)
        sf3.pack(fill=tk.X, padx=4, pady=2)
        ttk.Label(sf3, text="X:").pack(side=tk.LEFT, padx=4)
        self.xlabel_var = tk.StringVar(value="Путь трения, м")
        ttk.Entry(sf3, textvariable=self.xlabel_var, width=25).pack(side=tk.LEFT, padx=2)
        ttk.Label(sf3, text="Y:").pack(side=tk.LEFT, padx=(8, 4))
        self.ylabel_var = tk.StringVar(value="Коэффициент трения")
        ttk.Entry(sf3, textvariable=self.ylabel_var, width=25).pack(side=tk.LEFT, padx=2)

        # Font family
        sf_font = ttk.Frame(gf)
        sf_font.pack(fill=tk.X, padx=4, pady=2)
        ttk.Label(sf_font, text="Шрифт:").pack(side=tk.LEFT, padx=4)
        self.font_family_var = tk.StringVar(value="DejaVu Sans")
        font_families = ["DejaVu Sans", "Times New Roman", "Arial", "Helvetica", "Courier New", "Verdana", "Tahoma"]
        ttk.Combobox(sf_font, textvariable=self.font_family_var, values=font_families, width=18, state="readonly").pack(side=tk.LEFT, padx=2)

        # Font sizes
        sf3b = ttk.Frame(gf)
        sf3b.pack(fill=tk.X, padx=4, pady=2)
        ttk.Label(sf3b, text="Шрифт подписей:").pack(side=tk.LEFT, padx=4)
        self.label_fontsize_var = tk.StringVar(value="11")
        ttk.Spinbox(sf3b, from_=6, to=36, width=4, textvariable=self.label_fontsize_var).pack(side=tk.LEFT)
        ttk.Label(sf3b, text="Шрифт цифр:").pack(side=tk.LEFT, padx=(8, 2))
        self.tick_fontsize_var = tk.StringVar(value="9")
        ttk.Spinbox(sf3b, from_=6, to=36, width=4, textvariable=self.tick_fontsize_var).pack(side=tk.LEFT)
        ttk.Label(sf3b, text="Шрифт легенды:").pack(side=tk.LEFT, padx=(8, 2))
        self.legend_fontsize_var = tk.StringVar(value="9")
        ttk.Spinbox(sf3b, from_=6, to=36, width=4, textvariable=self.legend_fontsize_var).pack(side=tk.LEFT)

        # Grid, legend, regimes
        sf4 = ttk.Frame(gf)
        sf4.pack(fill=tk.X, padx=4, pady=2)
        self.grid_var = tk.BooleanVar(value=True)
        self.legend_var = tk.BooleanVar(value=True)
        self.graph_comma_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(sf4, text="Сетка", variable=self.grid_var).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(sf4, text="Легенда", variable=self.legend_var).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(sf4, text="Зоны притирки", variable=self.show_regimes_var,
                        command=self._update_graph).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(sf4, text="Запятая на графике", variable=self.graph_comma_var,
                        command=self._update_graph).pack(side=tk.LEFT, padx=4)

        # Curve visibility toggles
        self._sf_curves = ttk.LabelFrame(gf, text="Кривые", padding=2)
        self._sf_curves.pack(fill=tk.X, padx=4, pady=2)
        self._rebuild_curve_toggles()

        # Axis limits
        sf5 = ttk.Frame(gf)
        sf5.pack(fill=tk.X, padx=4, pady=2)
        self.xlim_auto = tk.BooleanVar(value=True)
        ttk.Checkbutton(sf5, text="Авто X", variable=self.xlim_auto).pack(side=tk.LEFT, padx=4)
        ttk.Label(sf5, text="от:").pack(side=tk.LEFT)
        self.xmin_var = tk.StringVar(value="0")
        ttk.Entry(sf5, textvariable=self.xmin_var, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Label(sf5, text="до:").pack(side=tk.LEFT)
        self.xmax_var = tk.StringVar(value="100")
        ttk.Entry(sf5, textvariable=self.xmax_var, width=8).pack(side=tk.LEFT, padx=2)
        self.ylim_auto = tk.BooleanVar(value=True)
        ttk.Checkbutton(sf5, text="Авто Y", variable=self.ylim_auto).pack(side=tk.LEFT, padx=(10, 4))
        ttk.Label(sf5, text="от:").pack(side=tk.LEFT)
        self.ymin_var = tk.StringVar(value="0")
        ttk.Entry(sf5, textvariable=self.ymin_var, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Label(sf5, text="до:").pack(side=tk.LEFT)
        self.ymax_var = tk.StringVar(value="1")
        ttk.Entry(sf5, textvariable=self.ymax_var, width=8).pack(side=tk.LEFT, padx=2)

        # Bind click on curve
        self.canvas.mpl_connect("pick_event", self._on_curve_pick)

    def _rebuild_curve_toggles(self):
        """Rebuild the curve visibility checkboxes."""
        for w in self._sf_curves.winfo_children():
            w.destroy()
        self.show_curve_var.clear()
        for i, sample in enumerate(self.samples):
            key = sample.name
            var = tk.BooleanVar(value=True)
            self.show_curve_var[key] = var
            color = self._get_curve_color(i)
            cb = ttk.Checkbutton(self._sf_curves, text=sample.name, variable=var,
                                 command=self._update_graph)
            cb.pack(side=tk.LEFT, padx=4)

    # ----- Right panel -------------------------------------------------------

    def _build_right_panel(self, parent: ttk.Frame):
        ttk.Label(parent, text="Итоговая таблица", style="Title.TLabel").pack(anchor=tk.W, padx=5, pady=(5, 2))

        self.table_cols = ("name", "mu_avg", "mu_std",
                "L_mm", "W_mm", "h_mm", "S_mm2", "V_mm3",
                "D_m", "A_J", "I_h", "I_A", "eps", "k", "V_D", "eps_V", "P_W", "p_MPa",
                "t_steady_s", "mu_amplitude", "stick_slip", "mu_cov",
                "grav_delta_m", "grav_V", "grav_delta_V", "grav_k", "grav_delta_k")

        # Tree + both scrollbars in a frame
        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)

        self.tree = ttk.Treeview(tree_frame, columns=self.table_cols, show="headings", height=15)
        for c in self.table_cols:
            self.tree.heading(c, text=self._col_header(c))
            anchor = tk.W if c == "name" else tk.CENTER
            self.tree.column(c, width=90 if c == "name" else 70, minwidth=40, anchor=anchor)
            # Add tooltip to heading label
            tip_text = COLUMN_TOOLTIPS.get(c, "")
            if tip_text:
                self._add_heading_tooltip(c, tip_text)

        # Vertical scrollbar
        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=vsb.set)

        # Horizontal scrollbar
        hsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree.configure(xscrollcommand=hsb.set)

        self.tree.pack(fill=tk.BOTH, expand=True)

        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=5, pady=6)
        self.summary_var = tk.StringVar(value="Загрузите файлы для анализа.")
        ttk.Label(parent, textvariable=self.summary_var, wraplength=400, justify=tk.LEFT).pack(fill=tk.X, padx=5)

        # --- Average values table ---
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=5, pady=6)
        ttk.Label(parent, text="Средние значения", style="Title.TLabel").pack(anchor=tk.W, padx=5, pady=(0, 2))

        avg_frame = ttk.Frame(parent)
        avg_frame.pack(fill=tk.X, padx=5, pady=2)
        
        # Use same columns as main table
        self.avg_tree = ttk.Treeview(avg_frame, columns=self.table_cols, show="headings", height=1)
        for c in self.table_cols:
            self.avg_tree.heading(c, text=self.tree.heading(c)["text"])
            self.avg_tree.column(c, width=self.tree.column(c)["width"], minwidth=40)
        self.avg_tree.pack(fill=tk.X)

    def _add_heading_tooltip(self, col: str, text: str):
        """Add tooltip to a Treeview heading."""
        try:
            # Get the heading label widget
            heading_id = self.tree.heading(col)
            # Find the label widget for this column
            # We need to bind after the tree is rendered
            self.root.after(100, lambda c=col, t=text: self._bind_heading_tip(c, t))
        except Exception:
            pass

    def _bind_heading_tip(self, col: str, text: str):
        """Bind tooltip to the heading label of a column."""
        try:
            # Walk through all children of the treeview to find heading labels
            for child in self.tree.winfo_children():
                pass
            # Use a workaround: bind to the tree itself and check coordinates
            # Actually, we use a simple approach: add tooltip text to the heading itself
            self.tree.heading(col, text=self.tree.heading(col)["text"] + " ℹ")
            # Store tooltip mapping
            if not hasattr(self, "_heading_tooltips"):
                self._heading_tooltips = {}
            self._heading_tooltips[col] = text
            self.tree.bind("<Motion>", self._check_heading_hover, add="+")
        except Exception:
            pass

    def _check_heading_hover(self, event):
        """Check if mouse is over a heading and show tooltip."""
        if not hasattr(self, "_heading_tooltips"):
            return
        # Identify region
        region = self.tree.identify_region(event.x, event.y)
        if region == "heading":
            col = self.tree.identify_column(event.x)
            if col:
                # col is like "#1", "#2", etc.
                col_idx = int(col.replace("#", "")) - 1
                cols_list = list(self.tree["columns"])
                if col_idx < len(cols_list):
                    c = cols_list[col_idx]
                    tip = self._heading_tooltips.get(c, "")
                    if tip and not hasattr(self, "_current_tip_widget"):
                        self._show_heading_tip(event, tip)

    def _show_heading_tip(self, event, text):
        if hasattr(self, "_heading_tip_win") and self._heading_tip_win:
            self._heading_tip_win.destroy()
        x = event.x_root + 15
        y = event.y_root + 15
        tw = tk.Toplevel(self.root)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw, text=text, justify=tk.LEFT,
            background="#ffffe0", relief=tk.SOLID, borderwidth=1,
            font=("Segoe UI", 9), wraplength=350, padx=6, pady=4,
        )
        label.pack()
        self._heading_tip_win = tw

        def destroy_tip():
            if hasattr(self, "_heading_tip_win") and self._heading_tip_win:
                self._heading_tip_win.destroy()
                self._heading_tip_win = None

        self._heading_tip_win.after(3000, destroy_tip)

    # ==================================================================
    # File operations
    # ==================================================================

    def _load_files(self, paths):
        for p in paths:
            self._load_file(p)

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            title="Выберите файлы данных",
            filetypes=[("Текстовые файлы", "*.txt"), ("Все файлы", "*.*")],
        )
        for p in paths:
            self._load_file(p)

    def _add_folder(self):
        folder = filedialog.askdirectory(title="Выберите папку с данными")
        if not folder:
            return
        folder = os.path.normpath(folder)
        loaded = 0
        for fn in sorted(os.listdir(folder)):
            if fn.lower().endswith(".txt"):
                self._load_file(os.path.join(folder, fn))
                loaded += 1
        if loaded == 0:
            messagebox.showinfo("Инфо", "В папке нет .txt файлов.")

    def _load_file(self, path: str):
        norm = os.path.normpath(os.fspath(path))
        if any(s.filepath == norm for s in self.samples):
            return
        try:
            sample = parse_tribology_file(norm)
            if len(sample.time_ms) > 1 and self.params.dt == 0.0:
                dt_ms = np.mean(np.diff(sample.time_ms))
                self.params.dt = dt_ms / 1000.0
            compute_friction_path(sample, self.params)
            self.samples.append(sample)
            color = self.SAMPLE_COLORS[self.color_idx % len(self.SAMPLE_COLORS)]
            self.color_idx += 1
            self.file_listbox.insert(tk.END, f"* {sample.name}  ({len(sample.time_ms)} pts)")
            self.file_listbox.itemconfig(tk.END, fg=color)
            self._refresh_smooth_combo()
            self._rebuild_curve_toggles()
            self._update_graph()
        except Exception as exc:
            messagebox.showerror("Ошибка загрузки", f"Файл: {norm}\n\n{type(exc).__name__}: {exc}")

    def _remove_selected(self):
        sel = list(self.file_listbox.curselection())
        if not sel:
            return
        for i in reversed(sel):
            self.file_listbox.delete(i)
            self.samples.pop(i)
        self._rebuild_curve_toggles()
        self._refresh_all()

    def _clear_files(self):
        self.samples.clear()
        self.file_listbox.delete(0, tk.END)
        self._rebuild_curve_toggles()
        self._refresh_all()

    def _apply_params(self):
        try:
            new_d = float(self.param_vars["disk_diameter_mm"].get())
            new_l = float(self.param_vars["load_mN"].get())
            new_t = float(self.param_vars["test_time_s"].get())
            new_s = float(self.param_vars["rotation_speed_rev_s"].get())
            new_r = float(self.param_vars.get("edge_radius_mm", tk.StringVar(value="0.0")).get())
            new_calib_rel = float(self.param_vars.get("calib_rel_error", tk.StringVar(value="1")).get()) / 100.0
        except ValueError:
            messagebox.showerror("Ошибка", "Проверьте числовые значения параметров.")
            return
        if new_d <= 0 or new_l <= 0 or new_t <= 0 or new_s <= 0 or new_r < 0:
            messagebox.showerror("Ошибка", "Параметры: диаметр, нагрузка, время, скорость > 0; радиус кромки ≥ 0.")
            return
        self.params.disk_diameter_mm = new_d
        self.params.load_mN = new_l
        self.params.test_time_s = new_t
        self.params.rotation_speed_rev_s = new_s
        self.params.edge_radius_mm = new_r
        self.calib_rel_error = new_calib_rel
        for s in self.samples:
            compute_friction_path(s, self.params)
        self._refresh_all()

    def _recalc_all_metrics(self):
        if not self.samples:
            return
        count = 0
        for s in self.samples:
            L = s.wear_L
            W = s.wear_W
            if L <= 0 or W <= 0:
                continue
            if L > self.params.disk_diameter_mm:
                messagebox.showwarning("Внимание", f"Образец {s.name}: длина трека ({L:.2f} мм) превышает диаметр диска ({self.params.disk_diameter_mm:.2f} мм). Расчёт пропущен.")
                continue
            R = self.params.disk_diameter_mm / 2.0
            h = calc_wear_depth(R, L)
            S = calc_wear_area(R, L, h)
            V = calc_wear_volume(S, W) if W > 0 else 0.0
            r = self.params.edge_radius_mm if hasattr(self.params, 'edge_radius_mm') else 0.0
            V_edge = calc_wear_volume_edge_radius(S, W, L, r) if r > 0 and W > 0 else 0.0
            V_final = V_edge if V_edge > 0 else V
            trib = compute_tribology_wear(s, self.params, h, V, V_edge)
            if not trib:
                continue
            s.wear_h = h
            s.wear_S = S
            s.wear_V = V_final
            for key in ("D_m", "A_J", "P_W", "I_h", "I_A", "eps", "k",
                        "mu_avg", "mu_std", "mu_cov", "V_D", "eps_V",
                        "p_MPa", "t_steady_s", "mu_amplitude"):
                setattr(s, f"wear_{key}", trib.get(key, 0.0))
            s.wear_stick_slip = trib.get("stick_slip", "")
            px_per_mm = self._find_calib_for_sample(s)
            compute_wear_metrics_and_errors(s, self.params, R, L, W, V, V_edge, px_per_mm, trib, self.calib_rel_error)
            count += 1
        self._refresh_table()
        if count:
            messagebox.showinfo("Готово", f"Пересчитано {count} образцов.")
        else:
            messagebox.showinfo("Инфо", "Нет образцов с wear L/W. Сначала внесите данные из анализатора.")

    def _find_calib_for_sample(self, sample):
        """Find px_per_mm calibration from analyzer tabs linked to this sample."""
        for aw in self._analyzer_windows:
            if not aw.win.winfo_exists():
                continue
            for tab in aw.tabs:
                if tab.linked_sample is sample and tab.calib_mm > 0:
                    return tab.calib_px / tab.calib_mm
        return self._project_default_calib.get("calib_px", 100.0) / max(self._project_default_calib.get("calib_mm", 1.0), 0.001)

    # ==================================================================
    # Wear mode
    # ==================================================================

    def _on_wear_mode_change(self):
        mode = self.wear_mode_var.get()
        # Show/hide gravimetric frame
        if mode == "geometry":
            self.grav_frame.pack_forget()
        else:  # gravimetric or both
            self.grav_frame.pack(fill=tk.X, padx=5, pady=2)

        # Show/hide table columns
        geom_cols = ["L_mm", "W_mm", "h_mm", "S_mm2", "V_mm3",
                     "D_m", "I_h", "I_A", "eps", "k", "V_D", "P_W", "p_MPa",
                     "t_steady_s", "mu_amplitude", "stick_slip", "mu_cov"]
        grav_cols = ["grav_delta_m", "grav_V", "grav_delta_V", "grav_k", "grav_delta_k"]
        # Friction dynamics columns (hide in gravimetric mode)
        friction_dyn_cols = ["t_steady_s", "mu_amplitude", "stick_slip", "mu_cov"]

        for c in geom_cols:
            # Hide by setting width to 0
            if mode == "gravimetric":
                self.tree.column(c, width=0, minwidth=0, stretch=False)
            else:
                # Restore original width
                orig_widths = {"L_mm": 60, "W_mm": 60, "h_mm": 60, "S_mm2": 65, "V_mm3": 65,
                               "D_m": 70, "I_h": 80, "I_A": 90, "eps": 70, "k": 90,
                               "V_D": 80, "P_W": 65, "p_MPa": 65, "t_steady_s": 70,
                               "mu_amplitude": 70, "stick_slip": 70, "mu_cov": 65}
                self.tree.column(c, width=orig_widths.get(c, 60), minwidth=40, stretch=True)

        for c in grav_cols:
            if mode == "geometry":
                self.tree.column(c, width=0, minwidth=0, stretch=False)
            else:
                orig_widths = {"grav_delta_m": 70, "grav_V": 80, "grav_delta_V": 75,
                               "grav_k": 90, "grav_delta_k": 80}
                self.tree.column(c, width=orig_widths.get(c, 70), minwidth=40, stretch=True)

        # In gravimetric mode, also hide friction dynamics columns
        for c in friction_dyn_cols:
            if mode == "gravimetric":
                self.tree.column(c, width=0, minwidth=0, stretch=False)
            else:
                orig_widths = {"t_steady_s": 70, "mu_amplitude": 70, "stick_slip": 70, "mu_cov": 65}
                self.tree.column(c, width=orig_widths.get(c, 60), minwidth=40, stretch=True)

        # Force Treeview to update column display
        self.tree.update_idletasks()
        self._refresh_table()

    def _on_grav_combo_select(self, _event=None):
        """Load gravimetric data for selected sample."""
        name = self.grav_sample_var.get()
        for s in self.samples:
            if s.name == name:
                self.grav_vars["m_before_mg"].set(str(s.grav_m_before_mg) if s.grav_m_before_mg else "0")
                self.grav_vars["m_after_mg"].set(str(s.grav_m_after_mg) if s.grav_m_after_mg else "0")
                self.grav_vars["density_g_cm3"].set(str(s.grav_density_g_cm3) if s.grav_density_g_cm3 else "0")
                self.grav_vars["error_mg"].set(str(s.grav_error_mg) if s.grav_error_mg else "0.1")
                if s.grav_delta_m_mg != 0:
                    self.grav_result_var.set(
                        f"Δm = {s.grav_delta_m_mg:.3f} мг  V = {s.grav_V_mm3:.4f} мм³\n"
                        f"±ΔV = {s.grav_delta_V_mm3:.4f} мм³\n"
                        f"k = {s.grav_k_mm3_N_m:.3e} мм³/Н·м  ±{s.grav_delta_k:.3e}"
                    )
                break

    # ==================================================================
    # Smoothing
    # ==================================================================

    def _refresh_smooth_combo(self):
        names = [s.name for s in self.samples]
        self.smooth_sample_combo["values"] = names
        self.grav_sample_combo["values"] = names
        if names:
            cur = self.smooth_sample_var.get()
            if cur not in names:
                self.smooth_sample_var.set(names[0])
                self._on_smooth_combo_select()
            grav_cur = self.grav_sample_var.get()
            if grav_cur not in names:
                self.grav_sample_var.set(names[0])

    def _get_selected_sample(self) -> Optional[TribSample]:
        name = self.smooth_sample_var.get()
        for s in self.samples:
            if s.name == name:
                return s
        return None

    def _on_smooth_combo_select(self, _event=None):
        s = self._get_selected_sample()
        if s is None:
            return
        self.smooth_enabled_var.set(s.smooth_enabled)
        method_keys = list(SMOOTH_METHODS.keys())
        if s.smooth_method in method_keys:
            self.smooth_method_combo.current(method_keys.index(s.smooth_method))
        self.smooth_window_var.set(str(s.smooth_window))
        self.smooth_poly_var.set(str(s.smooth_polyorder))

    def _read_smooth_params(self, s: TribSample):
        s.smooth_enabled = self.smooth_enabled_var.get()
        method_keys = list(SMOOTH_METHODS.keys())
        idx = self.smooth_method_combo.current()
        s.smooth_method = method_keys[idx] if idx >= 0 else "savgol"
        try:
            s.smooth_window = max(3, int(self.smooth_window_var.get()))
        except ValueError:
            s.smooth_window = 21
        try:
            s.smooth_polyorder = max(1, int(self.smooth_poly_var.get()))
        except ValueError:
            s.smooth_polyorder = 3

    def _apply_smooth_to_selected(self):
        s = self._get_selected_sample()
        if s is None:
            return
        self._read_smooth_params(s)
        apply_smoothing(s)
        self._update_graph()

    def _apply_smooth_to_all(self):
        if not self.samples:
            return
        for s in self.samples:
            self._read_smooth_params(s)
            apply_smoothing(s)
        self._update_graph()

    # ==================================================================
    # Drag-and-drop & file opening
    # ==================================================================

    def _enable_dnd(self):
        try:
            self.tk.eval('''
                proc ::tkdnd::platform::GetFileFormat {filename} {
                    return {text/plain}
                }
            ''')
            self.drop_target_register("all")
            self.tkdnd_bind('<<Drop>>', self._on_drop)
        except Exception:
            pass  # silent fallback

    def _on_drop(self, event):
        raw = event.data
        if not raw:
            return
        import re
        paths = re.split(r'[\r\n]+', raw.strip())
        self._load_files([p.strip('{}') for p in paths if p.strip()])

    def _on_listbox_right_click(self, event):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Вставить из буфера", command=self._paste_files)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _paste_files(self):
        try:
            import pyperclip
            raw = pyperclip.paste()
        except Exception:
            try:
                raw = self.clipboard_get()
            except Exception:
                messagebox.showerror("Ошибка", "Не удалось прочитать буфер обмена.")
                return
        import os, re
        paths = [line.strip() for line in raw.splitlines() if line.strip()]
        valid = [p for p in paths if os.path.isfile(p)]
        if not valid:
            messagebox.showwarning("Предупреждение", "Буфер обмена не содержит файлов.")
            return
        self._load_files(valid)

    # ==================================================================
    # Graph
    # ==================================================================

    def _get_curve_color(self, idx: int) -> str:
        if idx in self._curve_colors:
            return self._curve_colors[idx]
        return self.SAMPLE_COLORS[idx % len(self.SAMPLE_COLORS)]

    def _on_curve_pick(self, event):
        """Handle click on a curve — open color chooser."""
        if event.mouseevent.button != 1:
            return
        line = event.artist
        if not hasattr(line, "_sample_idx"):
            return
        idx = line._sample_idx
        from tkinter import colorchooser
        cur = self._get_curve_color(idx)
        result = colorchooser.askcolor(initialcolor=cur, title=f"Цвет кривой: {self.samples[idx].name}")
        if result and result[1]:
            self._curve_colors[idx] = result[1]
            self._update_graph()

    def _update_graph(self):
        self.ax.clear()
        try:
            lfs = int(self.label_fontsize_var.get())
        except ValueError:
            lfs = 11
        try:
            tfs = int(self.tick_fontsize_var.get())
        except ValueError:
            tfs = 9
        try:
            legfs = int(self.legend_fontsize_var.get())
        except ValueError:
            legfs = 9
        try:
            lw = float(self.linewidth_var.get())
        except ValueError:
            lw = 1.5
        try:
            ms = float(self.markersize_var.get())
        except ValueError:
            ms = 0
        ls = self.linestyle_var.get()

        font_family = self.font_family_var.get()
        font_props = {'family': font_family}

        for i, sample in enumerate(self.samples):
            key = sample.name
            v = self.show_curve_var.get(key)
            if v is not None and not v.get():
                continue
            color = self._get_curve_color(i)
            path_m = sample.friction_path_m
            if sample.smooth_enabled and len(sample.friction_smooth) > 0:
                ln1 = self.ax.plot(path_m, sample.friction, linestyle=":", linewidth=0.8, color=color, alpha=0.35, markersize=0)
                ln2 = self.ax.plot(path_m, sample.friction_smooth, linestyle=ls, linewidth=lw, color=color, label=f"{sample.name} (сглаж.)", markersize=ms, picker=5)
                ln2[0]._sample_idx = i
            else:
                ln = self.ax.plot(path_m, sample.friction, linestyle=ls, linewidth=lw, color=color, label=sample.name, markersize=ms, picker=5)
                ln[0]._sample_idx = i

            # Colored regime backgrounds (semi-transparent) — use cache
            if self.show_regimes_var.get() and len(path_m) > 10:
                if not sample._regimes_cache:
                    mu_data = sample.friction_smooth if sample.smooth_enabled and len(sample.friction_smooth) > 0 else sample.friction
                    _, _, sample._regimes_cache = detect_friction_regimes(mu_data, path_m)
                regimes = sample._regimes_cache
                colors_map = {"приработка": "#4CAF50", "стационар": "#2196F3", "износ": "#FF5722"}
                for name, i0, i1 in regimes:
                    if i1 > i0 and i0 < len(path_m) and i1 <= len(path_m):
                        x0, x1 = path_m[i0], path_m[i1 - 1]
                        self.ax.axvspan(x0, x1, alpha=0.06, color=colors_map.get(name, "#888"),
                                        zorder=0)

        self.ax.set_xlabel(self.xlabel_var.get(), fontsize=lfs, fontproperties=font_props)
        self.ax.set_ylabel(self.ylabel_var.get(), fontsize=lfs, fontproperties=font_props)
        self.ax.set_title(self.title_var.get(), fontsize=lfs + 1, fontproperties=font_props)
        self.ax.tick_params(axis="both", labelsize=tfs)
        for label in self.ax.get_xticklabels() + self.ax.get_yticklabels():
            label.set_fontproperties(font_props)
        if self.graph_comma_var.get():
            def _comma_formatter(x, pos):
                return f"{x:.2f}".replace(".", ",")
            self.ax.xaxis.set_major_formatter(mticker.FuncFormatter(_comma_formatter))
            self.ax.yaxis.set_major_formatter(mticker.FuncFormatter(_comma_formatter))
        else:
            self.ax.xaxis.set_major_formatter(mticker.ScalarFormatter())
            self.ax.yaxis.set_major_formatter(mticker.ScalarFormatter())
        self.ax.grid(self.grid_var.get(), alpha=0.3)
        if self.legend_var.get() and self.samples:
            self.ax.legend(fontsize=legfs, loc="best", prop=font_props)
        if not self.xlim_auto.get():
            try:
                self.ax.set_xlim(float(self.xmin_var.get()), float(self.xmax_var.get()))
            except ValueError:
                pass
        if not self.ylim_auto.get():
            try:
                self.ax.set_ylim(float(self.ymin_var.get()), float(self.ymax_var.get()))
            except ValueError:
                pass
        self.fig.tight_layout()
        self.canvas.draw()

    # ==================================================================
    # Summary table
    # ==================================================================

    COL_ERR_MAP = {
        "h_mm": "err_h_mm", "S_mm2": "err_S_mm2", "V_mm3": "err_V_mm3",
        "k": "wear_k_err", "I_h": "wear_I_h_err", "I_A": "wear_I_A_err",
        "eps": "wear_eps_err", "V_D": "wear_V_D_err", "eps_V": "wear_eps_V_err",
        "mu_avg": "wear_mu_err", "D_m": "wear_D_err",
        "L_mm": "err_L_mm", "W_mm": "err_W_mm",
        "A_J": "wear_A_err", "P_W": "wear_P_err",
        "p_MPa": "wear_p_err",
        "grav_V": "grav_delta_V_mm3",
        "grav_k": "grav_delta_k",
        "grav_delta_m": "err_grav_delta_m",
    }

    def _get_err(self, s, col):
        fld = self.COL_ERR_MAP.get(col)
        return getattr(s, fld, 0.0) if fld else 0.0

    def _col_header(self, col):
        """Build column header text with unit from format_config."""
        if col == "name":
            return "Образец"
        cfg = self.format_config.get(col, {})
        header = cfg.get("header", col)
        unit = cfg.get("selected_unit", "")
        if unit:
            return f"{header}, {unit}"
        return header

    def _build_table_row(self, sample):
        row = {}
        if sample is None:
            for c in self.table_cols:
                row[c] = ""
            return row
        mu_avg = float(np.mean(sample.friction)) if len(sample.friction) > 0 else 0.0
        mu_std = float(np.std(sample.friction)) if len(sample.friction) > 0 else 0.0
        row["name"] = sample.name
        row["mu_avg"] = self._fmt_val(mu_avg, "mu_avg", self._get_err(sample, "mu_avg"))
        row["mu_std"] = self._fmt_val(mu_std, "mu_std")
        row["L_mm"] = self._fmt_val(sample.wear_L, "L_mm", self._get_err(sample, "L_mm")) if sample.wear_L > 0 else ""
        row["W_mm"] = self._fmt_val(sample.wear_W, "W_mm", self._get_err(sample, "W_mm")) if sample.wear_W > 0 else ""
        row["h_mm"] = self._fmt_val(sample.wear_h, "h_mm", self._get_err(sample, "h_mm")) if sample.wear_h > 0 else ""
        row["S_mm2"] = self._fmt_val(sample.wear_S, "S_mm2", self._get_err(sample, "S_mm2")) if sample.wear_S > 0 else ""
        row["V_mm3"] = self._fmt_val(sample.wear_V, "V_mm3", self._get_err(sample, "V_mm3")) if sample.wear_V > 0 else ""
        row["D_m"] = self._fmt_val(sample.wear_D_m, "D_m", self._get_err(sample, "D_m")) if sample.wear_D_m > 0 else ""
        row["A_J"] = self._fmt_val(sample.wear_A_J, "A_J", self._get_err(sample, "A_J")) if sample.wear_A_J > 0 else ""
        row["I_h"] = self._fmt_val(sample.wear_I_h, "I_h", self._get_err(sample, "I_h")) if sample.wear_I_h > 0 else ""
        row["I_A"] = self._fmt_val(sample.wear_I_A, "I_A", self._get_err(sample, "I_A")) if sample.wear_I_A > 0 else ""
        row["eps"] = self._fmt_val(sample.wear_eps, "eps", self._get_err(sample, "eps")) if sample.wear_eps > 0 else ""
        row["k"] = self._fmt_val(sample.wear_k, "k", self._get_err(sample, "k")) if sample.wear_k > 0 else ""
        row["V_D"] = self._fmt_val(sample.wear_V_D, "V_D", self._get_err(sample, "V_D")) if sample.wear_V_D > 0 else ""
        row["eps_V"] = self._fmt_val(sample.wear_eps_V, "eps_V", self._get_err(sample, "eps_V")) if sample.wear_eps_V > 0 else ""
        row["P_W"] = self._fmt_val(sample.wear_P_W, "P_W", self._get_err(sample, "P_W")) if sample.wear_P_W > 0 else ""
        row["p_MPa"] = self._fmt_val(sample.wear_p_MPa, "p_MPa", self._get_err(sample, "p_MPa")) if sample.wear_p_MPa > 0 else ""
        row["t_steady_s"] = self._fmt_val(sample.wear_t_steady_s, "t_steady_s") if sample.wear_t_steady_s > 0 else ""
        row["mu_amplitude"] = self._fmt_val(sample.wear_mu_amplitude, "mu_amplitude") if sample.wear_mu_amplitude > 0 else ""
        row["stick_slip"] = sample.wear_stick_slip if sample.wear_stick_slip else ""
        row["mu_cov"] = self._fmt_val(sample.wear_mu_cov, "mu_cov") if sample.wear_mu_cov > 0 else ""
        row["grav_delta_m"] = self._fmt_val(sample.grav_delta_m_mg, "grav_delta_m", self._get_err(sample, "grav_delta_m")) if sample.grav_delta_m_mg != 0 else ""
        row["grav_V"] = self._fmt_val(sample.grav_V_mm3, "grav_V", self._get_err(sample, "grav_V")) if sample.grav_V_mm3 > 0 else ""
        row["grav_delta_V"] = self._fmt_val(sample.grav_delta_V_mm3, "grav_delta_V") if sample.grav_delta_V_mm3 > 0 else ""
        row["grav_k"] = self._fmt_val(sample.grav_k_mm3_N_m, "grav_k", self._get_err(sample, "grav_k")) if sample.grav_k_mm3_N_m > 0 else ""
        row["grav_delta_k"] = self._fmt_val(sample.grav_delta_k, "grav_delta_k") if sample.grav_delta_k > 0 else ""
        return row

    def _refresh_table(self):
        for c in self.table_cols:
            self.tree.heading(c, text=self._col_header(c))
        existing = {self.tree.set(item, "name"): item for item in self.tree.get_children()}
        seen = set()
        for s in self.samples:
            if len(s.friction) == 0:
                continue
            row = self._build_table_row(s)
            vals = [row.get(c, "") for c in self.table_cols]
            if s.name in existing:
                self.tree.item(existing[s.name], values=vals)
                del existing[s.name]
            else:
                self.tree.insert("", tk.END, values=vals)
            seen.add(s.name)
        for item in existing.values():
            self.tree.delete(item)
        all_mu = [float(np.mean(s.friction)) for s in self.samples if len(s.friction) > 0]

        # Average values table
        for item in self.avg_tree.get_children():
            self.avg_tree.delete(item)
        
        if self.samples:
            # Collect numeric values for averaging
            numeric_cols = {
                "mu_avg": [], "mu_std": [],
                "L_mm": [], "W_mm": [], "h_mm": [], "S_mm2": [], "V_mm3": [],
                "D_m": [], "A_J": [], "I_h": [], "I_A": [], "eps": [], "k": [], "V_D": [],
                "eps_V": [],
                "P_W": [], "p_MPa": [], "t_steady_s": [], "mu_amplitude": [], "mu_cov": [],
                "grav_delta_m": [], "grav_V": [], "grav_delta_V": [], "grav_k": [], "grav_delta_k": []
            }
            
            valid_samples = [s for s in self.samples if len(s.friction) > 0]
            
            for s in valid_samples:
                mu_avg = float(np.mean(s.friction))
                mu_std = float(np.std(s.friction))
                numeric_cols["mu_avg"].append(mu_avg)
                numeric_cols["mu_std"].append(mu_std)
                
                if s.wear_L > 0: numeric_cols["L_mm"].append(s.wear_L)
                if s.wear_W > 0: numeric_cols["W_mm"].append(s.wear_W)
                if s.wear_h > 0: numeric_cols["h_mm"].append(s.wear_h)
                if s.wear_S > 0: numeric_cols["S_mm2"].append(s.wear_S)
                if s.wear_V > 0: numeric_cols["V_mm3"].append(s.wear_V)
                if s.wear_D_m > 0: numeric_cols["D_m"].append(s.wear_D_m)
                if s.wear_I_h > 0: numeric_cols["I_h"].append(s.wear_I_h)
                if s.wear_I_A > 0: numeric_cols["I_A"].append(s.wear_I_A)
                if s.wear_eps > 0: numeric_cols["eps"].append(s.wear_eps)
                if s.wear_k > 0: numeric_cols["k"].append(s.wear_k)
                if s.wear_V_D > 0: numeric_cols["V_D"].append(s.wear_V_D)
                if s.wear_eps_V > 0: numeric_cols["eps_V"].append(s.wear_eps_V)
                if s.wear_A_J > 0: numeric_cols["A_J"].append(s.wear_A_J)
                if s.wear_P_W > 0: numeric_cols["P_W"].append(s.wear_P_W)
                if s.wear_p_MPa > 0: numeric_cols["p_MPa"].append(s.wear_p_MPa)
                if s.wear_t_steady_s > 0: numeric_cols["t_steady_s"].append(s.wear_t_steady_s)
                if s.wear_mu_amplitude > 0: numeric_cols["mu_amplitude"].append(s.wear_mu_amplitude)
                if s.wear_mu_cov > 0: numeric_cols["mu_cov"].append(s.wear_mu_cov)
                if s.grav_delta_m_mg != 0: numeric_cols["grav_delta_m"].append(s.grav_delta_m_mg)
                if s.grav_V_mm3 > 0: numeric_cols["grav_V"].append(s.grav_V_mm3)
                if s.grav_delta_V_mm3 > 0: numeric_cols["grav_delta_V"].append(s.grav_delta_V_mm3)
                if s.grav_k_mm3_N_m > 0: numeric_cols["grav_k"].append(s.grav_k_mm3_N_m)
                if s.grav_delta_k > 0: numeric_cols["grav_delta_k"].append(s.grav_delta_k)
            
            # Build average row
            avg_row = {}
            mode = self.wear_mode_var.get()
            
            for col in self.table_cols:
                if col == "name":
                    avg_row[col] = f"Среднее ({len(valid_samples)})"
                elif col in numeric_cols and numeric_cols[col]:
                    avg_val = np.mean(numeric_cols[col])
                    # Check if column should be shown based on mode
                    show = True
                    if mode == "gravimetric" and col not in ["name", "mu_avg", "mu_std", "grav_delta_m", "grav_V", "grav_delta_V", "grav_k", "grav_delta_k"]:
                        show = False
                    if show:
                        avg_row[col] = self._fmt_val(avg_val, col)
                    else:
                        avg_row[col] = ""
                else:
                    avg_row[col] = ""
            
            # Insert in column order
            self.avg_tree.insert("", tk.END, values=[avg_row.get(c, "") for c in self.table_cols])

        if all_mu:
            self.summary_var.set(f"Образцов: {len(self.samples)}\nСредний μ: {np.mean(all_mu):.4f} ± {np.std(all_mu):.4f}")
        else:
            self.summary_var.set("Загрузите файлы для анализа.")

    # ==================================================================
    # Gravimetric wear
    # ==================================================================

    def _calc_gravimetric(self):
        try:
            m_before = float(self.grav_vars["m_before_mg"].get())
            m_after = float(self.grav_vars["m_after_mg"].get())
            density = float(self.grav_vars["density_g_cm3"].get())
            error = float(self.grav_vars["error_mg"].get())
        except ValueError:
            messagebox.showerror("Ошибка", "Введите числовые значения.")
            return
        if density <= 0:
            messagebox.showerror("Ошибка", "Плотность должна быть > 0.")
            return
        D_m = self.params.dt * len(self.samples[0].friction) if self.samples else 0.0
        # Try to get D from selected sample
        sel = self._get_selected_sample()
        if sel and len(sel.friction_path_m) > 0:
            D_m = float(sel.friction_path_m[-1])
        result = calc_gravimetric(m_before, m_after, density, error, self.params.load_mN, D_m)
        delta_m = result["delta_m_mg"]
        V = result["V_mm3"]
        delta_V = result["delta_V_mm3"]
        k = result["k_mm3_N_m"]
        delta_k = result["delta_k"]
        self.grav_result_var.set(
            f"Δm = {delta_m:.3f} мг  V = {V:.4f} мм³\n"
            f"±ΔV = {delta_V:.4f} мм³\n"
            f"k = {k:.3e} мм³/Н·м  ±{delta_k:.3e}"
        )

    def _apply_grav_to_selected(self):
        name = self.grav_sample_var.get()
        sel = None
        for s in self.samples:
            if s.name == name:
                sel = s
                break
        if sel is None:
            messagebox.showinfo("Инфо", "Выберите образец в списке.")
            return
        self._set_grav_to_sample(sel)
        self._refresh_table()

    def _apply_grav_to_all(self):
        if not self.samples:
            return
        for s in self.samples:
            self._set_grav_to_sample(s)
        self._refresh_table()

    def _set_grav_to_sample(self, sample):
        try:
            m_before = float(self.grav_vars["m_before_mg"].get())
            m_after = float(self.grav_vars["m_after_mg"].get())
            density = float(self.grav_vars["density_g_cm3"].get())
            error = float(self.grav_vars["error_mg"].get())
        except ValueError:
            return
        sample.grav_m_before_mg = m_before
        sample.grav_m_after_mg = m_after
        sample.grav_density_g_cm3 = density
        sample.grav_error_mg = error
        D_m = float(sample.friction_path_m[-1]) if len(sample.friction_path_m) > 0 else 0.0
        result = calc_gravimetric(m_before, m_after, density, error, self.params.load_mN, D_m)
        sample.grav_delta_m_mg = result["delta_m_mg"]
        sample.grav_V_mm3 = result["V_mm3"]
        sample.grav_delta_V_mm3 = result["delta_V_mm3"]
        sample.grav_k_mm3_N_m = result["k_mm3_N_m"]
        sample.grav_delta_k = result["delta_k"]

    # ==================================================================
    # Wear analyzer
    # ==================================================================

    def _on_calibration_changed(self, calib_px: float, calib_mm: float):
        """Called from WearScarWindow when 'Ко всем' calibration is applied."""
        self._project_default_calib = {"calib_px": calib_px, "calib_mm": calib_mm}

    # ==================================================================
    # Refresh / Export
    # ==================================================================

    def _refresh_all(self):
        self._refresh_smooth_combo()
        self._update_graph()
        self._refresh_table()

    def _export_graph(self):
        if not self.samples:
            messagebox.showinfo("Инфо", "Нет данных.")
            return
        path = filedialog.asksaveasfilename(
            title="Сохранить график", defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("PDF", "*.pdf"), ("SVG", "*.svg")],
        )
        if path:
            self.fig.savefig(path, dpi=200, bbox_inches="tight")
            messagebox.showinfo("Готово", f"Сохранено: {path}")

    # ==================================================================
    # Table formatting
    # ==================================================================

    def _fmt_val(self, val, col, err_val=None, decimal_comma=False):
        """Format a value using format_config. If err_val given, format as 'val±err'."""
        if val is None or val == 0:
            return ""
        cfg = self.format_config.get(col, {"decimals": 2, "err_decimals": 2, "units": {"": 1}, "selected_unit": ""})
        decimals = cfg.get("decimals", 2)
        err_decimals = cfg.get("err_decimals", decimals)
        units = cfg.get("units", {"": 1})
        selected = cfg.get("selected_unit", "")
        mult = units.get(selected, 1)
        scaled = val * mult
        s = f"{scaled:.{decimals}f}" if decimals > 0 else f"{round(scaled)}"
        show_err = cfg.get("show_err", True)
        if show_err and err_val is not None and abs(err_val) > 1e-12:
            err_scaled = err_val * mult
            if err_decimals > 0:
                if err_scaled >= 10**err_decimals:
                    err_s = f"{err_scaled:.{max(0, err_decimals-1)}f}"
                else:
                    err_s = f"{err_scaled:.{err_decimals}f}"
            else:
                err_s = f"{round(err_scaled)}"
            s += f"±{err_s}"
        if decimal_comma:
            s = s.replace(".", ",")
        return s

    def _format_settings_dialog(self):
        """Dialog to configure table formatting (decimals + units)."""
        dlg = tk.Toplevel(self.root)
        dlg.title("Настройки формата таблицы")
        dlg.geometry("580x550")
        dlg.minsize(530, 400)
        dlg.transient(self.root)
        dlg.grab_set()

        ttk.Label(dlg, text="Форматирование столбцов таблицы результатов",
                  style="Title.TLabel").pack(anchor=tk.W, padx=10, pady=(10, 5))

        canvas = tk.Canvas(dlg, highlightthickness=0)
        scrollbar = ttk.Scrollbar(dlg, orient=tk.VERTICAL, command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0), pady=5)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=5, padx=(0, 10))

        hdr = ttk.Frame(scroll_frame)
        hdr.pack(fill=tk.X, padx=5, pady=(0, 5))
        ttk.Label(hdr, text="Параметр", width=14, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        ttk.Label(hdr, text="Знаков", width=7, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        ttk.Label(hdr, text="Погр.", width=7, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        ttk.Label(hdr, text="Единица", width=12, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        ttk.Label(hdr, text="±", width=4, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)

        dec_vars = {}
        err_dec_vars = {}
        unit_vars = {}
        err_vars = {}
        for col, cfg in self.format_config.items():
            row = ttk.Frame(scroll_frame)
            row.pack(fill=tk.X, padx=5, pady=1)
            ttk.Label(row, text=cfg["header"], width=14).pack(side=tk.LEFT)
            dv = tk.IntVar(value=cfg["decimals"])
            dec_vars[col] = dv
            ttk.Spinbox(row, from_=0, to=6, width=5, textvariable=dv).pack(side=tk.LEFT, padx=2)
            edv = tk.IntVar(value=cfg.get("err_decimals", cfg["decimals"]))
            err_dec_vars[col] = edv
            ttk.Spinbox(row, from_=0, to=6, width=5, textvariable=edv).pack(side=tk.LEFT, padx=2)
            unit_list = list(cfg.get("units", {"": 1}).keys())
            uv = tk.StringVar(value=cfg.get("selected_unit", unit_list[0]))
            unit_vars[col] = uv
            cb = ttk.Combobox(row, textvariable=uv, values=unit_list, width=12, state="readonly")
            cb.pack(side=tk.LEFT, padx=2)
            ev = tk.BooleanVar(value=cfg.get("show_err", True))
            err_vars[col] = ev
            ttk.Checkbutton(row, variable=ev).pack(side=tk.LEFT, padx=4)

        def apply_settings():
            for col in self.format_config:
                self.format_config[col]["decimals"] = dec_vars[col].get()
                self.format_config[col]["err_decimals"] = err_dec_vars[col].get()
                self.format_config[col]["selected_unit"] = unit_vars[col].get()
                self.format_config[col]["show_err"] = err_vars[col].get()
            self._refresh_table()

        def on_ok():
            apply_settings()
            dlg.destroy()

        def on_reset():
            for col, cfg in DEFAULT_FORMAT_CONFIG.items():
                self.format_config[col]["decimals"] = cfg["decimals"]
                self.format_config[col]["err_decimals"] = cfg.get("err_decimals", cfg["decimals"])
                self.format_config[col]["selected_unit"] = cfg["selected_unit"]
                self.format_config[col]["show_err"] = cfg.get("show_err", True)
            for col in self.format_config:
                dec_vars[col].set(self.format_config[col]["decimals"])
                err_dec_vars[col].set(self.format_config[col].get("err_decimals", self.format_config[col]["decimals"]))
                unit_vars[col].set(self.format_config[col]["selected_unit"])
                err_vars[col].set(self.format_config[col].get("show_err", True))
            self._refresh_table()

        bf = ttk.Frame(dlg)
        bf.pack(fill=tk.X, padx=10, pady=10)
        ttk.Button(bf, text="Применить", command=apply_settings).pack(fill=tk.X, pady=2)
        ttk.Button(bf, text="OK", command=on_ok).pack(fill=tk.X, pady=2)
        ttk.Button(bf, text="Сбросить по умолчанию", command=on_reset).pack(fill=tk.X, pady=2)
        ttk.Button(bf, text="Отмена", command=dlg.destroy).pack(fill=tk.X, pady=2)

    def _export_table(self):
        if not self.samples:
            messagebox.showinfo("Инфо", "Нет данных.")
            return

        dlg = tk.Toplevel(self.root)
        dlg.title("Экспорт таблицы")
        dlg.geometry("420x320")
        dlg.minsize(400, 300)
        dlg.transient(self.root)
        dlg.grab_set()

        dlg.rowconfigure(0, weight=1)
        dlg.columnconfigure(0, weight=1)

        main_frame = ttk.Frame(dlg)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        main_frame.rowconfigure(3, weight=1)
        main_frame.columnconfigure(0, weight=1)

        ttk.Label(main_frame, text="Формат файла:").grid(row=0, column=0, sticky=tk.W, pady=(0, 5))
        format_var = tk.StringVar(value="csv")
        ttk.Radiobutton(main_frame, text="CSV (табуляция/запятая)", variable=format_var, value="csv").grid(row=1, column=0, sticky=tk.W, padx=10)
        ttk.Radiobutton(main_frame, text="Word (.docx)", variable=format_var, value="docx").grid(row=2, column=0, sticky=tk.W, padx=10)
        ttk.Radiobutton(main_frame, text="Excel (.xlsx)", variable=format_var, value="xlsx").grid(row=3, column=0, sticky=tk.W, padx=10)

        ttk.Separator(main_frame, orient=tk.HORIZONTAL).grid(row=4, column=0, sticky=tk.EW, pady=15)

        ttk.Label(main_frame, text="Десятичный разделитель:").grid(row=5, column=0, sticky=tk.W, pady=(0, 5))
        decimal_var = tk.StringVar(value="dot")
        ttk.Radiobutton(main_frame, text="Точка (1.23)", variable=decimal_var, value="dot").grid(row=6, column=0, sticky=tk.W, padx=10)
        ttk.Radiobutton(main_frame, text="Запятая (1,23) — русский стандарт", variable=decimal_var, value="comma").grid(row=7, column=0, sticky=tk.W, padx=10)

        main_frame.rowconfigure(8, weight=1)

        result = {"format": None, "decimal": None}

        def on_ok():
            result["format"] = format_var.get()
            result["decimal"] = decimal_var.get()
            dlg.destroy()

        def on_cancel():
            dlg.destroy()

        bf = ttk.Frame(main_frame)
        bf.grid(row=9, column=0, sticky=tk.EW, pady=(15, 0))
        ttk.Button(bf, text="OK", command=on_ok).pack(side=tk.RIGHT, padx=5)
        ttk.Button(bf, text="Отмена", command=on_cancel).pack(side=tk.RIGHT)

        self.root.wait_window(dlg)

        if result["format"] is None:
            return

        dec_comma = (result["decimal"] == "comma")
        if result["format"] == "docx":
            self._export_table_docx(decimal_comma=dec_comma)
        elif result["format"] == "xlsx":
            self._export_table_xlsx(decimal_comma=dec_comma)
        else:
            self._export_table_csv(decimal_comma=dec_comma)

    def _export_table_csv(self, decimal_comma=False):
        path = filedialog.asksaveasfilename(
            title="Сохранить таблицу", defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("TSV", "*.tsv")],
        )
        if not path:
            return
        delim = "\t" if path.endswith(".tsv") else ","
        
        def fmt(val, col):
            return self._fmt_val(val, col, decimal_comma=decimal_comma)
        
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh, delimiter=delim)
            header = ["Образец"] + [self._col_header(c) for c in self.table_cols if c != "name"]
            w.writerow(header)
            for s in self.samples:
                if len(s.friction) == 0:
                    continue
                mu_avg = float(np.mean(s.friction))
                mu_std = float(np.std(s.friction))
                w.writerow([
                    s.name,
                    fmt(mu_avg, "mu_avg"), fmt(mu_std, "mu_std"),
                    fmt(s.wear_L, "L_mm") if s.wear_L > 0 else "",
                    fmt(s.wear_W, "W_mm") if s.wear_W > 0 else "",
                    fmt(s.wear_h, "h_mm") if s.wear_h > 0 else "",
                    fmt(s.wear_S, "S_mm2") if s.wear_S > 0 else "",
                    fmt(s.wear_V, "V_mm3") if s.wear_V > 0 else "",
                    fmt(s.wear_D_m, "D_m") if s.wear_D_m > 0 else "",
                    fmt(s.wear_A_J, "A_J") if s.wear_A_J > 0 else "",
                    fmt(s.wear_I_h, "I_h") if s.wear_I_h > 0 else "",
                    fmt(s.wear_I_A, "I_A") if s.wear_I_A > 0 else "",
                    fmt(s.wear_eps, "eps") if s.wear_eps > 0 else "",
                    fmt(s.wear_k, "k") if s.wear_k > 0 else "",
                    fmt(s.wear_V_D, "V_D") if s.wear_V_D > 0 else "",
                    fmt(s.wear_eps_V, "eps_V") if s.wear_eps_V > 0 else "",
                    fmt(s.wear_P_W, "P_W") if s.wear_P_W > 0 else "",
                    fmt(s.wear_p_MPa, "p_MPa") if s.wear_p_MPa > 0 else "",
                    fmt(s.wear_t_steady_s, "t_steady_s") if s.wear_t_steady_s > 0 else "",
                    fmt(s.wear_mu_amplitude, "mu_amplitude") if s.wear_mu_amplitude > 0 else "",
                    s.wear_stick_slip if s.wear_stick_slip else "",
                    fmt(s.wear_mu_cov, "mu_cov") if s.wear_mu_cov > 0 else "",
                    fmt(s.grav_delta_m_mg, "grav_delta_m") if s.grav_delta_m_mg != 0 else "",
                    fmt(s.grav_V_mm3, "grav_V") if s.grav_V_mm3 > 0 else "",
                    fmt(s.grav_delta_V_mm3, "grav_delta_V") if s.grav_delta_V_mm3 > 0 else "",
                    fmt(s.grav_k_mm3_N_m, "grav_k") if s.grav_k_mm3_N_m > 0 else "",
                    fmt(s.grav_delta_k, "grav_delta_k") if s.grav_delta_k > 0 else "",
                ])
        messagebox.showinfo("Готово", f"Сохранено: {path}")

    def _export_table_docx(self, decimal_comma=False):
        if not DOCX_AVAILABLE:
            messagebox.showerror("Ошибка", "python-docx не установлен. Установите: pip install python-docx")
            return
        path = filedialog.asksaveasfilename(
            title="Сохранить таблицу в Word", defaultextension=".docx",
            filetypes=[("Word Document", "*.docx")],
        )
        if not path:
            return
        graph_path = os.path.join(tempfile.gettempdir(), "tribo_graph_16_9.png")
        self._save_graph_16_9(graph_path)
        export_table_docx(path, self.format_config, self.table_cols, self.samples, self._build_table_row, graph_path)
        if os.path.isfile(graph_path):
            os.remove(graph_path)
        messagebox.showinfo("Готово", f"Сохранено: {path}")

    def _export_table_xlsx(self, decimal_comma=False):
        if not XLSX_AVAILABLE:
            messagebox.showerror("Ошибка", "openpyxl не установлен. Установите: pip install openpyxl")
            return
        path = filedialog.asksaveasfilename(
            title="Сохранить таблицу в Excel", defaultextension=".xlsx",
            filetypes=[("Excel Document", "*.xlsx")],
        )
        if not path:
            return
        graph_path = os.path.join(tempfile.gettempdir(), "tribo_graph_16_9.png")
        self._save_graph_16_9(graph_path)
        dec_sep = "comma" if decimal_comma else "dot"
        export_table_xlsx(path, self.format_config, self.table_cols, self.samples,
                          self._build_table_row, decimal_sep=dec_sep, graph_path=graph_path)
        if os.path.isfile(graph_path):
            os.remove(graph_path)
        messagebox.showinfo("Готово", f"Сохранено: {path}")

    def _save_graph_16_9(self, path):
        """Save the current graph as a 16:9 aspect ratio PNG."""
        cur_size = self.fig.get_size_inches()
        cur_w, cur_h = cur_size[0], cur_size[1]
        target_ratio = 16 / 9
        new_w = max(cur_w, 10)
        new_h = new_w / target_ratio
        self.fig.set_size_inches(new_w, new_h)
        self.fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white", edgecolor="none")
        self.fig.set_size_inches(cur_w, cur_h)

    # ==================================================================
    # Project save / load
    # ==================================================================

    def _new_project(self):
        if self.samples:
            if not messagebox.askyesno("Новый проект", "Текущие данные будут очищены. Продолжить?"):
                return
        self.samples.clear()
        self.file_listbox.delete(0, tk.END)
        self._curve_colors.clear()
        self._project_path = None
        self.wear_mode_var.set("geometry")
        self._on_wear_mode_change()
        self.root.title("TriboAnalyzer v1.0")
        self._rebuild_curve_toggles()
        self._refresh_all()

    def _save_project_as(self):
        path = filedialog.asksaveasfilename(
            title="Сохранить проект", defaultextension=".triboproj",
            filetypes=[("Triboproj", "*.triboproj"), ("Все", "*.*")],
        )
        if path:
            self._project_path = path
            self._save_project()

    def _save_project(self):
        if not self._project_path:
            self._save_project_as()
            return

        proj_dir = self._project_path
        os.makedirs(proj_dir, exist_ok=True)

        samples_dir = os.path.join(proj_dir, "samples")
        os.makedirs(samples_dir, exist_ok=True)
        images_dir = os.path.join(proj_dir, "images")
        os.makedirs(images_dir, exist_ok=True)
        masks_dir = os.path.join(proj_dir, "masks")
        os.makedirs(masks_dir, exist_ok=True)

        # Copy .txt files into project
        for s in self.samples:
            src = s.filepath
            dst = os.path.join(samples_dir, os.path.basename(src))
            if os.path.isfile(src) and not os.path.isfile(dst):
                shutil.copy2(src, dst)

        # Collect wear analyzer tabs data
        analyzer_tabs = self._collect_wear_analyzer_tabs()

        # Save images and masks from analyzer tabs
        for i, td in enumerate(analyzer_tabs):
            img_src = td["path"]
            if os.path.isfile(img_src):
                img_dst = os.path.join(images_dir, os.path.basename(img_src))
                if not os.path.isfile(img_dst):
                    shutil.copy2(img_src, img_dst)
                td["path"] = img_dst  # store project-internal path

            # Save mask
            mask = td.get("_mask_array")
            if mask is not None and mask.max() > 0:
                mask_dst = os.path.join(masks_dir, f"mask_{i}.npy")
                np.save(mask_dst, mask)
                td["mask_path"] = mask_dst
            del td["_mask_array"]  # remove numpy array from JSON

        # Get default calibration from analyzer windows
        default_calib = {"calib_px": 100.0, "calib_mm": 1.0}
        self._analyzer_windows = [w for w in self._analyzer_windows if w.win.winfo_exists()]
        if self._analyzer_windows:
            aw = self._analyzer_windows[0]
            default_calib["calib_px"] = aw.default_calib_px
            default_calib["calib_mm"] = aw.default_calib_mm

        data = {
            "params": {
                "disk_diameter_mm": self.params.disk_diameter_mm,
                "load_mN": self.params.load_mN,
                "test_time_s": self.params.test_time_s,
                "rotation_speed_rev_s": self.params.rotation_speed_rev_s,
                "dt": self.params.dt,
                "edge_radius_mm": getattr(self.params, 'edge_radius_mm', 0.0),
                "calib_rel_error": self.calib_rel_error,
            },
            "samples": [],
            "curve_colors": {str(k): v for k, v in self._curve_colors.items()},
            "wear_analyzer_tabs": analyzer_tabs,
            "default_calib": default_calib,
            "wear_mode": self.wear_mode_var.get(),
            "format_config": self.format_config,
            "show_regimes": self.show_regimes_var.get(),
            "graph_comma": self.graph_comma_var.get(),
            "curve_visibility": {s.name: self.show_curve_var.get(s.name, tk.BooleanVar(value=True)).get() for s in self.samples},
        }

        for s in self.samples:
            sample_data = {
                "name": s.name,
                "filepath": s.filepath,
                "date": s.date,
                "num_points": s.num_points,
                "smooth_enabled": s.smooth_enabled,
                "smooth_method": s.smooth_method,
                "smooth_window": s.smooth_window,
                "smooth_polyorder": s.smooth_polyorder,
                "wear_L": s.wear_L,
                "wear_W": s.wear_W,
                "wear_h": s.wear_h,
                "wear_S": s.wear_S,
                "wear_V": s.wear_V,
                "wear_D_m": s.wear_D_m,
                "wear_A_J": s.wear_A_J,
                "wear_P_W": s.wear_P_W,
                "wear_I_h": s.wear_I_h,
                "wear_I_A": s.wear_I_A,
                "wear_eps": s.wear_eps,
                "wear_k": s.wear_k,
                "wear_mu_avg": s.wear_mu_avg,
                "wear_mu_std": s.wear_mu_std,
                "wear_mu_cov": s.wear_mu_cov,
                "wear_V_D": s.wear_V_D,
                "wear_eps_V": s.wear_eps_V,
                "wear_p_MPa": s.wear_p_MPa,
                "wear_t_steady_s": s.wear_t_steady_s,
                "wear_mu_amplitude": s.wear_mu_amplitude,
                "wear_stick_slip": s.wear_stick_slip,
                "grav_m_before_mg": s.grav_m_before_mg,
                "grav_m_after_mg": s.grav_m_after_mg,
                "grav_density_g_cm3": s.grav_density_g_cm3,
                "grav_error_mg": s.grav_error_mg,
                "grav_delta_m_mg": s.grav_delta_m_mg,
                "grav_V_mm3": s.grav_V_mm3,
                "grav_delta_V_mm3": s.grav_delta_V_mm3,
                "grav_k_mm3_N_m": s.grav_k_mm3_N_m,
                "grav_delta_k": s.grav_delta_k,
                # Error fields
                "wear_mu_err": s.wear_mu_err,
                "wear_D_err": s.wear_D_err,
                "err_h_mm": s.err_h_mm,
                "err_S_mm2": s.err_S_mm2,
                "err_V_mm3": s.err_V_mm3,
                "err_L_mm": s.err_L_mm,
                "err_W_mm": s.err_W_mm,
                "wear_A_err": s.wear_A_err,
                "wear_P_err": s.wear_P_err,
                "wear_p_err": s.wear_p_err,
                "err_grav_delta_m": s.err_grav_delta_m,
                "wear_k_err": s.wear_k_err,
                "wear_I_h_err": s.wear_I_h_err,
                "wear_I_A_err": s.wear_I_A_err,
                "wear_eps_err": s.wear_eps_err,
                "wear_V_D_err": s.wear_V_D_err,
                "wear_eps_V_err": s.wear_eps_V_err,
            }
            data["samples"].append(sample_data)

        with open(os.path.join(proj_dir, "data.json"), "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)

        self.root.title(f"TriboAnalyzer v1.0 — {os.path.basename(proj_dir)}")
        messagebox.showinfo("Готово", f"Проект сохранён:\n{proj_dir}")

    def _open_project(self):
        path = filedialog.askdirectory(title="Выберите папку проекта (.triboproj)")
        if not path:
            return
        proj_dir = path
        data_file = os.path.join(proj_dir, "data.json")
        if not os.path.isfile(data_file):
            messagebox.showerror("Ошибка", "В папке нет data.json — это не проект.")
            return

        with open(data_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        # Clear current state
        self.samples.clear()
        self.file_listbox.delete(0, tk.END)
        self._curve_colors.clear()

        # Restore params
        p = data.get("params", {})
        self.params.disk_diameter_mm = p.get("disk_diameter_mm", 60.0)
        self.params.load_mN = p.get("load_mN", 200.0)
        self.params.test_time_s = p.get("test_time_s", 1500.0)
        self.params.rotation_speed_rev_s = p.get("rotation_speed_rev_s", 0.5)
        self.params.dt = p.get("dt", 0.0)
        self.params.edge_radius_mm = p.get("edge_radius_mm", 0.0)
        self.calib_rel_error = p.get("calib_rel_error", 0.01)
        for key, var in self.param_vars.items():
            if key in p:
                val = p[key]
                if key == "calib_rel_error":
                    val = val * 100.0
                var.set(str(val))

        # Restore curve colors
        for k, v in data.get("curve_colors", {}).items():
            self._curve_colors[int(k)] = v

        # Restore samples — try project-local copies first, then original paths
        samples_dir = os.path.join(proj_dir, "samples")
        for sd in data.get("samples", []):
            filepath = sd.get("filepath", "")
            # Try local copy first
            local_path = os.path.join(samples_dir, os.path.basename(filepath))
            if os.path.isfile(local_path):
                filepath = local_path
            elif not os.path.isfile(filepath):
                continue
            try:
                sample = parse_tribology_file(filepath)
                if len(sample.time_ms) > 1 and self.params.dt == 0.0:
                    dt_ms = np.mean(np.diff(sample.time_ms))
                    self.params.dt = dt_ms / 1000.0
                compute_friction_path(sample, self.params)
                for attr in ["wear_L", "wear_W", "wear_h", "wear_S", "wear_V",
                             "wear_D_m", "wear_A_J", "wear_P_W", "wear_I_h", "wear_I_A",
                             "wear_eps", "wear_k", "wear_mu_avg", "wear_mu_std",
                              "wear_mu_cov", "wear_V_D", "wear_eps_V", "wear_p_MPa", "wear_t_steady_s",
                             "wear_mu_amplitude", "wear_stick_slip",
                             "grav_m_before_mg", "grav_m_after_mg", "grav_density_g_cm3",
                             "grav_error_mg", "grav_delta_m_mg", "grav_V_mm3",
                              "grav_delta_V_mm3", "grav_k_mm3_N_m", "grav_delta_k",
                              "wear_mu_err", "wear_D_err",
                              "err_h_mm", "err_S_mm2", "err_V_mm3",
                              "err_L_mm", "err_W_mm",
                              "wear_A_err", "wear_P_err", "wear_p_err",
                              "err_grav_delta_m",
                              "wear_k_err", "wear_I_h_err", "wear_I_A_err",
                              "wear_eps_err", "wear_V_D_err", "wear_eps_V_err"]:
                    if attr in sd:
                        setattr(sample, attr, sd[attr])
                sample.smooth_enabled = sd.get("smooth_enabled", False)
                sample.smooth_method = sd.get("smooth_method", "savgol")
                sample.smooth_window = sd.get("smooth_window", 21)
                sample.smooth_polyorder = sd.get("smooth_polyorder", 3)
                self.samples.append(sample)
                color = self.SAMPLE_COLORS[self.color_idx % len(self.SAMPLE_COLORS)]
                self.color_idx += 1
                self.file_listbox.insert(tk.END, f"* {sample.name}  ({len(sample.time_ms)} pts)")
                self.file_listbox.itemconfig(tk.END, fg=color)
            except Exception as exc:
                print(f"Ошибка загрузки {filepath}: {exc}")

        self._project_path = proj_dir
        self.root.title(f"TriboAnalyzer v1.0 — {os.path.basename(proj_dir)}")
        self._rebuild_curve_toggles()

        # Restore curve visibility
        saved_vis = data.get("curve_visibility", {})
        if saved_vis:
            for s in self.samples:
                if s.name in saved_vis:
                    self.show_curve_var[s.name].set(saved_vis[s.name])

        # Restore graph settings
        self.show_regimes_var.set(data.get("show_regimes", True))
        self.graph_comma_var.set(data.get("graph_comma", False))

        # Store default calibration for analyzer restore (BEFORE _refresh_all)
        self._project_default_calib = data.get("default_calib", {})

        # Restore wear mode
        self.wear_mode_var.set(data.get("wear_mode", "geometry"))
        self._on_wear_mode_change()

        # Restore format config (BEFORE _refresh_all so table shows correct formatting)
        saved_fc = data.get("format_config", {})
        if saved_fc:
            for col, cfg in saved_fc.items():
                if col in self.format_config:
                    self.format_config[col]["decimals"] = cfg.get("decimals", self.format_config[col]["decimals"])
                    self.format_config[col]["err_decimals"] = cfg.get("err_decimals", self.format_config[col].get("err_decimals", self.format_config[col]["decimals"]))
                    self.format_config[col]["selected_unit"] = cfg.get("selected_unit", self.format_config[col].get("selected_unit", ""))
                    self.format_config[col]["show_err"] = cfg.get("show_err", self.format_config[col].get("show_err", True))

        # Restore wear analyzer tabs (BEFORE _refresh_all so calibration is available)
        analyzer_tabs = data.get("wear_analyzer_tabs", [])
        if analyzer_tabs:
            self._restore_wear_analyzer_tabs(analyzer_tabs)

        # NOW refresh — all data, calibration, format settings are in place
        self._refresh_all()

    # ==================================================================
    # Wear scar images (for project save/load)
    # ==================================================================

    def _collect_wear_analyzer_tabs(self) -> list[dict]:
        """Collect wear scar image data from all open analyzer windows."""
        result = []
        # Clean up dead references
        self._analyzer_windows = [w for w in self._analyzer_windows if w.win.winfo_exists()]
        for analyzer in self._analyzer_windows:
            for tab in analyzer.tabs:
                td = {
                    "path": tab.path,
                    "linked_sample": tab.linked_sample.name if tab.linked_sample else None,
                    "L_value": tab.L_value,
                    "W_value": tab.W_value,
                    "calib_px": tab.calib_px,
                    "calib_mm": tab.calib_mm,
                    "mask_path": "",
                    "_mask_array": tab.mask,
                }
                result.append(td)
        return result

    def _restore_wear_analyzer_tabs(self, tabs_data: list[dict]):
        """Load tabs into the embedded wear analyzer from project data."""
        # Resolve paths relative to project directory
        for td in tabs_data:
            img_path = td.get("path", "")
            if not os.path.isabs(img_path):
                img_path = os.path.join(self._project_path, img_path)
                td["path"] = img_path
            mask_path = td.get("mask_path", "")
            if mask_path and not os.path.isabs(mask_path):
                td["mask_path"] = os.path.join(self._project_path, mask_path)

        # Use the embedded analyzer, not a new Toplevel
        analyzer = self._analyzer
        # Clear old tabs first
        analyzer.tabs.clear()
        while analyzer.notebook.index("end") > 0:
            analyzer.notebook.forget(0)
        analyzer._add_tab_button()
        analyzer.notebook.update_idletasks()
        default_calib = getattr(self, '_project_default_calib', {})
        analyzer.default_calib_px = default_calib.get("calib_px", 100.0)
        analyzer.default_calib_mm = default_calib.get("calib_mm", 1.0)
        # Load tabs
        analyzer.load_tabs_from_project(tabs_data)


def main():
    root = tk.Tk()
    TriboApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
