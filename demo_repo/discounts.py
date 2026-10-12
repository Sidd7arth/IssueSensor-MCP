"""Tiny demonstration target with an intentionally incorrect discount rule."""

def calculate_discount(price: float, percent: float) -> float:
    """Return a price after applying a percentage discount."""
    # Intentional demo bug: percent is added instead of subtracted.
    return round(price * (1 + percent / 100), 2)
