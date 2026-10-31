"""PDF rendering for Phase 10. A PURE function: it takes the same
``AnalysisPublic`` the dashboard shows (so every number matches the screen) and
returns PDF bytes. No database, storage or network access.

Security note: ReportLab ``Paragraph`` text is mini-HTML and can load images
from file paths (``<img src=...>``). Column names, categories and AI text are
user- or model-controlled, so EVERY such string goes through ``_t`` (control
characters removed, length bounded, XML-escaped) before it becomes markup.
"""

from __future__ import annotations

import io
import re
import unicodedata
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.lineplots import LinePlot, ScatterPlot
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.widgets.markers import makeMarker
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.schemas.ai import AI_DISCLAIMER, AIInsightPublic
from app.schemas.analysis import AnalysisPublic, ChartRecommendation

FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
MAX_CHARTS = 8
MAX_STAT_ROWS = 40
MAX_PAIRS = 12
MAX_OUTLIER_ROWS = 30
MAX_POINTS = 400
NAME_MAX = 60
TEXT_MAX = 1500
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
INK = colors.HexColor("#1f2937")
MUTED = colors.HexColor("#6b7280")
ACCENT = colors.HexColor("#2563eb")
RULE = colors.HexColor("#d1d5db")
HEAD_BG = colors.HexColor("#eef2ff")


@lru_cache(maxsize=1)
def _fonts() -> tuple[str, str, bool]:
    """(regular, bold, is_unicode). Falls back to Helvetica (Latin-1 only)."""
    try:
        pdfmetrics.registerFont(TTFont("ReportSans", str(FONT_DIR / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("ReportSans-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
        pdfmetrics.registerFontFamily(
            "ReportSans", normal="ReportSans", bold="ReportSans-Bold", italic="ReportSans"
        )
        return "ReportSans", "ReportSans-Bold", True
    except Exception:  # missing/corrupt font file: still produce a readable PDF
        return "Helvetica", "Helvetica-Bold", False


@lru_cache(maxsize=1)
def _glyphs() -> frozenset[int]:
    face = pdfmetrics.getFont(_fonts()[0]).face
    return frozenset(face.charToGlyph)


def _t(value: object, *, limit: int = TEXT_MAX) -> str:
    """Safe paragraph text for an untrusted string."""
    text = unicodedata.normalize("NFC", str(value))
    text = _CONTROL.sub(" ", text)
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    if _fonts()[2]:
        # Characters the bundled font lacks (e.g. CJK) would draw as blank boxes.
        have = _glyphs()
        text = "".join(ch if ord(ch) in have else "?" for ch in text)
    else:
        text = text.encode("latin-1", "replace").decode("latin-1")
    return escape(text)


def _name(value: object) -> str:
    return _t(value, limit=NAME_MAX)


def _num(value: float | int | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if value != value or value in (float("inf"), float("-inf")):
        return "—"
    if value == 0:
        return "0"
    if abs(value) >= 1_000_000 or abs(value) < 0.01:
        return f"{value:.4g}"
    return f"{value:,.2f}"


def _styles() -> dict[str, ParagraphStyle]:
    regular, bold, _ = _fonts()
    base = ParagraphStyle("base", fontName=regular, fontSize=9, leading=12.5, textColor=INK)
    return {
        "base": base,
        "title": ParagraphStyle("title", parent=base, fontName=bold, fontSize=20, leading=25),
        "h1": ParagraphStyle(
            "h1",
            parent=base,
            fontName=bold,
            fontSize=13,
            leading=17,
            spaceBefore=14,
            spaceAfter=5,
            textColor=ACCENT,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base, fontName=bold, fontSize=10, leading=14, spaceBefore=6
        ),
        "small": ParagraphStyle("small", parent=base, fontSize=8, leading=10.5, textColor=MUTED),
        "cell": ParagraphStyle("cell", parent=base, fontSize=8, leading=10),
        "cellb": ParagraphStyle("cellb", parent=base, fontName=bold, fontSize=8, leading=10),
        "bullet": ParagraphStyle("bullet", parent=base, leftIndent=10, bulletIndent=0),
        "note": ParagraphStyle(
            "note",
            parent=base,
            fontSize=8.5,
            leading=11.5,
            backColor=colors.HexColor("#fff7ed"),
            borderColor=colors.HexColor("#fdba74"),
            borderWidth=0.6,
            borderPadding=5,
            spaceBefore=4,
            spaceAfter=8,
        ),
    }


def _table(
    header: list[str], rows: list[list[str]], widths: list[float], st: dict[str, ParagraphStyle]
) -> Table:
    data: list[list[Any]] = [[Paragraph(h, st["cellb"]) for h in header]]
    data += [[Paragraph(c, st["cell"]) for c in row] for row in rows]
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ]
        )
    )
    return table


# --- charts ---------------------------------------------------------------


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _bars(labels: list[str], values: list[float]) -> Drawing:
    regular = _fonts()[0]
    drawing = Drawing(480, 180)
    chart = VerticalBarChart()
    chart.x, chart.y, chart.width, chart.height = 45, 38, 410, 125
    chart.data = [values]
    chart.categoryAxis.categoryNames = labels
    chart.categoryAxis.labels.fontName = regular
    chart.categoryAxis.labels.fontSize = 6.5
    chart.categoryAxis.labels.angle = 30
    chart.categoryAxis.labels.boxAnchor = "ne"
    chart.categoryAxis.labels.dy = -2
    chart.valueAxis.labels.fontName = regular
    chart.valueAxis.labels.fontSize = 7
    chart.valueAxis.labelTextFormat = "%.4g"
    chart.bars[0].fillColor = ACCENT
    chart.barWidth = 6
    drawing.add(chart)
    return drawing


def _xy(points: list[tuple[float, float]], *, scatter: bool) -> Drawing:
    regular = _fonts()[0]
    drawing = Drawing(480, 180)
    plot: LinePlot = ScatterPlot() if scatter else LinePlot()
    plot.x, plot.y, plot.width, plot.height = 45, 25, 410, 135
    plot.data = [points]
    plot.xValueAxis.labels.fontName = regular
    plot.yValueAxis.labels.fontName = regular
    plot.xValueAxis.labels.fontSize = plot.yValueAxis.labels.fontSize = 7
    plot.xValueAxis.labelTextFormat = plot.yValueAxis.labelTextFormat = "%.4g"
    if scatter:
        plot.lines[0].strokeColor = None
        plot.lines[0].symbol = makeMarker("FilledCircle")
        plot.lines[0].symbol.size = 2.6
        plot.lines[0].symbol.fillColor = ACCENT
        plot.lines[0].symbol.strokeColor = None
    else:
        plot.lines[0].strokeColor = ACCENT
        plot.lines[0].strokeWidth = 1.2
    drawing.add(plot)
    return drawing


def _chart_drawing(chart: ChartRecommendation) -> Drawing | None:
    rows = [r for r in chart.data if isinstance(r, dict)]
    kind = chart.chart_type
    if kind == "histogram":
        pairs = [(_finite(r.get("bin_start")), _finite(r.get("count"))) for r in rows]
        used = [(a, c) for a, c in pairs if a is not None and c is not None]
        return _bars([f"{a:.3g}" for a, _ in used], [c for _, c in used]) if used else None
    if kind in ("count", "bar"):
        value_key = "count" if kind == "count" else "y"
        cats: list[tuple[str, float]] = []
        for r in rows[:15]:
            v = _finite(r.get(value_key))
            if v is not None:
                cats.append((_t(r.get("x", ""), limit=14), v))
        return _bars([a for a, _ in cats], [v for _, v in cats]) if cats else None
    if kind == "scatter":
        pts = [(_finite(r.get("x")), _finite(r.get("y"))) for r in rows][:MAX_POINTS]
        clean = [(x, y) for x, y in pts if x is not None and y is not None]
        return _xy(clean, scatter=True) if clean else None
    if kind == "line":
        ys = [_finite(r.get("y")) for r in rows][:MAX_POINTS]
        line = [(float(i), y) for i, y in enumerate(ys) if y is not None]
        return _xy(line, scatter=False) if len(line) > 1 else None
    return None


# --- document ---------------------------------------------------------------


def _footer(canvas: Any, doc: Any) -> None:
    regular = _fonts()[0]
    canvas.saveState()
    canvas.setFont(regular, 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 10 * mm, "StatFlow AI — automatically generated report")
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build_report_pdf(
    *,
    project_name: str,
    file_name: str | None,
    analysis: AnalysisPublic,
    ai: AIInsightPublic | None,
    generated_at: datetime,
) -> bytes:
    st = _styles()
    width = A4[0] - 36 * mm
    story: list[Flowable] = []

    story.append(Paragraph(_name(project_name) or "Untitled project", st["title"]))
    meta = f"Generated {generated_at:%Y-%m-%d %H:%M} UTC"
    if file_name:
        meta += f" · Dataset file: {_name(file_name)}"
    story.append(Paragraph(meta, st["small"]))
    story.append(
        Paragraph(
            "Every number in this report is the stored result of the analysis shown in the "
            "dashboard. Statistics describe this dataset only and do not prove cause.",
            st["note"],
        )
    )

    profile = analysis.profile
    cleaning = analysis.cleaning
    story.append(Paragraph("1. Dataset and cleaning", st["h1"]))
    if profile is not None:
        story.append(
            _table(
                [
                    "Rows",
                    "Columns",
                    "Numeric",
                    "Categorical",
                    "Date",
                    "Missing values",
                    "Duplicate rows",
                ],
                [
                    [
                        _num(profile.row_count),
                        _num(profile.column_count),
                        _num(profile.numeric_column_count),
                        _num(profile.categorical_column_count),
                        _num(profile.date_column_count),
                        _num(profile.total_missing_values),
                        _num(profile.duplicate_row_count),
                    ]
                ],
                [width / 7] * 7,
                st,
            )
        )
    if cleaning is not None:
        story.append(Spacer(1, 6))
        story.append(
            Paragraph(
                f"Cleaning settings: {', '.join(f'{_t(k)} = {_t(v)}' for k, v in sorted(cleaning.config.items()))}. "
                f"Rows {_num(cleaning.rows_before)} → {_num(cleaning.rows_after)} "
                f"({_num(cleaning.rows_removed)} removed). Missing values "
                f"{_num(cleaning.missing_before)} → {_num(cleaning.missing_after)} "
                f"({_num(cleaning.missing_values_imputed)} filled). Duplicate rows "
                f"{_num(cleaning.duplicates_before)} → {_num(cleaning.duplicates_after)}.",
                st["base"],
            )
        )
        acted = [a for a in cleaning.column_actions if a.missing_before or a.values_changed][:20]
        if acted:
            story.append(Spacer(1, 4))
            story.append(
                _table(
                    ["Column", "Action", "Method", "Missing before → after", "Values changed"],
                    [
                        [
                            _name(a.column),
                            _t(a.action),
                            _t(a.method or a.reason or "—", limit=60),
                            f"{_num(a.missing_before)} → {_num(a.missing_after)}",
                            _num(a.values_changed),
                        ]
                        for a in acted
                    ],
                    [width * 0.28, width * 0.14, width * 0.28, width * 0.18, width * 0.12],
                    st,
                )
            )

    if analysis.statistics is not None and analysis.statistics.columns:
        story.append(Paragraph("2. Descriptive statistics (numeric columns)", st["h1"]))
        shown = analysis.statistics.columns[:MAX_STAT_ROWS]
        story.append(
            _table(
                ["Column", "Count", "Missing", "Mean", "Median", "Std dev", "Min", "Max"],
                [
                    [
                        _name(c.column),
                        _num(c.count),
                        _num(c.missing_count),
                        _num(c.mean),
                        _num(c.median),
                        _num(c.std),
                        _num(c.min),
                        _num(c.max),
                    ]
                    for c in shown
                ],
                [width * 0.24] + [width * 0.76 / 7] * 7,
                st,
            )
        )
        if len(analysis.statistics.columns) > len(shown):
            story.append(
                Paragraph(
                    f"Showing {len(shown)} of {len(analysis.statistics.columns)} columns.",
                    st["small"],
                )
            )
        if analysis.statistics.skipped_columns:
            skipped = ", ".join(_name(c) for c in analysis.statistics.skipped_columns[:15])
            story.append(Paragraph(f"Not numeric, so not summarised: {skipped}.", st["small"]))

    corr = analysis.correlations
    if corr is not None:
        story.append(Paragraph("3. Correlations", st["h1"]))
        if not corr.available or not corr.pairs:
            story.append(
                Paragraph(
                    _t(corr.reason or "Correlations are not available for this dataset."),
                    st["base"],
                )
            )
        else:
            ranked = sorted(corr.pairs, key=lambda p: abs(p.correlation), reverse=True)[:MAX_PAIRS]
            story.append(
                _table(
                    ["Column A", "Column B", "Correlation (r)", "Strength", "Direction"],
                    [
                        [
                            _name(p.column_a),
                            _name(p.column_b),
                            f"{p.correlation:.3f}",
                            _t(p.strength),
                            _t(p.direction),
                        ]
                        for p in ranked
                    ],
                    [width * 0.27, width * 0.27, width * 0.16, width * 0.15, width * 0.15],
                    st,
                )
            )
            story.append(
                Paragraph(
                    "Correlation measures linear association only. It does not show that one column causes another.",
                    st["small"],
                )
            )

    outliers = analysis.outliers
    if outliers is not None:
        story.append(Paragraph("4. Outliers", st["h1"]))
        story.append(
            Paragraph(
                f"Method: IQR rule with multiplier {_num(outliers.iqr_multiplier)}. "
                f"{_num(outliers.total_outlier_count)} flagged value(s) in {_num(outliers.columns_with_outliers)} column(s). "
                "A flagged value is unusual, not necessarily wrong.",
                st["base"],
            )
        )
        flagged = [c for c in outliers.columns if c.outlier_count > 0][:MAX_OUTLIER_ROWS]
        if flagged:
            story.append(Spacer(1, 4))
            story.append(
                _table(
                    ["Column", "Outliers", "Share of values", "Lower bound", "Upper bound"],
                    [
                        [
                            _name(c.column),
                            _num(c.outlier_count),
                            f"{c.outlier_percentage:.2f}%",
                            _num(c.lower_bound),
                            _num(c.upper_bound),
                        ]
                        for c in flagged
                    ],
                    [width * 0.3, width * 0.15, width * 0.2, width * 0.175, width * 0.175],
                    st,
                )
            )

    reg = analysis.regression
    if reg is not None and reg.available and reg.model is not None:
        story.append(Paragraph("5. Regression", st["h1"]))
        story.append(
            Paragraph(
                f"Linear regression (ordinary least squares) of {_name(reg.model.target)} on "
                f"{', '.join(_name(p) for p in reg.model.predictors)}. "
                f"{_num(reg.model.observations_used)} of {_num(reg.model.observations_total)} rows used; "
                f"{_num(reg.model.train_observations)} for fitting and {_num(reg.model.test_observations)} held out for testing.",
                st["base"],
            )
        )
        if reg.metrics is not None:
            m = reg.metrics
            story.append(Spacer(1, 4))
            story.append(
                _table(
                    ["R²", "Adjusted R²", "MAE", "RMSE", "F-statistic", "F p-value"],
                    [
                        [
                            _num(m.r_squared),
                            _num(m.adjusted_r_squared),
                            _num(m.mae),
                            _num(m.rmse),
                            _num(m.f_statistic),
                            _num(m.f_p_value),
                        ]
                    ],
                    [width / 6] * 6,
                    st,
                )
            )
        if reg.coefficients:
            story.append(Spacer(1, 6))
            story.append(
                _table(
                    ["Term", "Coefficient", "Std error", "p-value", "95% interval"],
                    [
                        [
                            _name(c.name),
                            _num(c.coefficient),
                            _num(c.std_error),
                            _num(c.p_value),
                            f"{_num(c.conf_int_lower)} to {_num(c.conf_int_upper)}",
                        ]
                        for c in reg.coefficients[:30]
                    ],
                    [width * 0.28, width * 0.17, width * 0.15, width * 0.15, width * 0.25],
                    st,
                )
            )
        story.append(
            Paragraph(
                "Coefficients describe association in this dataset; they are not proof of cause or of future accuracy.",
                st["small"],
            )
        )

    charts = analysis.visualizations.charts[:MAX_CHARTS] if analysis.visualizations else []
    drawn = [(c, _chart_drawing(c)) for c in charts]
    drawn = [(c, d) for c, d in drawn if d is not None]
    if drawn:
        story.append(Paragraph("6. Charts", st["h1"]))
        for chart, drawing in drawn:
            block: list[Flowable] = [
                Paragraph(_t(chart.title, limit=120), st["h2"]),
                drawing,
                Paragraph(_t(chart.reason, limit=300), st["small"]),
            ]
            if chart.sampling is not None:
                block.append(
                    Paragraph(
                        f"Showing {_num(chart.sampling.displayed_points)} of {_num(chart.sampling.total_points)} points for display; statistics use every row.",
                        st["small"],
                    )
                )
            story.append(KeepTogether(block))
            story.append(Spacer(1, 6))

    if ai is not None:
        story.append(Paragraph("7. AI-generated explanation", st["h1"]))
        story.append(Paragraph(_t(AI_DISCLAIMER), st["note"]))
        for code in ai.evidence_warnings:
            if code == "small_sample":
                story.append(
                    Paragraph(
                        "Small sample: with fewer than 30 rows, treat any pattern as a hint to check, not a conclusion.",
                        st["note"],
                    )
                )
        story.append(Paragraph(_t(ai.summary), st["base"]))
        for title, items in (
            ("Key findings", ai.key_findings),
            ("Data quality", ai.data_quality),
            ("Limitations", ai.limitations),
            ("Things to check next", ai.next_steps),
        ):
            if items:
                story.append(Paragraph(title, st["h2"]))
                story.extend(Paragraph(_t(item), st["bullet"], bulletText="•") for item in items)
        story.append(Spacer(1, 4))
        story.append(
            Paragraph(
                f"Generated {ai.generated_at:%Y-%m-%d %H:%M} UTC by {_t(ai.model, limit=80)}.",
                st["small"],
            )
        )

    buffer = io.BytesIO()
    doc = BaseDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title=_t(project_name, limit=100) or "Report",
        author="StatFlow AI",
        creator="StatFlow AI",
        invariant=1,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")
    doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=_footer)])
    doc.build(story)
    return buffer.getvalue()
