"""Render TRADES_V7_GUIDE.md as a self-contained Aureas-branded HTML page.

The Markdown text is converted verbatim by pandoc; only markup and styling are added.
"""

from __future__ import annotations

import html
import json
import re
import subprocess
from pathlib import Path

STUDY = Path(__file__).resolve().parent
SRC = STUDY / "TRADES_V7_GUIDE.md"
OUT = STUDY / "TRADES_V7_GUIDE.html"
AC_BRAND = Path.home() / "agent-commons/.venv/bin/ac-brand"

LAYOUT_CSS = """
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body.ca-document { margin: 0; font-size: 16px; }
.ca-report-header { padding: 56px 0 44px; }
.wrap { max-width: 1180px; margin: 0 auto; padding: 0 40px; }
.ca-report-header h1 { margin: 10px 0 12px; font-size: 38px; line-height: 1.15; letter-spacing: -0.5px; font-weight: 700; color: #fff; }
.ca-report-header .lede { margin: 0; font-size: 18px; color: var(--ca-color-text-muted); max-width: 760px; }
.ca-report-header hr.ca-rule-accent { margin: 22px 0 0; }
.snapshot { margin: -22px auto 0; max-width: 1100px; position: relative; }
.snapshot .ca-callout { background: #fff; border-color: var(--ca-color-gold-500); box-shadow: 0 6px 20px rgba(13, 27, 42, 0.08); padding: 16px 20px; }
.snapshot .ca-callout p { margin: 0; }
.layout { display: grid; grid-template-columns: 240px minmax(0, 1fr); gap: 40px; margin-top: 36px; padding-bottom: 64px; }
nav.toc { position: sticky; top: 24px; align-self: start; max-height: calc(100vh - 48px); overflow-y: auto; font-size: 13.5px; }
nav.toc .ca-section-label { margin-bottom: 10px; }
nav.toc ul { list-style: none; margin: 0; padding: 0; }
nav.toc li { margin: 0; }
nav.toc a { display: block; padding: 5px 0 5px 12px; color: var(--ca-color-text-primary); text-decoration: none; border-left: 2px solid #e3e8ef; }
nav.toc a:hover { color: var(--ca-color-navy-900); border-left-color: var(--ca-color-gold-500); }
nav.toc li.l3 a { padding-left: 24px; font-size: 12.5px; color: #5a6a80; }
main { min-width: 0; }
main > section.level2 { background: #fff; border: 1px solid #e3e8ef; padding: 36px 44px 28px; margin-bottom: 32px; }
main h2 { color: var(--ca-color-navy-900); font-size: 26px; line-height: 1.25; margin: 0 0 6px; letter-spacing: -0.2px; }
main h2 + hr.ca-rule-accent { margin: 12px 0 24px; }
main h3 { color: var(--ca-color-navy-700); font-size: 19px; margin: 34px 0 10px; padding-top: 18px; border-top: 1px solid #e3e8ef; }
main section.level2 > section.level3:first-of-type > h3 { border-top: none; padding-top: 0; margin-top: 8px; }
main p, main li { max-width: 78ch; }
main p { margin: 0 0 14px; }
main strong { color: var(--ca-color-navy-900); }
main a { color: var(--ca-color-blue-500); text-decoration: none; border-bottom: 1px solid rgba(30, 111, 191, 0.3); }
main a:hover { border-bottom-color: var(--ca-color-blue-500); }
main code { font-family: var(--ca-font-data); font-size: 0.88em; background: var(--ca-color-surface-page); padding: 1px 5px; border: 1px solid #e3e8ef; }
ul.ca-bullets, ol.ca-numbers { margin: 0 0 16px; }
ul.ca-bullets > li, ol.ca-numbers > li { margin-bottom: 6px; }
ul.ca-bullets ul.ca-bullets { margin: 6px 0 4px; }
.table-wrap { overflow-x: auto; margin: 6px 0 22px; border: 1px solid #e3e8ef; }
table.ca-table { font-size: 14px; font-variant-numeric: tabular-nums; }
table.ca-table th { background: var(--ca-color-navy-900); color: #fff; text-align: left; font-weight: 600; padding: 10px 12px; font-size: 13px; letter-spacing: 0.01em; vertical-align: bottom; }
table.ca-table td { padding: 9px 12px; border-top: 1px solid #e3e8ef; vertical-align: top; }
table.ca-table tbody tr:nth-child(even) td { background: var(--ca-color-surface-page); }
table.ca-table td:first-child { color: var(--ca-color-navy-900); font-weight: 600; }
table.ca-table strong { color: var(--ca-color-navy-900); }
footer.page-foot { background: var(--ca-color-navy-900); color: var(--ca-color-text-muted); font-size: 12.5px; padding: 22px 0; }
footer.page-foot .ca-eyebrow { display: inline-block; margin-right: 12px; }
@media (max-width: 960px) {
  .layout { grid-template-columns: 1fr; }
  nav.toc { position: static; max-height: none; }
  main > section.level2 { padding: 24px 20px; }
  .wrap { padding: 0 20px; }
}
@media print {
  nav.toc { display: none; }
  .layout { display: block; margin-top: 16px; }
  .snapshot { margin-top: 12px; }
  .snapshot .ca-callout { box-shadow: none; }
  main > section.level2 { border: none; padding: 0; margin-bottom: 20px; page-break-before: always; }
  main > section.level2:first-child { page-break-before: auto; }
  .table-wrap, h3 { page-break-inside: avoid; }
  body.ca-document { background: #fff; }
}
"""


def _document_css() -> str:
    paths = json.loads(subprocess.check_output([str(AC_BRAND), "paths"], text=True))
    return Path(paths["surfaces"]["document"]["document.css"]).read_text()


def _pandoc(md: str) -> str:
    return subprocess.check_output(
        ["pandoc", "-f", "gfm", "-t", "html5", "--section-divs", "--wrap=none"],
        input=md,
        text=True,
    )


def _brand_markup(body: str) -> str:
    body = re.sub(r"<ul>", '<ul class="ca-bullets">', body)
    body = re.sub(r"<ol>", '<ol class="ca-numbers">', body)
    body = re.sub(r"<table>", '<div class="table-wrap"><table class="ca-table">', body)
    body = body.replace("</table>", "</table></div>")
    body = re.sub(r"<hr\s*/?>", "", body)
    body = re.sub(r"(</h2>)", r'\1\n<hr class="ca-rule-accent" />', body)
    return body


def _toc(body: str) -> str:
    items = []
    for m in re.finditer(
        r'<section id="(?P<id>[^"]+)" class="level(?P<lv>[23])">\s*<h(?P=lv)>(?P<t>.*?)</h(?P=lv)>',
        body,
    ):
        label = re.sub(r"<[^>]+>", "", m["t"])
        items.append(
            f'<li class="l{m["lv"]}"><a href="#{m["id"]}">{label}</a></li>'
        )
    return "\n".join(items)


def main() -> int:
    md = SRC.read_text()
    title_m = re.match(r"# (.+)\n\n(.+)\n\n(.+)\n\n---\n", md)
    if not title_m:
        raise SystemExit("unexpected guide header layout")
    title, lede_md, snapshot_md = title_m.groups()
    rest = md[title_m.end():]

    lede = _pandoc(lede_md).strip()
    snapshot = _pandoc(snapshot_md).strip()
    body = _brand_markup(_pandoc(rest))
    toc = _toc(body)

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{html.escape(title)}</title>
<style>
{_document_css()}
{LAYOUT_CSS}
</style>
</head>
<body class="ca-document">
<header class="ca-report-header">
  <div class="wrap">
    <div class="ca-eyebrow">Aureas · Research note</div>
    <h1>{html.escape(title)}</h1>
    {lede.replace("<p>", '<p class="lede">', 1)}
    <hr class="ca-rule-accent" />
  </div>
</header>
<div class="wrap">
  <div class="snapshot"><aside class="ca-callout">{snapshot}</aside></div>
  <div class="layout">
    <nav class="toc" aria-label="Contents">
      <div class="ca-section-label">Contents</div>
      <ul>
{toc}
      </ul>
    </nav>
    <main>
{body}
    </main>
  </div>
</div>
<footer class="page-foot">
  <div class="wrap"><span class="ca-eyebrow">Aureas</span>{html.escape(title)}</div>
</footer>
</body>
</html>
"""
    OUT.write_text(page)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
