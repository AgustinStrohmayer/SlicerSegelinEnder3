"""Empirical power law, prediction curves of every source, and their export."""
from __future__ import annotations

import numpy as np
import pytest

from appSlicerSegelin.v2.core.calibration import Measurement, fit_empirical
from appSlicerSegelin.v2.core.cutting_physics import Calibration, CutSetup
from appSlicerSegelin.v2.core.model_curves import (
    QUANTITIES,
    empirical_series,
    errors_vs_measured,
    measured_series,
    model_series,
    thermal2d_series,
    to_csv,
)


def _synthetic(a=1.1, b=-0.6, c=1.2, noise=0.0, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    for d in (1.0, 1.2, 1.5):
        for v in (1.0, 2.0, 3.5, 6.0):
            k = a * v**b * d**c * np.exp(noise * rng.standard_normal())
            out.append(Measurement(v, d, "current", 10.0 - k, 10.0))
    return out


def test_empirical_fit_recovers_the_power_law():
    e = fit_empirical(_synthetic())
    assert (e.a, e.b, e.c) == pytest.approx((1.1, -0.6, 1.2), rel=1e-6)
    assert e.r2 == pytest.approx(1.0) and e.rms_mm < 1e-9
    assert len(e.per_drive) == 3 and all(b == pytest.approx(-0.6) for _, _, b in e.per_drive)
    assert e.predict(2.0, 1.2) == pytest.approx(1.1 * 2.0**-0.6 * 1.2**1.2)
    assert "v^-0.60" in e.equation() and "I^1.20" in e.equation()


def test_empirical_fit_with_noise_reports_uncertainty():
    e = fit_empirical(_synthetic(noise=0.05, seed=3))
    assert abs(e.b + 0.6) < 3 * e.se_b + 0.02
    assert 0 < e.se_b < 0.1 and 0 < e.se_c < 0.5 and 0.9 < e.r2 < 1.0


def test_empirical_fit_single_drive_and_bad_input():
    one = [m for m in _synthetic() if m.drive == 1.0]
    e = fit_empirical(one)
    assert e.c == 0.0 and e.b == pytest.approx(-0.6) and "I^" not in e.equation()
    with pytest.raises(ValueError):
        fit_empirical([Measurement(2.0, 1.0, "current", 9.0), Measurement(2.0, 1.2, "current", 8.8)])
    with pytest.raises(ValueError):
        fit_empirical([Measurement(1.0, 1.0, "current", 9.0), Measurement(2.0, 4.0, "voltage", 9.2)])


def test_model_series_calibrated_vs_uncalibrated_and_errors():
    s = CutSetup(calib=Calibration(eta=1.0, kappa=1.4))
    vs = np.geomspace(0.5, 10, 30)
    cal = model_series(s, [1.0, 1.4], vs)
    unc = model_series(s, [1.0, 1.4], vs, "uncalibrated")
    assert set(cal[0].values) == set(QUANTITIES)
    assert np.allclose(cal[0].values["kerf_mm"], 1.4 * unc[0].values["kerf_mm"])
    assert np.all(np.diff(cal[1].values["kerf_mm"]) < 0)
    assert np.all(cal[1].values["kerf_mm"] > cal[0].values["kerf_mm"])  # more drive, wider kerf
    # measurements made exactly by the calibrated model: its error is ~0, the handbook model's is not
    ms = [Measurement(float(v), d, "current", 10 - float(sr.values["kerf_mm"][i]))
          for sr, d in zip(cal, (1.0, 1.4), strict=True) for i, v in enumerate(vs) if i % 7 == 3]
    errs = errors_vs_measured(cal + unc + measured_series(ms, "current"), ms, "current")
    assert errs["model"] < 1e-3 < errs["uncalibrated"]


def test_csv_and_2d_series():
    s = CutSetup(current_a=1.6)
    ms = _synthetic()
    e = fit_empirical(ms)
    vs = np.array([2.0, 4.0])
    two = thermal2d_series(s, [1.6], vs, quality="coarse")
    assert two[0].source == "2-D" and len(two[0].values["kerf_mm"]) == 2
    assert two[0].values["kerf_mm"][0] > two[0].values["kerf_mm"][1]
    series = model_series(s, [1.6], vs) + empirical_series(e, [1.6], vs) + two + measured_series(ms, "current")
    text = to_csv(series, "current")
    lines = text.strip().splitlines()
    assert lines[0].startswith("source,drive_A,feed_mm_s,kerf_mm")
    assert len(lines) == 1 + 2 + 2 + 2 + len(ms)
    assert any(line.startswith("2-D,1.6,") for line in lines)
    with pytest.raises(InterruptedError):
        thermal2d_series(s, [1.6], vs, quality="coarse", progress=lambda f, m: False)
