import os
import pandas as pd
import datetime
import time
import json
import random
import re
from typing import Tuple, List

import llm_toolkit as llm_toolkit
from sqlQueries import *

db_file = os.path.join(os.path.dirname(__file__), 'CSC510_DB.db')

## LLM error handling
MAX_LLM_TRIES = 3
LLM_ATTRIBUTE_ERROR = -1

## Increase to increase the sample size the AI can draw from at the cost of increased runtime
ITEM_CHOICES = 10

## Days of the week in an array - should be the same as in the database*
DAYS_OF_WEEK = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

## LLM Prompt - defined as global variables to enable testing
SYSTEM_TEMPLATE = "You are a health and nutrition expert planning meals for a customer based on their preferences. Use only the menu items provided under CSV CONTEXT."
PROMPT_TEMPLATE = '''Choose a meal for a customer based on their preferences: {preferences}
Make sure that the item makes sense for {meal}.
Provide only the itm_id as output. Do not provide names or descriptions.

CSV CONTEXT:
{context}'''

## Regex used for parsing a number from LLM Output
LLM_OUTPUT_MATCH = r"(\d+)"

## Preset Meal times - In the future, times will be user-provided
BREAKFAST_TIME = 1000
LUNCH_TIME = 1400
DINNER_TIME = 2000

def get_meal_and_order_time(meal_number : int) -> Tuple[str, int]:
    """
    Maps a meal number to it's cooresponding meal as a string as well as its cooreponding meal time
    """
    meal = ""
    order_time = -1
    match meal_number:
        case 1:
            meal = "breakfast"
            order_time = BREAKFAST_TIME
        case 2:
            meal = "lunch"
            order_time = LUNCH_TIME
        case 3:
            meal = "dinner"
            order_time = DINNER_TIME
        case _:
            raise ValueError("The meal number must be 1, 2, or 3")
    return meal, order_time

def get_weekday_and_increment(date: str) -> Tuple[str, str]:
    """
    Converts a date string in YYYY-MM-DD format to the corresponding day of the week and returns the next date
    """
    year, month, day = map(int, date.split("-"))
    try:
        date = datetime.datetime(year, month, day)
    except:
        raise ValueError("Unable to parse date string. Ensure it is formatted properly as to YYYY-MM-DD format")
    next_day = date + datetime.timedelta(days=1)
    return next_day.strftime(r"%Y-%m-%d"), DAYS_OF_WEEK[date.weekday()]

def format_llm_output(output: str) -> int:
    """
    Grabs the LLM output and extracts the item ID from it.
    Updated to be robust for both OpenAI (plain text) and Local models (tokens).
    """
    # Find all sequences of digits
    matches = re.findall(LLM_OUTPUT_MATCH, output)
    if matches:
        # If multiple numbers appear, usually the last one is the ID or the one we want.
        # OpenAI usually sends just "22", but sometimes "I chose 22".
        try:
            return int(matches[-1]) 
        except ValueError:
            return LLM_ATTRIBUTE_ERROR
            
    return LLM_ATTRIBUTE_ERROR

def limit_scope(items: pd.DataFrame, num_choices: int) -> List[int]:
    """
    Limits the number of items to ITEM_CHOICES by randomly selecting items if necessary
    """
    num_items = items.shape[0]
    choices = range(num_items)
    if num_items > num_choices:
        choices = random.sample(choices, num_choices)
    return choices

def filter_allergens(menu_items: pd.DataFrame, allergens: str) -> pd.DataFrame:
    """
    Filters out menu items that contain any of the specified allergens from the provided DataFrame
    """
    if not allergens:
        return menu_items
        
    for index, rows in menu_items.iterrows():
        if rows["allergens"] is not None:
            item_allergens = [x.strip().lower() for x in rows['allergens'].split(',')]
            user_allergens = [x.strip().lower() for x in allergens.split(',')]
            if any (allergen in item_allergens for allergen in user_allergens):
                menu_items.drop(index, inplace=True)
    return menu_items

def filter_closed_restaurants(restaurant: pd.DataFrame, weekday: str, time: int) -> pd.DataFrame:
    """
    Filters out restaurants that are closed at the specified time on the specified weekday
    """
    for index, rows in restaurant.iterrows():
        try:
            hours_json = rows["hours"]
            if not hours_json: continue # Skip check if no hours, or assume open? Assume open.
            
            # Simple check if hours is JSON-like
            if hours_json.strip().startswith('{'):
                opening_times = json.loads(hours_json).get(weekday, [])
                if not opening_times:
                    # Closed today
                    restaurant = restaurant[restaurant["rtr_id"] != rows["rtr_id"]]
                    continue
                    
                if len(opening_times) % 2 == 1:
                    # Odd opening times - cannot process, assume closed or keep?
                    # Original code removed it.
                    restaurant = restaurant[restaurant["rtr_id"] != rows["rtr_id"]]
                elif len(opening_times) >= 2:
                    is_open = False
                    for x in range(int(len(opening_times) / 2)):
                        if opening_times[x*2] <= time and opening_times[x*2+1] >= time:
                            is_open = True
                    if not is_open:
                        restaurant = restaurant[restaurant["rtr_id"] != rows["rtr_id"]]
                else:
                    restaurant = restaurant[restaurant["rtr_id"] != rows["rtr_id"]]
        except Exception as e:
            # If hours parsing fails, safe to ignore or drop. Original dropped.
            pass
            
    return restaurant

class MenuGenerator:
    """
    MenuGenerator class that uses an LLM to generate menu items based on user preferences and restrictions
    """
    
    def __init__(self, tokens: int = 500):
        """
        Initializes the MenuGenerator with menu items and restaurants from the database and initializes
        the local LLM.
        """
        conn = create_connection(db_file)
        # Ensure we only fetch active items
        self.menu_items = pd.read_sql_query("SELECT * FROM MenuItem WHERE instock = 1 OR instock IS NULL", conn)
        self.restaurants = pd.read_sql_query("SELECT rtr_id, hours FROM Restaurant WHERE status='Open' OR status IS NULL", conn)
        close_connection(conn)
        
        self.generator = llm_toolkit.LLM(tokens=tokens)

    def __get_context(self, allergens: str, weekday: str, order_time: int, num_choices: int) -> Tuple[str, List[int]]:
        """
        Generates the context block for the LLM based on the provided allergens, date, and order time
        """
        start = time.time()
        
        combined = pd.merge(self.menu_items, self.restaurants, on="rtr_id", how="left")

        ## Removes restaurants that are closed during the order time
        combined = filter_closed_restaurants(combined, weekday, order_time)
        
        ## Removes items that contain allergens
        combined = filter_allergens(combined, allergens)

        ## Randomly selects ITEM_CHOICES number of items to present to the LLM
        choices = limit_scope(combined, num_choices)

        context_data = "item_id,name,description,price,calories\n"
        
        ## Create the context data with the chosen items
        item_ids = []
        for x in choices:
            row = combined.iloc[x]
            context_data += f"{row['itm_id']},{row['name']},{row['description']},{row['price']},{row['calories']}\n"
            item_ids.append(row['itm_id'])

        end = time.time()
        # print("Context block generated in %.4f seconds" % (end - start))
        return context_data, item_ids

    def __pick_menu_item(self, preferences: str, allergens: str, weekday: str, meal_number: int) -> int:
        """
        Picks a menu item based on user preferences, allergens, date, and meal number
        """
        meal, order_time = get_meal_and_order_time(meal_number)

        num_choices = ITEM_CHOICES
        llm_output = ""

        ## Tries to get output from LLM a number of times, increasing the number of options every time
        for x in range(MAX_LLM_TRIES):
            context, item_ids = self.__get_context(allergens, weekday, order_time, num_choices)

            ## Gets the prompt
            system = SYSTEM_TEMPLATE
            prompt = PROMPT_TEMPLATE

            ## Initializes variables in prompt
            prompt = prompt.replace("{preferences}", preferences)
            prompt = prompt.replace("{context}", context)
            prompt = prompt.replace("{meal}", meal)

            llm_output = self.generator.generate(system, prompt)
            output = format_llm_output(llm_output)
            
            # Validation: Output must be a number AND present in the provided context IDs
            if output > 0 and output in item_ids:
                return output
                
            ## If failed, try increasing the number of choices for next loop
            num_choices += ITEM_CHOICES
            print(f"LLM Retrying ({x+1}/{MAX_LLM_TRIES})... Output was: {llm_output}")
            
        raise RuntimeError(f'''LLM has failed {MAX_LLM_TRIES} times to generate a meal. Output: {llm_output}''')
    
    def update_menu(self, menu: str, preferences: str, allergens: str, date: str, meal_numbers: List[int], number_of_days: int = 1, goal: str = "") -> str:
        """
        Updates the menu string with a new menu item based on user preferences.
        """
        # If a goal is provided, prepend it to preferences
        if goal:
            preferences = f"GOAL: {goal}. {preferences}"

        next_date, current_weekday = get_weekday_and_increment(date)
        
        # Ensure menu is a string to avoid errors
        if not menu:
            menu = ""
            
        for x in range(number_of_days):
            for meal_number in meal_numbers:
                # Regex check for existing: [2025-10-27, 123, 1]
                pattern = fr"\[{date},\d+,{meal_number}\]"
                if re.search(pattern, menu):
                    # Already exists
                    continue

                itm_id = self.__pick_menu_item(preferences, allergens, current_weekday, meal_number)
                
                # Append to menu string
                new_entry = f"[{date},{itm_id},{meal_number}]"
                if len(menu) > 0:
                    menu = f"{menu},{new_entry}"
                else:
                    menu = new_entry
                    
            date = next_date
            next_date, current_weekday = get_weekday_and_increment(date)
            
        return menu