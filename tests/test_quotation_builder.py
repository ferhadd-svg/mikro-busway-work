import openpyxl

from app.schemas.boq import BOQLineItem, BOQRun, FlagAnswers
from app.services.quotation_builder import _fill_template, _insert_row


class FakeSalesperson:
    name = "Eric Tan"
    title = "Sales Manager"
    mobile = "+60 12-000 0000"
    email = "eric@mikro.com.my"


def _runs():
    return [BOQRun(
        run_id="RUN-1",
        routing="FROM TX TO MSB",
        run_type="TX-MSB",
        material="AL",
        items=[
            BOQLineItem(description="Busway feeder 630A", unit="m", qty=10,
                        unit_rate_myr=100.0, amount_myr=1000.0),
            BOQLineItem(description="End closure 630A", unit="pc", qty=1,
                        unit_rate_myr=500.0, amount_myr=500.0),
        ],
    )]


def _flags():
    return FlagAnswers(lme_usd_per_mt=2600.0, usd_to_myr=4.4500)


def _template():
    """Minimal stand-in for the Mikro salesperson template: token header,
    item-table header, merged totals labels, merged remarks footer."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "Our Ref: <<OUR_REF>>"
    for col, header in enumerate(
            ["No.", "DESCRIPTION", "UNIT", "QTY", "UNIT RATE (RM)", "AMOUNT (RM)"], 1):
        ws.cell(row=3, column=col, value=header)
    ws.merge_cells("A5:D5"); ws["A5"] = "SUB-TOTAL (RM)"
    ws.merge_cells("A6:D6"); ws["A6"] = "10% SST (RM)"
    ws.merge_cells("A7:D7"); ws["A7"] = "GRAND TOTAL (RM)"
    ws.merge_cells("A9:F9")
    ws["A9"] = "1. The quantities quoted are rough estimation only. Final busway amount shall based on the actual delivery."
    return wb, ws


def test_insert_row_keeps_merges_aligned_with_values():
    wb, ws = _template()
    _insert_row(ws, 4)
    merged = {str(r) for r in ws.merged_cells.ranges}
    assert ws["A6"].value == "SUB-TOTAL (RM)"
    assert "A6:D6" in merged
    assert "A5:D5" not in merged


def test_fill_template_totals_and_merges():
    wb, ws = _template()
    _fill_template(ws, _runs(), _flags(), FakeSalesperson(),
                   our_ref="MK/Q/001", client_name="ACME Sdn Bhd",
                   attn=None, me_consultant=None)

    # Token replaced
    assert ws["A1"].value == "Our Ref: MK/Q/001"

    # Labels still sit at the anchor of their (shifted) merged ranges,
    # and the totals landed in the AMOUNT column on the same rows.
    merged = {str(r) for r in ws.merged_cells.ranges}
    label_rows = {}
    for row in ws.iter_rows():
        for cell in row:
            v = str(cell.value or "")
            if v.startswith(("SUB-TOTAL", "10% SST", "GRAND TOTAL")):
                label_rows[v.split(" (")[0]] = cell.row
                assert f"A{cell.row}:D{cell.row}" in merged, \
                    f"merge for '{v}' not aligned with its row {cell.row}"

    assert ws.cell(row=label_rows["SUB-TOTAL"], column=6).value == 1500
    assert ws.cell(row=label_rows["10% SST"], column=6).value == 150
    assert ws.cell(row=label_rows["GRAND TOTAL"], column=6).value == 1650

    # Item rows were written with description and amount
    descriptions = [c.value for row in ws.iter_rows() for c in row
                    if c.value == "Busway feeder 630A"]
    assert descriptions, "item row missing from filled template"


def test_grand_total_equals_displayed_subtotal_plus_sst():
    wb, ws = _template()
    _fill_template(ws, _runs(), _flags(), FakeSalesperson(),
                   our_ref="X", client_name="Y", attn=None, me_consultant=None)
    values = {}
    for row in ws.iter_rows():
        for cell in row:
            v = str(cell.value or "")
            if v.startswith(("SUB-TOTAL", "10% SST", "GRAND TOTAL")):
                values[v.split(" (")[0]] = ws.cell(row=cell.row, column=6).value
    assert values["GRAND TOTAL"] == values["SUB-TOTAL"] + values["10% SST"]
