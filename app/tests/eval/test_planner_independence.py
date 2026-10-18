"""
The validator is the spec, so it must not share code with the planners it checks (issue #5).
These tests follow every import statement, transitively, through the eval package and app/.
"""

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
APP = REPO / "app"

PLANNER_MODULES = {"menu_generation", "llm_toolkit", "eval.baselines"}


def direct_imports(source: str) -> set[str]:
    """Module names imported anywhere in the source, including inside functions."""
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:  # relative imports only occur inside the flat eval package
                base = "eval" + (f".{base}" if base else "")
            names.add(base)
            # `from eval import baselines` imports a module, so count each name as a candidate.
            names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def source_file(module: str) -> Path | None:
    """The file for an eval or app module, or None for the standard library and packages."""
    if module == "eval":
        path = REPO / "eval" / "__init__.py"
    elif module.startswith("eval."):
        path = REPO / "eval" / f"{module.removeprefix('eval.')}.py"
    else:
        path = APP / f"{module}.py"
    return path if path.is_file() else None


def reachable_imports(module: str) -> set[str]:
    """Every module name imported by module or by the eval/app modules it reaches."""
    found, queue, visited = set(), [module], set()
    while queue:
        current = queue.pop()
        path = source_file(current)
        if current in visited or path is None:
            continue
        visited.add(current)
        imported = direct_imports(path.read_text())
        if current.startswith("eval."):
            imported.add("eval")  # importing a submodule runs the package's __init__
        found |= imported
        queue.extend(imported)
    return found


@pytest.mark.parametrize("module", ["eval.validate", "eval.feasibility"])
def test_does_not_import_planner_code(module):
    assert source_file(module) is not None
    assert reachable_imports(module) & PLANNER_MODULES == set()


def test_walker_follows_imports_through_other_modules():
    # Flask_app imports menu_generation, which imports llm_toolkit.
    assert {"menu_generation", "llm_toolkit"} <= reachable_imports("Flask_app")


def test_walker_sees_every_import_form():
    source = """
import menu_generation as mg
from eval import baselines

def later():
    from .baselines import plan
    import llm_toolkit
"""
    assert PLANNER_MODULES <= direct_imports(source)
