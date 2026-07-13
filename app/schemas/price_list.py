from pydantic import BaseModel
import datetime


class PriceListVersionOut(BaseModel):
    id: int
    original_filename: str
    uploaded_by_name: str | None = None
    uploaded_at: datetime.datetime
    is_active: bool
    row_count: int

    model_config = {"from_attributes": True}


class PriceRateOut(BaseModel):
    """Only the fields relevant to `category` are populated; the rest are
    None and the frontend renders '—' for those cells.

    Field relevance by category:
      - Feeder:                                    material, frame_a, earth_pct
      - Flange End / Flange End Box / Elbow /
        Flexible Conductor / Mounting Clamp /
        End Closure / Fixed Hanger / Spring Hanger /
        Plug-in Opening:                            material, frame_a
      - PIU:                                        rating_a, ka (no material)
      - Bi-Metal Plate:                              frame_a (no material)
    """
    category: str
    material: str | None = None
    frame_a: int | None = None
    rating_a: int | None = None
    earth_pct: int | None = None
    ka: int | None = None
    rate: float
