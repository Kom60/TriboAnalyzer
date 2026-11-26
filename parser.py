"""File parser for Tribology Logger 2013 v.1.00 format."""

import os
import re

import numpy as np

from models import TribSample


def parse_tribology_file(filepath: str) -> TribSample:
    """Parse a Tribology Logger 2013 v.1.00 export text file."""
    filepath = os.path.normpath(os.fspath(filepath))
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Файл не найден: {filepath}")
    sample = TribSample(filepath=filepath, name=os.path.splitext(os.path.basename(filepath))[0])

    content = None
    for enc in ("utf-8", "cp1251", "latin-1"):
        try:
            with open(filepath, "r", encoding=enc) as fh:
                content = fh.readlines()
            break
        except (UnicodeDecodeError, UnicodeError, OSError):
            continue
    if content is None:
        raise ValueError(f"Не удалось прочитать файл: {filepath}")

    data_started = False
    time_list: list[float] = []
    friction_list: list[float] = []

    for line in content:
        stripped = line.strip()

        if not data_started:
            m = re.search(r"(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}:\d{2})", stripped)
            if m:
                sample.date = m.group(1)

            if "Число отсчетов" in stripped or "otсчетов" in stripped:
                try:
                    sample.num_points = int(stripped.split()[-1])
                except ValueError:
                    pass

            if stripped.startswith("t,") or stripped.startswith("t\t"):
                data_started = True
                continue
            continue

        parts = stripped.split("\t")
        if len(parts) >= 2:
            try:
                t_val = float(parts[0].replace(",", "."))
                u_val = float(parts[1].replace(",", "."))
                if u_val < 0:
                    u_val = 0.0
                time_list.append(t_val)
                friction_list.append(u_val)
            except ValueError:
                continue

    sample.time_ms = np.array(time_list, dtype=float)
    sample.friction = np.array(friction_list, dtype=float)
    sample.source_file = os.path.basename(filepath)
    return sample