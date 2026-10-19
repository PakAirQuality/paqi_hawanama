"""Assemble the 4-city PM2.5 network comparison into a single PDF document.

Reads the figures and stats already produced by:
  scripts/compare_aqms_lcs_consulate.py  (CSVs)
  scripts/combined_panel.py              (combined_<city>.png)
  scripts/monthly_stats.py               (monthly_stats_<city>.png + monthly_stats.csv)

Writes:
  reports/pm25_network_comparison.pdf

The PDF mixes orientations — text-heavy pages portrait, combined-panel figure
pages landscape — so the wide time-series + scatter grid stays legible.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Optional

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate, Frame, Image, NextPageTemplate, PageBreak,
    PageTemplate, Paragraph, Spacer, Table, TableStyle,
)
from PIL import Image as PILImage

REPO = Path("/Users/rehanahmad/Desktop/hawanama-main")
DATA = REPO / "data"
PLOTS = REPO / "plots"
REPORTS = REPO / "reports"
REPORTS.mkdir(exist_ok=True)
OUT_PDF = REPORTS / "pm25_network_comparison.pdf"

WINDOW_START = "2024-05-13"
WINDOW_END   = "2026-05-13"
GENERATED = dt.date.today().isoformat()


# ─── City sections ──────────────────────────────────────────────────────────

CITY_SECTIONS = [
    {
        "slug": "lahore", "display": "Lahore",
        "blurb": (
            "Lahore is the only city in this study where all four networks are deployed within "
            "the city boundary. Regulatory Monitors (Punjab AQMS) and AirGradient both came "
            "online in mid-to-late 2025, while AirNow consulate data only covers May 2024 – "
            "Feb 2025. PAQI / IQAir is the longest-running network here."
        ),
        "findings": (
            "PAQI / IQAir tracks Regulatory Monitors strongly (R² ≥ 0.74 in every month with "
            "≥20 days of overlap, peaking at 0.98 in Oct 2025). The OLS slope of 0.66 indicates "
            "PAQI under-reads by ~34% at high concentrations — a classic winter humidity bias "
            "signature visible in the Dec 2024 / Jan 2025 MAE values of 76 – 87 µg/m³. "
            "AirGradient unexpectedly under-performs PAQI here (Nov 2025 R²=0.55 vs PAQI 0.81), "
            "suggesting either uncorrected raw output or different siting; worth investigating."
        ),
    },
    {
        "slug": "islamabad", "display": "Islamabad",
        "blurb": (
            "The Punjab EPA has no monitor inside Islamabad (ICT), so the Regulatory Monitors "
            "line uses three Rawalpindi stations 7–22 km from the US Embassy, treating the "
            "Rawalpindi-Islamabad twin-city region as one airshed. Islamabad is the only city "
            "with AirGradient–AirNow temporal overlap (221 days)."
        ),
        "findings": (
            "Both candidate networks correlate strongly with AirNow (PAQI R² ≥ 0.80 for 9 of 11 "
            "months; AirGradient R² ≥ 0.85 for most months in late 2025 / early 2026). Against "
            "Rawalpindi Regulatory Monitors the slopes are closer to 1:1, consistent with the "
            "lower baseline pollution here vs Lahore. MAE values stay below 12 µg/m³ for most "
            "of the period, reflecting good agreement at these moderate concentrations."
        ),
    },
    {
        "slug": "karachi", "display": "Karachi",
        "blurb": (
            "No Punjab AQMS coverage (different province). PAQI / IQAir is dense in Karachi; "
            "AirGradient was deployed mid-2025. AirNow consulate data ended 2025-03-04, before "
            "any AirGradient sensor came online — so the AirGradient–AirNow scatter has zero "
            "overlap days."
        ),
        "findings": (
            "PAQI / IQAir vs AirNow shows the cleanest performance of any city: R² ≥ 0.80 for 6 "
            "of 10 months with MAE typically 2–6 µg/m³. The two outlier months are May 2024 "
            "(R²=0.40, first month of deployment) and Jan-Feb 2025 (R²=0.75-0.86 but MAE jumps "
            "to 12–17 µg/m³ during winter pollution episodes)."
        ),
    },
    {
        "slug": "peshawar", "display": "Peshawar",
        "blurb": (
            "Same coverage profile as Karachi — no Punjab AQMS, only PAQI / IQAir vs AirNow can "
            "be compared. AirNow consulate data ran May 2024 – Mar 2025."
        ),
        "findings": (
            "Weaker performance than Karachi: PAQI / IQAir vs AirNow R² is 0.46–0.91 across 11 "
            "months, with the worst correlation in Mar 2025 (R²=0.15) when the consulate monitor "
            "was likely on its way out. Winter MAE spikes to 36 – 41 µg/m³ during Nov-Dec 2024 — "
            "consistent with the LCS humidity-bias pattern seen in Lahore."
        ),
    },
]


# ─── Page templates ─────────────────────────────────────────────────────────

PAGE_WIDTH_P, PAGE_HEIGHT_P = A4
PAGE_WIDTH_L, PAGE_HEIGHT_L = landscape(A4)
MARGIN = 1.5 * cm

styles = getSampleStyleSheet()
title_style    = ParagraphStyle("Title", parent=styles["Title"], fontSize=24, leading=28, alignment=1)
subtitle_style = ParagraphStyle("Subtitle", parent=styles["Heading2"], fontSize=14, leading=18, alignment=1, textColor=colors.HexColor("#555555"))
h1_style       = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=18, leading=22, spaceAfter=8, textColor=colors.HexColor("#1f3a93"))
h2_style       = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=13, leading=17, spaceAfter=6, textColor=colors.HexColor("#222"))
body_style     = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=10, leading=14, spaceAfter=6, alignment=4)
caption_style  = ParagraphStyle("Caption", parent=styles["BodyText"], fontSize=8.5, leading=11, textColor=colors.HexColor("#666"), alignment=1, spaceBefore=2)


def _page_decorator(canvas, doc, page_w=PAGE_WIDTH_P, page_h=PAGE_HEIGHT_P):
    canvas.saveState()
    # Header
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#888"))
    if doc.page > 1:
        canvas.drawString(MARGIN, page_h - 0.8 * cm,
                          f"PM2.5 Network Comparison — Pakistan · {WINDOW_START} → {WINDOW_END}")
    # Footer
    canvas.drawCentredString(page_w / 2, 0.7 * cm, f"Generated {GENERATED}")
    canvas.drawRightString(page_w - MARGIN, 0.7 * cm, f"Page {doc.page}")
    canvas.restoreState()


def _portrait_decorator(canvas, doc):  _page_decorator(canvas, doc, PAGE_WIDTH_P, PAGE_HEIGHT_P)
def _landscape_decorator(canvas, doc): _page_decorator(canvas, doc, PAGE_WIDTH_L, PAGE_HEIGHT_L)


# ─── Helpers ────────────────────────────────────────────────────────────────

def scaled_image(path: Path, max_w_cm: float, max_h_cm: Optional[float] = None) -> Image:
    """Return a reportlab Image scaled proportionally to fit a max width/height."""
    with PILImage.open(path) as im:
        px_w, px_h = im.size
    aspect = px_h / px_w
    max_w = max_w_cm * cm
    w = max_w
    h = w * aspect
    if max_h_cm is not None and h > max_h_cm * cm:
        h = max_h_cm * cm
        w = h / aspect
    return Image(str(path), width=w, height=h)


def fmt_para(text: str, style=body_style) -> Paragraph:
    return Paragraph(text, style)


# ─── Story builders ─────────────────────────────────────────────────────────

def build_title_page() -> list:
    return [
        Spacer(1, 5 * cm),
        fmt_para("PM2.5 Network Comparison", title_style),
        Spacer(1, 0.5 * cm),
        fmt_para("Pakistan · 24-month study", subtitle_style),
        Spacer(1, 0.3 * cm),
        fmt_para(f"{WINDOW_START} &nbsp;→&nbsp; {WINDOW_END}", subtitle_style),
        Spacer(1, 4 * cm),
        fmt_para(
            "Four PM2.5 networks compared at city scale: Regulatory Monitors "
            "(Punjab EPA), PAQI / IQAir, AirGradient, and AirNow (US Consulate). "
            "Daily-mean correlation, mean absolute error, and root-mean-square error "
            "are reported per month for each candidate-vs-reference pairing.",
            body_style,
        ),
        Spacer(1, 6 * cm),
        fmt_para(f"Report generated {GENERATED}", caption_style),
    ]


def build_executive_summary() -> list:
    bullets = []
    for c in CITY_SECTIONS:
        bullets.append(fmt_para(f"<b>{c['display']}</b>. {c['blurb']}", body_style))
    return [
        fmt_para("Executive summary", h1_style),
        fmt_para(
            "This report compares low-cost sensor networks (PAQI / IQAir and AirGradient) "
            "against two reference-grade networks (Regulatory Monitors and AirNow) at four "
            "Pakistani cities. Per-city availability differs because each network has its own "
            "deployment history, and the US Consulate AirNow monitors at Karachi, Lahore, and "
            "Peshawar all stopped reporting in early 2025.",
            body_style,
        ),
        Spacer(1, 0.4 * cm),
        *bullets,
    ]


def build_methodology() -> list:
    return [
        fmt_para("Methodology", h1_style),
        fmt_para("Data sources", h2_style),
        fmt_para(
            "<b>Regulatory Monitors</b> — Punjab EPA's AQMS network (provider code <font face='Courier'>punjab</font>). "
            "Reference-grade fixed monitors operated by the provincial authority; "
            "available in Punjab cities only. For Islamabad we use three nearby Rawalpindi "
            "stations as a twin-city airshed proxy (7–22 km from the US Embassy).",
            body_style,
        ),
        fmt_para(
            "<b>PAQI / IQAir</b> — IQAir AirVisual Outdoor community sensors enrolled in the "
            "Pakistan Air Quality Initiative network (provider display name <font face='Courier'>Airvisual/PAQI</font>). "
            "Low-cost optical sensors (~$300 each), the same 267 stations that are exported to "
            "OpenAQ as the PAQI network.",
            body_style,
        ),
        fmt_para(
            "<b>AirGradient</b> — 91 AirGradient open-hardware sensors tagged via "
            "<font face='Courier'>stations.monitor_type='AirGradient'</font>. Deployments started Feb 2025 "
            "and are continuing.",
            body_style,
        ),
        fmt_para(
            "<b>AirNow</b> — US Department of State PM2.5 monitors at the US Embassy/Consulates "
            "in Islamabad, Lahore, Karachi, and Peshawar. Pulled from the AirNow Data Query API "
            "in 7-day chunks. Reference-grade BAM/T640 instruments.",
            body_style,
        ),
        Spacer(1, 0.3 * cm),
        fmt_para("Aggregation and pairing", h2_style),
        fmt_para(
            "Hourly readings are aggregated to UTC-day daily means per station, then to a "
            "single daily mean per (city, network) by averaging across all that network's "
            "stations in the city. Comparison metrics are computed on the inner-join of daily "
            "means by date, so months with fewer than five overlap days are reported but their "
            "R² / MAE / RMSE are left blank (N&lt;5 is too noisy to interpret).",
            body_style,
        ),
        Spacer(1, 0.3 * cm),
        fmt_para("Statistics", h2_style),
        fmt_para(
            "For each (city, month, candidate, reference) cell: "
            "<b>N</b> is the count of overlapping daily means in that month. "
            "<b>R²</b> is 1 − SS<sub>res</sub>/SS<sub>tot</sub> from an OLS fit of candidate on reference. "
            "<b>MAE</b> = mean(|candidate − reference|). "
            "<b>RMSE</b> = √mean((candidate − reference)²). "
            "Cells are color-coded by R² (green ≥0.8, yellow 0.6–0.8, orange 0.3–0.6, red &lt;0.3).",
            body_style,
        ),
    ]


def build_availability_table() -> list:
    rows = [
        ["", "Regulatory Monitors", "PAQI / IQAir", "AirGradient", "AirNow"],
        ["Lahore",    "2025-10 → 2026-05",  "May 2024 → present",   "Jun 2025 → present", "May 2024 → Feb 2025"],
        ["Islamabad", "(Rawalpindi proxy)", "May 2024 → present",   "Jun 2025 → present", "May 2024 → Feb 2026"],
        ["Karachi",   "— (no Punjab AQMS)", "May 2024 → present",   "Jul 2025 → present", "May 2024 → Mar 2025"],
        ["Peshawar",  "— (no Punjab AQMS)", "May 2024 → present",   "Jun 2025 → present", "May 2024 → Mar 2025"],
    ]
    tbl = Table(rows, colWidths=[2.8 * cm, 4.0 * cm, 3.8 * cm, 3.8 * cm, 3.8 * cm], hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a93")),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONT",       (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("FONT",       (0, 1), (-1, -1), "Helvetica", 9),
        ("ALIGN",      (0, 0), (-1, -1), "LEFT"),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#dde6f0")),
        ("FONT",       (0, 1), (0, -1), "Helvetica-Bold", 9),
        ("GRID",       (0, 0), (-1, -1), 0.4, colors.HexColor("#bbbbbb")),
        ("ROWBACKGROUNDS", (1, 1), (-1, -1), [colors.white, colors.HexColor("#f6f8fb")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return [
        fmt_para("Data availability", h1_style),
        fmt_para(
            "Each network came online at a different date and some have stopped reporting. "
            "The table below summarises per-city coverage windows for the 24-month study. "
            "These windows determine which scatter pairs and monthly stats can be computed.",
            body_style,
        ),
        Spacer(1, 0.3 * cm),
        tbl,
        Spacer(1, 0.4 * cm),
        fmt_para(
            "Cells marked with a dash mean the network has no presence in that city: Punjab AQMS "
            "is a provincial regulator and does not monitor Karachi (Sindh) or Peshawar (KPK).",
            caption_style,
        ),
    ]


def build_city_pages(city: dict) -> list:
    name = city["display"]
    slug = city["slug"]
    story = []
    # Landscape page: combined panel
    story.append(NextPageTemplate("landscape"))
    story.append(PageBreak())
    story.append(fmt_para(f"{name} — daily means and candidate-vs-reference scatters",
                          ParagraphStyle("CityH", parent=h1_style, fontSize=16, leading=20)))
    story.append(Spacer(1, 0.2 * cm))
    story.append(scaled_image(PLOTS / f"combined_{slug}.png", max_w_cm=26.5, max_h_cm=16.0))
    story.append(fmt_para(
        f"<b>{name}.</b> {city['blurb']}",
        caption_style,
    ))

    # Portrait page: stats table + commentary
    story.append(NextPageTemplate("portrait"))
    story.append(PageBreak())
    story.append(fmt_para(f"{name} — monthly performance statistics",
                          ParagraphStyle("CityH2", parent=h1_style, fontSize=16, leading=20)))
    story.append(scaled_image(PLOTS / f"monthly_stats_{slug}.png", max_w_cm=18.0, max_h_cm=14.0))
    story.append(Spacer(1, 0.3 * cm))
    story.append(fmt_para("Notes", h2_style))
    story.append(fmt_para(city["findings"], body_style))
    return story


def build_cross_city_summary() -> list:
    # Read the live monthly_stats CSV and surface best/worst R² per city per pairing
    df = pd.read_csv(DATA / "monthly_stats.csv")
    df = df.dropna(subset=["R2"])
    rows = [["City", "Pairing", "Months", "Best R² (month)", "Worst R² (month)", "Median MAE"]]
    for city in [c["display"] for c in CITY_SECTIONS]:
        sub = df[df["city"] == city]
        for (cand, ref), g in sub.groupby(["candidate", "reference"]):
            if g.empty:
                continue
            best  = g.loc[g["R2"].idxmax()]
            worst = g.loc[g["R2"].idxmin()]
            rows.append([
                city,
                f"{cand} vs {ref}",
                str(len(g)),
                f"{best['R2']:.3f} ({best['month']})",
                f"{worst['R2']:.3f} ({worst['month']})",
                f"{g['MAE'].median():.1f} µg/m³",
            ])

    tbl = Table(rows, colWidths=[2.5 * cm, 5.5 * cm, 1.6 * cm, 3.5 * cm, 3.5 * cm, 2.5 * cm], hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a93")),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONT",       (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("FONT",       (0, 1), (-1, -1), "Helvetica", 8.5),
        ("ALIGN",      (0, 0), (-1, -1), "LEFT"),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("GRID",       (0, 0), (-1, -1), 0.3, colors.HexColor("#bbbbbb")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f8fb")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return [
        fmt_para("Cross-city summary", h1_style),
        fmt_para(
            "Per-city, per-pairing best/worst R² month and median MAE across the 24-month window. "
            "Months with N&lt;5 are excluded.",
            body_style,
        ),
        Spacer(1, 0.3 * cm),
        tbl,
    ]


def build_caveats() -> list:
    return [
        fmt_para("Caveats", h1_style),
        fmt_para("AirGradient vs AirNow temporal mismatch", h2_style),
        fmt_para(
            "AirGradient sensors began producing data in mid-2025 (Jun-Jul 2025 in our four "
            "cities). The US Consulate AirNow monitors at Karachi, Lahore, and Peshawar all "
            "stopped reporting by March 2025 — i.e., before any AirGradient sensor came online "
            "in those cities. Only Islamabad (where AirNow continues to Feb 2026) provides a "
            "real AirGradient-vs-AirNow comparison (221 overlapping days).",
            body_style,
        ),
        fmt_para("Rawalpindi proxy for Islamabad regulatory line", h2_style),
        fmt_para(
            "The Punjab EPA AQMS network has no monitor inside Islamabad (which is in Islamabad "
            "Capital Territory, not Punjab). Three Rawalpindi stations sit 7–22 km from the US "
            "Embassy and are used as the Regulatory Monitors line. Rawalpindi-Islamabad is "
            "treated as a single airshed in mainstream air-quality analysis; readings should be "
            "interpreted as regional, not co-located.",
            body_style,
        ),
        fmt_para("Low-cost sensor humidity bias", h2_style),
        fmt_para(
            "Both PAQI / IQAir and AirGradient use optical particle counters that are known to "
            "over-report during high-humidity, high-PM episodes (typical of winter haze in "
            "Pakistan). MAE values balloon to 70–90 µg/m³ in Lahore Dec 2024 – Jan 2025 even "
            "while R² stays above 0.75 — a classic multiplicative-bias signature. A simple "
            "linear correction using each pair's OLS slope/intercept closes most of this gap, "
            "but is not applied to the values reported here.",
            body_style,
        ),
        fmt_para("Consulate monitor outages", h2_style),
        fmt_para(
            "The State Department's PM2.5 monitors at Karachi, Lahore, and Peshawar appear to "
            "have gone offline in February–March 2025 based on AirNow's data API. Only "
            "Islamabad's monitor continued reporting through this study's end date.",
            body_style,
        ),
    ]


# ─── Build ──────────────────────────────────────────────────────────────────

def main():
    doc = BaseDocTemplate(
        str(OUT_PDF), pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN + 0.6 * cm, bottomMargin=MARGIN,
        title="PM2.5 Network Comparison — Pakistan",
        author="hawanama",
    )
    p_frame = Frame(MARGIN, MARGIN, PAGE_WIDTH_P - 2 * MARGIN, PAGE_HEIGHT_P - 2 * MARGIN - 0.6 * cm, id="p")
    l_frame = Frame(MARGIN, MARGIN, PAGE_WIDTH_L - 2 * MARGIN, PAGE_HEIGHT_L - 2 * MARGIN - 0.6 * cm, id="l")
    doc.addPageTemplates([
        PageTemplate(id="portrait",  frames=[p_frame], pagesize=A4,              onPage=_portrait_decorator),
        PageTemplate(id="landscape", frames=[l_frame], pagesize=landscape(A4),   onPage=_landscape_decorator),
    ])

    story = []
    story += build_title_page()

    story.append(NextPageTemplate("portrait"))
    story.append(PageBreak())
    story += build_executive_summary()

    story.append(PageBreak())
    story += build_methodology()

    story.append(PageBreak())
    story += build_availability_table()

    for city in CITY_SECTIONS:
        story += build_city_pages(city)

    story.append(NextPageTemplate("portrait"))
    story.append(PageBreak())
    story += build_cross_city_summary()

    story.append(PageBreak())
    story += build_caveats()

    doc.build(story)
    print(f"wrote {OUT_PDF}  ({OUT_PDF.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
