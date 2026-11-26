"""Wear scar image analyzer window.

Measuring tools for wear track length (L) and width (W)
from microscope photos. Drawing on canvas overlay for
pixel-perfect coordinate mapping.
"""

import math
import os
import csv
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Optional
from collections import deque
from dataclasses import dataclass, field
import threading

import numpy as np
from PIL import Image, ImageTk, ImageDraw, ImageFont

from wear_calc import (
    calc_wear_depth, calc_wear_area, calc_wear_volume,
    calc_wear_volume_edge_radius, calc_wear_errors,
    compute_wear_metrics_and_errors,
    INSTRUMENT_SPECS,
)
from data_model import TestParams, TribSample, compute_tribology_wear


@dataclass
class ImageTab:
    """Per-image state for tabbed interface."""
    path: str
    pil_image: Image.Image
    mask: np.ndarray
    img_w: int
    img_h: int
    L_points_img: list = field(default_factory=list)
    W_points_img: list = field(default_factory=list)
    L_value: float = 0.0
    W_value: float = 0.0
    zoom: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    calib_px: float = 100.0
    calib_mm: float = 1.0
    linked_sample: Optional[TribSample] = None
    filename_var: str = ""


TOOL_NONE = "view"
TOOL_MEASURE_L = "measure_L"
TOOL_MEASURE_W = "measure_W"
TOOL_BRUSH_ADD = "brush_add"
TOOL_BRUSH_DEL = "brush_del"
TOOL_THRESHOLD = "threshold"
TOOL_SAM = "sam"


class WearScarWindow:
    """Wear scar image analysis. Can run as Toplevel or embedded in a parent frame."""

    def __init__(self, root: tk.Tk, params: TestParams, samples: list[TribSample] | None = None,
                 app=None, parent: tk.Widget = None):
        self.root = root
        self.params = params
        self._initial_samples = samples or []
        self.app = app
        self._embedded = parent is not None

        if parent is not None:
            self.win = parent
        else:
            self.win = tk.Toplevel(root)
            self.win.title("Анализатор лунок износа")
            self.win.geometry("1200x800")
            self.win.minsize(900, 600)

        # --- Tabbed state ---
        self.tabs: list[ImageTab] = []
        self.current_tab_idx: int = -1

        # Default calibration (shared across tabs, saved in project)
        self.default_calib_px: float = 100.0
        self.default_calib_mm: float = 1.0

        # Shared state (independent of tabs)
        self._pan_start = None
        self._drag_point: Optional[tuple[float, float]] = None
        self._last_brush_img: Optional[tuple[float, float]] = None
        self._brush_cursor_id = None
        self._last_mouse_canvas: tuple[float, float] = (600, 400)  # default canvas center

        # SAM segmentation
        self._sam_predictor = None
        self._sam_model_loaded = False

        # --- Tk variables (MUST exist before _build_ui binds callbacks) ---
        self.tool_var = tk.StringVar(value=TOOL_NONE)
        self.brush_var = tk.StringVar(value="15")
        self.thr_var = tk.StringVar(value="128")
        self.calib_px_var = tk.StringVar(value="100")
        self.calib_mm_var = tk.StringVar(value="1.0")
        self.L_var = tk.StringVar(value="0.00")
        self.W_var = tk.StringVar(value="0.00")
        self.result_var = tk.StringVar(value="R = \u2013")
        self.status_var = tk.StringVar(value="Откройте фото лунки износа")

        # Export settings
        self.export_show_L = tk.BooleanVar(value=True)
        self.export_show_W = tk.BooleanVar(value=True)
        self.export_font_size = tk.IntVar(value=14)
        self.export_line_width = tk.IntVar(value=3)
        self.export_bar_height = tk.IntVar(value=8)
        self.export_bar_pos = tk.StringVar(value="bottom-left")  # bottom-left, bottom-right, top-left, top-right
        self.export_scale_unit = tk.StringVar(value="мм")  # мм or мкм

        self._build_ui()

    @property
    def samples(self) -> list[TribSample]:
        """Get current samples from main app, fallback to initial samples."""
        if self.app is not None and hasattr(self.app, 'samples'):
            return self.app.samples
        return self._initial_samples

    # ==================================================================
    # UI
    # ==================================================================

    def _build_ui(self):
        # --- Toolbar row 1: tools & parameters ---
        tb1 = ttk.Frame(self.win)
        tb1.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(tb1, text="Открыть фото", command=self._open_image).pack(side=tk.LEFT, padx=2, pady=2)
        ttk.Separator(tb1, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=2)

        ttk.Label(tb1, text="Инструмент:").pack(side=tk.LEFT, padx=2)
        tools = [
            (TOOL_NONE, "Просмотр"),
            (TOOL_MEASURE_L, "Длина L"),
            (TOOL_MEASURE_W, "Ширина W"),
            (TOOL_BRUSH_ADD, "Кисть +"),
            (TOOL_BRUSH_DEL, "Кисть -"),
            (TOOL_THRESHOLD, "Порог"),
            (TOOL_SAM, "SAM сегментация"),
        ]
        for val, txt in tools:
            ttk.Radiobutton(tb1, text=txt, variable=self.tool_var, value=val,
                            command=self._on_tool_change).pack(side=tk.LEFT, padx=1)

        ttk.Separator(tb1, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=2)

        ttk.Label(tb1, text="Радиус:").pack(side=tk.LEFT)
        ttk.Spinbox(tb1, from_=1, to=100, width=4, textvariable=self.brush_var).pack(side=tk.LEFT)
        ttk.Label(tb1, text="Порог:").pack(side=tk.LEFT, padx=(8, 2))
        ttk.Spinbox(tb1, from_=0, to=255, width=4, textvariable=self.thr_var).pack(side=tk.LEFT)

        ttk.Separator(tb1, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=2)
        ttk.Button(tb1, text="Авто-определение", command=self._auto_detect).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb1, text="Авто L/W из маски", command=self._auto_detect_LW_from_mask).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb1, text="Очистить маску", command=self._clear_mask).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb1, text="Сбросить L/W", command=self._reset_all_measurements).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb1, text="Инвертировать маску", command=self._invert_mask).pack(side=tk.LEFT, padx=2)

        # --- Toolbar row 2: export actions ---
        tb2 = ttk.Frame(self.win)
        tb2.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(tb2, text="Внести в таблицу", command=self._push_to_table).pack(side=tk.LEFT, padx=2, pady=2)
        ttk.Button(tb2, text="Экспорт итогов", command=self._export_summary).pack(side=tk.LEFT, padx=2, pady=2)
        ttk.Button(tb2, text="Экспорт фото с линейкой", command=self._export_image_scalebar).pack(side=tk.LEFT, padx=2, pady=2)
        ttk.Button(tb2, text="Настройки экспорта", command=self._export_settings_dialog).pack(side=tk.LEFT, padx=2, pady=2)

        # --- Bottom panel (packed BEFORE canvas so it gets space first) ---
        bp = ttk.Frame(self.win)
        bp.pack(side=tk.BOTTOM, fill=tk.X)

        # Current image filename
        self.filename_var = tk.StringVar(value="Фото не открыто")
        fnf = ttk.LabelFrame(bp, text="Текущий файл")
        fnf.pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=4)
        ttk.Label(fnf, textvariable=self.filename_var, font=("Consolas", 9), foreground="#333").pack(padx=8, pady=4)

        # Calibration
        cf = ttk.LabelFrame(bp, text="Калибровка (пиксели \u2192 мм)")
        cf.pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=4)
        ttk.Label(cf, text="Пикселей:").grid(row=0, column=0, padx=2)
        ttk.Entry(cf, textvariable=self.calib_px_var, width=8).grid(row=0, column=1, padx=2)
        ttk.Label(cf, text="мм:").grid(row=1, column=0, padx=2)
        ttk.Entry(cf, textvariable=self.calib_mm_var, width=8).grid(row=1, column=1, padx=2)
        bf = ttk.Frame(cf)
        bf.grid(row=2, column=0, columnspan=2, pady=2)
        ttk.Button(bf, text="Задать", command=self._set_calibration).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text="Ко всем", command=self._set_calibration_all).pack(side=tk.LEFT, padx=2)

        # Measurements
        mf = ttk.LabelFrame(bp, text="Измерения")
        mf.pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=4)
        ttk.Label(mf, text="L (длина), мм:").grid(row=0, column=0, padx=2)
        ttk.Entry(mf, textvariable=self.L_var, width=10, state="readonly").grid(row=0, column=1, padx=2)
        ttk.Button(mf, text="Сброс", command=self._reset_L).grid(row=0, column=2, padx=2)
        ttk.Label(mf, text="W (ширина), мм:").grid(row=1, column=0, padx=2)
        ttk.Entry(mf, textvariable=self.W_var, width=10, state="readonly").grid(row=1, column=1, padx=2)
        ttk.Button(mf, text="Сброс", command=self._reset_W).grid(row=1, column=2, padx=2)

        # Results
        rf = ttk.LabelFrame(bp, text="Результаты")
        rf.pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=4)
        self.linked_var = tk.StringVar(value="")
        ttk.Label(rf, textvariable=self.linked_var, font=("Consolas", 8), foreground="#1a73e8").pack(anchor=tk.W, padx=4)
        ttk.Label(rf, textvariable=self.result_var, justify=tk.LEFT, font=("Consolas", 9)).pack(anchor=tk.W, padx=4)
        ttk.Button(rf, text="Рассчитать", command=self._calc_wear).pack(fill=tk.X, padx=4, pady=2)

        # Status
        ttk.Label(bp, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W).pack(
            side=tk.BOTTOM, fill=tk.X, padx=2, pady=2
        )

        # --- Tab notebook ---
        self.notebook = ttk.Notebook(self.win)
        self.notebook.pack(fill=tk.X, padx=2, pady=2)
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # Add "+" button to notebook
        self._add_tab_button()

        # --- Canvas (no border, no highlight for clean coordinates) ---
        self.canvas = tk.Canvas(self.win, bg="#2b2b2b", highlightthickness=0, bd=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=2, pady=(0, 2))

        # Bind events
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_b1_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<ButtonPress-3>", self._on_pan_start)
        self.canvas.bind("<B3-Motion>", self._on_pan_move)
        self.canvas.bind("<ButtonRelease-3>", self._on_pan_end)
        self.canvas.bind("<MouseWheel>", self._on_zoom)
        self.canvas.bind("<Button-4>", lambda e: self._apply_zoom(1.15, e.x, e.y))
        self.canvas.bind("<Button-5>", lambda e: self._apply_zoom(1 / 1.15, e.x, e.y))
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Enter>", lambda e: self._update_cursor())
        self.canvas.bind("<Leave>", lambda e: self._hide_cursor())

    # ==================================================================
    # Tab management
    # ==================================================================

    def _add_tab_button(self):
        """Add a '+' tab for creating new tabs."""
        # Create a dummy tab with a '+' label
        plus_frame = ttk.Frame(self.notebook)
        self.notebook.add(plus_frame, text="+")
        # Bind click on the plus tab
        self.notebook.bind("<Button-1>", self._on_notebook_click, add="+")

    def _on_notebook_click(self, event):
        """Handle click on notebook tabs."""
        try:
            tab_idx = self.notebook.index(f"@{event.x},{event.y}")
            tab_text = self.notebook.tab(tab_idx, "text")
        except tk.TclError:
            return
        if tab_text == "+":  # Plus tab
            self._open_image()
            return "break"

    def _on_tab_changed(self, event):
        """Handle tab switch."""
        if not self.tabs:
            return
        try:
            new_idx = self.notebook.index(self.notebook.select())
        except tk.TclError:
            return
        if new_idx < len(self.tabs) and new_idx != self.current_tab_idx:
            self._switch_tab(new_idx)

    def _switch_tab(self, idx: int):
        """Switch to tab at index."""
        if not (0 <= idx < len(self.tabs)):
            return
        try:
            if idx >= self.notebook.index("end"):
                return
        except tk.TclError:
            return
        self.current_tab_idx = idx
        tab = self.tabs[idx]

        # Update UI variables from tab
        self.calib_px_var.set(str(tab.calib_px))
        self.calib_mm_var.set(str(tab.calib_mm))
        self.L_var.set(f"{tab.L_value:.3f}")
        self.W_var.set(f"{tab.W_value:.3f}")
        self.filename_var.set(tab.filename_var or os.path.basename(tab.path))
        if tab.linked_sample:
            self.linked_var.set(f"Связано: {tab.linked_sample.name}")
        else:
            self.linked_var.set("")

        # Update notebook tab text
        try:
            self.notebook.tab(idx, text=os.path.basename(tab.path)[:30])
        except tk.TclError:
            return

        # Refresh display
        self._refresh_display()
        self._update_zoom_fit()

    def _update_zoom_fit(self):
        """Fit current image to canvas."""
        if not self.tabs or self.current_tab_idx < 0:
            return
        tab = self.tabs[self.current_tab_idx]
        self.win.update_idletasks()
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw > 1 and ch > 1:
            tab.zoom = min(cw / tab.img_w, ch / tab.img_h, 1.0)
        else:
            tab.zoom = 1.0
        tab.offset_x = max(0, (cw - tab.img_w * tab.zoom) / 2)
        tab.offset_y = max(0, (ch - tab.img_h * tab.zoom) / 2)

    def _get_current_tab(self) -> Optional[ImageTab]:
        """Get current tab or None."""
        if 0 <= self.current_tab_idx < len(self.tabs):
            return self.tabs[self.current_tab_idx]
        return None

    def _close_tab(self, idx: int):
        """Close tab at index."""
        if not (0 <= idx < len(self.tabs)):
            return
        self.tabs.pop(idx)
        self.notebook.unbind("<<NotebookTabChanged>>")
        try:
            self.notebook.forget(idx)
            self.notebook.update_idletasks()
        finally:
            self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        if not self.tabs:
            self.current_tab_idx = -1
            self.pil_image = None
            self.tk_image = None
            self.mask = None
            self._refresh_display()
        else:
            # Switch to valid tab
            new_idx = min(idx, len(self.tabs) - 1)
            self._switch_tab(new_idx)

    def _export_settings_dialog(self):
        """Show dialog to configure export settings."""
        dlg = tk.Toplevel(self.win)
        dlg.title("Настройки экспорта фото")
        dlg.geometry("400x480")
        dlg.minsize(350, 400)
        dlg.transient(self.win)
        dlg.grab_set()

        # L line
        ttk.Checkbutton(dlg, text="Показывать длину (L)", variable=self.export_show_L).pack(anchor=tk.W, padx=10, pady=5)
        # W line
        ttk.Checkbutton(dlg, text="Показывать ширину (W)", variable=self.export_show_W).pack(anchor=tk.W, padx=10, pady=5)

        # Font size
        ff = ttk.Frame(dlg)
        ff.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(ff, text="Размер шрифта:").pack(side=tk.LEFT)
        ttk.Spinbox(ff, from_=8, to=72, width=5, textvariable=self.export_font_size).pack(side=tk.LEFT, padx=5)

        # Line width
        lf = ttk.Frame(dlg)
        lf.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(lf, text="Толщина линий:").pack(side=tk.LEFT)
        ttk.Spinbox(lf, from_=1, to=10, width=5, textvariable=self.export_line_width).pack(side=tk.LEFT, padx=5)

        # Scale bar info (auto-sized)
        info_frame = ttk.LabelFrame(dlg, text="Линейка масштаба")
        info_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(info_frame, text="• Высота чёрного прямоугольника = 1/5 высоты изображения").pack(anchor=tk.W, padx=5, pady=2)
        ttk.Label(info_frame, text="• Ширина подбирается по содержимому (линия + текст + отступы)").pack(anchor=tk.W, padx=5, pady=2)
        ttk.Label(info_frame, text="• Отступ от края уменьшен на 20%").pack(anchor=tk.W, padx=5, pady=2)
        ttk.Label(info_frame, text="• Белая линия: длина = 1/8 ширины изображения, толщина = 1/5 высоты прямоугольника").pack(anchor=tk.W, padx=5, pady=2)
        ttk.Label(info_frame, text="• Значение кратно 10 (мм или мкм)").pack(anchor=tk.W, padx=5, pady=2)
        ttk.Label(info_frame, text="• Шрифт подбирается автоматически (максимальный, вписывающийся)").pack(anchor=tk.W, padx=5, pady=2)

        # Scale unit
        uf = ttk.Frame(dlg)
        uf.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(uf, text="Единица масштаба:").pack(side=tk.LEFT)
        ttk.Combobox(uf, textvariable=self.export_scale_unit, width=8, state="readonly",
                     values=["мм", "мкм"]).pack(side=tk.LEFT, padx=5)

        # Scale bar position
        pf = ttk.Frame(dlg)
        pf.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(pf, text="Позиция линейки:").pack(side=tk.LEFT)
        pos_combo = ttk.Combobox(pf, textvariable=self.export_bar_pos, width=15, state="readonly",
                                  values=["bottom-left", "bottom-right", "top-left", "top-right"])
        pos_combo.pack(side=tk.LEFT, padx=5)

        # Buttons
        btn_f = ttk.Frame(dlg)
        btn_f.pack(fill=tk.X, padx=10, pady=15)
        ttk.Button(btn_f, text="OK", command=dlg.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_f, text="Отмена", command=lambda: (setattr(self, '_export_cancelled', True), dlg.destroy())).pack(side=tk.RIGHT)

        self._export_cancelled = False
        self.win.wait_window(dlg)
        return not self._export_cancelled

    # ==================================================================
    # Coordinate mapping: image <-> canvas
    # ==================================================================

    def _img_to_canvas(self, ix: float, iy: float) -> tuple[float, float]:
        """Image pixel coords -> canvas widget coords."""
        tab = self._get_current_tab()
        if not tab:
            return ix, iy
        return ix * tab.zoom + tab.offset_x, iy * tab.zoom + tab.offset_y

    def _canvas_to_img(self, cx: float, cy: float) -> tuple[float, float]:
        """Canvas widget coords -> image pixel coords."""
        tab = self._get_current_tab()
        if not tab:
            return cx, cy
        return (cx - tab.offset_x) / tab.zoom, (cy - tab.offset_y) / tab.zoom

    # ==================================================================
    # Display
    # ==================================================================

    def _refresh_display(self):
        tab = self._get_current_tab()
        if not tab or tab.pil_image is None:
            return

        # Build display image: original + mask overlay
        img = tab.pil_image.copy()
        if tab.mask is not None and tab.mask.max() > 0:
            # Create semi-transparent red overlay
            rgba = img.convert("RGBA")
            red = Image.new("RGBA", rgba.size, (255, 50, 50, 70))
            mask_img = Image.fromarray(tab.mask)
            rgba.paste(red, mask=mask_img)
            img = rgba.convert("RGB")

        # Scale
        w = max(1, int(img.width * tab.zoom))
        h = max(1, int(img.height * tab.zoom))
        self.tk_image = ImageTk.PhotoImage(img.resize((w, h), Image.LANCZOS))

        # Redraw canvas
        self.canvas.delete("image")
        self.canvas.create_image(tab.offset_x, tab.offset_y, anchor=tk.NW,
                                 image=self.tk_image, tags="image")

        # Draw measurement overlays on canvas (in canvas coords)
        self._draw_measurements()

        # Update brush cursor
        self._update_cursor()

    def _draw_measurements(self):
        """Draw measurement lines and labels directly on canvas."""
        tab = self._get_current_tab()
        if not tab:
            return
        self.canvas.delete("measure")

        def img_to_c(ix, iy):
            return ix * tab.zoom + tab.offset_x, iy * tab.zoom + tab.offset_y

        # L line (green)
        if len(tab.L_points_img) >= 1:
            pts = tab.L_points_img
            # Draw committed points
            if len(pts) == 2:
                c1 = img_to_c(*pts[0])
                c2 = img_to_c(*pts[1])
                self.canvas.create_line(*c1, *c2, fill="#00ff00", width=2, dash=(6, 4), tags="measure")
                # Endpoint markers
                r = 5
                self.canvas.create_oval(c1[0]-r, c1[1]-r, c1[0]+r, c1[1]+r, outline="#00ff00", width=2, tags="measure")
                self.canvas.create_oval(c2[0]-r, c2[1]-r, c2[0]+r, c2[1]+r, outline="#00ff00", width=2, tags="measure")
                # Label
                mx = (c1[0] + c2[0]) / 2
                my = (c1[1] + c2[1]) / 2
                self.canvas.create_text(mx, my - 12, text=f"L = {tab.L_value:.3f} мм",
                                        fill="#00ff00", font=("Consolas", 10, "bold"), tags="measure")
            # Rubber-band while placing 2nd point
            if self._drag_point and self.tool_var.get() == TOOL_MEASURE_L:
                c1 = img_to_c(*pts[-1])
                self.canvas.create_line(*c1, *self._drag_point, fill="#00ff00", width=1, dash=(4, 4), tags="measure")

        # W line (blue)
        if len(tab.W_points_img) >= 1:
            pts = tab.W_points_img
            if len(pts) == 2:
                c1 = img_to_c(*pts[0])
                c2 = img_to_c(*pts[1])
                self.canvas.create_line(*c1, *c2, fill="#0099ff", width=2, dash=(6, 4), tags="measure")
                r = 5
                self.canvas.create_oval(c1[0]-r, c1[1]-r, c1[0]+r, c1[1]+r, outline="#0099ff", width=2, tags="measure")
                self.canvas.create_oval(c2[0]-r, c2[1]-r, c2[0]+r, c2[1]+r, outline="#0099ff", width=2, tags="measure")
                mx = (c1[0] + c2[0]) / 2
                my = (c1[1] + c2[1]) / 2
                self.canvas.create_text(mx, my + 14, text=f"W = {tab.W_value:.3f} мм",
                                        fill="#0099ff", font=("Consolas", 10, "bold"), tags="measure")
            if self._drag_point and self.tool_var.get() == TOOL_MEASURE_W:
                c1 = img_to_c(*pts[-1])
                self.canvas.create_line(*c1, *self._drag_point, fill="#0099ff", width=1, dash=(4, 4), tags="measure")

    # ==================================================================
    # Brush cursor
    # ==================================================================

    def _update_cursor(self):
        self.canvas.delete("brush_cursor")
        tool = self.tool_var.get()
        if tool not in (TOOL_BRUSH_ADD, TOOL_BRUSH_DEL):
            self.canvas.config(cursor="crosshair" if "measure" in tool else "")
            return
        self.canvas.config(cursor="none")
        # Show last known position if available
        if self._last_mouse_canvas:
            self._draw_brush_circle(*self._last_mouse_canvas)

    def _draw_brush_circle(self, cx: float, cy: float):
        tab = self._get_current_tab()
        if not tab:
            return
        self.canvas.delete("brush_cursor")
        try:
            r_img = max(1, int(self.brush_var.get()))
        except ValueError:
            r_img = 15
        r_canvas = r_img * tab.zoom
        color = "#00ff88" if self.tool_var.get() == TOOL_BRUSH_ADD else "#ff4444"
        # Filled circle with outline for high visibility
        self.canvas.create_oval(cx - r_canvas, cy - r_canvas, cx + r_canvas, cy + r_canvas,
                                outline=color, fill="", width=3, tags="brush_cursor")
        # Center cross (larger)
        cross_size = max(8, int(r_canvas * 0.3))
        self.canvas.create_line(cx - cross_size, cy, cx + cross_size, cy, fill=color, width=2, tags="brush_cursor")
        self.canvas.create_line(cx, cy - cross_size, cx, cy + cross_size, fill=color, width=2, tags="brush_cursor")
        # Ensure on top
        self.canvas.tag_raise("brush_cursor")

    def _hide_cursor(self):
        self.canvas.delete("brush_cursor")

    # ==================================================================
    # Tool change
    # ==================================================================

    def _on_tool_change(self):
        self._drag_point = None
        self._update_cursor()
        tool = self.tool_var.get()
        if tool == TOOL_NONE:
            self.canvas.config(cursor="")
        elif "measure" in tool:
            self.canvas.config(cursor="crosshair")
        elif "brush" in tool:
            self.canvas.config(cursor="none")
        elif tool == TOOL_SAM:
            self.canvas.config(cursor="crosshair")

    # ==================================================================
    # Image loading
    # ==================================================================

    def _open_image(self):
        path = filedialog.askopenfilename(
            title="Фото лунки износа",
            filetypes=[("Изображения", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"), ("Все", "*.*")],
        )
        if not path:
            return
        try:
            img = Image.open(path)
            pil_image = img.convert("RGB")
            img_w, img_h = pil_image.size
            mask = np.zeros((img_h, img_w), dtype=np.uint8)

            tab = ImageTab(
                path=path,
                pil_image=pil_image,
                mask=mask,
                img_w=img_w,
                img_h=img_h,
                linked_sample=None,
                filename_var=os.path.basename(path),
                calib_px=self.default_calib_px,
                calib_mm=self.default_calib_mm,
            )

            frame = ttk.Frame(self.notebook)

            self.notebook.unbind("<<NotebookTabChanged>>")
            try:
                self.notebook.add(frame, text=os.path.basename(path)[:30])
                self.notebook.update_idletasks()
                self.tabs.append(tab)
                self._switch_tab(len(self.tabs) - 1)
            finally:
                self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

            self.status_var.set(f"Открыто: {os.path.basename(path)}  ({img_w}x{img_h})")

            # Immediately prompt to link with a test file
            self._prompt_link_sample(tab)

        except Exception as exc:
            messagebox.showerror("Ошибка", f"Не удалось открыть:\n{exc}")

    def _prompt_link_sample(self, tab: ImageTab):
        """Prompt user to link the image to a test sample immediately."""
        if not self.samples:
            messagebox.showinfo("Инфо", "Нет загруженных файлов испытаний.\nСначала загрузите .txt файлы в главное окно.")
            return

        img_name = os.path.splitext(os.path.basename(tab.path))[0]

        # Try auto-link by name
        linked_sample = None
        for s in self.samples:
            if s.name == img_name:
                linked_sample = s
                break

        dlg = tk.Toplevel(self.win)
        dlg.title("Связать с файлом испытания")
        dlg.geometry("450x350")
        dlg.transient(self.win)
        dlg.grab_set()

        ttk.Label(dlg, text=f"Изображение: {img_name}", anchor=tk.W, font=("Arial", 10, "bold")).pack(fill=tk.X, padx=10, pady=(10, 2))
        ttk.Label(dlg, text="Выберите образец для связи:", anchor=tk.W).pack(fill=tk.X, padx=10, pady=(5, 2))

        # Listbox with samples
        lb = tk.Listbox(dlg, font=("Consolas", 10), selectmode=tk.SINGLE)
        for i, s in enumerate(self.samples):
            lb.insert(tk.END, s.name)
            # Highlight matching sample
            if linked_sample and s.name == linked_sample.name:
                lb.selection_set(i)
                lb.activate(i)
        lb.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        result = {"sample": None}

        def on_ok():
            sel = lb.curselection()
            if sel:
                result["sample"] = self.samples[sel[0]]
            dlg.destroy()

        def on_skip():
            dlg.destroy()

        bf = ttk.Frame(dlg)
        bf.pack(fill=tk.X, padx=10, pady=10)
        ttk.Button(bf, text="Связать", command=on_ok).pack(side=tk.RIGHT, padx=5)
        ttk.Button(bf, text="Пропустить", command=on_skip).pack(side=tk.RIGHT)

        self.win.wait_window(dlg)

        if result["sample"]:
            tab.linked_sample = result["sample"]
            self.linked_var.set(f"Связано: {result['sample'].name}")
            self.status_var.set(f"Связано с: {result['sample'].name}")

    # ==================================================================
    # Mouse events
    # ==================================================================

    def _on_press(self, event):
        tab = self._get_current_tab()
        if not tab or tab.pil_image is None:
            return
        tool = self.tool_var.get()
        ix, iy = self._canvas_to_img(event.x, event.y)

        if tool == TOOL_NONE:
            self._pan_start = (event.x, event.y)
            return

        if tool == TOOL_MEASURE_L:
            tab.L_points_img.append((ix, iy))
            if len(tab.L_points_img) > 2:
                tab.L_points_img = tab.L_points_img[-2:]
            if len(tab.L_points_img) == 2:
                self._calc_L()
            self._refresh_display()
            return

        if tool == TOOL_MEASURE_W:
            tab.W_points_img.append((ix, iy))
            if len(tab.W_points_img) > 2:
                tab.W_points_img = tab.W_points_img[-2:]
            if len(tab.W_points_img) == 2:
                self._calc_W()
            self._refresh_display()
            return

        if tool in (TOOL_BRUSH_ADD, TOOL_BRUSH_DEL):
            self._apply_brush(ix, iy, add=(tool == TOOL_BRUSH_ADD))
            self._last_brush_img = (ix, iy)
            self._refresh_display()
            return

        if tool == TOOL_THRESHOLD:
            self._auto_detect_at(ix, iy)

        if tool == TOOL_SAM:
            self._sam_predict(ix, iy)

    def _on_b1_motion(self, event):
        tab = self._get_current_tab()
        if not tab or tab.pil_image is None:
            return
        tool = self.tool_var.get()

        # Pan
        if tool == TOOL_NONE and self._pan_start is not None:
            dx = event.x - self._pan_start[0]
            dy = event.y - self._pan_start[1]
            tab.offset_x += dx
            tab.offset_y += dy
            self._pan_start = (event.x, event.y)
            self._refresh_display()
            return

        # Rubber-band for measurements
        if tool in (TOOL_MEASURE_L, TOOL_MEASURE_W):
            self._drag_point = (event.x, event.y)
            self._refresh_display()
            return

        # Brush drag — interpolate between prev and current
        if tool in (TOOL_BRUSH_ADD, TOOL_BRUSH_DEL):
            ix, iy = self._canvas_to_img(event.x, event.y)
            prev = getattr(self, "_last_brush_img", None)
            if prev is not None:
                self._brush_line(prev[0], prev[1], ix, iy, add=(tool == TOOL_BRUSH_ADD))
            else:
                self._apply_brush(ix, iy, add=(tool == TOOL_BRUSH_ADD))
            self._last_brush_img = (ix, iy)
            self._refresh_display()

    def _on_release(self, _event):
        self._pan_start = None
        self._drag_point = None
        self._last_brush_img = None

    def _on_pan_start(self, event):
        self._pan_start = (event.x, event.y)

    def _on_pan_move(self, event):
        tab = self._get_current_tab()
        if not tab or self._pan_start is None:
            return
        dx = event.x - self._pan_start[0]
        dy = event.y - self._pan_start[1]
        tab.offset_x += dx
        tab.offset_y += dy
        self._pan_start = (event.x, event.y)
        self._refresh_display()

    def _on_pan_end(self, _event):
        self._pan_start = None

    def _on_motion(self, event):
        """Track mouse for brush cursor and status bar."""
        tab = self._get_current_tab()
        self._last_mouse_canvas = (event.x, event.y)
        if not tab or tab.pil_image is None:
            return
        ix, iy = self._canvas_to_img(event.x, event.y)
        in_bounds = 0 <= ix < tab.img_w and 0 <= iy < tab.img_h
        tool = self.tool_var.get()
        if "brush" in tool:
            self._draw_brush_circle(event.x, event.y)
        if in_bounds:
            gray_val = ""
            if tab.pil_image:
                g = tab.pil_image.getpixel((int(ix), int(iy)))
                gray_val = f"  gray={g[0]},{g[1]},{g[2]}"
            self.status_var.set(f"x={ix:.1f} y={iy:.1f}  zoom={tab.zoom:.2f}{gray_val}")
        else:
            self.status_var.set(f"zoom={tab.zoom:.2f}")

    # ==================================================================
    # Zoom
    # ==================================================================

    def _on_zoom(self, event):
        factor = 1.15 if event.delta > 0 else 1 / 1.15
        self._apply_zoom(factor, event.x, event.y)

    def _apply_zoom(self, factor: float, cx: float, cy: float):
        tab = self._get_current_tab()
        if not tab:
            return
        old_zoom = tab.zoom
        tab.zoom = max(0.02, min(80.0, tab.zoom * factor))
        ratio = tab.zoom / old_zoom
        tab.offset_x = cx - ratio * (cx - tab.offset_x)
        tab.offset_y = cy - ratio * (cy - tab.offset_y)
        self._refresh_display()

    # ==================================================================
    # Measurement helpers
    # ==================================================================

    def _calc_L(self):
        tab = self._get_current_tab()
        if not tab or len(tab.L_points_img) != 2:
            return
        dx = tab.L_points_img[1][0] - tab.L_points_img[0][0]
        dy = tab.L_points_img[1][1] - tab.L_points_img[0][1]
        px_per_mm = tab.calib_px / tab.calib_mm if tab.calib_mm > 0 else 1.0
        tab.L_value = math.sqrt(dx**2 + dy**2) / px_per_mm
        self.L_var.set(f"{tab.L_value:.3f}")

    def _calc_W(self):
        tab = self._get_current_tab()
        if not tab or len(tab.W_points_img) != 2:
            return
        dx = tab.W_points_img[1][0] - tab.W_points_img[0][0]
        dy = tab.W_points_img[1][1] - tab.W_points_img[0][1]
        px_per_mm = tab.calib_px / tab.calib_mm if tab.calib_mm > 0 else 1.0
        tab.W_value = math.sqrt(dx**2 + dy**2) / px_per_mm
        self.W_var.set(f"{tab.W_value:.3f}")

    def _reset_L(self):
        tab = self._get_current_tab()
        if tab:
            tab.L_points_img.clear()
            tab.L_value = 0.0
            self.L_var.set("0.00")
            self._refresh_display()

    def _reset_W(self):
        tab = self._get_current_tab()
        if tab:
            tab.W_points_img.clear()
            tab.W_value = 0.0
            self.W_var.set("0.00")
            self._refresh_display()

    def _reset_all_measurements(self):
        self._reset_L()
        self._reset_W()

    # ==================================================================
    # Brush
    # ==================================================================

    def _brush_line(self, x0: float, y0: float, x1: float, y1: float, add: bool):
        """Draw brush along a line segment (interpolated)."""
        tab = self._get_current_tab()
        if not tab or tab.mask is None:
            return
        try:
            r = max(1, int(self.brush_var.get()))
        except ValueError:
            r = 15
        # Step size smaller than radius for no gaps
        step = max(1, r // 2)
        dx = x1 - x0
        dy = y1 - y0
        dist = math.sqrt(dx * dx + dy * dy)
        n_steps = max(1, int(dist / step))
        for i in range(n_steps + 1):
            t = i / n_steps
            self._apply_brush(x0 + dx * t, y0 + dy * t, add=add)

    def _apply_brush(self, ix: float, iy: float, add: bool):
        tab = self._get_current_tab()
        if not tab or tab.mask is None:
            return
        try:
            r = max(1, int(self.brush_var.get()))
        except ValueError:
            r = 15
        h, w = tab.mask.shape
        cx, cy = int(ix), int(iy)
        y_min = max(0, cy - r)
        y_max = min(h, cy + r + 1)
        x_min = max(0, cx - r)
        x_max = min(w, cx + r + 1)
        yy, xx = np.ogrid[y_min:y_max, x_min:x_max]
        dist2 = (xx - cx) ** 2 + (yy - cy) ** 2
        circle = dist2 <= r**2
        tab.mask[y_min:y_max, x_min:x_max][circle] = 255 if add else 0

    # ==================================================================
    # Auto-detect
    # ==================================================================

    def _auto_detect(self):
        tab = self._get_current_tab()
        if not tab or tab.pil_image is None:
            return
        gray = np.array(tab.pil_image.convert("L"))
        try:
            thr = int(self.thr_var.get())
        except ValueError:
            thr = 128
        tab.mask = np.where(gray < thr, np.uint8(255), np.uint8(0))
        self._refresh_display()
        n_px = int(np.sum(tab.mask > 0))
        self.status_var.set(f"Авто: порог={thr}, пикселей: {n_px}")

    def _auto_detect_at(self, ix: float, iy: float):
        tab = self._get_current_tab()
        if not tab or tab.pil_image is None:
            return
        gray = np.array(tab.pil_image.convert("L"))
        h, w = gray.shape
        cx, cy = int(ix), int(iy)
        if not (0 <= cx < w and 0 <= cy < h):
            return
        try:
            thr = int(self.thr_var.get())
        except ValueError:
            thr = 128
        seed_val = int(gray[cy, cx])
        visited = np.zeros((h, w), dtype=bool)
        result = np.zeros((h, w), dtype=np.uint8)
        q: deque = deque()
        q.append((cy, cx))
        visited[cy, cx] = True
        while q:
            r, c = q.popleft()
            if abs(int(gray[r, c]) - seed_val) <= thr:
                result[r, c] = 255
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < h and 0 <= nc < w and not visited[nr, nc]:
                        visited[nr, nc] = True
                        q.append((nr, nc))
        tab.mask = np.maximum(tab.mask, result)
        self._refresh_display()
        n_px = int(np.sum(tab.mask > 0))
        self.status_var.set(f"Из точки: пикселей: {n_px}")

    def _clear_mask(self):
        tab = self._get_current_tab()
        if tab and tab.pil_image is not None:
            tab.mask = np.zeros((tab.img_h, tab.img_w), dtype=np.uint8)
            self._refresh_display()

    def _invert_mask(self):
        """Invert the current mask (foreground <-> background)."""
        tab = self._get_current_tab()
        if tab and tab.mask is not None:
            tab.mask = 255 - tab.mask
            self._refresh_display()
            n_px = int(np.sum(tab.mask > 0))
            self.status_var.set(f"Маска инвертирована: {n_px} пикселей")

    def _load_sam_model(self):
        """Lazy-load SAM model (ViT-B)."""
        if self._sam_model_loaded:
            return True
        try:
            from segment_anything import sam_model_registry, SamPredictor
            import torch
            import sys
            model_type = "vit_b"

            # Find model path: EXE bundle dir or script dir
            if getattr(sys, 'frozen', False):
                base_dir = sys._MEIPASS
            else:
                base_dir = os.path.dirname(os.path.abspath(__file__))
            checkpoint_path = os.path.join(base_dir, "sam_vit_b_01ec64.pth")

            # Also check current working directory
            if not os.path.exists(checkpoint_path):
                checkpoint_path = os.path.join(os.getcwd(), "sam_vit_b_01ec64.pth")

            if not os.path.exists(checkpoint_path):
                self._download_sam_with_progress(checkpoint_path, model_type)
                return False

            self._init_sam_from_checkpoint(checkpoint_path, model_type)
            return True
        except Exception as e:
            messagebox.showerror("Ошибка SAM", f"Не удалось загрузить модель:\n{e}")
            self.tool_var.set(TOOL_NONE)
            return False

    def _init_sam_from_checkpoint(self, checkpoint_path, model_type):
        from segment_anything import sam_model_registry, SamPredictor
        import torch
        sam = sam_model_registry[model_type](checkpoint=checkpoint_path)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        sam.to(device)
        self._sam_predictor = SamPredictor(sam)
        self._sam_model_loaded = True
        self.status_var.set(f"SAM загружен на {device.upper()}")

    def _download_sam_with_progress(self, checkpoint_path, model_type):
        import urllib.request
        url = "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth"

        prog = tk.Toplevel(self.win)
        prog.title("Загрузка SAM модели")
        prog.geometry("400x150")
        prog.transient(self.win)
        prog.grab_set()
        ttk.Label(prog, text="Загрузка SAM модели (~375 MB)...").pack(pady=10)
        pb = ttk.Progressbar(prog, mode='determinate', length=350)
        pb.pack(pady=5, padx=20)
        status_lbl = ttk.Label(prog, text="0 / 375 MB")
        status_lbl.pack()

        def download():
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=120) as resp:
                    total = int(resp.headers.get('content-length', 0))
                    downloaded = 0
                    chunk_size = 8192
                    os.makedirs(os.path.dirname(checkpoint_path), exist_ok=True)
                    with open(checkpoint_path, 'wb') as f:
                        while True:
                            chunk = resp.read(chunk_size)
                            if not chunk:
                                break
                            f.write(chunk)
                            downloaded += len(chunk)
                            pct = int(downloaded * 100 / total) if total > 0 else 0
                            prog.after(0, lambda p=pct, d=downloaded, t=total: (
                                pb.config(value=p),
                                status_lbl.config(text=f"{d//1048576} / {t//1048576} MB")
                            ))
                prog.after(0, lambda: (
                    prog.destroy(),
                    self._init_sam_from_checkpoint(checkpoint_path, model_type)
                ))
            except Exception as exc:
                prog.after(0, lambda exc=exc: (
                    status_lbl.config(text=f"Ошибка: {exc}"),
                    ttk.Button(prog, text="Закрыть", command=prog.destroy).pack()
                ))

        threading.Thread(target=download, daemon=True).start()

    def _sam_predict(self, ix: float, iy: float):
        """Run SAM prediction on click point."""
        tab = self._get_current_tab()
        if not tab or tab.pil_image is None:
            return
        if not self._load_sam_model():
            return
        try:
            # Prepare image
            img_np = np.array(tab.pil_image.convert("RGB"))
            self._sam_predictor.set_image(img_np)

            # Point prompt (foreground)
            point_coords = np.array([[ix, iy]], dtype=np.float32)
            point_labels = np.array([1], dtype=np.int32)  # 1 = foreground

            masks, scores, logits = self._sam_predictor.predict(
                point_coords=point_coords,
                point_labels=point_labels,
                multimask_output=True,
            )

            # Take best mask (highest score)
            best_idx = int(np.argmax(scores))
            best_mask = masks[best_idx]

            # Update mask (add to existing or replace)
            if tab.mask is None:
                tab.mask = np.zeros((tab.img_h, tab.img_w), dtype=np.uint8)
            tab.mask = np.maximum(tab.mask, (best_mask * 255).astype(np.uint8))

            self._refresh_display()
            n_px = int(np.sum(tab.mask > 0))
            self.status_var.set(f"SAM: маска добавлена ({n_px} пикселей, score={scores[best_idx]:.3f})")

            # Auto-calculate L/W from mask
            self._auto_detect_LW_from_mask()
            if tab.L_value > 0:
                self._calc_L()
                self._calc_W()
                self.L_var.set(f"{tab.L_value:.3f}")
                self.W_var.set(f"{tab.W_value:.3f}")
                self.status_var.set(f"SAM: L={tab.L_value:.3f} мм, W={tab.W_value:.3f} мм (score={scores[best_idx]:.3f})")
        except Exception as e:
            messagebox.showerror("Ошибка SAM", f"Ошибка предсказания:\n{e}")

    # ==================================================================
    # Calibration
    # ==================================================================

    def _set_calibration(self):
        tab = self._get_current_tab()
        if not tab:
            return
        try:
            px = float(self.calib_px_var.get())
            mm = float(self.calib_mm_var.get())
        except ValueError:
            messagebox.showerror("Ошибка", "Введите числовые значения.")
            return
        if mm <= 0 or px <= 0:
            messagebox.showerror("Ошибка", "Значения должны быть > 0.")
            return
        tab.calib_px = px
        tab.calib_mm = mm
        self.default_calib_px = px
        self.default_calib_mm = mm
        # Recalculate existing measurements
        self._calc_L()
        self._calc_W()
        self.L_var.set(f"{tab.L_value:.3f}")
        self.W_var.set(f"{tab.W_value:.3f}")
        px_per_mm = tab.calib_px / tab.calib_mm
        self.status_var.set(f"Калибровка: {px:.1f} пк = {mm:.2f} мм ({px_per_mm:.2f} пк/мм)")
        self._refresh_display()

    def _set_calibration_all(self):
        """Apply calibration to all open tabs and save as default."""
        try:
            px = float(self.calib_px_var.get())
            mm = float(self.calib_mm_var.get())
        except ValueError:
            messagebox.showerror("Ошибка", "Введите числовые значения.")
            return
        if mm <= 0 or px <= 0:
            messagebox.showerror("Ошибка", "Значения должны быть > 0.")
            return
        # Save as default for future tabs
        self.default_calib_px = px
        self.default_calib_mm = mm
        for tab in self.tabs:
            tab.calib_px = px
            tab.calib_mm = mm
            self._calc_L()
            self._calc_W()
        # Update current tab display
        # Notify main app to update project default calibration
        if self.app and hasattr(self.app, '_on_calibration_changed'):
            self.app._on_calibration_changed(px, mm)
        tab = self._get_current_tab()
        if tab:
            self.L_var.set(f"{tab.L_value:.3f}")
            self.W_var.set(f"{tab.W_value:.3f}")
        px_per_mm = px / mm
        self.status_var.set(f"Калибровка ко всем: {px:.1f} пк = {mm:.2f} мм ({px_per_mm:.2f} пк/мм)")
        self._refresh_display()

    # ==================================================================
    # Wear calculation
    # ==================================================================

    def _calc_wear(self):
        tab = self._get_current_tab()
        if not tab:
            return
        L = tab.L_value
        W = tab.W_value
        if L <= 0:
            messagebox.showinfo("Инфо", "Измерьте длину трека L (два клика инструментом 'Длина L' или 'Авто L/W из маски').")
            return
        R = self.params.disk_diameter_mm / 2.0
        h = calc_wear_depth(R, L)
        S = calc_wear_area(R, L, h)
        V = calc_wear_volume(S, W) if W > 0 else 0.0
        r = self.params.edge_radius_mm if hasattr(self.params, 'edge_radius_mm') else 0.0
        V_edge = calc_wear_volume_edge_radius(S, W, L, r) if r > 0 and W > 0 else 0.0
        area_px = int(np.sum(tab.mask > 0)) if tab.mask is not None else 0
        px_per_mm = tab.calib_px / tab.calib_mm if tab.calib_mm > 0 else 1.0
        area_mm2 = area_px / (px_per_mm**2) if px_per_mm > 0 else 0.0
        
        # Tribological wear metrics
        trib = {}
        if tab.linked_sample is not None:
            trib = compute_tribology_wear(tab.linked_sample, self.params, h, V, V_edge)
            # Store in linked sample
            tab.linked_sample.wear_D_m = trib.get("D_m", 0.0)
            tab.linked_sample.wear_A_J = trib.get("A_J", 0.0)
            tab.linked_sample.wear_I_h = trib.get("I_h", 0.0)
            tab.linked_sample.wear_I_A = trib.get("I_A", 0.0)
            tab.linked_sample.wear_eps = trib.get("eps", 0.0)
            tab.linked_sample.wear_k = trib.get("k", 0.0)
            tab.linked_sample.wear_mu_avg = trib.get("mu_avg", 0.0)
            tab.linked_sample.wear_mu_std = trib.get("mu_std", 0.0)
            tab.linked_sample.wear_eps_V = trib.get("eps_V", 0.0)
            compute_wear_metrics_and_errors(
                tab.linked_sample, self.params, R, L, W, V, V_edge,
                tab.calib_px / tab.calib_mm if tab.calib_mm > 0 else 1.0,
                trib,
                getattr(self.app, 'calib_rel_error', 0.01),
            )
        
        lines = [
            f"R = {R:.1f} мм",
            f"L = {L:.3f} мм",
            f"W = {W:.3f} мм",
            f"h = {h:.4f} мм",
            f"S_BCD = {S:.4f} мм²",
            f"V = {V:.4f} мм³",
        ]
        if V_edge > 0:
            lines.append(f"V_edge = {V_edge:.4f} мм³  (r={r:.2f} мм)")
        lines.extend([
            f"Маска: {area_px} пк = {area_mm2:.4f} мм²",
            f"D = {trib.get('D_m', 0.0):.3f} м",
            f"A = {trib.get('A_J', 0.0):.4f} Дж",
            f"μ = {trib.get('mu_avg', 0.0):.4f} ± {trib.get('mu_std', 0.0):.4f}",
            f"I_h = {trib.get('I_h', 0.0):.3f} мкм/м",
            f"I_A = {trib.get('I_A', 0.0):.3e} мкм/Дж",
            f"ε = {trib.get('eps', 0.0):.1f} м/мкм",
            f"k = {trib.get('k', 0.0):.3e} мм³/Н·м",
            f"ε_V = {trib.get('eps_V', 0.0):.4f} м/мкм³",
        ])
        self.result_var.set("\n".join(lines))
        # Push to linked sample
        if tab.linked_sample is not None:
            tab.linked_sample.wear_L = L
            tab.linked_sample.wear_W = W
            tab.linked_sample.wear_h = h
            tab.linked_sample.wear_S = S
            tab.linked_sample.wear_V = V_edge if V_edge > 0 else V
            self.status_var.set(f"Результаты записаны в {tab.linked_sample.name}")

    # ==================================================================
    # Push to main table
    # ==================================================================

    def _push_to_table(self):
        """Write current wear results to the main window's summary table."""
        tab = self._get_current_tab()
        if not tab:
            return
        L = tab.L_value
        W = tab.W_value
        if L <= 0:
            messagebox.showinfo("Инфо", "Сначала измерьте L и W.")
            return
        R = self.params.disk_diameter_mm / 2.0
        h = calc_wear_depth(R, L)
        S = calc_wear_area(R, L, h)
        V = calc_wear_volume(S, W) if W > 0 else 0.0
        r = self.params.edge_radius_mm if hasattr(self.params, 'edge_radius_mm') else 0.0
        V_edge = calc_wear_volume_edge_radius(S, W, L, r) if r > 0 and W > 0 else 0.0
        V_final = V_edge if V_edge > 0 else V

        # Tribological wear metrics
        trib = {}
        if tab.linked_sample is not None:
            r = self.params.edge_radius_mm if hasattr(self.params, 'edge_radius_mm') else 0.0
            V_edge = calc_wear_volume_edge_radius(S, W, L, r) if r > 0 and W > 0 else 0.0
            trib = compute_tribology_wear(tab.linked_sample, self.params, h, V, V_edge)

        target_sample = tab.linked_sample

        # If no auto-linked sample, show selection dialog
        if target_sample is None:
            target_sample = self._select_sample_dialog()
            if target_sample is None:
                return
        else:
            # Confirm using the auto-linked sample
            if not messagebox.askyesno(
                "Подтвердить образец",
                f"Внести данные в образец:\n{target_sample.name}?\n\n"
                f"L={L:.3f} мм, W={W:.3f} мм, h={h:.4f} мм, S={S:.4f} мм², V={V:.4f} мм³",
                default=messagebox.YES,
            ):
                target_sample = self._select_sample_dialog()
                if target_sample is None:
                    return

        # Write to selected sample
        target_sample.wear_L = L
        target_sample.wear_W = W
        target_sample.wear_h = h
        target_sample.wear_S = S
        target_sample.wear_V = V_final
        target_sample.wear_D_m = trib.get("D_m", 0.0)
        target_sample.wear_A_J = trib.get("A_J", 0.0)
        target_sample.wear_P_W = trib.get("P_W", 0.0)
        target_sample.wear_I_h = trib.get("I_h", 0.0)
        target_sample.wear_I_A = trib.get("I_A", 0.0)
        target_sample.wear_eps = trib.get("eps", 0.0)
        target_sample.wear_k = trib.get("k", 0.0)
        target_sample.wear_mu_avg = trib.get("mu_avg", 0.0)
        target_sample.wear_mu_std = trib.get("mu_std", 0.0)
        target_sample.wear_mu_cov = trib.get("mu_cov", 0.0)
        target_sample.wear_V_D = trib.get("V_D", 0.0)
        target_sample.wear_eps_V = trib.get("eps_V", 0.0)
        target_sample.wear_p_MPa = trib.get("p_MPa", 0.0)
        target_sample.wear_t_steady_s = trib.get("t_steady_s", 0.0)
        target_sample.wear_mu_amplitude = trib.get("mu_amplitude", 0.0)
        target_sample.wear_stick_slip = trib.get("stick_slip", "")
        compute_wear_metrics_and_errors(
            target_sample, self.params, R, L, W, V, V_edge,
            tab.calib_px / tab.calib_mm if tab.calib_mm > 0 else 1.0,
            trib,
            getattr(self.app, 'calib_rel_error', 0.01),
        )

        # Also update linked_sample reference for future operations
        tab.linked_sample = target_sample
        self.linked_var.set(f"Связано: {target_sample.name}")

        # Refresh main table
        if self.app is not None:
            self.app._refresh_table()

        self.status_var.set(f"Внесено в таблицу: {target_sample.name}  L={L:.3f} W={W:.3f} h={h:.4f} S={S:.4f} V={V:.4f}")

    def _select_sample_dialog(self) -> Optional[TribSample]:
        """Show dialog to select a sample from available samples."""
        if not self.samples:
            messagebox.showinfo("Инфо", "Нет загруженных образцов в главном окне.")
            return None

        dlg = tk.Toplevel(self.win)
        dlg.title("Выбрать образец")
        dlg.geometry("400x300")
        dlg.transient(self.win)
        dlg.grab_set()

        ttk.Label(dlg, text="Выберите образец для внесения данных:", anchor=tk.W).pack(fill=tk.X, padx=10, pady=10)

        lb = tk.Listbox(dlg, font=("Consolas", 10), selectmode=tk.SINGLE)
        for s in self.samples:
            lb.insert(tk.END, s.name)
        lb.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Select first by default
        if self.samples:
            lb.selection_set(0)
            lb.activate(0)

        result = {"sample": None}

        def on_ok():
            sel = lb.curselection()
            if sel:
                result["sample"] = self.samples[sel[0]]
            dlg.destroy()

        def on_cancel():
            dlg.destroy()

        bf = ttk.Frame(dlg)
        bf.pack(fill=tk.X, padx=10, pady=10)
        ttk.Button(bf, text="OK", command=on_ok).pack(side=tk.RIGHT, padx=5)
        ttk.Button(bf, text="Отмена", command=on_cancel).pack(side=tk.RIGHT)

        self.win.wait_window(dlg)
        return result["sample"]

    # ==================================================================
    # Auto-detect L/W from mask (PCA / longest axis)
    # ==================================================================

    def _auto_detect_LW_from_mask(self):
        tab = self._get_current_tab()
        if not tab or tab.mask is None or tab.mask.max() == 0:
            messagebox.showinfo("Инфо", "Сначала создайте маску (Авто-определение или кисть).")
            return
        # Get mask coordinates
        ys, xs = np.where(tab.mask > 0)
        if len(xs) < 10:
            messagebox.showinfo("Инфо", "Маска слишком мала.")
            return

        # PCA to find principal axis
        coords = np.column_stack((xs.astype(float), ys.astype(float)))
        mean = coords.mean(axis=0)
        centered = coords - mean
        cov = np.cov(centered.T)
        eigenvalues, eigenvectors = np.linalg.eigh(cov)
        # Principal axis = eigenvector with largest eigenvalue
        principal = eigenvectors[:, np.argmax(eigenvalues)]
        perpendicular = eigenvectors[:, np.argmin(eigenvalues)]

        # Project all points onto principal axis
        proj_p = centered @ principal
        t_min, t_max = proj_p.min(), proj_p.max()
        L_px = t_max - t_min

        # For W: at each position along L, find max perpendicular spread
        proj_perp = centered @ perpendicular
        W_px = 0.0
        # Divide into slices along L axis
        n_slices = max(10, int(L_px))
        slice_edges = np.linspace(t_min, t_max, n_slices + 1)
        for i in range(n_slices):
            mask_slice = (proj_p >= slice_edges[i]) & (proj_p < slice_edges[i + 1])
            if mask_slice.sum() > 0:
                spread = proj_perp[mask_slice].max() - proj_perp[mask_slice].min()
                if spread > W_px:
                    W_px = spread

        px_per_mm = tab.calib_px / tab.calib_mm if tab.calib_mm > 0 else 1.0
        tab.L_value = L_px / px_per_mm
        tab.W_value = W_px / px_per_mm
        self.L_var.set(f"{tab.L_value:.3f}")
        self.W_var.set(f"{tab.W_value:.3f}")

        # Store endpoint images coords for visualization
        p_start = mean + principal * t_min
        p_end = mean + principal * t_max
        tab.L_points_img = [(p_start[0], p_start[1]), (p_end[0], p_end[1])]

        # Find widest point for W line
        mid_t = (t_min + t_max) / 2
        best_spread = 0.0
        best_p1 = best_p2 = None
        for i in range(n_slices):
            mask_slice = (proj_p >= slice_edges[i]) & (proj_p < slice_edges[i + 1])
            if mask_slice.sum() > 0:
                spread = proj_perp[mask_slice].max() - proj_perp[mask_slice].min()
                if spread > best_spread:
                    best_spread = spread
                    perp_min = proj_perp[mask_slice].min()
                    perp_max = proj_perp[mask_slice].max()
                    center_along = (slice_edges[i] + slice_edges[i + 1]) / 2
                    pt_center = mean + principal * center_along
                    best_p1 = pt_center + perpendicular * perp_min
                    best_p2 = pt_center + perpendicular * perp_max
        if best_p1 is not None:
            tab.W_points_img = [(best_p1[0], best_p1[1]), (best_p2[0], best_p2[1])]

        self._refresh_display()
        self.status_var.set(f"Авто L/W: L={tab.L_value:.3f} мм, W={tab.W_value:.3f} мм")

    # ==================================================================
    # Export summary
    # ==================================================================

    def _export_summary(self):
        tab = self._get_current_tab()
        if not tab:
            return
        L = tab.L_value
        W = tab.W_value
        if L <= 0:
            messagebox.showinfo("Инфо", "Нет данных для экспорта.")
            return
        R = self.params.disk_diameter_mm / 2.0
        h = calc_wear_depth(R, L)
        S = calc_wear_area(R, L, h)
        V = calc_wear_volume(S, W) if W > 0 else 0.0
        r = self.params.edge_radius_mm if hasattr(self.params, 'edge_radius_mm') else 0.0
        V_edge = calc_wear_volume_edge_radius(S, W, L, r) if r > 0 and W > 0 else 0.0
        area_px = int(np.sum(tab.mask > 0)) if tab.mask is not None else 0
        px_per_mm = tab.calib_px / tab.calib_mm if tab.calib_mm > 0 else 1.0
        area_mm2 = area_px / (px_per_mm**2) if px_per_mm > 0 else 0.0

        # Tribological wear metrics
        trib = {}
        if tab.linked_sample is not None:
            trib = compute_tribology_wear(tab.linked_sample, self.params, h, V, V_edge)

        path = filedialog.asksaveasfilename(
            title="Сохранить итоги", defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("TSV", "*.tsv")],
        )
        if not path:
            return
        delim = "\t" if path.endswith(".tsv") else ","
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh, delimiter=delim)
            w.writerow(["Параметр", "Значение", "Ед."])
            w.writerow(["Радиус диска R", f"{R:.1f}", "мм"])
            w.writerow(["Длина трека L", f"{L:.3f}", "мм"])
            w.writerow(["Ширина трека W", f"{W:.3f}", "мм"])
            w.writerow(["Глубина h", f"{h:.4f}", "мм"])
            w.writerow(["Площадь S_BCD", f"{S:.4f}", "мм²"])
            w.writerow(["Объём V", f"{V:.4f}", "мм³"])
            w.writerow(["Нагрузка", f"{self.params.load_mN:.1f}", "мН"])
            w.writerow(["Площадь маски", f"{area_mm2:.4f}", "мм²"])
            w.writerow(["Калибровка", f"{tab.calib_px:.1f} пк = {tab.calib_mm:.2f} мм", ""])
            if tab.linked_sample:
                w.writerow(["Образец", tab.linked_sample.name, ""])
                w.writerow(["Дистанция скольжения D", f"{trib.get('D_m', 0.0):.3f}", "м"])
                w.writerow(["Работа трения A", f"{trib.get('A_J', 0.0):.3f}", "Дж"])
                w.writerow(["Iₕ (h/D)", f"{trib.get('I_h', 0.0):.3f}", "мкм/м"])
                w.writerow(["Iₐ (h/A)", f"{trib.get('I_A', 0.0):.3e}", "мкм/Дж"])
                w.writerow(["ε (1/Iₕ)", f"{trib.get('eps', 0.0):.1f}", "м/мкм"])
                w.writerow(["k (Арчар)", f"{trib.get('k', 0.0):.3e}", "мм³/Н·м"])
                w.writerow(["μ ср.", f"{trib.get('mu_avg', 0.0):.4f}", ""])
                w.writerow(["σ(μ)", f"{trib.get('mu_std', 0.0):.4f}", ""])
        self.status_var.set(f"Итоги сохранены: {os.path.basename(path)}")

    # ==================================================================
    # Export image with scale bar (no mask)
    # ==================================================================

    def _export_image_scalebar(self):
        tab = self._get_current_tab()
        if not tab or tab.pil_image is None:
            messagebox.showinfo("Инфо", "Нет изображения.")
            return
        px_per_mm = tab.calib_px / tab.calib_mm if tab.calib_mm > 0 else 0
        if px_per_mm <= 0:
            messagebox.showinfo("Инфо", "Сначала задайте калибровку.")
            return

        # Show settings dialog first
        if not self._export_settings_dialog():
            return

        path = filedialog.asksaveasfilename(
            title="Сохранить фото с линейкой", defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg")],
        )
        if not path:
            return

        # Original image without mask
        img = tab.pil_image.copy()
        draw = ImageDraw.Draw(img)

        # Get settings
        font_size = self.export_font_size.get()
        line_w = self.export_line_width.get()
        pos = self.export_bar_pos.get()
        show_L = self.export_show_L.get()
        show_W = self.export_show_W.get()

        # ===== NEW SCALE BAR DESIGN =====
        # Height = 1/5 of image height
        rect_h = img.height // 5
        # Margin from edge = 1/2 of rect_h, reduced by 20%
        margin = int(rect_h * 0.4)
        if margin < 5:
            margin = 5

        # White line: length = 1/8 of image width
        target_line_px = img.width / 8
        scale_unit = self.export_scale_unit.get()

        # Nice round scale values
        nice_mm = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100]
        nice_um = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000]

        if scale_unit == "мкм":
            target_um = target_line_px / px_per_mm * 1000
            best_um = min(nice_um, key=lambda v: abs(v - target_um))
            white_line_px = round(best_um / 1000 * px_per_mm)
            if white_line_px < 10:
                white_line_px = 10
            white_line_value = best_um
        else:
            target_mm = target_line_px / px_per_mm
            best_mm = min(nice_mm, key=lambda v: abs(v - target_mm))
            white_line_px = round(best_mm * px_per_mm)
            if white_line_px < 10:
                white_line_px = 10
            white_line_value = best_mm

        # White line thickness = 1/5 of rect_h
        white_line_thickness = max(1, int(round(rect_h / 5)))

        # Side padding (independent of rect_w to avoid circular dependency)
        side_padding = max(6, int(rect_h * 0.1))

        # Position calculations
        if pos in ("bottom-left", "bottom-right"):
            rect_y2 = img.height - margin
            rect_y1 = rect_y2 - rect_h
        else:
            rect_y1 = margin
            rect_y2 = rect_y1 + rect_h

        # ===== FIND LARGEST FONT THAT FITS =====
        margin_inner = max(4, int(rect_h * 0.08))
        line_bottom = rect_y2 - margin_inner
        line_y = line_bottom - white_line_thickness // 2
        line_top = line_y - white_line_thickness // 2
        gap = max(3, int(rect_h * 0.04))
        text_area_h = line_top - gap - rect_y1

        def _font(sz):
            try:
                return ImageFont.truetype("arial.ttf", sz)
            except (OSError, IOError):
                return ImageFont.load_default()

        font = _font(8)
        if text_area_h > 10:
            lo, hi = 8, min(text_area_h, 200)
            font = _font(lo)
            while lo <= hi:
                mid = (lo + hi) // 2
                f = _font(mid)
                tmp = Image.new("RGB", (1, 1))
                tmp_d = ImageDraw.Draw(tmp)
                bb = tmp_d.textbbox((0, 0), "00.0 мм", font=f)
                th_t = bb[3] - bb[1]
                if th_t <= text_area_h:
                    font = f
                    lo = mid + 1
                else:
                    hi = mid - 1

        # Measure text width with final font
        if scale_unit == "мкм":
            label = f"{white_line_value:.0f} мкм"
        else:
            label = f"{white_line_value:g} мм"
        tmp_img = Image.new("RGB", (1, 1))
        tmp_d = ImageDraw.Draw(tmp_img)
        bb = tmp_d.textbbox((0, 0), label, font=font)
        text_w = bb[2] - bb[0]

        # Rectangle width = max(white_line_px, text_w) + 2 * side_padding
        rect_w = max(white_line_px, text_w) + 2 * side_padding
        # Cap to image width
        if rect_w > img.width - 2 * margin:
            rect_w = img.width - 2 * margin

        if pos in ("bottom-left", "top-left"):
            rect_x1 = margin
            rect_x2 = rect_x1 + rect_w
        else:
            rect_x2 = img.width - margin
            rect_x1 = rect_x2 - rect_w

        # Clamp white_line_px to fit inside rect
        if white_line_px > rect_w - 2 * side_padding:
            white_line_px = rect_w - 2 * side_padding

        line_x1 = rect_x1 + (rect_w - white_line_px) // 2
        line_x2 = line_x1 + white_line_px

        # ===== DRAW SCALE BAR =====
        draw.rectangle([rect_x1, rect_y1, rect_x2, rect_y2], fill="black")

        # White line (horizontal bar) — fully inside rectangle
        draw.line([(line_x1, line_y), (line_x2, line_y)], fill="white", width=white_line_thickness)

        # Label — positioned above the line with gap
        if scale_unit == "мкм":
            label = f"{white_line_value:.0f} мкм"
        else:
            label = f"{white_line_value:g} мм"
        bb = draw.textbbox((0, 0), label, font=font)
        tw = bb[2] - bb[0]
        th = bb[3] - bb[1]
        text_x = rect_x1 + (rect_w - tw) / 2
        text_y = rect_y1 + (text_area_h - th) * 0.24
        draw.text((text_x, text_y), label, fill="white", font=font)

        # Draw L/W lines if enabled and set
        if show_L and len(tab.L_points_img) == 2:
            p1, p2 = tab.L_points_img
            draw.line([p1, p2], fill=(0, 200, 0), width=line_w)
            mx = (p1[0] + p2[0]) / 2
            my = (p1[1] + p2[1]) / 2
            l_label = f"L={tab.L_value:.3f} мм"
            lbbox = draw.textbbox((0, 0), l_label, font=font)
            ltw = lbbox[2] - lbbox[0]
            draw.text((mx - ltw / 2, my - th - 4), l_label, fill=(0, 200, 0), font=font)

        if show_W and len(tab.W_points_img) == 2:
            p1, p2 = tab.W_points_img
            draw.line([p1, p2], fill=(0, 100, 255), width=line_w)
            mx = (p1[0] + p2[0]) / 2
            my = (p1[1] + p2[1]) / 2
            w_label = f"W={tab.W_value:.3f} мм"
            wbbox = draw.textbbox((0, 0), w_label, font=font)
            wtw = wbbox[2] - wbbox[0]
            draw.text((mx - wtw / 2, my + 4), w_label, fill=(0, 100, 255), font=font)

        img.save(path, quality=95)
        self.status_var.set(f"Фото сохранено: {os.path.basename(path)}")

    # ==================================================================
    # Project load helpers
    # ==================================================================

    def load_tabs_from_project(self, tabs_data: list[dict]):
        """Load tabs from project data (called by TriboApp after opening project)."""
        self.notebook.unbind("<<NotebookTabChanged>>")
        try:
            for td in tabs_data:
                img_path = td.get("path", "")
                if not os.path.isfile(img_path):
                    continue
                try:
                    img = Image.open(img_path)
                    pil_image = img.convert("RGB")
                    img_w, img_h = pil_image.size

                    # Load mask if saved
                    mask_path = td.get("mask_path", "")
                    if mask_path and os.path.isfile(mask_path):
                        mask = np.load(mask_path)
                    else:
                        mask = np.zeros((img_h, img_w), dtype=np.uint8)

                    # Find linked sample
                    linked_sample = None
                    linked_name = td.get("linked_sample", None)
                    if linked_name:
                        for s in self.samples:
                            if s.name == linked_name:
                                linked_sample = s
                                break

                    tab = ImageTab(
                        path=img_path,
                        pil_image=pil_image,
                        mask=mask,
                        img_w=img_w,
                        img_h=img_h,
                        linked_sample=linked_sample,
                        filename_var=os.path.basename(img_path),
                        L_value=td.get("L_value", 0.0),
                        W_value=td.get("W_value", 0.0),
                        calib_px=td.get("calib_px", 100.0),
                        calib_mm=td.get("calib_mm", 1.0),
                    )
                    self.tabs.append(tab)
                    new_idx = len(self.tabs) - 1
                    frame = ttk.Frame(self.notebook)
                    self.notebook.add(frame, text=os.path.basename(img_path)[:30])
                    self.notebook.update_idletasks()
                except Exception as exc:
                    print(f"Ошибка загрузки изображения {img_path}: {exc}")
        finally:
            self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        if self.tabs:
            self._switch_tab(0)
            self.status_var.set(f"Загружено {len(self.tabs)} изображений из проекта")

    def collect_tabs_data(self) -> list[dict]:
        """Collect current tabs state for saving."""
        result = []
        for tab in self.tabs:
            td = {
                "path": tab.path,
                "linked_sample": tab.linked_sample.name if tab.linked_sample else None,
                "L_value": tab.L_value,
                "W_value": tab.W_value,
                "calib_px": tab.calib_px,
                "calib_mm": tab.calib_mm,
                "mask_path": "",  # will be filled by caller
            }
            result.append(td)
        return result
