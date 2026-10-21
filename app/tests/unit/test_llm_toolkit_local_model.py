"""Choosing llm_toolkit's local model, which the plan-edit parser does via EDIT_LLM_MODEL."""

from types import SimpleNamespace

import pytest

import Flask_app
import llm_toolkit


@pytest.fixture()
def no_downloads(monkeypatch):
    """Load nothing from Hugging Face; record which model would have been loaded."""
    loaded = []

    class FakeLoader:
        @staticmethod
        def from_pretrained(name, **kwargs):
            loaded.append(name)
            return SimpleNamespace(eval=lambda: None)

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(llm_toolkit, "load_dotenv", lambda: None)
    monkeypatch.setattr(llm_toolkit, "AutoTokenizer", FakeLoader)
    monkeypatch.setattr(llm_toolkit, "AutoModelForCausalLM", FakeLoader)
    return loaded


def test_the_default_local_model_is_unchanged(no_downloads):
    llm = llm_toolkit.LLM(tokens=10)
    assert llm.model_name == llm_toolkit.DEFAULT_LOCAL_MODEL == "ibm-granite/granite-4.0-h-350M"
    assert set(no_downloads) == {llm_toolkit.DEFAULT_LOCAL_MODEL}


def test_another_local_model_can_be_chosen(no_downloads):
    llm = llm_toolkit.LLM(tokens=10, local_model="ibm-granite/granite-4.0-micro")
    assert llm.provider == "local" and llm.model_name == "ibm-granite/granite-4.0-micro"
    assert set(no_downloads) == {"ibm-granite/granite-4.0-micro"}


@pytest.mark.parametrize(
    "value, expected",
    [("ibm-granite/granite-4.0-micro", "ibm-granite/granite-4.0-micro"), ("", None)],
)
def test_the_edit_parser_uses_edit_llm_model(monkeypatch, value, expected):
    made = []
    monkeypatch.setattr(llm_toolkit, "LLM", lambda **kw: made.append(kw) or SimpleNamespace())
    monkeypatch.setattr(Flask_app, "_edit_llm_parser", None)
    monkeypatch.delenv("EDIT_PARSER", raising=False)
    monkeypatch.setenv("EDIT_LLM_MODEL", value)
    Flask_app.get_edit_parser()
    assert made == [{"tokens": 300, "local_model": expected}]
