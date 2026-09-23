from pydantic import BaseModel, Field
from typing import Annotated, Literal

PositiveInt = Annotated[int, Field(gt=0)]


class BusRun(BaseModel):
    run_id: str
    run_type: Literal["TX-MSB", "MSB-Riser", "RISER"]
    rating_a: int = Field(gt=0)
    frame_rating_a: int = Field(gt=0)
    material: Literal["AL", "CU"]
    earth_pct: Literal[50, 100]
    routing: str
    phases: str = "3P4W"
    length_m: float | None = Field(default=None, ge=0)
    # gt=0, not ge=0: this is a divisor in boq_builder._calc_hangers — a
    # zero value would raise ZeroDivisionError instead of a clean 400.
    hanger_spacing_m: float = Field(default=1.5, gt=0)
    num_fixed_hangers: int | None = Field(default=None, ge=0)
    num_spring_hangers: int | None = Field(default=None, ge=0)
    piu_ratings: list[PositiveInt] = []
    spare_openings: int = Field(default=0, ge=0)
    needs_bimetal: bool = False
    flags: list[str] = []


class DrawingExtraction(BaseModel):
    runs: list[BusRun]
    global_flags: list[str] = []
    raw_notes: str = ""


class FlagAnswers(BaseModel):
    # gt=0 here is about protecting the quotation's own disclaimer text
    # ("LME Aluminium @USD {lme_usd_per_mt}/MT") from a nonsensical value —
    # these two numbers are never used in the actual pricing math, only
    # quoted back to the client, but a negative or zero rate would still
    # look broken on a document going out the door.
    lme_usd_per_mt: float = Field(gt=0)
    usd_to_myr: float = Field(gt=0)
    piu_ka: Literal[26, 36, 50] = 26
    run_overrides: dict[str, dict] = {}


class BOQLineItem(BaseModel):
    description: str
    unit: str
    qty: float
    unit_rate_myr: float
    amount_myr: float
    # House-format rendering hints:
    #   is_subheader → a label-only row like "OPTIONAL" (no qty/rate/amount)
    #   is_excluded  → priced-out row like "CONNECTION BARS (TX & MSB)" that
    #                  shows the literal text "EXCLUDED" instead of a number
    is_subheader: bool = False
    is_excluded: bool = False


class BOQRun(BaseModel):
    run_id: str
    routing: str
    run_type: str
    material: str
    items: list[BOQLineItem]
    piu_items: list[BOQLineItem] = []
    # Carried through for the quotation's run title
    # ("MIKRO BUSWAY # 500A (630A) TPNE, 3P4W+50%E, ..."):
    rating_a: int | None = None          # nominal
    frame_rating_a: int | None = None    # standard frame
    earth_pct: int | None = None
    phases: str = "3P4W"


class BOQResponse(BaseModel):
    project_our_ref: str
    runs: list[BOQRun]
    subtotal_myr: float
    boq_file: str
    # Populated when a real (non-subheader, non-excluded) line item's rate
    # lookup came back empty — the price list has no entry for that
    # frame/rating/material combination. The BOQ still generates (a
    # salesperson needs to see it to know what's missing) but this item
    # is silently priced at RM 0 unless someone notices — surfaced here so
    # the UI can flag it instead of that happening invisibly.
    warnings: list[str] = []
