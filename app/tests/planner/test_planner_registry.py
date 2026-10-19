"""The rule registry: discovery, configuration, and rejecting broken plug-ins at load."""

import sys
import textwrap

import pytest
from menu_factory import request

from planner import registry
from planner.constraint import Constraint, ItemFilter, Kind, SoftConstraint
from planner.registry import PluginError, register


@pytest.fixture(autouse=True)
def restore_registry():
    """Tests register throwaway rules; put the registry back afterwards."""
    registry.registered()  # load the built-ins first so they are part of the snapshot
    rules, loaded = dict(registry._rules), set(registry._loaded_packages)
    yield
    registry._rules.clear()
    registry._rules.update(rules)
    registry._loaded_packages.clear()
    registry._loaded_packages.update(loaded)


def test_a_complete_rule_registers_and_is_used_by_default():
    @register
    class Fine(Constraint):
        name = "fine_rule"
        summary = "A rule that does nothing."

        def apply(self, ctx):
            pass

    assert registry.get("fine_rule") is Fine
    assert any(isinstance(r, Fine) for r in registry.rules_for(request()))


def test_an_opt_in_rule_is_used_only_when_the_request_turns_it_on():
    @register
    class OptIn(Constraint):
        name = "opt_in_rule"
        summary = "Off unless asked for."
        enabled_by_default = False

        def apply(self, ctx):
            pass

    assert not any(isinstance(r, OptIn) for r in registry.rules_for(request()))
    on = registry.rules_for(request(options={"opt_in_rule": True}))
    assert any(isinstance(r, OptIn) for r in on)


def test_rules_are_listed_in_application_order():
    @register
    class Late(Constraint):
        name = "late_rule"
        summary = "Applied last."
        order = 10_000

        def apply(self, ctx):
            pass

    names = list(registry.registered())
    assert names[-1] == "late_rule"
    orders = [cls.order for cls in registry.registered().values()]
    assert orders == sorted(orders)


def test_an_unknown_option_is_reported_instead_of_silently_ignored():
    with pytest.raises(KeyError, match="max_meal_per_restaurant"):
        registry.rules_for(request(options={"max_meal_per_restaurant": 2}))


def test_get_names_the_known_rules_when_one_is_missing():
    with pytest.raises(KeyError, match="no planner rule named 'nope'"):
        registry.get("nope")


class _NoApply(Constraint):
    name = "no_apply"
    summary = "Forgot apply."


class _NoName(Constraint):
    summary = "Forgot the name."

    def apply(self, ctx):
        pass


class _BadName(_NoName):
    name = "Bad Name"


class _NoSummary(Constraint):
    name = "no_summary"

    def apply(self, ctx):
        pass


class _BadKind(_NoName):
    name = "bad_kind"
    kind = "hard"


class _SoftButNotSoftConstraint(_NoName):
    name = "soft_mismatch"
    kind = Kind.SOFT


class _FilterWithoutReason(ItemFilter):
    name = "filter_without_reason"
    summary = "Blocks everything."

    def allows(self, item, slot, ctx):
        return False


class _FilterWithoutAllows(ItemFilter):
    name = "filter_without_allows"
    summary = "Forgot allows."
    blocked_reason = "are blocked"


class _BadOrder(_NoName):
    name = "bad_order"
    order = "first"


class _SoftWithoutApply(SoftConstraint):
    name = "soft_without_apply"
    summary = "Forgot apply."


@pytest.mark.parametrize(
    "cls, message",
    [
        (_NoApply, "does not implement apply"),
        (_NoName, "snake_case"),
        (_BadName, "snake_case"),
        (_NoSummary, "summary"),
        (_BadKind, "Kind.HARD or Kind.SOFT"),
        (_SoftButNotSoftConstraint, "must subclass SoftConstraint"),
        (_FilterWithoutReason, "blocked_reason"),
        (_FilterWithoutAllows, "does not implement allows"),
        (_BadOrder, "order must be an int"),
        (_SoftWithoutApply, "does not implement apply"),
        (object, "not a subclass"),
        (len, "not a subclass"),
    ],
)
def test_a_broken_plug_in_is_rejected_when_it_registers(cls, message):
    with pytest.raises(PluginError, match=message):
        register(cls)


def test_two_rules_cannot_share_a_name():
    class First(Constraint):
        name = "shared_name"
        summary = "First."

        def apply(self, ctx):
            pass

    class Second(First):
        summary = "Second."

    register(First)
    with pytest.raises(PluginError, match="already taken"):
        register(Second)


def _write_package(tmp_path, name, files):
    pkg = tmp_path / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    for filename, source in files.items():
        (pkg / filename).write_text(textwrap.dedent(source))
    sys.path.insert(0, str(tmp_path))
    return name


def test_a_rule_file_that_crashes_on_import_is_rejected_at_load(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))
    package = _write_package(
        tmp_path, "crashing_rules_pkg", {"broken.py": "raise RuntimeError('typo in rule')\n"}
    )
    with pytest.raises(PluginError, match=r"crashing_rules_pkg\.broken failed to load"):
        registry.load_rules(package)


def test_a_rule_file_with_an_incomplete_rule_is_rejected_at_load(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))
    package = _write_package(
        tmp_path,
        "incomplete_rules_pkg",
        {
            "half_done.py": """
                from planner.constraint import Constraint
                from planner.registry import register

                @register
                class HalfDone(Constraint):
                    name = "half_done"
                    summary = "No apply yet."
            """
        },
    )
    with pytest.raises(PluginError, match="does not implement apply"):
        registry.load_rules(package)


def test_a_package_of_good_rules_loads_once(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))
    package = _write_package(
        tmp_path,
        "good_rules_pkg",
        {
            "good.py": """
                from planner.constraint import Constraint
                from planner.registry import register

                @register
                class Good(Constraint):
                    name = "good_external_rule"
                    summary = "Loaded from another package."

                    def apply(self, ctx):
                        pass
            """
        },
    )
    registry.load_rules(package)
    registry.load_rules(package)  # second call is a no-op
    assert "good_external_rule" in registry.registered()
