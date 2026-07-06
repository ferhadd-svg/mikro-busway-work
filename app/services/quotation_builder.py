"""
Generate the priced quotation Excel by writing item blocks into the
salesperson template (logo, pink header, borders, fonts preserved).

Template structure assumptions (Mikro standard):
  - Header rows: logo, company info, quotation title, client/ref block
  - Item body: starts after a header sentinel row
  - Footer: remarks block + subtotal / SST / grand total + signatures
"""

import copy
from datetime import date
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.cell_range import CellRange

from app.schemas.boq import BOQRun, BOQLineItem, FlagAnswers
from app.models.salesperson import Salesperson
from app.config import settings


REMARKS_AL = [
    "The quantities quoted are rough estimation only. Final busway amount shall based on the actual delivery and approved shop-drawings.",
    "All Bi-Metal materials for Aluminum Busway are by contractor.",
    "Should any modification on factory standard dimensions are chargeable.",
    "All horizontal hanger support are by contractor.",
    "Any delivery to other than project site are subject to additional transportation surcharge.",
    "The prices quoted are EXCLUDING all installation works, all termination of the busway to panels or transformers, testing and commissioning at site.",
    "Warranty against manufacturing defects is 12 calendar months after delivery. This warranty does not cover reimbursement of consequential or incidental damages, labour, transportation, removal of the installation or any other expenses which may be incurred in connection with the repair and replacement.",
]


def _remarks_cu(flags) -> list[str]:
    today = date.today().strftime("%d-%m-%Y")
    return [
        "The quantities quoted are rough estimation only. Final busway amount shall based on the actual delivery and approved shop-drawings.",
        "All Copper Bars are 100% Electro Tin-Plated.",
        f"The prices quoted are based on {today} LME Copper @ USD {flags.lme_usd_per_mt:,.0f}/MT.",
        "Should any modification on factory standard dimensions are chargeable.",
        "All horizontal hanger support are by contractor.",
        "Any delivery to other than project site are subject to additional transportation surcharge.",
        "The prices quoted are EXCLUDING all installation works, all termination of the busway to panels or transformers, testing and commissioning at site.",
        "Warranty against manufacturing defects is 12 calendar months after delivery. This warranty does not cover reimbursement of consequential or incidental damages, labour, transportation, removal of the installation or any other expenses which may be incurred in connection with the repair and replacement.",
    ]


def _terms_block(runs: list, flags) -> list[tuple[str, str]]:
    """Return [(label, value)] rows for Manufacturer/Validity/Delivery/Price/Payment."""
    materials = {r.material for r in runs}
    if "CU" in materials:
        return _terms_cu(flags)
    return _terms_al(flags)


def _terms_al(flags) -> list[tuple[str, str]]:
    validity = (
        f"Prices are based on LME Aluminium at USD {flags.lme_usd_per_mt:,.0f}/MT. "
        f"Any subsequent adjustment shall follow the prevailing LME Aluminium price within a ±2% variation."
    )
    return [
        ("Manufacturer", "Mikro Busway Sdn Bhd, Malaysia."),
        ("Validity",     validity),
        ("Delivery",     "Approximately 8 to 10 working weeks upon receipt of approval drawings."),
        ("Price",        "Ex-Nilai Factory in Ringgit Malaysia (RM)."),
        ("Payment",      "30% Deposit is required upon confirmation of order.\nBalance on Irrevocable Letter of Credit 60 Days."),
    ]


def _terms_cu(flags) -> list[tuple[str, str]]:
    payment = (
        f"30% deposit is required to secure LME CU US{flags.lme_usd_per_mt:,.0f}/MT upon successful transfer to the account \n"
        f"Price within +2% remain unchanged, variations over 2.3% require base of adjustment \n"
        f"The balance is payable via an irrevocable 60days Letter Of Credit "
    )
    return [
        ("Manufacturer", "Mikro Busway Sdn Bhd, Malaysia."),
        ("Validity",     f"Based on LME Copper@USD{flags.lme_usd_per_mt:,.0f}/ MT and thereafter depands on current LME price "),
        ("Delivery",     "Approximately 8 to 10 working weeks upon receipt of approval drawings."),
        ("Price",        "Ex-Nilai Factory in Ringgit Malaysia (RM)."),
        ("Payment",      payment),
        ("Cancellation", "30% from total amount will be imposed on cancellation of purchase order "),
    ]


def _remarks_for_runs(runs: list[BOQRun], flags) -> list[str]:
    materials = {r.material for r in runs}
    if "CU" in materials:
        return _remarks_cu(flags)
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


def _insert_row(ws, row: int):
    """Insert one row, keeping merged cells aligned with their values.

    openpyxl's insert_rows shifts cell values down but leaves merged ranges
    at their old coordinates, so every merge at or below the insertion point
    (the totals block, remarks, signature area at the end of the template)
    drifts one row out of place per inserted item. Re-anchor them manually.
    """
    to_shift, to_expand = [], []
    for rng in ws.merged_cells.ranges:
        if rng.min_row >= row:
            to_shift.append(str(rng))
        elif rng.max_row >= row:
            to_expand.append(str(rng))
    for ref in to_shift + to_expand:
        ws.unmerge_cells(ref)
    ws.insert_rows(row)
    for ref in to_shift:
        r = CellRange(ref)
        r.shift(row_shift=1)
        ws.merge_cells(str(r))
    for ref in to_expand:
        r = CellRange(ref)
        r.expand(down=1)
        ws.merge_cells(str(r))


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
        _insert_row(ws, row)
        ws.merge_cells(f"A{row}:F{row}")
        c = ws.cell(row=row, column=1,
                    value=f"{run.run_id} — {run.routing} ({run.run_type}, {run.material})")
        c.font = section_font
        c.fill = section_fill
        c.border = border
        row += 1

        for item in run.items:
            _insert_row(ws, row)
            _write_quotation_row(ws, row, item_num, item, border)
            item_num += 1
            row += 1

        if run.piu_items:
            _insert_row(ws, row)
            ws.merge_cells(f"A{row}:F{row}")
            c = ws.cell(row=row, column=1, value="PIU — PLUG-IN UNITS")
            c.font = Font(italic=True, bold=True)
            c.border = border
            row += 1
            for item in run.piu_items:
                _insert_row(ws, row)
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


def _amount_column(ws) -> int | None:
    """Column of the 'AMOUNT (RM)' header in the item table, if present."""
    for row in ws.iter_rows():
        for cell in row:
            if isinstance(cell.value, str) and cell.value.strip().upper().startswith("AMOUNT"):
                return cell.column
    return None


def _subtotal_sst_grand(runs: list[BOQRun]) -> tuple[int, int, int]:
    subtotal = round(sum(
        item.amount_myr for r in runs for item in (r.items + r.piu_items)
    ))
    sst = round(subtotal * 0.10)
    return subtotal, sst, subtotal + sst


def _write_totals(ws, runs: list[BOQRun], min_row: int):
    subtotal, sst, grand_total = _subtotal_sst_grand(runs)
    # Write into the AMOUNT column when the template has one; otherwise fall
    # back to the historical assumption of two columns right of the label.
    amount_col = _amount_column(ws)

    for row in ws.iter_rows(min_row=min_row):
        for cell in row:
            v = str(cell.value or "").upper()
            value = None
            if "SUB-TOTAL" in v or "SUBTOTAL" in v:
                value = subtotal
            elif "GRAND TOTAL" in v:
                value = grand_total
            elif "SST" in v or "TAX" in v:
                value = sst
            if value is not None:
                ws.cell(row=cell.row, column=amount_col or (cell.column + 2)).value = value


def _append_items(ws, runs: list[BOQRun], flags: FlagAnswers):
    """Last-resort: write items at first empty row, then a totals block."""
    max_row = ws.max_row + 2
    _insert_item_block(ws, runs, flags, max_row)

    subtotal, sst, grand_total = _subtotal_sst_grand(runs)
    bold = Font(bold=True)
    row = ws.max_row + 1
    for label, value in [("SUB-TOTAL (RM)", subtotal),
                         ("10% SST (RM)", sst),
                         ("GRAND TOTAL (RM)", grand_total)]:
        ws.cell(row=row, column=5, value=label).font = bold
        ws.cell(row=row, column=6, value=value).font = bold
        row += 1


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

    # Terms block (Manufacturer, Validity, Delivery, Price, Payment)
    row = 10
    label_font = Font(bold=True)
    for label, value in _terms_block(runs, flags):
        ws.cell(row=row, column=1, value=label).font = label_font
        c = ws.cell(row=row, column=2, value=value)
        c.alignment = Alignment(wrap_text=True)
        ws.row_dimensions[row].height = 30 if "\n" in value or len(value) > 80 else 15
        row += 1

    row += 1  # blank spacer

    for col, header in enumerate(["No.", "DESCRIPTION", "UNIT", "QTY", "UNIT RATE (RM)", "AMOUNT (RM)"], 1):
        c = ws.cell(row=row, column=col, value=header)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="4472C4")
        c.border = border
        c.alignment = Alignment(horizontal="center")
    row += 1

    _insert_item_block(ws, runs, flags, row)

    subtotal, sst, grand = _subtotal_sst_grand(runs)
    end_row = ws.max_row + 2

    ws.cell(row=end_row, column=5, value="SUB-TOTAL (RM)").font = bold
    ws.cell(row=end_row, column=6, value=subtotal).font = bold
    end_row += 1
    ws.cell(row=end_row, column=5, value="10% SST (RM)").font = bold
    ws.cell(row=end_row, column=6, value=sst).font = bold
    end_row += 1
    ws.cell(row=end_row, column=5, value="GRAND TOTAL (RM)").font = Font(bold=True, size=12)
    ws.cell(row=end_row, column=6, value=grand).font = Font(bold=True, size=12)

    end_row += 2
    remarks = _remarks_for_runs(runs, flags)
    ws.cell(row=end_row, column=1, value="Remarks :").font = Font(bold=True, underline="single")
    for i, remark in enumerate(remarks, 1):
        c = ws.cell(row=end_row + i, column=1, value=f"{i}.  {remark}")
        c.alignment = Alignment(wrap_text=True)
        ws.row_dimensions[end_row + i].height = 30 if len(remark) > 100 else 15

    sig_row = end_row + len(remarks) + 3
    ws.cell(row=sig_row, column=1, value="Prepared by:").font = bold
    ws.cell(row=sig_row + 2, column=1, value=salesperson.name)
    ws.cell(row=sig_row + 3, column=1, value=salesperson.title)
    ws.cell(row=sig_row + 4, column=1, value=f"Tel: {salesperson.mobile}")
    ws.cell(row=sig_row + 5, column=1, value=f"Email: {salesperson.email}")

    return wb
