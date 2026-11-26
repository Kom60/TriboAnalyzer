"""Table and graph export functions."""

import os
import csv
import io
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Callable, Optional, Any

try:
    from docx import Document
    from docx.shared import Inches, Pt, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

try:
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as XlsxImage
    from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
    from openpyxl.utils import get_column_letter
    XLSX_AVAILABLE = True
except ImportError:
    XLSX_AVAILABLE = False


def export_graph(fig, samples, parent_widget):
    """Save graph figure to file."""
    path = filedialog.asksaveasfilename(
        title="Сохранить график", defaultextension=".png",
        filetypes=[("PNG", "*.png"), ("PDF", "*.pdf"), ("SVG", "*.svg")],
    )
    if path:
        fig.savefig(path, dpi=200, bbox_inches="tight")


def export_table_dialog(parent_widget, format_config, table_cols, samples, build_row_fn, fig, save_graph_16_9_fn=None):
    """Show export dialog for CSV, DOCX or XLSX."""
    dlg = tk.Toplevel(parent_widget)
    dlg.title("Экспорт таблицы")
    dlg.geometry("420x320")
    dlg.minsize(400, 300)
    dlg.transient(parent_widget)
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
    ttk.Radiobutton(main_frame, text="Запятая (1,23)", variable=decimal_var, value="comma").grid(row=7, column=0, sticky=tk.W, padx=10)

    bf = ttk.Frame(main_frame)
    bf.grid(row=8, column=0, sticky=tk.EW)
    bf.columnconfigure(0, weight=1)
    bf.columnconfigure(1, weight=1)

    def do_export():
        fmt = format_var.get()
        dec = decimal_var.get()
        dlg.destroy()
        if fmt == "csv":
            path = filedialog.asksaveasfilename(
                title="Сохранить CSV", defaultextension=".csv",
                filetypes=[("CSV", "*.csv"), ("Все", "*.*")],
            )
            if path:
                sep = "," if dec == "comma" else "\t"
                export_table_csv(path, format_config, table_cols, samples, build_row_fn, dec, sep)
        elif fmt == "docx":
            path = filedialog.asksaveasfilename(
                title="Сохранить DOCX", defaultextension=".docx",
                filetypes=[("Word", "*.docx")],
            )
            if path:
                if not DOCX_AVAILABLE:
                    messagebox.showerror("Ошибка", "python-docx не установлен.\nУстановите: pip install python-docx")
                    return
                graph_path = os.path.join(tempfile.gettempdir(), "_temp_tribo_graph.png")
                if save_graph_16_9_fn:
                    save_graph_16_9_fn(graph_path)
                else:
                    fig.savefig(graph_path, dpi=150, bbox_inches="tight",
                                facecolor="white", edgecolor="none")
                export_table_docx(path, format_config, table_cols, samples, build_row_fn, graph_path)
                if os.path.isfile(graph_path):
                    os.remove(graph_path)
        elif fmt == "xlsx":
            path = filedialog.asksaveasfilename(
                title="Сохранить Excel", defaultextension=".xlsx",
                filetypes=[("Excel", "*.xlsx")],
            )
            if path:
                if not XLSX_AVAILABLE:
                    messagebox.showerror("Ошибка", "openpyxl не установлен.\nУстановите: pip install openpyxl")
                    return
                graph_path = os.path.join(tempfile.gettempdir(), "_temp_tribo_graph.png")
                if save_graph_16_9_fn:
                    save_graph_16_9_fn(graph_path)
                else:
                    fig.savefig(graph_path, dpi=150, bbox_inches="tight",
                                facecolor="white", edgecolor="none")
                export_table_xlsx(path, format_config, table_cols, samples, build_row_fn, decimal_sep=dec, graph_path=graph_path)
                if os.path.isfile(graph_path):
                    os.remove(graph_path)

    ttk.Button(bf, text="Экспорт", command=do_export).grid(row=0, column=0, padx=5, pady=10, sticky=tk.EW)
    ttk.Button(bf, text="Отмена", command=dlg.destroy).grid(row=0, column=1, padx=5, pady=10, sticky=tk.EW)


def export_table_csv(path, format_config, table_cols, samples, build_row_fn, decimal_sep, delimiter):
    """Export table to CSV."""
    header = ["Образец"] + [_col_header(c, format_config) for c in table_cols if c != "name"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=delimiter)
        writer.writerow(header)
        for s in samples:
            if len(s.friction) == 0:
                continue
            row = build_row_fn(s)
            vals = [row[c] for c in table_cols if c != "name"]
            if decimal_sep == "comma":
                vals = [v.replace(".", ",") for v in vals]
            writer.writerow(vals)


def export_table_docx(path, format_config, table_cols, samples, build_row_fn, graph_path=None):
    """Export table to DOCX with 16:9 graph and two split tables."""
    doc = Document()

    if graph_path and os.path.isfile(graph_path):
        doc.add_picture(graph_path, width=Inches(6.0))
        doc.add_paragraph()

    param_cols = [c for c in table_cols if c != "name"]
    n = len(param_cols)
    third = n // 3
    cols_part1 = param_cols[:third]
    cols_part2 = param_cols[third:2*third]
    cols_part3 = param_cols[2*third:]

    valid_samples = [s for s in samples if len(s.friction) > 0]

    _add_docx_table(doc, format_config, cols_part1, valid_samples, build_row_fn)
    doc.add_paragraph()
    _add_docx_table(doc, format_config, cols_part2, valid_samples, build_row_fn)
    doc.add_paragraph()
    _add_docx_table(doc, format_config, cols_part3, valid_samples, build_row_fn)

    doc.save(path)


def _add_docx_table(doc, format_config, param_cols, valid_samples, build_row_fn):
    """Add a single table to a DOCX document."""
    headers = ["Образец"] + [_col_header(c, format_config) for c in param_cols]
    ncols = len(headers)
    nrows = 1 + len(valid_samples)

    table = doc.add_table(rows=nrows, cols=ncols)
    table.style = 'Light Grid Accent 1'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    for j, hdr in enumerate(headers):
        cell = table.rows[0].cells[j]
        cell.text = hdr
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.font.size = Pt(9)
                run.font.bold = True

    for i, s in enumerate(valid_samples):
        row_data = build_row_fn(s)
        table.rows[i + 1].cells[0].text = str(row_data.get("name", ""))
        for paragraph in table.rows[i + 1].cells[0].paragraphs:
            for run in paragraph.runs:
                run.font.size = Pt(8)
        for j, c in enumerate(param_cols):
            cell = table.rows[i + 1].cells[j + 1]
            cell.text = str(row_data.get(c, ""))
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(8)

    for row in table.rows:
        row.cells[0].width = Cm(3)
        for j in range(1, ncols):
            row.cells[j].width = Cm(2)


def export_table_xlsx(path, format_config, table_cols, samples, build_row_fn,
                      decimal_sep="dot", graph_path=None):
    """Export table to XLSX with graph image and each value in its own cell."""
    wb = Workbook()

    header_font = Font(bold=True, size=10)
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font_white = Font(bold=True, size=10, color="FFFFFF")
    cell_font = Font(size=10)
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin'),
    )
    center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)

    param_cols = [c for c in table_cols if c != "name"]
    valid_samples = [s for s in samples if len(s.friction) > 0]

    mid = len(param_cols) // 2
    cols_part1 = param_cols[:mid]
    cols_part2 = param_cols[mid:]

    ws = wb.active
    ws.title = "Результаты"

    if graph_path and os.path.isfile(graph_path):
        img = XlsxImage(graph_path)
        img.width = 800
        img.height = 450
        ws.add_image(img, "A1")
        start_row = 20
    else:
        start_row = 1

    _add_xlsx_table(ws, start_row, format_config, cols_part1, valid_samples, build_row_fn,
                    header_font_white, header_fill, cell_font, thin_border, center_align, decimal_sep)

    second_start = start_row + len(valid_samples) + 3
    _add_xlsx_table(ws, second_start, format_config, cols_part2, valid_samples, build_row_fn,
                    header_font_white, header_fill, cell_font, thin_border, center_align, decimal_sep)

    wb.save(path)


def _add_xlsx_table(ws, start_row, format_config, param_cols, valid_samples, build_row_fn,
                     header_font, header_fill, cell_font, thin_border, center_align, decimal_sep):
    """Add a single table to an XLSX worksheet."""
    headers = ["Образец"] + [_col_header(c, format_config) for c in param_cols]

    for j, hdr in enumerate(headers):
        cell = ws.cell(row=start_row, column=j + 1, value=hdr)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_align
        cell.border = thin_border

    for i, s in enumerate(valid_samples):
        row_data = build_row_fn(s)
        row_idx = start_row + i + 1

        val = str(row_data.get("name", ""))
        cell = ws.cell(row=row_idx, column=1, value=val)
        cell.font = cell_font
        cell.alignment = center_align
        cell.border = thin_border

        for j, c in enumerate(param_cols):
            val = str(row_data.get(c, ""))
            if decimal_sep == "comma":
                val = val.replace(".", ",")
            cell = ws.cell(row=row_idx, column=j + 2, value=val)
            cell.font = cell_font
            cell.alignment = center_align
            cell.border = thin_border

    for j in range(len(headers)):
        col_letter = get_column_letter(j + 1)
        if j == 0:
            ws.column_dimensions[col_letter].width = 18
        else:
            ws.column_dimensions[col_letter].width = 14


def _col_header(col, format_config):
    """Build column header text with unit."""
    cfg = format_config.get(col, {})
    header = cfg.get("header", col)
    unit = cfg.get("selected_unit", "")
    if unit:
        return f"{header}, {unit}"
    return header
