"""Parsing the calorie target and weekly budget typed on Edit Profile."""

import pytest

from planner.targets import (
    MAX_DAILY_KCAL,
    MIN_DAILY_KCAL,
    TargetError,
    format_budget,
    parse_daily_calorie_target,
    parse_weekly_budget,
)


@pytest.mark.parametrize("raw, kcal", [("2000", 2000), (" 2,200 ", 2200), ("800", 800)])
def test_calorie_target_accepts_whole_numbers(raw, kcal):
    assert parse_daily_calorie_target(raw) == kcal


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_blank_calorie_target_means_not_set(raw):
    assert parse_daily_calorie_target(raw) is None


@pytest.mark.parametrize("raw", ["abc", "2000.5", "-2000", "2k", "1e3"])
def test_calorie_target_rejects_non_whole_numbers(raw):
    with pytest.raises(TargetError, match="whole number"):
        parse_daily_calorie_target(raw)


@pytest.mark.parametrize("kcal", [MIN_DAILY_KCAL - 1, MAX_DAILY_KCAL + 1, 0])
def test_calorie_target_rejects_values_outside_the_range(kcal):
    with pytest.raises(TargetError, match="between"):
        parse_daily_calorie_target(str(kcal))


@pytest.mark.parametrize(
    "raw, cents",
    [("150", 15000), ("$150.50", 15050), ("1,200", 120000), (" 99.9 ", 9990), ("1", 100)],
)
def test_weekly_budget_is_typed_in_dollars_and_stored_in_cents(raw, cents):
    assert parse_weekly_budget(raw) == cents


@pytest.mark.parametrize("raw", [None, "", "$", "  "])
def test_blank_weekly_budget_means_not_set(raw):
    assert parse_weekly_budget(raw) is None


@pytest.mark.parametrize("raw", ["cheap", "150.505", "NaN", "Infinity", "1e3", "12..5"])
def test_weekly_budget_rejects_anything_but_dollars_and_cents(raw):
    with pytest.raises(TargetError, match="dollars"):
        parse_weekly_budget(raw)


@pytest.mark.parametrize("raw", ["0", "0.99", "-150", "5000.01"])
def test_weekly_budget_rejects_amounts_outside_the_range(raw):
    with pytest.raises(TargetError, match="between"):
        parse_weekly_budget(raw)


def test_format_budget_round_trips_through_the_parser():
    assert format_budget(15050) == "150.50"
    assert parse_weekly_budget(format_budget(15050)) == 15050
    assert format_budget(None) == ""
