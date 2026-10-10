import re
import pytest
import os
import pandas as pd

import menu_generation as menu_generation
from sqlQueries import *
from Flask_app import parse_generated_menu

db_file = os.path.join(os.path.dirname(__file__), '../../CSC510_DB.db')

generator = menu_generation.MenuGenerator()
conn = create_connection(db_file)
menu_items = pd.read_sql_query("SELECT * FROM MenuItem WHERE instock == 1", conn)
close_connection(conn)

'''
menugenerator_single_menu1 = generator.update_menu(menu = None, preferences = "high protein,low carb", allergens = "Peanuts,Shellfish", date = "2025-10-14", meal_numbers = [2])
menugenerator_single_menu2 = generator.update_menu(menu = menugenerator_single_menu1, preferences = "high protein,low carb", allergens = "Peanuts,Shellfish", date = "2025-10-14", meal_numbers = [3])
menugenerator_single_menu3 = generator.update_menu(menu = menugenerator_single_menu2, preferences = "high protein,low carb", allergens = "Peanuts,Shellfish", date = "2025-10-15", meal_numbers = [1])
menugenerator_single_menu4 = generator.update_menu(menu = menugenerator_single_menu3, preferences = "high protein,low carb", allergens = "Peanuts,Shellfish", date = "2025-10-15", meal_numbers = [2])
menugenerator_single_menu5 = generator.update_menu(menu = menugenerator_single_menu4, preferences = "high protein,low carb", allergens = "Peanuts,Shellfish", date = "2025-10-15", meal_numbers = [3])

def test_MenuGenerator_single_no_regression():
    parsed1 = parse_generated_menu(menugenerator_single_menu1)
    parsed2 = parse_generated_menu(menugenerator_single_menu2)
    parsed3 = parse_generated_menu(menugenerator_single_menu3)
    parsed4 = parse_generated_menu(menugenerator_single_menu4)
    parsed5 = parse_generated_menu(menugenerator_single_menu5)

    assert parsed1["2025-10-14"][0] == parsed2["2025-10-14"][0]
    assert parsed1["2025-10-14"][0] == parsed3["2025-10-14"][0]
    assert parsed1["2025-10-14"][0] == parsed4["2025-10-14"][0]
    assert parsed1["2025-10-14"][0] == parsed5["2025-10-14"][0]
    assert parsed2["2025-10-14"][1] == parsed3["2025-10-14"][1]
    assert parsed2["2025-10-14"][1] == parsed4["2025-10-14"][1]
    assert parsed2["2025-10-14"][1] == parsed5["2025-10-14"][1]
    assert parsed3["2025-10-15"][0] == parsed4["2025-10-15"][0]
    assert parsed3["2025-10-15"][0] == parsed5["2025-10-15"][0]
    assert parsed4["2025-10-15"][1] == parsed5["2025-10-15"][1]

def test_MenuGenerator_single_valid_items():
    parsed1 = parse_generated_menu(menugenerator_single_menu1)
    parsed2 = parse_generated_menu(menugenerator_single_menu2)
    parsed3 = parse_generated_menu(menugenerator_single_menu3)
    parsed4 = parse_generated_menu(menugenerator_single_menu4)
    parsed5 = parse_generated_menu(menugenerator_single_menu5)

    assert menu_items[menu_items["itm_id"] == parsed5["2025-10-14"][0]["itm_id"]].shape[0] == 1
    assert menu_items[menu_items["itm_id"] == parsed5["2025-10-14"][1]["itm_id"]].shape[0] == 1
    assert menu_items[menu_items["itm_id"] == parsed5["2025-10-15"][0]["itm_id"]].shape[0] == 1
    assert menu_items[menu_items["itm_id"] == parsed5["2025-10-15"][1]["itm_id"]].shape[0] == 1
    assert menu_items[menu_items["itm_id"] == parsed5["2025-10-15"][2]["itm_id"]].shape[0] == 1

def test_MenuGenerator_single_correct_meals():
    parsed1 = parse_generated_menu(menugenerator_single_menu1)
    parsed2 = parse_generated_menu(menugenerator_single_menu2)
    parsed3 = parse_generated_menu(menugenerator_single_menu3)
    parsed4 = parse_generated_menu(menugenerator_single_menu4)
    parsed5 = parse_generated_menu(menugenerator_single_menu5)

    assert parsed5["2025-10-14"][0]["meal"] == 2
    assert parsed5["2025-10-14"][1]["meal"] == 3
    assert parsed5["2025-10-15"][0]["meal"] == 1
    assert parsed5["2025-10-15"][1]["meal"] == 2
    assert parsed5["2025-10-15"][2]["meal"] == 3

menugenerator_multiple_meals_menu1 = generator.update_menu(menu = None, preferences = "high protein,low carb", allergens = "Peanuts,Shellfish", date = "2025-10-14", meal_numbers = [2,3])
menugenerator_multiple_meals_menu2 = generator.update_menu(menu = menugenerator_multiple_meals_menu1, preferences = "high protein,low carb", allergens = "Peanuts,Shellfish", date = "2025-10-15", meal_numbers = [1,2,3])

def test_MenuGenerator_multiple_meals_no_regression():
    parsed1 = parse_generated_menu(menugenerator_multiple_meals_menu1)
    parsed2 = parse_generated_menu(menugenerator_multiple_meals_menu2)

    assert parsed1["2025-10-14"][0] == parsed2["2025-10-14"][0]
    assert parsed1["2025-10-14"][1] == parsed2["2025-10-14"][1]

def test_MenuGenerator_multiple_meals_valid_items():
    parsed1 = parse_generated_menu(menugenerator_multiple_meals_menu1)
    parsed2 = parse_generated_menu(menugenerator_multiple_meals_menu2)

    assert menu_items[menu_items["itm_id"] == parsed2["2025-10-14"][0]["itm_id"]].shape[0] == 1
    assert menu_items[menu_items["itm_id"] == parsed2["2025-10-14"][1]["itm_id"]].shape[0] == 1
    assert menu_items[menu_items["itm_id"] == parsed2["2025-10-15"][0]["itm_id"]].shape[0] == 1
    assert menu_items[menu_items["itm_id"] == parsed2["2025-10-15"][1]["itm_id"]].shape[0] == 1
    assert menu_items[menu_items["itm_id"] == parsed2["2025-10-15"][2]["itm_id"]].shape[0] == 1

def test_MenuGenerator_multiple_meals_correct_meals():
    parsed1 = parse_generated_menu(menugenerator_multiple_meals_menu1)
    parsed2 = parse_generated_menu(menugenerator_multiple_meals_menu2)

    assert parsed2["2025-10-14"][0]["meal"] == 2
    assert parsed2["2025-10-14"][1]["meal"] == 3
    assert parsed2["2025-10-15"][0]["meal"] == 1
    assert parsed2["2025-10-15"][1]["meal"] == 2
    assert parsed2["2025-10-15"][2]["meal"] == 3


menugenerator_multiple_meals_oof_menu1 = generator.update_menu(menu = None, preferences = "high protein,low carb", allergens = "Peanuts,Shellfish", date = "2025-10-14", meal_numbers = [3,2])
menugenerator_multiple_meals_oof_menu2 = generator.update_menu(menu = menugenerator_multiple_meals_oof_menu1, preferences = "high protein,low carb", allergens = "Peanuts,Shellfish", date = "2025-10-15", meal_numbers = [2,1,3])

def test_MenuGenerator_multiple_meals_out_of_order_no_regression():
    parsed1 = parse_generated_menu(menugenerator_multiple_meals_oof_menu1)
    parsed2 = parse_generated_menu(menugenerator_multiple_meals_oof_menu2)

    assert parsed1["2025-10-14"][0] == parsed2["2025-10-14"][0]
    assert parsed1["2025-10-14"][1] == parsed2["2025-10-14"][1]

def test_MenuGenerator_multiple_meals_out_of_order_valid_items():
    parsed1 = parse_generated_menu(menugenerator_multiple_meals_oof_menu1)
    parsed2 = parse_generated_menu(menugenerator_multiple_meals_oof_menu2)

    assert menu_items[menu_items["itm_id"] == parsed2["2025-10-14"][0]["itm_id"]].shape[0] == 1
    assert menu_items[menu_items["itm_id"] == parsed2["2025-10-14"][1]["itm_id"]].shape[0] == 1
    assert menu_items[menu_items["itm_id"] == parsed2["2025-10-15"][0]["itm_id"]].shape[0] == 1
    assert menu_items[menu_items["itm_id"] == parsed2["2025-10-15"][1]["itm_id"]].shape[0] == 1
    assert menu_items[menu_items["itm_id"] == parsed2["2025-10-15"][2]["itm_id"]].shape[0] == 1

def test_MenuGenerator_multiple_meals_out_of_order_correct_meals():
    parsed1 = parse_generated_menu(menugenerator_multiple_meals_oof_menu1)
    parsed2 = parse_generated_menu(menugenerator_multiple_meals_oof_menu2)

    assert parsed2["2025-10-14"][0]["meal"] == 3
    assert parsed2["2025-10-14"][1]["meal"] == 2
    assert parsed2["2025-10-15"][0]["meal"] == 2
    assert parsed2["2025-10-15"][1]["meal"] == 1
    assert parsed2["2025-10-15"][2]["meal"] == 3
    
menugenerator_multiple_days_menu1 = generator.update_menu(menu = None, preferences = "high protein,low carb", allergens = "Peanuts,Shellfish", date = "2025-10-15", meal_numbers = [1], number_of_days = 1)
menugenerator_multiple_days_menu2 = generator.update_menu(menu = menugenerator_multiple_days_menu1, preferences = "high protein,low carb", allergens = "Peanuts,Shellfish", date = "2025-10-14", meal_numbers = [2], number_of_days = 2)
menugenerator_multiple_days_menu3 = generator.update_menu(menu = menugenerator_multiple_days_menu2, preferences = "high protein,low carb", allergens = "Peanuts,Shellfish", date = "2025-10-14", meal_numbers = [3], number_of_days = 2)

def test_MenuGenerator_multiple_days_no_regression():
    parsed1 = parse_generated_menu(menugenerator_multiple_days_menu1)
    parsed2 = parse_generated_menu(menugenerator_multiple_days_menu2)
    parsed3 = parse_generated_menu(menugenerator_multiple_days_menu3)

    assert parsed1["2025-10-15"][0] == parsed2["2025-10-15"][0]
    assert parsed1["2025-10-15"][0] == parsed3["2025-10-15"][0]
    assert parsed2["2025-10-14"][0] == parsed3["2025-10-14"][0]
    assert parsed2["2025-10-15"][1] == parsed3["2025-10-15"][1]

def test_MenuGenerator_multiple_days_valid_items():
    parsed1 = parse_generated_menu(menugenerator_multiple_days_menu1)
    parsed2 = parse_generated_menu(menugenerator_multiple_days_menu2)
    parsed3 = parse_generated_menu(menugenerator_multiple_days_menu3)
    
    assert menu_items[menu_items["itm_id"] == parsed3["2025-10-14"][0]["itm_id"]].shape[0] == 1
    assert menu_items[menu_items["itm_id"] == parsed3["2025-10-14"][1]["itm_id"]].shape[0] == 1
    assert menu_items[menu_items["itm_id"] == parsed3["2025-10-15"][0]["itm_id"]].shape[0] == 1
    assert menu_items[menu_items["itm_id"] == parsed3["2025-10-15"][1]["itm_id"]].shape[0] == 1
    assert menu_items[menu_items["itm_id"] == parsed3["2025-10-15"][2]["itm_id"]].shape[0] == 1

def test_MenuGenerator_multiple_days_correct_meals():
    parsed1 = parse_generated_menu(menugenerator_multiple_days_menu1)
    parsed2 = parse_generated_menu(menugenerator_multiple_days_menu2)
    parsed3 = parse_generated_menu(menugenerator_multiple_days_menu3)

    assert parsed3["2025-10-14"][0]["meal"] == 2
    assert parsed3["2025-10-14"][1]["meal"] == 3
    assert parsed3["2025-10-15"][0]["meal"] == 1
    assert parsed3["2025-10-15"][1]["meal"] == 2
    assert parsed3["2025-10-15"][2]["meal"] == 3

'''
menugenerator_multiple_days_multiple_meals_menu = generator.update_menu(menu = None, preferences = "high protein,low carb", allergens = "Peanuts,Shellfish", date = "2025-10-14", meal_numbers = [1,2,3], number_of_days = 2)

def test_MenuGenerator_multiple_days_multiple_meals_valid_items():
    parsed = parse_generated_menu(menugenerator_multiple_days_multiple_meals_menu)

    assert menu_items[menu_items["itm_id"] == parsed["2025-10-14"][0]["itm_id"]].shape[0] == 1
    assert menu_items[menu_items["itm_id"] == parsed["2025-10-14"][1]["itm_id"]].shape[0] == 1
    assert menu_items[menu_items["itm_id"] == parsed["2025-10-14"][2]["itm_id"]].shape[0] == 1
    assert menu_items[menu_items["itm_id"] == parsed["2025-10-15"][0]["itm_id"]].shape[0] == 1
    assert menu_items[menu_items["itm_id"] == parsed["2025-10-15"][1]["itm_id"]].shape[0] == 1
    assert menu_items[menu_items["itm_id"] == parsed["2025-10-15"][2]["itm_id"]].shape[0] == 1

def test_MenuGenerator_multiple_days_multiple_meals_correct_meals():
    parsed = parse_generated_menu(menugenerator_multiple_days_multiple_meals_menu)

    assert parsed["2025-10-14"][0]["meal"] == 1
    assert parsed["2025-10-14"][1]["meal"] == 2
    assert parsed["2025-10-14"][2]["meal"] == 3
    assert parsed["2025-10-15"][0]["meal"] == 1
    assert parsed["2025-10-15"][1]["meal"] == 2
    assert parsed["2025-10-15"][2]["meal"] == 3

def test_MenuGenerator_full_duplicate():
    attempt_duplicate = generator.update_menu(menu = menugenerator_multiple_days_multiple_meals_menu, preferences = "high protein,low carb", allergens = "Peanuts,Shellfish", date = "2025-10-14", meal_numbers = [1,2,3], number_of_days = 2)
    assert attempt_duplicate == menugenerator_multiple_days_multiple_meals_menu

menugenerator_partial_duplicate = generator.update_menu(menu = menugenerator_multiple_days_multiple_meals_menu, preferences = "high protein,low carb", allergens = "Peanuts,Shellfish", date = "2025-10-14", meal_numbers = [2,3], number_of_days = 3)

def test_MenuGenerator_partial_duplicate_no_regression():
    parse_original = parse_generated_menu(menugenerator_multiple_days_multiple_meals_menu)
    parse_partial_duplicate = parse_generated_menu(menugenerator_partial_duplicate)

    assert parse_original["2025-10-14"][0] == parse_partial_duplicate["2025-10-14"][0]
    assert parse_original["2025-10-14"][1] == parse_partial_duplicate["2025-10-14"][1]
    assert parse_original["2025-10-14"][2] == parse_partial_duplicate["2025-10-14"][2]
    assert parse_original["2025-10-15"][0] == parse_partial_duplicate["2025-10-15"][0]
    assert parse_original["2025-10-15"][1] == parse_partial_duplicate["2025-10-15"][1]
    assert parse_original["2025-10-15"][2] == parse_partial_duplicate["2025-10-15"][2]
    
def test_MenuGenerator_partial_duplicate_valid_items():
    parse_partial_duplicate = parse_generated_menu(menugenerator_partial_duplicate)

    assert menu_items[menu_items["itm_id"] == parse_partial_duplicate["2025-10-16"][0]["itm_id"]].shape[0] == 1
    assert menu_items[menu_items["itm_id"] == parse_partial_duplicate["2025-10-16"][1]["itm_id"]].shape[0] == 1

def test_MenuGenerator_partial_duplicate_correct_meals():
    parse_partial_duplicate = parse_generated_menu(menugenerator_partial_duplicate)

    assert parse_partial_duplicate["2025-10-16"][0]["meal"] == 2
    assert parse_partial_duplicate["2025-10-16"][1]["meal"] == 3