from __future__ import annotations

import pytest

from app.domain.indoor import (
    cadr_needed,
    estimate_room,
    indoor_pm25,
    occupied_hours,
    round_up_cadr,
    source_indoor_increase,
    ventilation_window,
)
from app.domain.models import HomeSource, Room, SourceUse, WindowType
from tests.conftest import make_profile

V = 36.0  # the 3 x 4 x 3 m bedroom from the plan


def test_bedroom_leaky_no_purifier() -> None:
    assert indoor_pm25(250, 1.0, V) == pytest.approx(173.08, abs=0.01)


def test_bedroom_with_purifier_cadr_200() -> None:
    assert indoor_pm25(250, 1.0, V, 200) == pytest.approx(32.82, abs=0.01)


def test_bedroom_purifier_and_sealed_gaps() -> None:
    assert indoor_pm25(250, 0.5, V, 200) == pytest.approx(17.70, abs=0.01)


def test_source_adds_concentration() -> None:
    base = indoor_pm25(100, 1.0, V)
    with_source = indoor_pm25(100, 1.0, V, source_ug_per_h=3600)
    # S/V = 100, divided by (a + k) = 1.3
    assert with_source - base == pytest.approx(100 / 1.3)


def test_cadr_needed_hand_computed_and_round_trips() -> None:
    need = cadr_needed(250, 1.0, V, 30)
    assert need == pytest.approx(223.2)
    assert indoor_pm25(250, 1.0, V, need) == pytest.approx(30.0)


def test_cadr_needed_clamps_to_zero_when_air_is_already_clean() -> None:
    assert cadr_needed(10, 1.0, V, 30) == 0.0


def test_round_up_cadr() -> None:
    assert round_up_cadr(223.2) == 250
    assert round_up_cadr(0) == 0


def test_occupied_hours_wrap_past_midnight() -> None:
    room = Room(name="Bedroom", volume_m3=36, occupied_from=22, occupied_to=6)
    assert occupied_hours(room) == [22, 23, 0, 1, 2, 3, 4, 5]


def test_estimate_room_uses_occupied_hour_mean() -> None:
    room = Room(name="Bedroom", volume_m3=36, windows=WindowType.LEAKY)
    est = estimate_room(make_profile(250.0), room)
    assert est.indoor_no_purifier == pytest.approx(173.08, abs=0.01)
    assert est.indoor_purifier_sealed < est.indoor_with_purifier < est.indoor_no_purifier
    assert est.category_now == "very_poor"  # 173 is in the 121-250 band
    assert est.cadr_needed == pytest.approx(223.2)


def test_source_increase_zero_for_outdoor_burning() -> None:
    room = Room(name="Hall", volume_m3=40)
    assert source_indoor_increase(room, SourceUse(kind=HomeSource.WASTE_BURNING)) == 0.0
    assert source_indoor_increase(room, SourceUse(kind=HomeSource.INCENSE)) > 0


def test_ventilation_window_is_lowest_waking_hour() -> None:
    values = [300.0] * 24
    values[13] = 120.0
    values[3] = 20.0  # a clean hour in the middle of the night must not be chosen
    win = ventilation_window(make_profile(values))
    assert win.best_hour == 13
    assert win.pm25_best == 120.0
    assert win.pm25_waking_mean > win.pm25_best
