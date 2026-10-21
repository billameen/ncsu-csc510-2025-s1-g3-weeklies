import importlib
import types
import pytest

@pytest.mark.parametrize("modname", ["Flask_app", "sqlQueries"])
def test_modules_import(modname):
    """
    Tests if the main application and SQL query modules can be successfully imported.
    This validates the basic project structure and module existence.
    """
    mod = importlib.import_module(modname)
    assert isinstance(mod, types.ModuleType)

def test_flask_app_exposes_app_if_present():
    """
    Tests if the Flask_app module exposes a 'app' instance of the Flask class.
    This is necessary for the Flask CLI and testing framework to function.
    """
    mod = importlib.import_module("Flask_app")
    if hasattr(mod, "app"):
        from flask import Flask
        assert isinstance(mod.app, Flask)
    else:
        pytest.skip("Flask_app.app not defined; skipping.")

def test_root_route_if_client_available():
    """
    Tests the root route ("/") to ensure the Flask application is running and responding.
    It accepts 200 (OK), 302 (Redirect, e.g., for login), or 404 (Not Found, if not defined).
    """
    mod = importlib.import_module("Flask_app")
    if hasattr(mod, "app"):
        client = mod.app.test_client()
        resp = client.get("/")
        # login redirect (302) is fine; we just ensure the app responds
        assert resp.status_code in (200, 302, 404)
    else:
        pytest.skip("No app object; skipping.")
