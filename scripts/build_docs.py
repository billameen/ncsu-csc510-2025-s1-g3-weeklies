# scripts/build_docs.py
import pathlib, html
from markdown import markdown

ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE = ROOT / "app" / "site"
DOCS_SRC = ROOT / "app" / "docs"
DOCS_OUT = SITE / "docs"

def wrap_html(title, body, rel_css):
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<link rel="stylesheet" href="{rel_css}">
</head><body class="pdoc"><main class="pdoc">
<article>{body}</article>
<p><a href="../app.html">← Back to API Reference</a></p>
</main></body></html>"""

def build_markdown_pages():
    DOCS_OUT.mkdir(parents=True, exist_ok=True)
    for md in DOCS_SRC.glob("*.md"):
        title = md.stem.replace("-", " ").title()
        body = markdown(md.read_text(encoding="utf-8"), extensions=["tables","fenced_code"])
        (DOCS_OUT / f"{md.stem}.html").write_text(
            wrap_html(title, body, "../assets/custom.css"), encoding="utf-8"
        )

def write_index_html():
    (SITE / "index.html").write_text(
        """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Project Docs</title>
<link rel="stylesheet" href="assets/custom.css">
</head><body class="pdoc"><main class="pdoc">
<h1>Project Documentation</h1>
<ul>
  <li><a href="app.html">🧩 API Reference (pdoc)</a></li>
</ul>
</main></body></html>""",
        encoding="utf-8"
    )

if __name__ == "__main__":
    build_markdown_pages()
    write_index_html()
