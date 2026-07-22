from pydantic import BaseModel
from typing import Literal


class BusRun(BaseModel):
    run_id: str
    run_type: Literal["TX-MSB", "MSB-Riser", "RISER"]
    rating_a: int
    frame_rating_a: int
    material: Literal["AL", "CU"]
    earth_pct: Literal[50, 100]
    routing: str
    phases: str = "3P4W"
    length_m: float | None = None
    hanger_spacing_m: float = 1.5
    num_fixed_hangers: int | None = None
    num_spring_hangers: int | None = None
    piu_ratings: list[int] = []
    spare_openings: int = 0
    needs_bimetal: bool = False
    flags: list[str] = []


class DrawingExtraction(BaseModel):
    runs: list[BusRun]
    global_flags: list[str] = []
    raw_notes: str = ""


class FlagAnswers(BaseModel):
    lme_usd_per_mt: float
    usd_to_myr: float
    piu_ka: int = 26
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
