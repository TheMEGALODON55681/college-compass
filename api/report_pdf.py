"""Renders a report_data dict (see api/report_data.py) into a PDF. One
dependency, reportlab, already in requirements.txt. Every figure printed here
was already computed by /recommend - this module only lays it out.
"""

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

PDF_TITLE = "College Compass Counselling Report"
PDF_ORG_NAME = "College Compass"

BAND_LABELS = {"safe": "Safe", "moderate": "Moderate", "dream": "Dream"}
BAND_DESCRIPTIONS = {
    "safe": "You comfortably clear the predicted cutoff.",
    "moderate": "You're close to the predicted cutoff.",
    "dream": "A reach, but within striking distance.",
}
CATEGORY_LABELS = {
    "cs_adjacent": "CS-adjacent (CS, IT, AI, Data Science)",
    "core": "Core engineering",
    "any": "No preference",
}
OWNERSHIP_LABELS = {"government": "Government only", "ppp": "PPP institutes only (IIIT)", "both": "No preference"}

TABLE_HEADER = ["College / Branch", "Type", "State", "NIRF", "Quota", "Predicted closing rank", "Admission chance"]


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportNote", parent=styles["Normal"], fontSize=9, textColor=colors.grey, spaceAfter=6))
    styles.add(ParagraphStyle(name="CellText", parent=styles["Normal"], fontSize=8, leading=10))
    styles.add(ParagraphStyle(name="BandDescription", parent=styles["Normal"], fontSize=10, spaceAfter=8, textColor=colors.grey))
    return styles


def _format_rank(value):
    return f"{value:,}"


def _format_probability(row):
    pct = f"{round(row['admission_probability'] * 100)}%"
    return f"{pct} (approx.)" if row["probability_is_approximate"] else pct


def _student_summary_rows(student):
    rows = [
        ("JEE rank / category rank", f"{student['jee_rank']:,}"),
        ("Category", student["category"]),
        ("Home state", student["home_state"] or "Not specified"),
        ("Preferred branch type", CATEGORY_LABELS.get(student["preferred_branch_category"], student["preferred_branch_category"])),
        ("Budget (annual fees, lakhs)", f"{student['budget_annual_lakhs']:.1f}" if student["budget_annual_lakhs"] is not None else "Not specified"),
        ("Institute ownership preference", OWNERSHIP_LABELS.get(student["institute_ownership_pref"], student["institute_ownership_pref"])),
        ("Prioritize NIRF-ranked institutes", "Yes" if student["wants_top_nirf"] else "No"),
        ("Prefer home-state colleges", "Yes" if student["prefers_home_state"] else "No"),
    ]
    return rows


def _band_table(rows, styles):
    data = [TABLE_HEADER]
    for r in rows:
        college_cell = Paragraph(f"<b>{r['college_name']}</b><br/>{r['branch_name']}", styles["CellText"])
        data.append(
            [
                college_cell,
                r["institute_type"],
                r["state"] or "-",
                f"#{r['nirf_rank']}" if r["nirf_rank"] is not None else "-",
                r["quota_used"],
                _format_rank(r["predicted_closing_rank"]),
                _format_probability(r),
            ]
        )

    col_widths = [1.9 * inch, 0.5 * inch, 0.9 * inch, 0.5 * inch, 0.55 * inch, 1.0 * inch, 1.05 * inch]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2e303a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f3ec")]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e4e7")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def render_report_pdf(report_data):
    """Returns the PDF as raw bytes, ready for a FastAPI Response."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        title=PDF_TITLE,
        author=PDF_ORG_NAME,
        subject="JEE Main / JoSAA counselling report",
        creator=PDF_ORG_NAME,
        producer=PDF_ORG_NAME,
    )
    styles = _styles()
    story = []

    story.append(Paragraph(PDF_TITLE, styles["Title"]))
    story.append(Paragraph(f"Based on {report_data['based_on_year']} forecast closing ranks.", styles["ReportNote"]))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Student profile", styles["Heading2"]))
    summary_table = Table(_student_summary_rows(report_data["student"]), colWidths=[2.4 * inch, 3.5 * inch])
    summary_table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 10))
    story.append(Paragraph(report_data["how_to_read_note"], styles["ReportNote"]))
    story.append(Spacer(1, 6))

    total = sum(report_data["counts"].values())
    if total == 0:
        story.append(Paragraph("No eligible colleges were found for this profile.", styles["Normal"]))
    else:
        for band in ("safe", "moderate", "dream"):
            rows = report_data["bands"][band]
            if not rows:
                continue
            story.append(Paragraph(f"{BAND_LABELS[band]} ({len(rows)})", styles["Heading2"]))
            story.append(Paragraph(BAND_DESCRIPTIONS[band], styles["BandDescription"]))
            story.append(_band_table(rows, styles))
            story.append(Spacer(1, 14))

    story.append(PageBreak())
    story.append(Paragraph("Next steps", styles["Heading2"]))
    for fact in report_data["next_steps_facts"]:
        story.append(Paragraph(f"- {fact}", styles["Normal"]))
        story.append(Spacer(1, 4))

    story.append(Spacer(1, 16))
    story.append(Paragraph(report_data["scope_note"], styles["ReportNote"]))

    doc.build(story)
    return _scrub_library_signature(buffer.getvalue())


def _scrub_library_signature(pdf_bytes):
    """reportlab hardcodes its own name into two PDF comment lines (the
    %PDF-1.4 header comment and the trailer's %ID comment) - not the
    Title/Author/Creator/Producer metadata fields, which are already set to
    the project's own name above, but still a vendor name written into the
    file. Comments have no structural role (PDF readers skip lines starting
    with %), so a same-length substitution can't shift any byte offset the
    xref table depends on.
    """
    target = b"ReportLab"
    replacement = b"Generated"  # same byte length as target, on purpose - see docstring
    assert len(replacement) == len(target)
    return pdf_bytes.replace(target, replacement)
