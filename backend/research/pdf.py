"""One-click professional PDF research report.

Pages: executive summary (confidence stamp + measured headline numbers),
methodology (static, mirrors docs/VALIDATION.md), charts (equity +
drawdown, Monte Carlo fan, sensitivity heatmap), walk-forward table,
warnings + confidence rationale. The disclaimer prints on every page —
a report without it doesn't leave this module.
"""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from engine.validation.report import DISCLAIMER

INK = colors.HexColor("#0a0e14")
AMBER = colors.HexColor("#b97d20")
GAIN = colors.HexColor("#1f7a55")
LOSS = colors.HexColor("#b23a46")
MUTED = colors.HexColor("#6b7687")

CONFIDENCE_COLORS = {
    "strong": GAIN,
    "moderate": AMBER,
    "weak": LOSS,
    "insufficient": colors.HexColor("#7a2830"),
}

METHODOLOGY = (
    "Walk-forward optimization scores every candidate parameter set on each "
    "training window and evaluates the winner once on the following "
    "validation window; the final holdout is split off before any "
    "optimization and is evaluated exactly once, with the selected "
    "parameters. Sensitivity analysis prefers broad stable parameter "
    "regions over isolated peaks (robustness = geometric mean of neighbor "
    "consistency and plateau fraction). Monte Carlo resampling rebuilds "
    "additive equity paths from recorded trades (reshuffle, bootstrap, "
    "random skip) and re-runs the full engine under perturbed costs and "
    "delayed execution. Regime attribution is in-sample and descriptive. "
    "Warnings are heuristics with pinned thresholds; their absence is not "
    "evidence of edge."
)


def _fig_to_image(fig, width_mm: float = 170) -> Image:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor="white")
    plt.close(fig)
    buf.seek(0)
    img = Image(buf)
    scale = (width_mm * mm) / img.imageWidth
    img.drawWidth = width_mm * mm
    img.drawHeight = img.imageHeight * scale
    return img


def _equity_chart(exp: dict):
    equity = exp["development"]["equity"]
    drawdown = exp["development"]["drawdown"]
    xs = np.arange(len(equity))
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(9, 4.6), sharex=True,
        gridspec_kw={"height_ratios": [3, 1]},
    )
    ax1.plot(xs, [p[1] for p in equity], color="#1a4a8a", linewidth=1.2)
    ax1.set_title("Development equity (parameters selected on this range)",
                  fontsize=9, loc="left")
    ax1.grid(alpha=0.25, linewidth=0.4)
    dd = [p[1] if p[1] is not None else 0.0 for p in drawdown]
    ax2.fill_between(np.arange(len(dd)), dd, 0, color="#b23a46", alpha=0.55)
    ax2.set_title("Drawdown", fontsize=9, loc="left")
    ax2.grid(alpha=0.25, linewidth=0.4)
    for ax in (ax1, ax2):
        ax.tick_params(labelsize=7)
    return _fig_to_image(fig)


def _mc_chart(exp: dict):
    fan = exp.get("montecarlo", {}).get("fan")
    if not fan:
        return None
    xs = np.arange(fan["steps"])
    q = fan["quantiles"]
    fig, ax = plt.subplots(figsize=(9, 3.4))
    ax.fill_between(xs, q["0.05"], q["0.95"], color="#c9d6ea", label="5–95%")
    ax.fill_between(xs, q["0.25"], q["0.75"], color="#93aed1", label="25–75%")
    ax.plot(xs, q["0.5"], color="#1a4a8a", linewidth=1.4, label="median")
    ax.plot(xs, fan["worst_path"], color="#b23a46", linewidth=0.9,
            linestyle="--", label="worst path")
    ax.plot(xs, fan["best_path"], color="#1f7a55", linewidth=0.9,
            linestyle="--", label="best path")
    ax.set_title(
        f"Monte Carlo: {fan['n_paths']} reshuffled trade sequences "
        "(additive paths)", fontsize=9, loc="left")
    ax.legend(fontsize=7, ncols=5, frameon=False)
    ax.grid(alpha=0.25, linewidth=0.4)
    ax.tick_params(labelsize=7)
    return _fig_to_image(fig)


def _heatmap_chart(exp: dict):
    heat = exp.get("sensitivity", {}).get("heatmap")
    if not heat:
        return None
    xs, ys = heat["x_values"], heat["y_values"]
    grid = np.full((len(ys), len(xs)), np.nan)
    lookup = {(c["x"], c["y"]): c.get("sharpe") for c in heat["cells"]}
    for j, y in enumerate(ys):
        for i, x in enumerate(xs):
            v = lookup.get((x, y))
            grid[j, i] = np.nan if v is None else v
    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    im = ax.imshow(grid, cmap="RdYlGn", aspect="auto", origin="lower")
    ax.set_xticks(range(len(xs)), [str(v) for v in xs], fontsize=7)
    ax.set_yticks(range(len(ys)), [str(v) for v in ys], fontsize=7)
    ax.set_xlabel(heat["x"], fontsize=8)
    ax.set_ylabel(heat["y"], fontsize=8)
    for j in range(len(ys)):
        for i in range(len(xs)):
            if not np.isnan(grid[j, i]):
                ax.text(i, j, f"{grid[j, i]:.2f}", ha="center", va="center",
                        fontsize=7)
    ax.set_title(f"{heat['objective']} across the parameter grid",
                 fontsize=9, loc="left")
    fig.colorbar(im, ax=ax, shrink=0.8).ax.tick_params(labelsize=7)
    return _fig_to_image(fig, width_mm=140)


def _metric_table(title: str, metrics: dict, styles) -> list:
    rows = [[k, f"{v:.4f}" if isinstance(v, (int, float)) and v is not None else str(v)]
            for k, v in metrics.items() if v is not None]
    if not rows:
        return []
    table = Table([["metric", "value"], *rows], colWidths=[70 * mm, 50 * mm])
    table.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Courier", 8),
        ("FONT", (0, 0), (-1, 0), "Courier-Bold", 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("GRID", (0, 0), (-1, -1), 0.4, MUTED),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f4f8")]),
    ]))
    return [Paragraph(title, styles["h3"]), Spacer(1, 2 * mm), table, Spacer(1, 5 * mm)]


def build_pdf(exp: dict, target) -> None:
    """target: file path or binary buffer."""
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("h3x", parent=styles["Heading3"], textColor=INK))
    h1, h2, h3 = styles["Heading1"], styles["Heading2"], styles["Heading3"]
    body = ParagraphStyle("bodyx", parent=styles["BodyText"], fontSize=9, leading=12)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica-Oblique", 6.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(15 * mm, 10 * mm, DISCLAIMER[:150] + "…")
        canvas.drawRightString(195 * mm, 10 * mm, f"EdgeLab · {exp['id']} · p{doc.page}")
        canvas.restoreState()

    confidence = exp["confidence"]["level"]
    stamp = Table([[confidence.upper()]], colWidths=[45 * mm], rowHeights=[10 * mm])
    stamp.setStyle(TableStyle([
        ("FONT", (0, 0), (0, 0), "Courier-Bold", 12),
        ("TEXTCOLOR", (0, 0), (0, 0), colors.white),
        ("BACKGROUND", (0, 0), (0, 0), CONFIDENCE_COLORS.get(confidence, MUTED)),
        ("ALIGN", (0, 0), (0, 0), "CENTER"),
        ("VALIGN", (0, 0), (0, 0), "MIDDLE"),
    ]))

    dev = exp["development"]["metrics"]
    wf = exp["walkforward"]["aggregate"]
    story = [
        Paragraph(f"Research report — {exp['strategy']}", h1),
        Paragraph(
            f"Experiment {exp['id']} · engine {exp['engine_version']} · "
            f"{', '.join(exp['symbols'])} {exp['timeframe']} · "
            f"generated {exp['created_at'][:19]}Z", body),
        Spacer(1, 3 * mm),
        stamp,
        Spacer(1, 2 * mm),
        Paragraph("Confidence rationale: " +
                  "; ".join(exp["confidence"]["rationale"]), body),
        Spacer(1, 5 * mm),
        Paragraph("Executive summary", h2),
        Paragraph(exp.get("description") or "—", body),
        Paragraph(
            f"Dataset fingerprint <font face='Courier'>"
            f"{exp['dataset']['fingerprint']}</font>. "
            f"{exp['param_sets_tested']} parameter sets searched; selected "
            f"<font face='Courier'>{exp['selected_params']}</font> "
            f"(modal walk-forward winner).", body),
        Spacer(1, 3 * mm),
        *_metric_table("Development range (in-sample by construction)", {
            k: dev.get(k) for k in ("sharpe", "sortino", "max_drawdown",
                                    "profit_factor", "win_rate", "n_trades")
        }, {"h3": h3}),
        *_metric_table("Walk-forward validation (out-of-sample folds)", {
            "folds": wf.get("n_folds"),
            "sharpe_mean": wf.get("sharpe_mean"),
            "sharpe_min": wf.get("sharpe_min"),
            "fraction_positive": wf.get("fraction_positive_objective"),
        }, {"h3": h3}),
        *_metric_table("Final holdout (single permitted evaluation)", {
            k: exp["final_test"].get(k) for k in ("sharpe", "max_drawdown",
                                                  "profit_factor", "n_trades")
        }, {"h3": h3}),
        PageBreak(),
        Paragraph("Methodology", h2),
        Paragraph(METHODOLOGY, body),
        Spacer(1, 4 * mm),
        Paragraph("Charts", h2),
        _equity_chart(exp),
        Spacer(1, 3 * mm),
    ]
    mc_img = _mc_chart(exp)
    if mc_img is not None:
        story += [mc_img, Spacer(1, 3 * mm)]
    heat_img = _heatmap_chart(exp)
    if heat_img is not None:
        story += [heat_img]
    story += [PageBreak(), Paragraph("Warnings", h2)]
    if exp["warnings"]:
        for w in exp["warnings"]:
            story.append(Paragraph(
                f"<b>[{w['severity']}] {w['code']}</b> — {w['message']}", body))
    else:
        story.append(Paragraph(
            "None raised. Absence of warnings is not evidence of edge.", body))
    story += [
        Spacer(1, 4 * mm),
        Paragraph("Monte Carlo probability of ruin (reshuffled paths)", h3),
    ]
    ruin = exp.get("montecarlo", {}).get("fan", {}).get("prob_ruin", {})
    if ruin:
        story += _metric_table("P(max drawdown exceeds threshold)", {
            f"dd ≥ {float(k):.0%}": v for k, v in ruin.items()
        }, {"h3": h3})
    story += [
        Spacer(1, 4 * mm),
        Paragraph("Disclaimer", h2),
        Paragraph(DISCLAIMER, body),
    ]

    doc = SimpleDocTemplate(target, pagesize=A4, topMargin=16 * mm,
                            bottomMargin=18 * mm)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
