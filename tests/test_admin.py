import pytest

from bot.handlers.admin import _parse_positive_amount


@pytest.mark.parametrize(
    "text", ["nan", "NaN", "inf", "Infinity", "-inf", "0", "-5", "abc", ""]
)
def test_parse_positive_amount_rejects_non_finite_and_non_positive(text):
    assert _parse_positive_amount(text) is None


@pytest.mark.parametrize(
    "text,expected", [("20", 20.0), ("19.99", 19.99), ("0.01", 0.01)]
)
def test_parse_positive_amount_accepts_positive_finite_numbers(text, expected):
    assert _parse_positive_amount(text) == expected
