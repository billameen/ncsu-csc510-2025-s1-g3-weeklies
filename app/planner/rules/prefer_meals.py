"""Edit rule: a preference for some meals ("cheaper lunches if possible", "more variety")."""

from planner.constraint import SoftConstraint
from planner.match import Condition
from planner.registry import register
from planner.scope import EVERY_MEAL

# Goal -> default weight, in the cents-equivalent units every soft rule uses. prefer_current
# charges 1000 ($10) for each meal an edit changes, so these say how much better a meal must
# be before it is swapped: 50 cents cheaper, 50 kcal lighter or heavier, one repeat fewer,
# or one more meal that matches.
GOALS = {
    "cheaper": 20,
    "fewer_calories": 20,
    "more_calories": 20,
    "variety": 3000,
    "match": 3000,
}
# Weights in a closest option, where the other edits become preferences worth $50 a missed
# meal (prefer_edits): small enough that a wish only breaks ties and never makes the plan
# miss more of what the user required.
CLOSEST_GOALS = {
    "cheaper": 1,
    "fewer_calories": 1,
    "more_calories": 1,
    "variety": 100,
    "match": 100,
}


@register
class PreferMeals(SoftConstraint):
    """
    Inside its scope, prefer cheaper meals, fewer or more calories, fewer repeats, or meals
    that meet a condition ("vegetarian when you can"). A preference never breaks a hard rule
    and never makes an edit impossible.
    """

    name = "prefer_meals"
    summary = "Prefer some meals to be cheaper, lighter, more varied or match a condition."
    order = 235
    enabled_by_default = False
    default_weight = 0  # replaced by the goal's weight

    def __init__(self, goal: str = "cheaper", scope=None, condition=None, weight=None):
        if goal not in GOALS:
            raise ValueError(f"{self.name}: goal must be one of {', '.join(GOALS)}, got {goal!r}")
        if (goal == "match") != isinstance(condition, Condition):
            raise ValueError(f"{self.name}: a condition goes with goal 'match' and only with it")
        super().__init__(GOALS[goal] if weight is None else weight)
        self.goal = goal
        self.scope = scope or EVERY_MEAL
        self.condition = condition

    def apply(self, ctx):
        """Add the goal's penalty over the covered slots."""
        covered = [slot for slot in ctx.slots if self.scope.covers(slot)]
        if not covered:
            return
        if self.goal == "cheaper":
            ctx.add_penalty(self, ctx.cost_cents(covered))
        elif self.goal == "fewer_calories":
            ctx.add_penalty(self, ctx.calories(covered))
        elif self.goal == "more_calories":
            ctx.add_penalty(self, -ctx.calories(covered))
        elif self.goal == "match":
            misses = [
                var
                for slot in covered
                for item, var in ctx.picks(slot)
                if not self.condition.matches(item)
            ]
            if misses:
                ctx.add_penalty(self, sum(misses))
        else:  # variety: each pick of an item past its first, within the scope
            uses: dict[int, list] = {}
            for slot in covered:
                for item, var in ctx.picks(slot):
                    uses.setdefault(item.itm_id, []).append(var)
            for itm_id, picks in uses.items():
                if len(picks) > 1:
                    repeats = ctx.model.NewIntVar(0, len(picks) - 1, f"repeat_{itm_id}_{id(self)}")
                    ctx.model.Add(repeats >= sum(picks) - 1)
                    ctx.add_penalty(self, repeats)

    def soften(self):
        """This preference at a tie-breaking weight, for the closest option."""
        return PreferMeals(self.goal, self.scope, self.condition, CLOSEST_GOALS[self.goal])

    def __repr__(self) -> str:
        what = self.condition.describe() if self.condition else self.goal
        return f"PreferMeals({what!r}, {self.scope.describe()!r})"
