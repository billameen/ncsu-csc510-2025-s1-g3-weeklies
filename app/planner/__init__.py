"""
Weekly meal planner: picks every meal of the week at once with the OR-Tools CP-SAT solver.

Modules:
- `planner.solver`: `plan_week(request, menu)`, the entry point, and `PlanResult`.
- `planner.request`: `PlanRequest`, what the user asks for, checked when built.
- `planner.menu`: the menu model, `load_menu`, and `meal_cost_cents` (price + tax + fees).
- `planner.constraint`: the plug-in interface every rule implements.
- `planner.context`: `PlanContext`, the model and the helpers rules use.
- `planner.registry`: `@register`, rule discovery, and `rules_for(request)`.
- `planner.rules`: the built-in rules, one per module.
- `planner.fees`: `FeeSchedule`, tax and per-restaurant delivery and service fees (M4).
- `planner.allergens`: allergen normalization ("Egg" = "Eggs").
- `planner.targets`: parsing the calorie target and weekly budget typed on Edit Profile.

Import the submodule you need (e.g. ``from planner.solver import plan_week``); this package's
``__init__`` stays empty so importing `planner.targets` never loads OR-Tools.

Guides: ``app/docs/planner-rules.md`` (add a rule) and ``app/docs/why-a-solver.md``.
"""
