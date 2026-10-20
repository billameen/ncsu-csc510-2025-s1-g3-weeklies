"""
Evaluate M4, fee-aware batching (GitHub issue #9), on M0's 100 users.

    python -m eval.m4 --seed 510                     # about 10 minutes; resumes if stopped
    python -m eval.m4 --seed 510 --max-seconds 150   # plan for at most 150 s, then report
    python -m eval.m4 --seed 510 --fresh             # forget earlier results and start over

Three planners plan every user's week from the app's seed menu (with its synthetic,
per-restaurant fees):

- ``m1``: the M1 solver with batching off: every meal its own delivery order. The baseline.
- ``m4_batching``: batching on (same restaurant, meals at most 6 h apart share an order).
- ``m4_pickup``: batching on, plus pickup where the user opted in. Users' pickup opt-ins are
  synthetic (see ``pickup_opt_in``): half the users opt into pickup at 5 restaurants on the
  weekend and one weekday.

Every week is checked by the M0 validator, which recomputes costs and checks the orders on
its own (eval.validate.validate_orders); nothing the planner reports is trusted.

Per-user results are appended to eval/results/m4_runs.jsonl as they finish, so a run that is
stopped (or limited with --max-seconds) picks up where it left off. The report, m4.json and
m4.md, and the poster chart m4_savings.png (needs matplotlib) are written from whatever is
done; the report says how many users that is.
"""

import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path

from planner.request import PlanRequest
from planner.solver import plan_week

from eval.catalog import Catalog, load_catalog
from eval.planners import menu_from_catalog
from eval.profiles import Profile, generate_profiles, user_seed
from eval.validate import (
    WEEK_START,
    WEEKDAYS,
    Meal,
    Order,
    PickupOptIn,
    ViolationKind,
    order_fee_cents,
    separate_fee_cents,
    validate_week,
)

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "app" / "CSC510_DB.db"
OUT = REPO / "eval" / "results"
PLANNERS = ("m1", "m4_batching", "m4_pickup")
LABELS = {"m1": "M1 (batching off)", "m4_batching": "M4 batching",
          "m4_pickup": "M4 batching + pickup"}

# The issue's targets.
TARGET_MEDIAN_SAVINGS_PCT = 25
TARGET_MAX_VARIETY_DROP = 2
ORDER_VIOLATIONS = (ViolationKind.FOOD_SAFETY, ViolationKind.MIXED_ORDER,
                    ViolationKind.ORDER_MISMATCH, ViolationKind.PICKUP_NOT_OPTED)


def pickup_opt_in(profile: Profile, catalog: Catalog, seed: int) -> PickupOptIn:
    """
    A user's synthetic pickup opt-in: deterministic per user. Half the users opt in, choosing
    5 restaurants and the weekend plus one weekday; the rest never pick up.
    """
    rng = random.Random(user_seed(seed, profile.user_id) ^ 0x4D34)
    if rng.random() >= 0.5:
        return PickupOptIn()
    restaurants = rng.sample(sorted(catalog.restaurants), k=min(5, len(catalog.restaurants)))
    days = ("Sat", "Sun", rng.choice(WEEKDAYS[:5]))
    return PickupOptIn(frozenset(restaurants), frozenset(days))


def plan_user(profile: Profile, catalog: Catalog, planner: str, seed: int) -> dict:
    """Plan one user's week with one planner and validate it. Returns a JSON-able record."""
    pickup = pickup_opt_in(profile, catalog, seed) if planner == "m4_pickup" else PickupOptIn()
    options = {}
    if planner != "m1":
        options["fee_cost"] = {
            "batching": True,
            "pickup_restaurants": sorted(pickup.restaurants),
            "pickup_days": sorted(pickup.days, key=WEEKDAYS.index),
        }
    request = PlanRequest(
        daily_calorie_target=profile.kcal_target,
        weekly_budget_cents=profile.budget_dollars * 100,
        start=WEEK_START,
        allergens=profile.allergens,
        options=options,
    )
    started = time.monotonic()
    result = plan_week(request, menu_from_catalog(catalog))
    seconds = time.monotonic() - started
    record = {"user_id": profile.user_id, "planner": planner, "status": result.status.value,
              "seconds": round(seconds, 3), "valid": False}
    if not result.ok:
        return record

    def meal(m):
        return Meal(WEEKDAYS[m.day.weekday()], m.meal, m.itm_id)

    meals = tuple(meal(m) for m in result.meals)
    orders = tuple(Order(tuple(meal(m) for m in o.meals), o.pickup) for o in result.orders)
    violations = validate_week(meals, profile, catalog, orders, pickup)
    record.update(
        valid=not violations,
        violations=sorted({v.kind.value for v in violations}),
        order_violations=sum(v.kind in ORDER_VIOLATIONS for v in violations),
        food_safety_violations=sum(v.kind is ViolationKind.FOOD_SAFETY for v in violations),
        fees_cents=sum(order_fee_cents(o, catalog) for o in orders),
        separate_fees_cents=separate_fee_cents(meals, catalog),
        orders=len(orders),
        batched_orders=sum(len(o.meals) > 1 for o in orders),
        pickup_orders=sum(o.pickup for o in orders),
        distinct_items=len({m.itm_id for m in meals}),
        planner_fees_cents=result.fees_cents,
    )
    return record


def summarize(records: dict, users: list[int]) -> dict:
    """Metrics per planner and the issue's pass/fail checks for each M4 planner."""
    def rec(planner, user):
        return records.get((user, planner))

    done = [u for u in users if all(rec(p, u) for p in PLANNERS)]
    per_planner = {}
    for p in PLANNERS:
        rs = [rec(p, u) for u in done]
        valid = [r for r in rs if r["valid"]]
        per_planner[p] = {
            "valid_week_pct": 100 * len(valid) / len(rs) if rs else None,
            "median_distinct_items": statistics.median(r["distinct_items"] for r in valid) if valid else None,
            "median_fees_cents": statistics.median(r["fees_cents"] for r in valid) if valid else None,
            "food_safety_violations": sum(r.get("food_safety_violations", 0) for r in rs),
            "order_violations": sum(r.get("order_violations", 0) for r in rs),
            "p95_seconds": sorted(r["seconds"] for r in rs)[max(0, -(-95 * len(rs) // 100) - 1)] if rs else None,
            "median_orders": statistics.median(r["orders"] for r in valid) if valid else None,
        }
    checks = {}
    for p in PLANNERS[1:]:
        both = [u for u in done if rec("m1", u)["valid"] and rec(p, u)["valid"]]
        savings = [100 * (rec("m1", u)["fees_cents"] - rec(p, u)["fees_cents"]) / rec("m1", u)["fees_cents"]
                   for u in both]
        median_savings = statistics.median(savings) if savings else None
        made_possible = [u for u in done if not rec("m1", u)["valid"] and rec(p, u)["valid"]]
        lost = [u for u in done if rec("m1", u)["valid"] and not rec(p, u)["valid"]]
        m1, mp = per_planner["m1"], per_planner[p]
        variety_drop = (m1["median_distinct_items"] - mp["median_distinct_items"]
                        if m1["median_distinct_items"] is not None and mp["median_distinct_items"] is not None else None)
        checks[p] = {
            "savings_pct": [round(x, 2) for x in savings],
            "median_savings_pct": median_savings,
            "savings_pass": median_savings is not None and median_savings >= TARGET_MEDIAN_SAVINGS_PCT,
            "valid_week_pct_m1": m1["valid_week_pct"],
            "valid_week_pct": mp["valid_week_pct"],
            "valid_pass": mp["valid_week_pct"] is not None and mp["valid_week_pct"] >= m1["valid_week_pct"],
            "variety_drop": variety_drop,
            "variety_pass": variety_drop is not None and variety_drop <= TARGET_MAX_VARIETY_DROP,
            "food_safety_violations": mp["food_safety_violations"],
            "food_safety_pass": mp["food_safety_violations"] == 0 and mp["order_violations"] == 0,
            "budgets_made_possible": len(made_possible),
            "users_made_possible": made_possible,
            "valid_weeks_lost": lost,
        }
    demo = None
    if checks.get("m4_batching", {}).get("savings_pct"):
        both = [u for u in done if rec("m1", u)["valid"] and rec("m4_batching", u)["valid"]]
        ranked = sorted(both, key=lambda u: (rec("m1", u)["fees_cents"] - rec("m4_batching", u)["fees_cents"])
                        / rec("m1", u)["fees_cents"])
        u = ranked[len(ranked) // 2]
        demo = {"user_id": u, "m1_fees_cents": rec("m1", u)["fees_cents"],
                "m4_batching_fees_cents": rec("m4_batching", u)["fees_cents"],
                "m4_pickup_fees_cents": rec("m4_pickup", u)["fees_cents"] if rec("m4_pickup", u)["valid"] else None}
    return {"users_total": len(users), "users_done": len(done), "planners": per_planner,
            "checks": checks, "median_user_demo": demo}


def _money(cents):
    return "n/a" if cents is None else f"${cents / 100:,.2f}"


def _num(x, suffix=""):
    return "n/a" if x is None else f"{x:.1f}{suffix}"


def render_markdown(report: dict) -> str:
    c, pp = report["checks"], report["planners"]
    mark = lambda ok: "✅ pass" if ok else "❌ fail"  # noqa: E731
    lines = [
        "# M4 results: fee-aware batching",
        "",
        f"{report['users_done']} of {report['users_total']} M0 users planned with each planner "
        "(seed menu, synthetic per-restaurant fees). Baseline: M1 with batching off.",
        "",
        "| Target | Goal | M4 batching | M4 batching + pickup |",
        "|---|---|---|---|",
        f"| Median weekly fee savings vs M1 | ≥ {TARGET_MEDIAN_SAVINGS_PCT}% | "
        + " | ".join(f"{_num(c[p]['median_savings_pct'], '%')} {mark(c[p]['savings_pass'])}" for p in PLANNERS[1:]) + " |",
        "| Valid-week rate | no drop vs M1 ("
        + _num(pp["m1"]["valid_week_pct"], "%") + ") | "
        + " | ".join(f"{_num(c[p]['valid_week_pct'], '%')} {mark(c[p]['valid_pass'])}" for p in PLANNERS[1:]) + " |",
        f"| Variety (median distinct items) | drop ≤ {TARGET_MAX_VARIETY_DROP} vs M1 ("
        + _num(pp["m1"]["median_distinct_items"]) + ") | "
        + " | ".join(f"{_num(pp[p]['median_distinct_items'])} (drop {_num(c[p]['variety_drop'])}) "
                     f"{mark(c[p]['variety_pass'])}" for p in PLANNERS[1:]) + " |",
        "| Food-safety window violations | 0 | "
        + " | ".join(f"{c[p]['food_safety_violations']} {mark(c[p]['food_safety_pass'])}" for p in PLANNERS[1:]) + " |",
        "| Budgets only possible with batching | report | "
        + " | ".join(str(c[p]["budgets_made_possible"]) for p in PLANNERS[1:]) + " |",
        "",
        "| Planner | Valid weeks | Median fees / week | Median orders / week | p95 planning time |",
        "|---|---|---|---|---|",
    ]
    for p in PLANNERS:
        lines.append(f"| {LABELS[p]} | {_num(pp[p]['valid_week_pct'], '%')} | {_money(pp[p]['median_fees_cents'])} "
                     f"| {_num(pp[p]['median_orders'])} | {_num(pp[p]['p95_seconds'], ' s')} |")
    demo = report.get("median_user_demo")
    if demo:
        lines += ["", f"Median user (user {demo['user_id']}): fees {_money(demo['m1_fees_cents'])} a week with M1 → "
                      f"{_money(demo['m4_batching_fees_cents'])} with batching"
                      + (f" → {_money(demo['m4_pickup_fees_cents'])} with batching + pickup." if demo["m4_pickup_fees_cents"] is not None else ".")]
    lines += ["", "Fee savings compare each user's fees with M1's fees for the same user; users without a "
                  "valid week from both planners are left out of that median. All fees are a synthetic model."]
    return "\n".join(lines) + "\n"


def render_chart(report: dict, path: Path) -> bool:
    """Per-user fee savings, one panel per M4 planner. Returns False if matplotlib is missing."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    surface, ink, muted, grid = "#fcfcfb", "#0b0b0b", "#898781", "#e1e0d9"
    colors = {"m4_batching": "#2a78d6", "m4_pickup": "#eb6834"}
    plt.rcParams.update({"font.size": 11, "axes.edgecolor": grid, "axes.labelcolor": ink,
                         "xtick.color": muted, "ytick.color": muted, "font.family": "DejaVu Sans"})
    fig, axes = plt.subplots(2, 1, figsize=(8, 6), sharex=True, facecolor=surface)
    bins = list(range(0, 66, 5))
    for ax, p in zip(axes, PLANNERS[1:]):
        c = report["checks"][p]
        ax.set_facecolor(surface)
        ax.hist(c["savings_pct"], bins=bins, color=colors[p], edgecolor=surface, linewidth=2)
        ax.axvline(TARGET_MEDIAN_SAVINGS_PCT, color=muted, linestyle=(0, (4, 3)), linewidth=1.5)
        med = c["median_savings_pct"]
        if med is not None:
            ax.axvline(med, color=ink, linewidth=2)
            ax.annotate(f"median {med:.0f}%", xy=(med, ax.get_ylim()[1] * 0.92), xytext=(6, 0),
                        textcoords="offset points", color=ink, fontsize=10)
        ax.annotate("target 25%", xy=(TARGET_MEDIAN_SAVINGS_PCT, ax.get_ylim()[1] * 0.78), xytext=(-6, 0),
                    textcoords="offset points", ha="right", color=muted, fontsize=10)
        ax.set_title(f"{LABELS[p]}: {len(c['savings_pct'])} users", loc="left", color=ink, fontsize=11)
        ax.set_ylabel("users")
        ax.grid(axis="y", color=grid, linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    axes[-1].set_xlabel("weekly fee savings vs M1 (batching off), %")
    fig.suptitle("M4: fewer orders, lower fees", x=0.06, ha="left", color=ink, fontsize=13, fontweight="bold")
    fig.tight_layout()
    fig.savefig(path, dpi=200, facecolor=surface)
    plt.close(fig)
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the M4 evaluation (GitHub issue #9).")
    parser.add_argument("--seed", type=int, default=510)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--max-seconds", type=float, default=None,
                        help="stop planning after this long and report what is done")
    parser.add_argument("--fresh", action="store_true", help="discard earlier per-user results")
    args = parser.parse_args(argv)

    catalog = load_catalog(args.db)
    profiles = generate_profiles(args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    runs = args.out / "m4_runs.jsonl"
    if args.fresh and runs.exists():
        runs.unlink()
    records = {}
    if runs.exists():
        for line in runs.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("seed") == args.seed:
                    records[(r["user_id"], r["planner"])] = r

    started = time.monotonic()
    stopped_early = False
    with runs.open("a", encoding="utf-8") as f:
        for profile in profiles:
            for planner in PLANNERS:
                if (profile.user_id, planner) in records:
                    continue
                if args.max_seconds is not None and time.monotonic() - started > args.max_seconds:
                    stopped_early = True
                    break
                r = plan_user(profile, catalog, planner, args.seed)
                r["seed"] = args.seed
                records[(profile.user_id, planner)] = r
                f.write(json.dumps(r) + "\n")
                f.flush()
            if stopped_early:
                break

    report = summarize(records, [p.user_id for p in profiles])
    report["seed"] = args.seed
    (args.out / "m4.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (args.out / "m4.md").write_text(render_markdown(report), encoding="utf-8")
    chart = render_chart(report, args.out / "m4_savings.png")
    print(render_markdown(report))
    if not chart:
        print("(m4_savings.png not drawn: install matplotlib to draw the savings chart)")
    if report["users_done"] < report["users_total"]:
        print(f"Stopped after {report['users_done']} users; run again to continue.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
