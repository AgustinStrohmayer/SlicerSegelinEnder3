from __future__ import annotations

import math

import pytest

from appSlicerSegelin.v2.core.units import inches_from_mm, mm_from_inches, parse_float, try_parse_float


def test_parse_float_period_and_comma():
    assert parse_float("1.5") == 1.5
    assert parse_float("1,5") == 1.5


def test_parse_float_scientific_notation():
    assert parse_float("1e-3") == 0.001
    assert parse_float("-2.5E+2") == -250.0


def test_parse_float_whitespace_is_tolerated():
    assert parse_float("  0.25  ") == 0.25


@pytest.mark.parametrize("bad", ["", "   ", None, "foo", "1.2.3"])
def test_parse_float_rejects_bad_input(bad):
    with pytest.raises((ValueError, TypeError)):
        parse_float(bad)


def test_parse_float_rejects_non_finite():
    with pytest.raises(ValueError):
        parse_float("nan")
    with pytest.raises(ValueError):
        parse_float("inf")


def test_try_parse_float_falls_back():
    assert try_parse_float("oops", default=42.0) == 42.0
    assert try_parse_float("3.14") == pytest.approx(3.14)


def test_inch_mm_round_trip():
    assert math.isclose(inches_from_mm(mm_from_inches(7.5)), 7.5)
