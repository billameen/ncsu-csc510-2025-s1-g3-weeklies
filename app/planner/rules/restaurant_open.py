"""Hard rule: only plan items from restaurants that are open at the meal's time."""

from planner.constraint import ItemFilter
from planner.registry import register


@register
class RestaurantOpen(ItemFilter):
    """
    Skip items whose restaurant is not taking orders at the meal's time on that day: its
    status is not Open, or the time is outside its hours (see Restaurant.is_open_at). Meal
    times are fixed: breakfast 10:00, lunch 14:00, dinner 20:00. Items from a restaurant
    missing from the menu are skipped too.
    """

    name = "restaurant_open"
    summary = "Every item comes from a restaurant that is open at that meal's time."
    blocked_reason = "come from restaurants that are closed then"
    order = 11

    def allows(self, item, slot, ctx):
        """True if the item's restaurant takes orders at the slot's time."""
        restaurant = ctx.menu.restaurants.get(item.rtr_id)
        return restaurant is not None and restaurant.is_open_at(slot.weekday, slot.time)

    def describe_block(self, slot, ctx):
        """Names the meal time, or says no restaurant is taking orders at all."""
        if not any(r.status_open for r in ctx.menu.restaurants.values()):
            return "come from restaurants that are not taking orders"
        return f"come from restaurants closed at {slot.time // 100}:{slot.time % 100:02d}"
