from discounts import calculate_discount


def test_twenty_percent_discount_reduces_price():
    # Expected 80.00, but the intentionally buggy function returns 120.00.
    assert calculate_discount(100, 20) == 80.00


def test_zero_discount_leaves_price_unchanged():
    assert calculate_discount(100, 0) == 100.00

