"""
Generate the priced quotation Excel by writing item blocks into the
salesperson template (logo, pink header, borders, fonts preserved).

Template structure assumptions (Mikro standard):
  - Header rows: logo, company info, quotation title, client/ref block
  - Item body: starts after a header sentinel row
  - Footer: remarks block + subtotal / SST / grand total + signatures
"""

import copy
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter

from app.schemas.boq import BOQRun, BOQLineItem, FlagAnswers
from app.models.salesperson import Salesperson
from app.config import settings


REMARKS_AL = [
    "All busway systems are manufactured to IEC 60439-2 standard.",
    "Aluminium conductor busway — LME aluminium rate applies.",
    "Price validity: 30 days from date of quotation.",
    "Delivery: 8–12 weeks ex-factory Nilai upon confirmed order.",
    "Payment terms: 30% down payment, 70% upon delivery.",
]

REMARKS_CU = [
    "All busway systems are manufactured to IEC 60439-2 standard.",
    "Copper conductor busway — LME copper rate applies.",
    "Price validity: 30 days from date of quotation.",
    "Delivery: 8–12 weeks ex-factory Nilai upon confirmed order.",
    "Payment terms: 30% down payment, 70% upon delivery.",
]


def _remarks_for_runs(runs: list[BOQRun]) -> list[str]:
    materials = {r.material for r in runs}
    # Mixed Cu+Al → copper remarks govern
    if "CU" in materials:
        return REMARKS_CU
    return REMARKS_AL


def build_quotation(
    runs: list[BOQRun],
    flags: FlagAnswers,
    salesperson: Salesperson,
    our_ref: str,
    client_name: str,
    attn: str | None,
    me_consultant: str | None,
    template_path: Path | None,
) -> Path:
    """
    Write a priced quotation Excel. If a salesperson template exists, use it
    as the base; otherwise build from scratch.
    """
    if template_path and template_path.exists():
        wb = openpyxl.load_workbook(str(template_path))
        ws = wb.active
        _fill_template(ws, runs, flags, salesperson, our_ref, client_name, attn, me_consultant)
    else:
        wb = _build_from_scratch(runs, flags, salesperson, our_ref, client_name, attn, me_consultant)

    out_path = settings.projects_dir / f"QUOTATION_{our_ref.replace('/', '-')}_{salesperson.name.replace(' ', '_')}.xlsx"
    wb.save(str(out_path))
    return out_path


# ------------------------------------------------------------------ #
#  Template fill (preferred path)                                     #
# ------------------------------------------------------------------ #

def _fill_template(ws, runs, flags, salesperson, our_ref, client_name, attn, me_consultant):
    """
    Scan the template for known sentinel strings and replace them.
    Then inject item rows above the totals block.
    """
    # Replace placeholder tokens
    _replace_tokens(ws, {
        "<<OUR_REF>>": our_ref,
        "<<CLIENT>>": client_name or "",
        "<<ATTN>>": attn or "",
        "<<ME>>": me_consultant or "",
        "<<SALESPERSON_NAME>>": salesperson.name,
        "<<SALESPERSON_TITLE>>": salesperson.title,
        "<<SALESPERSON_MOBILE>>": salesperson.mobile,
        "<<SALESPERSON_EMAIL>>": salesperson.email,
        "<<LME_USD>>": f"USD {flags.lme_usd_per_mt:,.0f}/MT",
        "<<USD_MYR>>": f"USD 1 = RM {flags.usd_to_myr:.4f}",
    })

    # Find the row that contains "SUB-TOTAL" or "SUBTOTAL"
    subtotal_row = None
    for row in ws.iter_rows():
        for cell in row:
            v = str(cell.value or "").upper()
            if "SUB-TOTAL" in v or "SUBTOTAL" in v:
                subtotal_row = cell.row
                break
        if subtotal_row:
            break

    if subtotal_row is None:
        # Fallback: append items at the bottom
        _append_items(ws, runs, flags)
        return

    # Find item start row (first blank row above subtotal that's below the header)
    insert_row = subtotal_row
    for r in range(subtotal_row - 1, 0, -1):
        all_empty = all(
            ws.cell(row=r, column=c).value in (None, "")
            for c in range(1, 7)
        )
        if not all_empty:
            insert_row = r + 1
            break

    _insert_item_block(ws, runs, flags, insert_row)
    _write_totals(ws, runs, subtotal_row)


def _replace_tokens(ws, token_map: dict):
    for row in ws.iter_rows():
        for cell in row:
            if isinstance(cell.value, str):
                for token, value in token_map.items():
                    if token in cell.value:
                        cell.value = cell.value.replace(token, value)


def _insert_item_block(ws, runs: list[BOQRun], flags: FlagAnswers, start_row: int):
    thin = Side(border_style="thin", color="000000")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    section_fill = PatternFill("solid", fgColor="D9E1F2")
    section_font = Font(bold=True)

    row = start_row
    item_num = 1

    for run in runs:
        # Section header
        ws.insert_rows(row)
        ws.merge_cells(f"A{row}:F{row}")
        c = ws.cell(row=row, column=1,
                    value=f"{run.run_id} — {run.routing} ({run.run_type}, {run.material})")
        c.font = section_font
        c.fill = section_fill
        c.border = border
        row += 1

        for item in run.items:
            ws.insert_rows(row)
            _write_quotation_row(ws, row, item_num, item, border)
            item_num += 1
            row += 1

        if run.piu_items:
            ws.insert_rows(row)
            ws.merge_cells(f"A{row}:F{row}")
            c = ws.cell(row=row, column=1, value="PIU — PLUG-IN UNITS")
            c.font = Font(italic=True, bold=True)
            c.border = border
            row += 1
            for item in run.piu_items:
                ws.insert_rows(row)
                _write_quotation_row(ws, row, item_num, item, border)
                item_num += 1
                row += 1

        row += 1  # blank spacer


def _write_quotation_row(ws, row: int, item_num: int, item: BOQLineItem, border):
    values = [item_num, item.description, item.unit, item.qty,
              item.unit_rate_myr, item.amount_myr]
    for col, val in enumerate(values, 1):
        c = ws.cell(row=row, column=col, value=val)
        c.border = border
        if col >= 3:
            c.alignment = Alignment(horizontal="right")


def _write_totals(ws, runs: list[BOQRun], subtotal_row: int):
    subtotal = sum(
        item.amount_myr for r in runs for item in (r.items + r.piu_items)
    )
    sst = round(subtotal * 0.10)
    grand_total = round(subtotal + sst)

    for row in ws.iter_rows(min_row=subtotal_row):
        for cell in row:
            v = str(cell.value or "").upper()
            if "SUB-TOTAL" in v or "SUBTOTAL" in v:
                # Amount is typically 2 cols to the right
                ws.cell(row=cell.row, column=cell.column + 2).value = round(subtotal)
            if "SST" in v or "TAX" in v:
                ws.cell(row=cell.row, column=cell.column + 2).value = sst
            if "GRAND TOTAL" in v:
                ws.cell(row=cell.row, column=cell.column + 2).value = grand_total


def _append_items(ws, runs: list[BOQRun], flags: FlagAnswers):
    """Last-resort: write items at first empty row."""
    max_row = ws.max_row + 2
    _insert_item_block(ws, runs, flags, max_row)


# ------------------------------------------------------------------ #
#  From-scratch builder (no template)                                 #
# ------------------------------------------------------------------ #

def _build_from_scratch(runs, flags, salesperson, our_ref, client_name, attn, me_consultant):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "QUOTATION"

    thin = Side(border_style="thin", color="000000")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    header_fill = PatternFill("solid", fgColor="C00000")
    header_font = Font(bold=True, color="FFFFFF", size=12)
    bold = Font(bold=True)

    ws.column_dimensions["A"].width = 8
    ws.column_dimensions["B"].width = 50
    ws.column_dimensions["C"].width = 8
    ws.column_dimensions["D"].width = 10
    ws.column_dimensions["E"].width = 16
    ws.column_dimensions["F"].width = 16

    # Header
    ws.merge_cells("A1:F1")
    ws["A1"] = "MIKRO ENGINEERING SDN BHD"
    ws["A1"].font = Font(bold=True, size=16)
    ws["A1"].alignment = Alignment(horizontal="center")

    ws.merge_cells("A2:F2")
    ws["A2"] = "BUSWAY SYSTEM QUOTATION"
    ws["A2"].font = header_font
    ws["A2"].fill = header_fill
    ws["A2"].alignment = Alignment(horizontal="center")

    ws["A4"] = "Our Ref:"
    ws["B4"] = our_ref
    ws["A5"] = "Client:"
    ws["B5"] = client_name
    if attn:
        ws["A6"] = "Attn:"
        ws["B6"] = attn
    if me_consultant:
        ws["A7"] = "M&E:"
        ws["B7"] = me_consultant

    ws["D4"] = "Salesperson:"
    ws["E4"] = salesperson.name
    ws["D5"] = "Title:"
    ws["E5"] = salesperson.title
    ws["D6"] = "Mobile:"
    ws["E6"] = salesperson.mobile

    ws["A8"] = f"LME: USD {flags.lme_usd_per_mt:,.0f}/MT | USD 1 = RM {flags.usd_to_myr:.4f}"
    ws["A8"].font = Font(italic=True)

    row = 10
    for col, header in enumerate(["No.", "DESCRIPTION", "UNIT", "QTY", "UNIT RATE (RM)", "AMOUNT (RM)"], 1):
        c = ws.cell(row=row, column=col, value=header)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="4472C4")
        c.border = border
        c.alignment = Alignment(horizontal="center")
    row += 1

    _insert_item_block(ws, runs, flags, row)

    subtotal = sum(item.amount_myr for r in runs for item in (r.items + r.piu_items))
    end_row = ws.max_row + 2

    sst = round(subtotal * 0.10)
    grand = round(subtotal + sst)

    ws.cell(row=end_row, column=5, value="SUB-TOTAL (RM)").font = bold
    ws.cell(row=end_row, column=6, value=round(subtotal)).font = bold
    end_row += 1
    ws.cell(row=end_row, column=5, value="10% SST (RM)").font = bold
    ws.cell(row=end_row, column=6, value=sst).font = bold
    end_row += 1
    ws.cell(row=end_row, column=5, value="GRAND TOTAL (RM)").font = Font(bold=True, size=12)
    ws.cell(row=end_row, column=6, value=grand).font = Font(bold=True, size=12)

    end_row += 2
    remarks = _remarks_for_runs(runs)
    ws.cell(row=end_row, column=1, value="REMARKS:").font = bold
    for i, remark in enumerate(remarks, 1):
        ws.cell(row=end_row + i, column=1, value=f"{i}. {remark}")

    sig_row = end_row + len(remarks) + 3
    ws.cell(row=sig_row, column=1, value="Prepared by:").font = bold
    ws.cell(row=sig_row + 2, column=1, value=salesperson.name)
    ws.cell(row=sig_row + 3, column=1, value=salesperson.title)
    ws.cell(row=sig_row + 4, column=1, value=f"Tel: {salesperson.mobile}")
    ws.cell(row=sig_row + 5, column=1, value=f"Email: {salesperson.email}")

    return wb
