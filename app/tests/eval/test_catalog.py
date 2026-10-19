import json
import sqlite3
from pathlib import Path

import pytest

from eval.catalog import Item, Restaurant, load_catalog

SEED_SQL = Path(__file__).resolve().parents[2] / "db" / "seed.sql"

MINI_SCHEMA = """
CREATE TABLE Restaurant (rtr_id INTEGER PRIMARY KEY, hours TEXT, status TEXT);
CREATE TABLE MenuItem (
  itm_id INTEGER PRIMARY KEY, rtr_id INTEGER, name TEXT, price INTEGER,
  calories INTEGER, instock INTEGER, allergens TEXT
);
"""

WEEK_HOURS = json.dumps({"Mon": [1700, 2100], "Tue": []})


def make_db(path, restaurants, items):
    """Build a tiny DB. restaurants: (rtr_id, hours, status); items: (itm_id, rtr_id, price,
    calories, instock, allergens)."""
    conn = sqlite3.connect(path)
    conn.executescript(MINI_SCHEMA)
    conn.executemany("INSERT INTO Restaurant VALUES (?, ?, ?)", restaurants)
    conn.executemany(
        "INSERT INTO MenuItem (itm_id, rtr_id, name, price, calories, instock, allergens) "
        "VALUES (?, ?, 'item', ?, ?, ?, ?)",
        items,
    )
    conn.commit()
    conn.close()
    return path


def test_loads_only_in_stock_items(tmp_path):
    db = make_db(
        tmp_path / "t.db",
        [(1, WEEK_HOURS, "Open")],
        [(10, 1, 1299, 650, 1, None), (11, 1, 899, 400, 0, None)],
    )

    catalog = load_catalog(db)

    assert catalog.items == {
        10: Item(itm_id=10, rtr_id=1, price_cents=1299, calories=650, allergens=())
    }


def test_skips_restaurants_that_are_not_open_and_their_items(tmp_path):
    db = make_db(
        tmp_path / "t.db",
        [(1, WEEK_HOURS, "Open"), (2, WEEK_HOURS, "Closed"), (3, WEEK_HOURS, None)],
        [(10, 1, 1000, 500, 1, None), (20, 2, 1000, 500, 1, None), (30, 3, 1000, 500, 1, None)],
    )

    catalog = load_catalog(db)

    assert list(catalog.restaurants) == [1]
    assert list(catalog.items) == [10]


def test_items_and_restaurants_are_ordered_by_id(tmp_path):
    db = make_db(
        tmp_path / "t.db",
        [(2, WEEK_HOURS, "Open"), (1, WEEK_HOURS, "Open")],
        [(30, 2, 1000, 500, 1, None), (10, 1, 1000, 500, 1, None), (20, 2, 1000, 500, 1, None)],
    )

    catalog = load_catalog(db)

    assert list(catalog.restaurants) == [1, 2]
    assert list(catalog.items) == [10, 20, 30]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Gluten, Soy, Egg", ("Gluten", "Soy", "Egg")),
        (" Dairy , ", ("Dairy",)),
        ("eggs,Eggs", ("eggs", "Eggs")),
        ("", ()),
        (None, ()),
    ],
)
def test_allergens_are_split_and_stripped_but_not_normalized(tmp_path, raw, expected):
    db = make_db(tmp_path / "t.db", [(1, WEEK_HOURS, "Open")], [(10, 1, 1000, 500, 1, raw)])

    assert load_catalog(db).items[10].allergens == expected


def test_hours_are_parsed_per_weekday(tmp_path):
    hours = json.dumps({"Mon": [1100, 1400, 1700, 2100], "Tue": [], "Wed": [600, 2200]})
    db = make_db(tmp_path / "t.db", [(1, hours, "Open")], [(10, 1, 1000, 500, 1, None)])

    assert load_catalog(db).restaurants[1] == Restaurant(
        rtr_id=1, hours={"Mon": (1100, 1400, 1700, 2100), "Tue": (), "Wed": (600, 2200)}
    )


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "not json",
        "[1700, 2100]",
        json.dumps({"Mon": "closed", "Tue": ["5pm"], "Wed": [True, False]}),
    ],
)
def test_missing_or_unreadable_hours_have_no_opening_times(tmp_path, raw):
    db = make_db(tmp_path / "t.db", [(1, raw, "Open")], [(10, 1, 1000, 500, 1, None)])

    assert load_catalog(db).restaurants[1].hours == {}


def test_missing_db_raises_with_init_hint_and_creates_no_file(tmp_path):
    db = tmp_path / "missing.db"

    with pytest.raises(FileNotFoundError, match=r"python app/scripts/init_db\.py"):
        load_catalog(db)
    assert not db.exists()


def test_db_without_menu_data_raises(tmp_path):
    db = tmp_path / "empty.db"
    sqlite3.connect(db).close()

    with pytest.raises(ValueError, match=r"python app/scripts/init_db\.py --force"):
        load_catalog(db)


def test_loads_the_seed_data(tmp_path):
    db = tmp_path / "seed.db"
    conn = sqlite3.connect(db)
    conn.executescript(SEED_SQL.read_text())
    conn.close()

    catalog = load_catalog(db)

    assert catalog.items and catalog.restaurants
    assert all(item.rtr_id in catalog.restaurants for item in catalog.items.values())
    # Raw tags survive: the seed has items tagged "Egg" alongside "Eggs".
    assert any("Egg" in item.allergens for item in catalog.items.values())
    assert all(len(r.hours) == 7 for r in catalog.restaurants.values())
