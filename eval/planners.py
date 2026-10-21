"""
The planner under test, M1 (the CP-SAT solver in app/planner), behind the eval's planner
interface: (profile, catalog, seed) -> meals, or `NoValidWeek` with the reason the user is
shown. The validator still checks every week M1 returns; nothing here is trusted.
"""

from dataclasses import dataclass

from planner.menu import Menu, MenuItem, Restaurant
from planner.request import PlanRequest
from planner.solver import DEFAULT_WORK_LIMIT, Status, plan_week

from eval.catalog import Catalog
from eval.profiles import Profile
from eval.validate import WEEK_START, WEEKDAYS, Meal


@dataclass(frozen=True)
class NoValidWeek:
    """A planner's explicit "no valid week" answer, with the reason given to the user."""

    reason: str


def m1_solver(
    profile: Profile, catalog: Catalog, seed: int, *, work_limit: float = DEFAULT_WORK_LIMIT
) -> tuple[Meal, ...] | NoValidWeek:
    """
    M1: plan the user's week with the solver and its default rules, as /generate_plan does.
    seed is unused: the solver is deterministic. The catalog's items are all in stock and
    from open restaurants (see eval.catalog), so in_stock passes everything and
    restaurant_open checks hours. work_limit is the solver's; tests lower it for speed.
    """
    request = PlanRequest(
        daily_calorie_target=profile.kcal_target,
        weekly_budget_cents=profile.budget_dollars * 100,
        start=WEEK_START,
        allergens=profile.allergens,
    )
    result = plan_week(request, menu_from_catalog(catalog), work_limit=work_limit)
    if result.status is Status.TIMED_OUT:
        # "No valid week", but without a reason the user can act on, so it must not count
        # toward explained_pct.
        return None
    if not result.ok:
        return NoValidWeek(result.explanation or "")
    return tuple(Meal(WEEKDAYS[m.day.weekday()], m.meal, m.itm_id) for m in result.meals)


def menu_from_catalog(catalog: Catalog) -> Menu:
    """The planner's view of an eval catalog. Names and descriptions are not loaded."""
    return Menu(
        items={
            i.itm_id: MenuItem(
                itm_id=i.itm_id,
                rtr_id=i.rtr_id,
                name="",
                description="",
                price_cents=i.price_cents,
                calories=i.calories,
                allergens=i.allergens,
                in_stock=True,
            )
            for i in catalog.items.values()
        },
        restaurants={
            r.rtr_id: Restaurant(rtr_id=r.rtr_id, name="", status_open=True, hours=r.hours)
            for r in catalog.restaurants.values()
        },
        fees=catalog.fees,
    )
