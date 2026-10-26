"""Build the final report: docs/report/chapters/*.md → docs/report/AdaptiveCare-Flow-Report.docx.

    .venv/bin/python scripts/build_report.py

Markers inside the chapters:
- ``{{uml U10}}`` becomes the rendered diagram ``docs/report/figures/<file>.png`` with the
  diagram's own title as caption, or, if it has not been rendered yet
  (``scripts/render_uml.sh``), a note naming its PlantUML source;
- ``{{chart velocity "caption"}}`` includes a chart from ``scripts/report_charts.py``;
- ``{{include docs/closure/traceability.md}}`` inlines another Markdown file, its headings
  pushed one level down.
Needs pandoc on the PATH (or PANDOC=/path/to/pandoc).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess  # nosec B404 - runs fixed developer tools (pandoc, git)
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "report"
FIGURES = REPORT / "figures"
UML = ROOT / "docs" / "uml"
OUT_MD = REPORT / "build" / "report.md"
OUT_DOCX = REPORT / "AdaptiveCare-Flow-Report.docx"
WORDS_PER_PAGE = 420  # body text with tables and figures, 11 pt

MARKER = re.compile(r"\{\{(uml|chart|include) ([^\s}]+)(?: \"([^\"]*)\")?\}\}")


def uml_figure(ident: str) -> str:
    sources = sorted(UML.glob(f"{ident}_*.puml"))
    if not sources:
        raise SystemExit(f"no diagram {ident} in docs/uml")
    source = sources[0]
    title = next((ln.removeprefix("title ").strip() for ln in source.read_text().splitlines()
                  if ln.startswith("title ")), ident)  # fmt: skip
    png = FIGURES / f"{source.stem}.png"
    if png.exists():
        return f"![{title}](figures/{png.name})"
    return (
        f"> **Figure {title}.** Source: `docs/uml/{source.name}`. "
        "*(Not rendered yet: run `scripts/render_uml.sh`, then rebuild the report.)*"
    )


def chart(name: str, caption: str) -> str:
    if not (FIGURES / f"{name}.png").exists():
        raise SystemExit(f"chart {name} missing: run scripts/report_charts.py")
    return f"![{caption}](figures/{name}.png)"


def include(path: str) -> str:
    """Another Markdown file, its headings one level down and unnumbered (appendix material)."""
    text = (ROOT / path).read_text()
    return re.sub(r"^(#+) (.*)$", lambda m: f"#{m.group(1)} {m.group(2)} {{.unnumbered}}", text, flags=re.M)


def expand(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        kind, arg, caption = m.group(1), m.group(2), m.group(3) or ""
        if kind == "uml":
            return uml_figure(arg)
        if kind == "chart":
            return chart(arg, caption)
        return include(arg)

    return MARKER.sub(repl, text)


def main() -> None:
    chapters = sorted((REPORT / "chapters").glob("*.md"))
    body = "\n\n".join(expand(p.read_text()) for p in chapters)
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(body)
    words = len(re.findall(r"\w+", body))
    pandoc = os.environ.get("PANDOC") or shutil.which("pandoc")
    if pandoc is None:
        sys.exit(f"wrote {OUT_MD.relative_to(ROOT)} ({words} words); pandoc not found, no .docx")
    # Developer tool with a fixed argument list; pandoc comes from the PATH or PANDOC.
    subprocess.run(  # noqa: S603  # nosec B603
        [pandoc, str(OUT_MD), "-o", str(OUT_DOCX), "--from", "markdown+pipe_tables+tex_math_dollars",
         "--toc", "--toc-depth=2", "--number-sections", f"--resource-path={REPORT}",
         "--metadata", "lang=en-GB"],
        check=True,
    )  # fmt: skip
    missing = len(re.findall(r"Not rendered yet", body))
    print(f"wrote {OUT_DOCX.relative_to(ROOT)}: {len(chapters)} chapters, {words} words "
          f"(about {words // WORDS_PER_PAGE} pages of text plus figures); "
          f"{missing} diagrams not rendered yet")  # fmt: skip


if __name__ == "__main__":
    main()
