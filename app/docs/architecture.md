# Architecture (Overview)

- **Framework**: Flask  
- **Entrypoint**: Flask_app.py  
- **Database helpers**: sqlQueries.py (use only provided helpers)  
- **Templates / Static**: templates/, static/  
- **Meal planner**: planner/ (OR-Tools CP-SAT). `/generate_plan` calls `planner.solver.plan_week`;
  each rule is a plug-in in planner/rules/ (see [Planner Rules](./planner-rules.html)).
  `PLANNER=llm` switches back to the v1 LLM planner in menu_generation.py.  
- **Evaluation**: eval/ at the repository root (see [How We Evaluate](./evaluation.html)).  

This document intentionally focuses on what’s present today.
