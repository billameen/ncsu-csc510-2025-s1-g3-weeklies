import pandas as pd
from menu_generation import format_llm_output, filter_allergens, filter_closed_restaurants

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