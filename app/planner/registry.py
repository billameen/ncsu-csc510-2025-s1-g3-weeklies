"""
The registry of planner rules.

Rules register themselves with the ``@register`` decorator when their module is imported.
Built-in rules live one per file in `planner.rules`, and every module there is imported the
first time the registry is read, so adding a rule means adding one file; nothing else needs
to list it. ``register`` checks each rule as it loads and refuses a broken one with a
`PluginError` that says what is wrong, instead of letting it fail halfway through a plan.
"""

import importlib
import inspect
import pkgutil
import re

from planner.constraint import Constraint, ItemFilter, Kind, SoftConstraint

BUILTIN_PACKAGE = "planner.rules"

_NAME = re.compile(r"[a-z][a-z0-9_]*\Z")
_rules: dict[str, type[Constraint]] = {}
_loaded_packages: set[str] = set()


class PluginError(Exception):
    """A rule failed to load or does not follow the plug-in interface."""


def register(cls: type[Constraint]) -> type[Constraint]:
    """
    Class decorator that adds a rule to the registry.
    Raises:
        PluginError: The class is not a complete Constraint subclass, its name is missing,
            malformed or taken, its kind is not a Kind, it has no summary, or (for an
            ItemFilter) no blocked_reason.
    """
    label = getattr(cls, "__name__", repr(cls))
    if not (inspect.isclass(cls) and issubclass(cls, Constraint)):
        raise PluginError(f"{label} is not a subclass of planner.constraint.Constraint")
    if not isinstance(cls.name, str) or not _NAME.match(cls.name):
        raise PluginError(f"{label}.name must be a snake_case id like 'no_allergens'")
    if inspect.isabstract(cls):
        missing = ", ".join(sorted(cls.__abstractmethods__))
        raise PluginError(f"{label} ({cls.name}) does not implement {missing}")
    if not isinstance(cls.kind, Kind):
        raise PluginError(f"{label}.kind must be Kind.HARD or Kind.SOFT")
    if cls.kind is Kind.SOFT and not issubclass(cls, SoftConstraint):
        raise PluginError(f"{label} is soft, so it must subclass SoftConstraint")
    if not isinstance(cls.summary, str) or not cls.summary.strip():
        raise PluginError(f"{label} needs a one-line summary")
    if issubclass(cls, ItemFilter) and not cls.blocked_reason:
        raise PluginError(f"{label} is an ItemFilter, so it needs a blocked_reason")
    if not isinstance(cls.order, int):
        raise PluginError(f"{label}.order must be an int")
    existing = _rules.get(cls.name)
    if existing is not None and existing.__qualname__ != cls.__qualname__:
        raise PluginError(
            f"rule name {cls.name!r} is already taken by {existing.__module__}."
            f"{existing.__qualname__}"
        )
    _rules[cls.name] = cls
    return cls


def unregister(name: str) -> None:
    """Remove a rule from the registry (for tests). Unknown names are ignored."""
    _rules.pop(name, None)


def load_rules(package: str = BUILTIN_PACKAGE) -> None:
    """
    Import every module in a package so its rules register. Each package is loaded once.
    Raises:
        PluginError: A module failed to import, or registered a broken rule.
    """
    if package in _loaded_packages:
        return
    pkg = importlib.import_module(package)
    for module in pkgutil.iter_modules(pkg.__path__, prefix=f"{package}."):
        try:
            importlib.import_module(module.name)
        except PluginError:
            raise
        except Exception as e:  # any error in a rule file means the rule is broken
            raise PluginError(f"rule module {module.name} failed to load: {e!r}") from e
    _loaded_packages.add(package)


def registered() -> dict[str, type[Constraint]]:
    """Every registered rule by name, built-in rules included, in application order."""
    load_rules()
    return dict(sorted(_rules.items(), key=lambda kv: (kv[1].order, kv[0])))


def get(name: str) -> type[Constraint]:
    """The rule class registered under name. Raises KeyError if there is none."""
    rules = registered()
    if name not in rules:
        raise KeyError(f"no planner rule named {name!r}; known: {', '.join(rules)}")
    return rules[name]


def rules_for(request) -> list[Constraint]:
    """
    The configured rules a request uses, in application order: every rule enabled by
    default, plus the ones the request turns on in its options, minus the ones it turns off.
    Raises:
        KeyError: The request's options name a rule that does not exist (likely a typo).
    """
    rules = registered()
    unknown = sorted(set(request.options) - set(rules))
    if unknown:
        raise KeyError(f"unknown planner rule(s) in options: {', '.join(unknown)}")
    configured = (cls.from_request(request) for cls in rules.values())
    return [rule for rule in configured if rule is not None]
