from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw

COREG_DIR = Path(__file__).resolve().parent
SHIFTS_CSV = COREG_DIR / "shifts.csv"
PLOTS_DIR = COREG_DIR / "plots"
REPORT_MD = COREG_DIR / "report.md"


def numeric_stats(frame: pd.DataFrame, column: str) -> dict[str, float]:
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    if values.empty:
        return {name: float("nan") for name in ("median", "mean", "std", "min", "max")}
    return {
        "median": float(values.median()),
        "mean": float(values.mean()),
        "std": float(values.std()),
        "min": float(values.min()),
        "max": float(values.max()),
    }


def pil_hist(values: pd.Series, title: str, output: Path) -> None:
    values = pd.to_numeric(values, errors="coerce").dropna()
    image = Image.new("RGB", (900, 400), "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 10), title, fill="black")
    if values.empty:
        image.save(output)
        return
    minimum, maximum = float(values.min()), float(values.max())
    if maximum == minimum:
        maximum = minimum + 1.0
    counts, edges = __import__("numpy").histogram(values, bins=30, range=(minimum, maximum))
    left, top, right, bottom = 60, 40, 880, 350
    max_count = max(int(counts.max()), 1)
    draw.line((left, bottom, right, bottom), fill="black")
    draw.line((left, top, left, bottom), fill="black")
    bar_width = (right - left) / len(counts)
    for index, count in enumerate(counts):
        x0 = left + index * bar_width
        h = (count / max_count) * (bottom - top)
        draw.rectangle((x0, bottom - h, x0 + bar_width - 1, bottom), fill="#4C78A8")
    image.save(output)


def pil_scatter(frame: pd.DataFrame, output: Path) -> None:
    dx = pd.to_numeric(frame["dx_m"], errors="coerce").to_numpy()
    dy = pd.to_numeric(frame["dy_m"], errors="coerce").to_numpy()
    status = frame["status"].fillna("").to_numpy()
    image = Image.new("RGB", (700, 700), "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 10), "dx_m / dy_m", fill="black")
    finite = __import__("numpy").isfinite(dx) & __import__("numpy").isfinite(dy)
    dx, dy, status = dx[finite], dy[finite], status[finite]
    if dx.size:
        minimum = min(float(dx.min()), float(dy.min()), -30.0)
        maximum = max(float(dx.max()), float(dy.max()), 30.0)
        if maximum == minimum:
            maximum = minimum + 1.0
        def point(value_x: float, value_y: float) -> tuple[int, int]:
            px = int(60 + (value_x - minimum) / (maximum - minimum) * 580)
            py = int(620 - (value_y - minimum) / (maximum - minimum) * 580)
            return px, py
        cx, cy = point(0.0, 0.0)
        draw.line((60, cy, 640, cy), fill="#BBBBBB")
        draw.line((cx, 40, cx, 620), fill="#BBBBBB")
        for value_x, value_y, state in zip(dx, dy, status):
            px, py = point(float(value_x), float(value_y))
            color = "#54A24B" if state == "ok" else "#E45756"
            draw.ellipse((px - 4, py - 4, px + 4, py + 4), fill=color)
    image.save(output)


def pil_status(frame: pd.DataFrame, output: Path) -> None:
    status = frame["status"].fillna("nieznany").value_counts()
    image = Image.new("RGB", (700, 400), "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 10), "Status koregistracji", fill="black")
    if status.empty:
        draw.text((80, 80), "Brak wyników", fill="black")
        image.save(output)
        return
    left, top, bottom = 80, 40, 330
    max_count = max(int(status.max()), 1)
    colors = ["#54A24B", "#E45756"]
    bar_width = 180
    for index, (label, count) in enumerate(status.items()):
        x = left + index * 220
        height = 250 * int(count) / max_count
        draw.rectangle((x, bottom - height, x + bar_width, bottom), fill=colors[index % len(colors)])
        draw.text((x, bottom + 10), f"{label}: {int(count)}", fill="black")
    image.save(output)


def generate_report(shifts_csv: Path = SHIFTS_CSV) -> Path:
    if not shifts_csv.exists():
        raise FileNotFoundError(f"Missing shifts table: {shifts_csv}")
    frame = pd.read_csv(shifts_csv)
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    pil_hist(frame["dx_m"], "Histogram dx_m [m]", PLOTS_DIR / "shift_dx_histogram.png")
    pil_hist(frame["dy_m"], "Histogram dy_m [m]", PLOTS_DIR / "shift_dy_histogram.png")
    pil_scatter(frame, PLOTS_DIR / "shift_scatter.png")
    pil_status(frame, PLOTS_DIR / "status_summary.png")

    dx = numeric_stats(frame, "dx_m")
    dy = numeric_stats(frame, "dy_m")
    failed = frame[frame["status"] == "porażka"]
    local_path = COREG_DIR / "local_check.csv"
    local_text = "Brak wykonanych testów lokalnych."
    if local_path.exists():
        local = pd.read_csv(local_path)
        spreads = pd.to_numeric(local["spread_px"], errors="coerce").dropna()
        if not spreads.empty:
            local_text = (
                f"Wykonano {len(local)} oceny okien w {local['n_windows'].sum()} oknach "
                f"(mediana rozstępu: {spreads.median():.3f} px, maks.: {spreads.max():.3f} px)."
            )

    lines = [
        "# Raport koregistracji",
        "",
        "## Przesunięcia",
        "",
        f"- Liczba scen: **{len(frame)}**",
        f"- Sukcesy: **{int((frame['status'] == 'ok').sum())}**",
        f"- Porażki: **{len(failed)}**",
        "",
        "| Oś | mediana [m] | średnia [m] | std [m] | min [m] | max [m] |",
        "|---|---:|---:|---:|---:|---:|",
        f"| dx | {dx['median']:.3f} | {dx['mean']:.3f} | {dx['std']:.3f} | {dx['min']:.3f} | {dx['max']:.3f} |",
        f"| dy | {dy['median']:.3f} | {dy['mean']:.3f} | {dy['std']:.3f} | {dy['min']:.3f} | {dy['max']:.3f} |",
        "",
        "## Wyniki testu lokalnego",
        "",
        local_text,
        "",
        "## Porażki i przyczyny",
        "",
    ]
    if failed.empty:
        lines.append("Brak zarejestrowanych porażek.")
    else:
        for reason, count in failed["uwagi"].fillna("brak opisu").value_counts().items():
            lines.append(f"- {reason}: **{count}**")

    enmap = frame[frame["sensor"].fillna("").str.startswith("EnMAP")]
    lines += [
        "",
        "## Wnioski dla EnMAP",
        "",
        f"- Liczba wyników EnMAP: **{len(enmap)}**.",
        "- Geometrię i deklarowaną dokładność należy dopasowywać do pól XML każdej sceny.",
        "- Wynik nocny powinien być interpretowany osobno dla pasa SWIR i stałych źródeł światła.",
    ]
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return REPORT_MD


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate co-registration plots and Markdown report")
    parser.add_argument("--shifts", type=Path, default=SHIFTS_CSV)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    report = generate_report(args.shifts)
    print(report)


if __name__ == "__main__":
    main()
