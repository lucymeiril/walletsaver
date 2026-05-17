"""Price grade label computation for API responses."""
from typing import Optional, Literal

GradeLabel = Literal["HOT_DEAL", "SALE", "NORMAL", "OVERPRICED", "INSUFFICIENT_DATA"]


def get_grade_label(
    observed_price: Optional[float],
    p10: Optional[float],
    p25: Optional[float],
    p75: Optional[float],
    sufficient: bool,
) -> GradeLabel:
    if not sufficient or p10 is None or observed_price is None:
        return "INSUFFICIENT_DATA"
    if observed_price <= p10:
        return "HOT_DEAL"
    if p25 is not None and observed_price <= p25:
        return "SALE"
    if p75 is not None and observed_price <= p75:
        return "NORMAL"
    return "OVERPRICED"


GRADE_BADGE_COLORS = {
    "HOT_DEAL": "red",
    "SALE": "orange",
    "NORMAL": "gray",
    "OVERPRICED": "blue",
    "INSUFFICIENT_DATA": "gray",
}
