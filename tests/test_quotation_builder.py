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


def _eric_style_template():
    """Mirror of the real Mikro salesperson template: labelled header fields
    (no <<tokens>>), Quantity/Unit/Unit Rate/Total Amount in E/F/G/H, sample
    items with formulas, totals labels in F/G/B."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["D1"] = "MIKRO BUSWAY SDN BHD (201001002004)"
    ws["A8"] = "To"; ws["B8"] = ": "
    ws["A9"] = "Attn"; ws["B9"] = ": "
    ws["E8"] = "Date"; ws["F8"] = ": "
    ws.merge_cells("A12:H12"); ws["A12"] = "QUOTATION"
    ws["A14"] = "OUR REF    : "
    ws["G14"] = "M&E : "
    ws["A16"] = "No."; ws.merge_cells("B16:D16"); ws["B16"] = "Description"
    ws["E16"] = "Quantity"; ws["F16"] = "Unit"
    ws["G16"] = "Unit Rate"; ws["H16"] = "Total Amount"
    ws["H17"] = "Ex-Nilai Factory in RM"
    # Sample items shipped with the template
    ws["A18"] = 1; ws["B18"] = "MIKRO BUSWAY # 2500A SAMPLE"
    ws["B19"] = "FEEDER C/W INTEGRAL EARTH"; ws["F19"] = "MTR"; ws["H19"] = "=E19*G19"
    ws["H20"] = "=SUM(H19:H19)"
    ws.merge_cells("F22:G22"); ws["F22"] = "Sub-Total Amount  :"
    ws["H22"] = "=SUM(H20)"
    ws["G23"] = "10% SST  :"; ws["H23"] = "=SUM(H22*10%)"
    ws.merge_cells("B24:G24")
    ws["B24"] = "Grand Total Amount for Item No. 1 , Ex-Nilai Factory in RM  :"
    ws["H24"] = "=SUM(H22,H23)"
    ws["B26"] = "Remarks :"
    ws["B27"] = "1. The quantities quoted are rough estimation only. Final busway amount shall based on the actual"
    return wb, ws


def test_fill_real_style_template():
    wb, ws = _eric_style_template()
    _fill_template(ws, _runs(), _flags(), FakeSalesperson(),
                   our_ref="MK/Q/2026/001", client_name="ACME Sdn Bhd",
                   attn="Mr. Lim", me_consultant="XYZ Consult")

    # Labelled header fields filled (this template has no <<tokens>>)
    assert ws["B8"].value == ": ACME Sdn Bhd"
    assert ws["B9"].value == ": Mr. Lim"
    assert ws["A14"].value.endswith("MK/Q/2026/001")
    assert ws["G14"].value.endswith("XYZ Consult")
    import re
    assert re.fullmatch(r": \d{2}-\d{2}-\d{4}", str(ws["F8"].value))  # ": <date>" filled

    # Sample items removed
    all_text = [str(c.value) for row in ws.iter_rows() for c in row if c.value]
    assert not any("SAMPLE" in t for t in all_text)

    # Items written into the template's own columns: qty E, unit F, rate G, amount H
    feeder_row = next(c.row for row in ws.iter_rows() for c in row
                      if c.value == "Busway feeder 630A")
    assert ws.cell(row=feeder_row, column=5).value == 10       # Quantity
    assert ws.cell(row=feeder_row, column=6).value == "m"      # Unit
    assert ws.cell(row=feeder_row, column=7).value == 100.0    # Unit Rate
    assert ws.cell(row=feeder_row, column=8).value == 1000.0   # Total Amount

    # Totals in column H on the shifted label rows; merges still aligned
    merged = {str(r) for r in ws.merged_cells.ranges}
    sub_row = next(c.row for row in ws.iter_rows() for c in row
                   if str(c.value or "").startswith("Sub-Total"))
    sst_row = next(c.row for row in ws.iter_rows() for c in row
                   if str(c.value or "").startswith("10% SST"))
    grand_row = next(c.row for row in ws.iter_rows() for c in row
                     if str(c.value or "").startswith("Grand Total"))
    assert ws.cell(row=sub_row, column=8).value == 1500
    assert ws.cell(row=sst_row, column=8).value == 150
    assert ws.cell(row=grand_row, column=8).value == 1650
    assert f"F{sub_row}:G{sub_row}" in merged
    assert f"B{grand_row}:G{grand_row}" in merged

    # Remarks survive below the totals
    assert any(str(c.value or "").startswith("Remarks") for row in ws.iter_rows() for c in row)


def test_multiple_runs_all_land_above_subtotal():
    wb, ws = _eric_style_template()
    runs = [_runs()[0],
            BOQRun(run_id="RUN-2", routing="FROM MSB TO L5", run_type="MSB-Riser",
                   material="CU",
                   items=[BOQLineItem(description="Busway riser 800A", unit="m",
                                      qty=20, unit_rate_myr=200.0, amount_myr=4000.0)])]
    _fill_template(ws, runs, _flags(), FakeSalesperson(),
                   our_ref="X", client_name="Y", attn=None, me_consultant=None)
    sub_row = next(c.row for row in ws.iter_rows() for c in row
                   if str(c.value or "").startswith("Sub-Total"))
    riser_row = next(c.row for row in ws.iter_rows() for c in row
                     if c.value == "Busway riser 800A")
    assert riser_row < sub_row, "second run leaked below the SUB-TOTAL row"
    assert ws.cell(row=sub_row, column=8).value == 1500 + 4000


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
