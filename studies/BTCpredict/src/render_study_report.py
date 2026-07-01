"""Render study report Markdown to styled HTML."""
from __future__ import annotations

import re
from pathlib import Path


_CSS = """
:root {
  --bg: #fafafa;
  --fg: #1a1a1a;
  --muted: #555;
  --border: #ddd;
  --accent: #1a4d8c;
  --code-bg: #f0f0f0;
  --pass: #1a7f37;
  --fail: #cf222e;
}
* { box-sizing: border-box; }
body {
  font-family: "Georgia", "Times New Roman", serif;
  line-height: 1.55;
  max-width: 52rem;
  margin: 0 auto;
  padding: 2rem 1.5rem 4rem;
  background: var(--bg);
  color: var(--fg);
}
h1, h2, h3, h4 { font-family: "Helvetica Neue", Arial, sans-serif; color: var(--accent); }
h1 { font-size: 1.9rem; border-bottom: 2px solid var(--accent); padding-bottom: 0.4rem; }
h2 { font-size: 1.45rem; margin-top: 2.2rem; border-bottom: 1px solid var(--border); }
h3 { font-size: 1.15rem; margin-top: 1.6rem; }
.meta { color: var(--muted); font-size: 0.95rem; margin-bottom: 2rem; }
.toc { background: #fff; border: 1px solid var(--border); padding: 1rem 1.5rem; margin: 1.5rem 0 2.5rem; }
.toc ul { margin: 0.3rem 0; padding-left: 1.2rem; }
.toc a { color: var(--accent); text-decoration: none; }
.toc a:hover { text-decoration: underline; }
table { border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: 0.92rem; }
th, td { border: 1px solid var(--border); padding: 0.45rem 0.65rem; text-align: left; }
th { background: #eee; }
tr:nth-child(even) { background: #f7f7f7; }
code, pre { font-family: "Menlo", "Consolas", monospace; font-size: 0.88rem; }
code { background: var(--code-bg); padding: 0.1rem 0.35rem; border-radius: 3px; }
pre { background: var(--code-bg); padding: 1rem; overflow-x: auto; border-radius: 4px; }
blockquote {
  border-left: 4px solid var(--accent);
  margin: 1rem 0;
  padding: 0.5rem 1rem;
  background: #fff;
  color: var(--muted);
}
.pass { color: var(--pass); font-weight: bold; }
.fail { color: var(--fail); font-weight: bold; }
hr { border: none; border-top: 1px solid var(--border); margin: 2rem 0; }
.artifact { font-family: monospace; font-size: 0.85rem; color: #333; }
footer { margin-top: 3rem; font-size: 0.85rem; color: var(--muted); border-top: 1px solid var(--border); padding-top: 1rem; }
"""


def _slug(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"\s+", "-", s.strip())[:60]


def md_to_html(md: str) -> str:
    """Lightweight MD→HTML (no external deps). Handles headings, tables, lists, code."""
    lines = md.splitlines()
    out: list[str] = []
    in_code = False
    in_table = False
    in_ul = False
    in_ol = False
    in_bq = False

    def close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    def close_table() -> None:
        nonlocal in_table
        if in_table:
            out.append("</tbody></table>")
            in_table = False

    def inline(s: str) -> str:
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", s)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
        return s

    for raw in lines:
        line = raw.rstrip()

        if line.startswith("```"):
            close_lists()
            close_table()
            if in_bq:
                out.append("</blockquote>")
                in_bq = False
            if not in_code:
                in_code = True
                out.append("<pre><code>")
            else:
                in_code = False
                out.append("</code></pre>")
            continue

        if in_code:
            out.append(line.replace("&", "&amp;").replace("<", "&lt;"))
            continue

        if line.startswith("|") and "|" in line[1:]:
            close_lists()
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(set(c) <= {"-", ":"} for c in cells):
                continue
            if not in_table:
                out.append("<table><thead><tr>")
                for c in cells:
                    out.append(f"<th>{inline(c)}</th>")
                out.append("</tr></thead><tbody>")
                in_table = True
            else:
                out.append("<tr>")
                for c in cells:
                    out.append(f"<td>{inline(c)}</td>")
                out.append("</tr>")
            continue
        else:
            close_table()

        if line.startswith("> "):
            close_lists()
            if not in_bq:
                out.append("<blockquote>")
                in_bq = True
            out.append(f"<p>{inline(line[2:])}</p>")
            continue
        elif in_bq and line.strip() == "":
            out.append("</blockquote>")
            in_bq = False
        elif in_bq:
            out.append(f"<p>{inline(line)}</p>")
            continue

        if line.startswith("---"):
            close_lists()
            out.append("<hr>")
            continue

        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            close_lists()
            level = len(m.group(1))
            title = m.group(2)
            sid = _slug(title)
            out.append(f'<h{level} id="{sid}">{inline(title)}</h{level}>')
            continue

        if re.match(r"^[-*]\s+", line):
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{inline(line[2:].strip())}</li>")
            continue

        if re.match(r"^\d+\.\s+", line):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            text = re.sub(r"^\d+\.\s+", "", line)
            out.append(f"<li>{inline(text)}</li>")
            continue

        close_lists()
        if line.strip() == "":
            continue
        out.append(f"<p>{inline(line)}</p>")

    close_lists()
    close_table()
    if in_bq:
        out.append("</blockquote>")
    if in_code:
        out.append("</code></pre>")
    return "\n".join(out)


def render_study_report_html(md_path: Path, html_path: Path, *, title: str) -> None:
    md = md_path.read_text(encoding="utf-8")
    body = md_to_html(md)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>{_CSS}</style>
</head>
<body>
{body}
<footer>
  Generated from <span class="artifact">{md_path.name}</span> —
  CryoQuant BTCpredict v1 study report.
</footer>
</body>
</html>
"""
    html_path.write_text(html, encoding="utf-8")
