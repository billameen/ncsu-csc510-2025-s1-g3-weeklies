import sqlite3

import pandas as pd

import menu_generation
from menu_generation import (
    MenuGenerator,
    format_llm_output,
    filter_allergens,
    filter_closed_restaurants,
)

def test_llm_output_parsing_simple():
    """Test extracting ID from simple string."""
    assert format_llm_output("22") == 22

def test_llm_output_parsing_sentence():
    """Test extracting ID from a sentence."""
    assert format_llm_output("I recommend item 105 for you.") == 105

def test_llm_output_parsing_failure():
    """Test failure case returns error code."""
    assert format_llm_output("I don't know") == -1

def test_filter_allergens_logic():
    """Test DataFrame filtering for allergens."""
    df = pd.DataFrame({
        'itm_id': [1, 2, 3],
        'allergens': ['Gluten', None, 'Peanuts, Soy']
    })
    
    # Filter Gluten
    res = filter_allergens(df.copy(), "Gluten")
    assert len(res) == 2
    assert 1 not in res['itm_id'].values

    # Filter Peanuts (case insensitive)
    res = filter_allergens(df.copy(), "peanuts")
    assert len(res) == 2
    assert 3 not in res['itm_id'].values

def test_filter_closed_restaurants_logic():
    """Test DataFrame filtering for hours."""
    # Restaurant 1 open Mon 1000-2000, Rtr 2 Closed Mon
    df = pd.DataFrame({
        'rtr_id': [1, 2],
        'hours': ['{"Mon": [1000, 2000]}', '{"Mon": []}']
    })
    
    # Check Mon 12:00 (Rtr 1 open)
    res = filter_closed_restaurants(df.copy(), "Mon", 1200)
    assert len(res) == 1
    assert res.iloc[0]['rtr_id'] == 1

    # Check Mon 22:00 (Both closed)
    res = filter_closed_restaurants(df.copy(), "Mon", 2200)
    assert len(res) == 0

def test_menu_parsing_regex_safety():
    """Ensure regex doesn't crash on empty/bad inputs."""
    from Flask_app import parse_generated_menu
    assert parse_generated_menu(None) == {}
    assert parse_generated_menu("") == {}
    assert parse_generated_menu("[bad data]") == {}


def _tiny_menu_db(tmp_path, monkeypatch):
    """Point MenuGenerator at a one-item menu instead of the real database."""
    db = tmp_path / "menu.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE Restaurant (rtr_id INTEGER, hours TEXT, status TEXT);
        CREATE TABLE MenuItem (itm_id INTEGER, rtr_id INTEGER, name TEXT, description TEXT,
                               price INTEGER, calories INTEGER, instock INTEGER, allergens TEXT);
        INSERT INTO Restaurant VALUES (1, '{"Mon": [600, 2300]}', 'Open');
        INSERT INTO MenuItem VALUES (7, 1, 'Oatmeal', 'Warm oats', 500, 300, 1, NULL);
    """)
    conn.close()
    monkeypatch.setattr(menu_generation, "db_file", str(db))


def test_menu_generator_uses_an_injected_llm(tmp_path, monkeypatch):
    """A passed-in LLM is used instead of building the real one."""
    _tiny_menu_db(tmp_path, monkeypatch)

    def no_real_llm(*args, **kwargs):
        raise AssertionError("the real LLM must not be built")

    monkeypatch.setattr(menu_generation.llm_toolkit, "LLM", no_real_llm)

    class FakeLLM:
        def __init__(self):
            self.prompts = []

        def generate(self, system, prompt):
            self.prompts.append(prompt)
            return "7"

    fake = FakeLLM()
    menu = MenuGenerator(llm=fake).update_menu(
        menu="", preferences="", allergens="", date="2026-10-19", meal_numbers=[1]
    )

    assert menu == "[2026-10-19,7,1]"
    assert len(fake.prompts) == 1
    assert "7,Oatmeal,Warm oats" in fake.prompts[0]


def test_menu_generator_builds_the_real_llm_by_default(tmp_path, monkeypatch):
    """Without an LLM argument, the real one is built with the requested token limit."""
    _tiny_menu_db(tmp_path, monkeypatch)
    built = []

    class RecordingLLM:
        def __init__(self, tokens):
            built.append(tokens)

    monkeypatch.setattr(menu_generation.llm_toolkit, "LLM", RecordingLLM)

    gen = MenuGenerator(tokens=123)

    assert built == [123]
    assert isinstance(gen.generator, RecordingLLM)
