"""Small hand-built menus and requests for planner tests (imported by the test modules)."""

from datetime import date

from planner.menu import WEEKDAYS, Menu, MenuItem, Restaurant
from planner.request import PlanRequest

MONDAY = date(2026, 10, 19)
OPEN_ALL_DAY = {day: (600, 2300) for day in WEEKDAYS}


def item(itm_id, price_cents=1000, calories=600, allergens=(), rtr_id=1, name=None, **kw):
    return MenuItem(
        itm_id=itm_id,
        rtr_id=rtr_id,
        name=name or f"Item {itm_id}",
        description=kw.pop("description", ""),
        price_cents=price_cents,
        calories=calories,
        allergens=tuple(allergens),
        in_stock=kw.pop("in_stock", True),
    )


def restaurant(rtr_id=1, hours=None, status_open=True, name=None):
    return Restaurant(
        rtr_id=rtr_id,
        name=name or f"Restaurant {rtr_id}",
        status_open=status_open,
        hours=OPEN_ALL_DAY if hours is None else hours,
    )


def menu(items, restaurants=None, fees=None):
    restaurants = restaurants or [restaurant(r) for r in sorted({i.rtr_id for i in items})]
    return Menu(
        items={i.itm_id: i for i in sorted(items, key=lambda i: i.itm_id)},
        restaurants={r.rtr_id: r for r in restaurants},
        **({"fees": fees} if fees is not None else {}),
    )


def request(kcal=1800, budget_cents=100_000, days=1, meals=(1, 2, 3), **kw):
    return PlanRequest(
        daily_calorie_target=kcal,
        weekly_budget_cents=budget_cents,
        start=kw.pop("start", MONDAY),
        days=days,
        meals=meals,
        **kw,
    )
