import re
import pytest

import llm_toolkit as llm_toolkit
import menu_generation as menu_generation

test_generator = llm_toolkit.LLM(tokens = 100)

# def test_llm():
#     output = test_generator.generate("This is a test", "test")
#     match = r"<\|start_of_role\|>assistant<\|end_of_role\|>(.*)<\|end_of_text\|>"
#     assert re.search(match, output).group(1) is not None, "Unable to get LLM output from llm_toolkit"
#     try:
#         re.search(match, output).group(2)
#         assert False
#     except Exception:
#         assert True

# def test_prompt():
#     prompt = menu_generation.PROMPT_TEMPLATE
#     prompt = prompt.replace("{preferences}", "high protein, low carb")
#     prompt = prompt.replace("{context}", '''item_id,name,description,price,calories
# 262,Kimchi Fried Rice,Fried rice with kimchi, vegetables, and a fried egg.,1400,650
# 110,Chicken Pot Pie,Flaky crust filled with chicken, vegetables, and a creamy sauce.,1600,700
# 235,Crispy Brussels Sprouts,Crispy Brussels sprouts with balsamic glaze and parmesan cheese.,1200,450
# 74,Sweet Potato Fries,Crispy sweet potato fries with a sprinkle of sea salt.,750,320
# 186,Pan-Seared Duck Breast,Pan-seared duck breast with cherry reduction and wild rice pilaf.,3200,750
# 107,Pan-Seared Salmon,Pan-seared salmon with roasted vegetables and balsamic glaze.,2000,550
# 252,Fried Green Tomatoes,Fried green tomatoes with remoulade sauce.,1000,350
# 175,Arancini,Fried risotto balls filled with mozzarella and meat ragu.,800,400
# 70,Potato Salad,Classic potato salad with mayonnaise, mustard, and celery.,600,350
# 195,Seasonal Fruit Tart,Pastry tart filled with seasonal fruit and pastry cream.,1200,400''')
#     prompt = prompt.replace("{meal}", "dinner")
#     output = test_generator.generate(menu_generation.SYSTEM_TEMPLATE, prompt)
#     match = r"<\|start_of_role\|>assistant<\|end_of_role\|>(\d+)<\|end_of_text\|>"
#     assert int(re.search(match, output).group(1)) is not None, "Direct Menu Generation Prompting Failed"
#     try:
#         re.search(match, output).group(2)
#         assert False
#     except Exception:
#         assert True