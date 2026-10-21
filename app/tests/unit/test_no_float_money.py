"""Enforce M2's rule: money code never uses floats.

Scans the source (AST) of every money module, and of every Flask route or helper
that moves money, and fails if it finds a float literal (``3.99``), a call to
``float()``, true division (``/``, which always makes a float), or a call to the
old float-dollar helpers (``_money``, ``_cents_to_dollars``, ``_dollars_to_cents``).
Display-only code (charts, page formatting) is out of scope.
"""
import ast
import inspect
import os

import pytest

import Flask_app

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

MONEY_MODULES = ["money.py", "ledger.py", "charges.py"]

MONEY_FUNCTIONS = [
    "wallet_topup",
    "wallet_gift",
    "order",
    "admin_refund_order",
    "_charge_and_save_order",
    "_wallet_cents",
    "_refresh_session_wallet",
    "_request_key",
    "_wallet_history",
]

OLD_FLOAT_HELPERS = {"_money", "_cents_to_dollars", "_dollars_to_cents"}


def float_problems(tree):
    """Return a list of (line, description) for float use in an AST."""
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and type(node.value) is float:
            problems.append((node.lineno, f"float literal {node.value!r}"))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "float":
                problems.append((node.lineno, "call to float()"))
            elif node.func.id in OLD_FLOAT_HELPERS:
                problems.append((node.lineno, f"call to old float helper {node.func.id}()"))
        elif isinstance(node, (ast.BinOp, ast.AugAssign)) and isinstance(node.op, ast.Div):
            problems.append((node.lineno, "true division '/' (makes a float); use // or Decimal"))
    return problems


@pytest.mark.parametrize("filename", MONEY_MODULES)
def test_money_modules_never_use_floats(filename):
    with open(os.path.join(APP_DIR, filename), encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=filename)
    assert float_problems(tree) == [], f"{filename} uses floats"


@pytest.mark.parametrize("name", MONEY_FUNCTIONS)
def test_routes_that_move_money_never_use_floats(name):
    source = inspect.getsource(getattr(Flask_app, name))
    tree = ast.parse(inspect.cleandoc("\n" + source) if source.startswith(" ") else source)
    assert float_problems(tree) == [], f"Flask_app.{name} uses floats"


@pytest.mark.parametrize("snippet,expected", [
    ("x = 3.99", "float literal"),
    ("x = float(y)", "float()"),
    ("x = a / 100", "true division"),
    ("x /= 2", "true division"),
    ("x = _money(y)", "old float helper"),
    ("x = _dollars_to_cents(y)", "old float helper"),
])
def test_the_checker_catches_each_kind_of_float_use(snippet, expected):
    problems = float_problems(ast.parse(snippet))
    assert len(problems) == 1 and expected in problems[0][1]


def test_the_checker_allows_integer_money_code():
    ok = "total = sum(parts) // 2\nx = int(Decimal('0.0725') * 100)\nlabel = 'a float in a string'"
    assert float_problems(ast.parse(ok)) == []
