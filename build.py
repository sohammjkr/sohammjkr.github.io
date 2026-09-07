#!/usr/bin/env python3
"""
build.py — static site generator for sohammjkr.github.io

Writes posts and projects in LaTeX, renders them to HTML. No dependencies
beyond the Python standard library (tested on 3.9+).

    python build.py            # build everything
    python build.py --serve    # build, then serve at http://localhost:8000
    python build.py --watch    # rebuild whenever a source file changes

Inputs                                Outputs
------------------------------------  --------------------------------------
blog/src/_intro.tex                   blog/blog.html   (one continuous page)
blog/src/YYYY-MM-DD-slug.tex
projects/src/_intro.tex               projects/projects_main.html
projects/src/<slug>/project.tex       projects/<slug>.html

index.html is hand-written — it is not generated. Everything shares CSS/site.css.

The LaTeX subset understood by this script is documented in README.md and
demonstrated in blog/src/_template.tex and projects/src/_template/project.tex.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import sys
from datetime import datetime, date
from urllib.parse import quote

# ---------------------------------------------------------------------------
# Site configuration
# ---------------------------------------------------------------------------

ROOT = os.path.dirname(os.path.abspath(__file__))

SITE_NAME    = "Soham Manjrekar"
SITE_BRAND   = "SOHAM MANJREKAR"
RESUME_PDF   = "files/FA26_Resume.pdf"   # root-relative; the viewer embeds this
RESUME_PAGE  = "resume.html"              # nav links here, so a click never downloads
DOB          = date(2002, 5, 18)                     # powers the \age command

# Tags that always appear in the blog tag bar, in this order, even at zero posts.
BLOG_TAGS = ["food", "travel", "friends", "hobbies", "life"]

# The project filter bar, in this order. Tags are matched lowercase; anything a
# project declares that is not listed here still works, it just sorts to the end.
PROJECT_TAGS = ["converters", "sensors", "control", "uiuc", "gt", "ml/ai",
                "product"]

# Display-only casing. Tags are stored and filtered lowercase; this is purely
# what the pill reads as, so acronyms do not come out as "uiuc" and "ml/ai".
TAG_LABELS = {"converters": "Converters", "sensors": "Sensors",
              "control": "Control", "uiuc": "UIUC", "gt": "GT",
              "ml/ai": "ML/AI", "product": "Product"}

MATHJAX = (
    '<script>window.MathJax={tex:{inlineMath:[["\\\\(","\\\\)"]],'
    'displayMath:[["\\\\[","\\\\]"]]},svg:{fontCache:"global"}};</script>\n'
    '<script id="MathJax-script" async '
    'src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>'
)

FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
    '<link href="https://fonts.googleapis.com/css2?'
    'family=Source+Serif+4:ital,wght@0,400;0,600;1,400;1,600&'
    'family=Inter:wght@400;500;600&display=swap" rel="stylesheet">'
)

WARNINGS: list[str] = []
DEFERRED_CHECKS: list[tuple] = []   # (abs_path, as_written, referring_dir)


def warn(msg: str) -> None:
    WARNINGS.append(msg)


# ---------------------------------------------------------------------------
# Small text helpers
# ---------------------------------------------------------------------------

def esc(s: str) -> str:
    return html.escape(s, quote=False)


def attr(s: str) -> str:
    return html.escape(s, quote=True)


def typo(s: str) -> str:
    """LaTeX typographic conventions -> real Unicode punctuation."""
    s = s.replace("---", "\u2014").replace("--", "\u2013")
    s = s.replace("``", "\u201c").replace("''", "\u201d")
    s = re.sub(r"(?<![A-Za-z0-9])`", "\u2018", s)
    s = s.replace("'", "\u2019")
    s = re.sub(r"[ \t]*\n[ \t]*", "\n", s)
    return s


def plain(s: str) -> str:
    """Strip LaTeX down to bare text — for <title>, alt= and meta description."""
    s = re.sub(r"\\[A-Za-z]+\s*", " ", s)
    s = re.sub(r"[{}$\\~]", "", s)
    return re.sub(r"\s+", " ", typo(s)).strip()


def slugify(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", s.lower()).strip()
    return re.sub(r"[\s_-]+", "-", s) or "untitled"


def age_today() -> int:
    t = date.today()
    return t.year - DOB.year - ((t.month, t.day) < (DOB.month, DOB.day))


# ---------------------------------------------------------------------------
# LaTeX scanning primitives
# ---------------------------------------------------------------------------

CMD_RE = re.compile(r"\\([A-Za-z@]+)\*?")


def read_group(s: str, i: int):
    """s[i] must be '{'. Returns (contents, index_after_closing_brace)."""
    if i >= len(s) or s[i] != "{":
        return None, i
    depth, j = 0, i
    while j < len(s):
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
        j += 1
    return s[i + 1:], len(s)          # unbalanced — be forgiving


def read_opt(s: str, i: int):
    """Read an optional [..] argument if present."""
    if i < len(s) and s[i] == "[":
        j = s.find("]", i)
        if j != -1:
            return s[i + 1:j], j + 1
    return None, i


def skip_ws(s: str, i: int) -> int:
    while i < len(s) and s[i] in " \t\n\r":
        i += 1
    return i


def eat_empty_group(s: str, i: int) -> int:
    r"""Swallow the `{}` in constructs like \age{} or \LaTeX{}."""
    j = skip_ws(s, i)
    if j < len(s) and s[j] == "{":
        g, k = read_group(s, j)
        if g is not None and not g.strip():
            return k
    return i


def read_args(s: str, i: int, count: int):
    """Read `count` brace groups, tolerating whitespace and [opt] args."""
    args = []
    for _ in range(count):
        i = skip_ws(s, i)
        _, i = read_opt(s, i)
        i = skip_ws(s, i)
        a, i = read_group(s, i)
        args.append(a if a is not None else "")
    return args, i


def strip_comments(s: str) -> str:
    out, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            out.append(s[i:i + 2])
            i += 2
            continue
        if c == "%":
            j = s.find("\n", i)
            if j == -1:
                break
            i = j + 1
            # a comment eats the newline; keep the line break only if the
            # comment sat on its own line
            if out and out[-1].endswith("\n"):
                continue
            out.append("\n")
            continue
        out.append(c)
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Render context
# ---------------------------------------------------------------------------

class Ctx:
    """Everything the renderer needs to resolve links and stash side content."""

    def __init__(self, src_dir: str, out_dir: str, asset_sub: str):
        self.src_dir = src_dir          # folder the .tex lives in
        self.out_dir = out_dir          # folder the .html is written to
        self.asset_sub = asset_sub      # e.g. "assets/regen-clamp"
        self.store: list[tuple] = []    # protected math / verbatim
        self.footnotes: list[str] = []
        self.has_math = False
        self.copied: set = set()

    # -- protected regions -------------------------------------------------
    def stash(self, kind: str, payload: str) -> str:
        self.store.append((kind, payload))
        return f"\x01{len(self.store) - 1}\x01"

    def unstash(self, s: str) -> str:
        def sub(m):
            kind, payload = self.store[int(m.group(1))]
            if kind == "verb":
                return f'<pre><code>{esc(payload)}</code></pre>'
            if kind == "inline-math":
                self.has_math = True
                return "\\(" + esc(payload) + "\\)"
            if kind == "display-math":
                self.has_math = True
                return "\\[" + esc(payload) + "\\]"
            if kind == "raw":
                return payload
            return esc(payload)
        return re.sub(r"\x01(\d+)\x01", sub, s)

    # -- link + asset resolution ------------------------------------------
    def resolve(self, raw: str) -> str:
        """Turn a LaTeX path into a URL that works from self.out_dir.

        http(s)://, mailto:, tel: and #anchors pass straight through.
        A leading '/' means "relative to the repo root".
        Anything else is relative to the .tex file and gets copied next to
        the generated page.
        """
        # URLs are written with LaTeX escapes (\%, \&, \_, \#) — undo them
        raw = re.sub(r"\\([%&_#$~^{}])", r"\1", raw.strip())
        if not raw:
            return "#"
        if re.match(r"^(https?:|mailto:|tel:|#|//)", raw):
            return raw

        if raw.startswith("/"):
            abs_path = os.path.join(ROOT, raw.lstrip("/"))
            # checked at the end of the build, so generated pages count as real
            DEFERRED_CHECKS.append((abs_path, raw, self.src_dir))
            rel = os.path.relpath(abs_path, os.path.join(ROOT, self.out_dir))
            return quote(rel.replace(os.sep, "/"), safe="/.~-_")

        src = os.path.join(self.src_dir, raw)
        if not os.path.exists(src):
            warn(f"missing file referenced from {self.src_dir}: {raw}")
            return raw
        dest_rel = f"{self.asset_sub}/{os.path.basename(raw)}"
        dest = os.path.join(ROOT, self.out_dir, dest_rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if src not in self.copied:
            shutil.copy2(src, dest)
            self.copied.add(src)
        return quote(dest_rel, safe="/.~-_")


# ---------------------------------------------------------------------------
# Protect verbatim + math before anything else touches the text
# ---------------------------------------------------------------------------

VERB_RE = re.compile(
    r"\\begin\{(verbatim|lstlisting)\}(?:\[[^\]]*\])?(.*?)\\end\{\1\}",
    re.S,
)
MATH_ENVS = ("equation", "equation*", "align", "align*", "gather", "gather*",
             "multline", "multline*", "eqnarray", "eqnarray*")


def protect_verb_inline(text: str, ctx: Ctx) -> str:
    r"""Handle \verb|...| / \verb+...+ before comments or math are considered."""
    out, i, n = [], 0, len(text)
    while i < n:
        if text.startswith("\\verb", i) and i + 5 < n and \
                not text[i + 5].isalpha():
            delim = text[i + 5]
            j = text.find(delim, i + 6)
            if j != -1:
                out.append(ctx.stash(
                    "raw", f"<code>{esc(text[i + 6:j])}</code>"))
                i = j + 1
                continue
        out.append(text[i])
        i += 1
    return "".join(out)


def protect(text: str, ctx: Ctx) -> str:
    text = VERB_RE.sub(lambda m: ctx.stash("verb", m.group(2).strip("\n")), text)
    text = protect_verb_inline(text, ctx)
    text = strip_comments(text)

    for env in MATH_ENVS:
        pat = re.compile(r"\\begin\{" + re.escape(env) + r"\}(.*?)\\end\{"
                         + re.escape(env) + r"\}", re.S)
        text = pat.sub(
            lambda m, e=env: ctx.stash(
                "display-math",
                "\\begin{%s}%s\\end{%s}" % (e, m.group(1), e)),
            text)

    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            if i + 1 < n and text[i + 1] in "\\$%&_#{}":
                out.append(text[i:i + 2]); i += 2; continue
            if text.startswith("\\[", i):
                j = text.find("\\]", i + 2)
                j = n if j == -1 else j
                out.append(ctx.stash("display-math", text[i + 2:j]))
                i = j + 2; continue
            if text.startswith("\\(", i):
                j = text.find("\\)", i + 2)
                j = n if j == -1 else j
                out.append(ctx.stash("inline-math", text[i + 2:j]))
                i = j + 2; continue
            out.append(c); i += 1; continue
        if c == "$":
            display = text.startswith("$$", i)
            open_len = 2 if display else 1
            j, k = i + open_len, -1
            while j < n:
                if text[j] == "\\":
                    j += 2; continue
                if text[j] == "$":
                    k = j; break
                j += 1
            if k == -1:
                out.append(c); i += 1; continue
            body = text[i + open_len:k]
            out.append(ctx.stash("display-math" if display else "inline-math", body))
            i = k + (2 if display else 1)
            continue
        out.append(c); i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Inline conversion
# ---------------------------------------------------------------------------

WRAP = {
    "textbf": ("<strong>", "</strong>"),
    "bf": ("<strong>", "</strong>"),
    "textit": ("<em>", "</em>"),
    "emph": ("<em>", "</em>"),
    "it": ("<em>", "</em>"),
    "texttt": ("<code>", "</code>"),
    "underline": ("<u>", "</u>"),
    "uline": ("<u>", "</u>"),
    "sout": ("<s>", "</s>"),
    "textsc": ('<span style="font-variant:small-caps">', "</span>"),
    "textsuperscript": ("<sup>", "</sup>"),
    "textsubscript": ("<sub>", "</sub>"),
    "text": ("", ""),
    "mbox": ("", ""),
    "textrm": ("", ""),
    "textnormal": ("", ""),
}

SYMBOL = {
    "ldots": "\u2026", "dots": "\u2026", "textellipsis": "\u2026",
    "textemdash": "\u2014", "textendash": "\u2013",
    "copyright": "\u00a9", "textcopyright": "\u00a9",
    "degree": "\u00b0", "textdegree": "\u00b0",
    "times": "\u00d7", "approx": "\u2248", "pm": "\u00b1",
    "to": "\u2192", "rightarrow": "\u2192", "leftarrow": "\u2190",
    "Omega": "\u03a9", "Sigma": "\u03a3", "Delta": "\u0394",
    "alpha": "\u03b1", "beta": "\u03b2", "mu": "\u00b5", "eta": "\u03b7",
    "LaTeX": "LaTeX", "TeX": "TeX",
    "quad": "\u2003", "qquad": "\u2003\u2003",
    "bullet": "\u2022", "dag": "\u2020", "S": "\u00a7",
    "&": "&",
}

# commands whose arguments are simply dropped
SWALLOW_1 = {"label", "ref", "index", "vspace", "hspace", "pagestyle",
             "documentclass", "usepackage", "bibliographystyle",
             "bibliography", "addbibresource", "setlength", "thispagestyle"}
IGNORE_0 = {"noindent", "centering", "par", "bigskip", "medskip", "smallskip",
            "hfill", "vfill", "maketitle", "clearpage", "newpage",
            "tableofcontents", "raggedright", "small", "footnotesize",
            "normalsize", "large", "Large", "huge", "protect", "sloppy"}


def convert_inline(s: str, ctx: Ctx) -> str:
    out: list[str] = []
    buf: list[str] = []

    def flush():
        if buf:
            out.append(esc(typo("".join(buf))))
            del buf[:]

    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "~":                      # LaTeX non-breaking space
            buf.append(" ")
            i += 1
            continue
        if c != "\\":
            buf.append(c)
            i += 1
            continue

        if i + 1 >= n:
            i += 1
            continue
        nxt = s[i + 1]

        if nxt == "\\":
            flush()
            out.append("<br>")
            i += 2
            _, i = read_opt(s, i)
            continue
        if nxt in "%&_#${}":
            buf.append(nxt); i += 2; continue
        if nxt in " \n\t":
            buf.append(" "); i += 2; continue
        if nxt == ",":
            buf.append("\u2009"); i += 2; continue

        m = CMD_RE.match(s, i)
        if not m:
            buf.append(nxt); i += 2; continue
        name, i = m.group(1), m.end()
        flush()

        if name in IGNORE_0:
            i = eat_empty_group(s, i)
            continue
        if name in SWALLOW_1:
            _, i = read_args(s, i, 1)
            continue
        if name in SYMBOL:
            out.append(esc(SYMBOL[name]))
            i = eat_empty_group(s, i)
            continue
        if name in WRAP:
            (a,), i = read_args(s, i, 1)
            open_t, close_t = WRAP[name]
            out.append(open_t + convert_inline(a, ctx) + close_t)
            continue
        if name == "href":
            (url, label), i = read_args(s, i, 2)
            out.append(link_html(ctx.resolve(url), convert_inline(label, ctx)))
            continue
        if name == "url":
            (url,), i = read_args(s, i, 1)
            resolved = ctx.resolve(url)
            out.append(link_html(resolved, esc(url)))
            continue
        if name == "footnote":
            (note,), i = read_args(s, i, 1)
            ctx.footnotes.append(convert_inline(note, ctx))
            k = len(ctx.footnotes)
            out.append(f'<sup class="fnref"><a href="#fn{k}">{k}</a></sup>')
            continue
        if name == "age":
            i = eat_empty_group(s, i)
            out.append('<span class="age-auto">%d</span>' % age_today())
            continue
        if name == "today":
            i = eat_empty_group(s, i)
            t = date.today()
            out.append(esc(f"{t.strftime('%B')} {t.day}, {t.year}"))
            continue
        if name == "tag":
            (t,), i = read_args(s, i, 1)
            out.append(tag_html(t.strip()))
            continue

        # unknown command: keep its first braced argument's text, drop the rest
        j = skip_ws(s, i)
        if j < n and s[j] == "{":
            g, i = read_group(s, j)
            out.append(convert_inline(g, ctx))
        continue

    flush()
    return "".join(out)


def link_html(href: str, inner: str) -> str:
    ext = ' target="_blank" rel="noopener noreferrer"' \
        if re.match(r"^(https?:)?//", href) or href.lower().endswith(".pdf") else ""
    return f'<a href="{attr(href)}"{ext}>{inner}</a>'


def tag_html(t: str, count: int | None = None, cls: str = "tag") -> str:
    n = f' <span class="count">{count}</span>' if count is not None else ""
    label = TAG_LABELS.get(t, t)
    return (f'<a class="{cls}" href="?tag={quote(t)}" data-tag="{attr(t)}" '
            f'data-label="{attr(label)}">{esc(label)}{n}</a>')


# ---------------------------------------------------------------------------
# Block conversion
# ---------------------------------------------------------------------------

BEGIN_RE = re.compile(r"\\begin\{([A-Za-z*]+)\}")
BLOCK_CMDS = ("section", "subsection", "subsubsection", "paragraph",
              "pdf", "img", "sep", "lead", "pullquote", "callout")
BLOCK_RE = re.compile(r"\\(" + "|".join(BLOCK_CMDS) + r")\*?(?![A-Za-z])")


def extract_env(text: str, start: int, env: str):
    """start points at \\begin{env}. Returns (inner, index_after_end)."""
    open_tok = "\\begin{%s}" % env
    close_tok = "\\end{%s}" % env
    depth, i = 1, start + len(open_tok)
    body_start = i
    while i < len(text):
        no = text.find(open_tok, i)
        nc = text.find(close_tok, i)
        if nc == -1:
            return text[body_start:], len(text)
        if no != -1 and no < nc:
            depth += 1
            i = no + len(open_tok)
            continue
        depth -= 1
        if depth == 0:
            return text[body_start:nc], nc + len(close_tok)
        i = nc + len(close_tok)
    return text[body_start:], len(text)


def render_body(text: str, ctx: Ctx) -> str:
    parts, pos = [], 0
    while True:
        m = BEGIN_RE.search(text, pos)
        if not m:
            parts.append(render_flow(text[pos:], ctx))
            break
        parts.append(render_flow(text[pos:m.start()], ctx))
        env = m.group(1)
        inner, after = extract_env(text, m.start(), env)
        parts.append(render_env(env, inner, ctx))
        pos = after
    return "\n".join(p for p in parts if p.strip())


def render_flow(chunk: str, ctx: Ctx) -> str:
    parts, pos = [], 0
    while True:
        m = BLOCK_RE.search(chunk, pos)
        if not m:
            parts.extend(paragraphs(chunk[pos:], ctx))
            break
        parts.extend(paragraphs(chunk[pos:m.start()], ctx))
        cmd, i = m.group(1), m.end()

        if cmd == "sep":
            parts.append('<hr class="rule tight">')
        elif cmd in ("section", "subsection", "subsubsection", "paragraph"):
            (a,), i = read_args(chunk, i, 1)
            level = {"section": "h3", "subsection": "h4",
                     "subsubsection": "h4", "paragraph": "h4"}[cmd]
            parts.append(f"<{level}>{convert_inline(a, ctx)}</{level}>")
        elif cmd == "lead":
            (a,), i = read_args(chunk, i, 1)
            parts.append(f'<p class="lead">{convert_inline(a, ctx)}</p>')
        elif cmd == "pullquote":
            (a,), i = read_args(chunk, i, 1)
            parts.append(f'<p class="pull">{convert_inline(a, ctx)}</p>')
        elif cmd == "callout":
            (a,), i = read_args(chunk, i, 1)
            parts.append(f'<div class="callout">{render_body(a, ctx)}</div>')
        elif cmd == "img":
            i = skip_ws(chunk, i)
            size, i = read_opt(chunk, i)
            (path, cap), i = read_args(chunk, i, 2)
            parts.append(figure_html(ctx.resolve(path), cap, ctx, size))
        elif cmd == "pdf":
            (path, cap), i = read_args(chunk, i, 2)
            parts.append(pdf_html(ctx.resolve(path), cap, ctx, os.path.basename(path)))
        pos = i
    return "\n".join(p for p in parts if p.strip())


LONE_TOKEN = re.compile(r"^\x01(\d+)\x01$")


def paragraphs(t: str, ctx: Ctx) -> list[str]:
    out = []
    for block in re.split(r"\n[ \t]*\n", t):
        block = block.strip()
        if not block:
            continue
        # a paragraph that is nothing but display math or a code block should
        # not be wrapped in <p>
        lone = LONE_TOKEN.match(block)
        if lone:
            kind = ctx.store[int(lone.group(1))][0]
            if kind == "display-math":
                out.append(f'<div class="math-block">{block}</div>')
                continue
            if kind in ("verb", "raw"):
                out.append(block)
                continue
        rendered = convert_inline(block, ctx)
        if rendered.strip():
            out.append(f"<p>{rendered}</p>")
    return out


def split_items(inner: str) -> list[str]:
    """Split a list body on top-level \\item."""
    items, depth, cur, i, n = [], 0, [], 0, len(inner)
    while i < n:
        if inner.startswith("\\begin{", i):
            depth += 1; cur.append(inner[i:i + 7]); i += 7; continue
        if inner.startswith("\\end{", i):
            depth -= 1; cur.append(inner[i:i + 5]); i += 5; continue
        if depth == 0 and inner.startswith("\\item", i) and \
                not re.match(r"\\item[A-Za-z]", inner[i:]):
            items.append("".join(cur))
            cur = []
            i += 5
            _, i = read_opt(inner, i)
            continue
        cur.append(inner[i]); i += 1
    items.append("".join(cur))
    return [x for x in items[1:]] if items and not items[0].strip() else items


def render_item(body: str, ctx: Ctx) -> str:
    body = body.strip()
    complex_item = ("\\begin{" in body or "\n\n" in body
                    or BLOCK_RE.search(body) is not None)
    return render_body(body, ctx) if complex_item else convert_inline(body, ctx)


def render_env(env: str, inner: str, ctx: Ctx) -> str:
    if env in ("itemize", "enumerate"):
        tag = "ul" if env == "itemize" else "ol"
        lis = "\n".join(f"<li>{render_item(x, ctx)}</li>"
                        for x in split_items(inner) if x.strip())
        return f"<{tag}>\n{lis}\n</{tag}>"

    if env in ("quote", "quotation", "verse"):
        return f"<blockquote>{render_body(inner, ctx)}</blockquote>"

    if env == "center":
        return f'<div class="center">{render_body(inner, ctx)}</div>'

    if env in ("abstract", "callout"):
        return f'<div class="callout">{render_body(inner, ctx)}</div>'

    if env in ("figure", "figure*"):
        _, i = read_opt(inner, 0)
        path, capt = "", ""
        gm = re.search(r"\\includegraphics(?:\[[^\]]*\])?\s*\{", inner)
        if gm:
            path, _ = read_group(inner, gm.end() - 1)
        cm = re.search(r"\\caption\s*\{", inner)
        if cm:
            capt, _ = read_group(inner, cm.end() - 1)
        if not path:
            return render_body(inner, ctx)
        return figure_html(ctx.resolve(path), capt or "", ctx)

    if env in ("table", "table*"):
        capt = ""
        cm = re.search(r"\\caption\s*\{", inner)
        if cm:
            capt, _ = read_group(inner, cm.end() - 1)
            inner = inner[:cm.start()] + inner[read_group(inner, cm.end() - 1)[1]:]
        body = render_body(inner, ctx)
        cap = f"<figcaption>{convert_inline(capt, ctx)}</figcaption>" if capt else ""
        return f"<figure>{body}{cap}</figure>"

    if env in ("tabular", "tabular*", "tabularx"):
        return render_tabular(inner, ctx)

    if env == "document":
        return render_body(inner, ctx)

    # unknown environment: render its contents and move on
    return render_body(inner, ctx)


def render_tabular(inner: str, ctx: Ctx) -> str:
    _, i = read_group(inner, skip_ws(inner, 0))       # drop the column spec
    body = inner[i:]
    body = re.sub(r"\\(hline|toprule|midrule|bottomrule)\b", "", body)
    rows = [r for r in re.split(r"\\\\", body) if r.strip()]
    if not rows:
        return ""
    out = ['<div class="table-scroll"><table>']
    for n, row in enumerate(rows):
        cells = [convert_inline(c.strip(), ctx) for c in row.split("&")]
        t = "th" if n == 0 else "td"
        wrap = "<thead>" if n == 0 else ""
        end = "</thead><tbody>" if n == 0 else ""
        out.append(wrap + "<tr>" + "".join(f"<{t}>{c}</{t}>" for c in cells)
                   + "</tr>" + end)
    out.append("</tbody></table></div>")
    return "".join(out)


FIG_SIZES = {"small", "medium", "full"}


def figure_html(src: str, caption: str, ctx: Ctx, size: str = None) -> str:
    cap = (f"<figcaption>{convert_inline(caption, ctx)}</figcaption>"
           if caption.strip() else "")
    alt = attr(plain(caption) or "figure")
    key = (size or "").strip().lower()
    pct = key.replace("\\", "").replace("%", "")
    if pct.isdigit() and 1 <= int(pct) <= 100:  # \img[70]{..}{..}
        cls = f' class="fig-scaled" style="--figw:{int(pct)}%"'
    elif key in FIG_SIZES:                     # \img[small]{..}{..}
        cls = f' class="fig-{key}"'
    else:
        cls = ""
    return (f'<figure{cls}><img src="{attr(src)}" alt="{alt}" loading="lazy">'
            f"{cap}</figure>")


def pdf_html(src: str, caption: str, ctx: Ctx, filename: str) -> str:
    label = convert_inline(caption, ctx) if caption.strip() else "View PDF"
    return (
        '<details class="pdf-embed" open>\n'
        f'  <summary>{label}<span class="pdf-file">{esc(filename)}</span></summary>\n'
        f'  <iframe class="pdf-frame" src="{attr(src)}#view=FitH" '
        f'title="{attr(filename)}" loading="lazy"></iframe>\n'
        '  <div class="pdf-fallback">Not rendering? '
        f'<a href="{attr(src)}" target="_blank" rel="noopener noreferrer">'
        'Open the PDF in a new tab</a>.</div>\n'
        "</details>"
    )


# ---------------------------------------------------------------------------
# Attachments — \attach{Label}{path}
#
# Every attached document is shown embedded at the end of the project, and
# every embed is a PDF: browsers cannot render .docx or .pptx inline. For an
# Office document we look for a PDF rendition sitting beside it under the same
# name, which tools/convert_docs_to_pdf.ps1 produces. Without one the document
# degrades to a download button and the build warns.
# ---------------------------------------------------------------------------

EMBEDDABLE = {".pdf"}
CONVERTIBLE = {".docx": "DOCX", ".doc": "DOC",
               ".pptx": "PPTX", ".ppt": "PPT"}


def local_path(ctx: Ctx, raw: str) -> str | None:
    """Absolute path on disk for a LaTeX path, or None if it is a URL."""
    raw = re.sub(r"\\([%&_#$~^{}])", r"\1", raw.strip())
    if not raw or re.match(r"^(https?:|mailto:|tel:|#|//)", raw):
        return None
    if raw.startswith("/"):
        return os.path.join(ROOT, raw.lstrip("/"))
    return os.path.join(ctx.src_dir, raw)


def resolve_attachment(ctx: Ctx, label: str, raw: str) -> dict:
    raw = re.sub(r"\\([%&_#$~^{}])", r"\1", raw.strip())
    ext = os.path.splitext(raw)[1].lower()
    src = local_path(ctx, raw)
    item = {
        "label": label,
        "filename": os.path.basename(raw),
        "kind": CONVERTIBLE.get(ext, ext.lstrip(".").upper() or "FILE"),
        "href": ctx.resolve(raw),
        "pdf": None,
        "original": None,
    }

    if ext in EMBEDDABLE:
        item["pdf"] = item["href"]
        return item

    # an Office document: embed its PDF rendition if one exists
    pdf_raw = raw[: len(raw) - len(ext)] + ".pdf" if ext else raw + ".pdf"
    pdf_src = local_path(ctx, pdf_raw)
    if src is not None and pdf_src and os.path.exists(pdf_src):
        item["pdf"] = ctx.resolve(pdf_raw)
        item["original"] = item["href"]
    elif src is not None:
        warn(f"no PDF rendition for {raw} — run tools/convert_docs_to_pdf.ps1; "
             "it will show as a download button only")
    return item


def attachments_html(items: list, slug: str) -> str:
    """The Documents block that closes a project's own page.

    The listing does not call this — it links to `<slug>.html#documents`
    instead, from the same button row as the project's external links.
    """
    if not items:
        return ""

    blocks = []
    for i in items:
        orig = (f' <span class="doc-orig">Source: '
                f'<a href="{attr(i["original"])}">{esc(i["filename"])}</a>'
                f"</span>") if i["original"] else ""
        if not i["pdf"]:
            blocks.append(
                '<div class="doc-embed no-embed">\n'
                f'  <div class="doc-head"><span class="doc-label">'
                f'{esc(i["label"])}<span class="doc-file">{esc(i["filename"])}'
                f'</span></span>\n'
                f'  <a class="btn" href="{attr(i["href"])}">'
                f'Download {esc(i["kind"])}</a></div>\n'
                "</div>")
            continue
        blocks.append(
            '<figure class="doc-embed">\n'
            '  <figcaption class="doc-head">\n'
            f'    <span class="doc-label">{esc(i["label"])}'
            f'<span class="doc-file">{esc(i["filename"])}</span></span>\n'
            f'    <a class="btn primary" href="{attr(i["pdf"])}" '
            'target="_blank" rel="noopener noreferrer">Open PDF ↗</a>\n'
            "  </figcaption>\n"
            f'  <iframe class="pdf-frame" src="{attr(i["pdf"])}#view=FitH" '
            f'title="{attr(i["label"])}" loading="lazy"></iframe>\n'
            '  <div class="pdf-fallback">Not rendering? '
            f'<a href="{attr(i["pdf"])}" target="_blank" '
            'rel="noopener noreferrer">Open the PDF in a new tab</a>.'
            f"{orig}</div>\n"
            "</figure>")

    return ('<section class="attachments" id="documents">\n'
            '  <h3 class="attachments-head">Documents</h3>\n'
            + "\n".join(blocks) + "\n</section>")


# ---------------------------------------------------------------------------
# Document parsing (metadata + body)
# ---------------------------------------------------------------------------

META_1 = ["title", "subtitle", "date", "tags", "excerpt", "period",
          "status", "order", "slug", "cover", "location"]


def parse_doc(path: str, ctx: Ctx) -> dict:
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()

    text = protect(raw, ctx)

    meta: dict = {"links": [], "attachments": []}

    # \link{Label}{url} and \attach{Label}{path} may appear anywhere in the
    # file; pull them all out into their own lists.
    def take_pairs(s: str, cmd: str, into: str) -> str:
        out, pos = [], 0
        pat = re.compile(r"\\" + cmd + r"\s*\{")
        while True:
            m = pat.search(s, pos)
            if not m:
                out.append(s[pos:]); break
            out.append(s[pos:m.start()])
            (label, url), i = read_args(s, m.end() - 1, 2)
            meta[into].append((label, url))
            pos = i
        return "".join(out)

    text = take_pairs(text, "link", "links")
    text = take_pairs(text, "attach", "attachments")

    for key in META_1:
        m = re.compile(r"\\" + key + r"\s*\{").search(text)
        if not m:
            continue
        val, end = read_group(text, m.end() - 1)
        meta[key] = (val or "").strip()
        text = text[:m.start()] + text[end:]

    # body = everything inside \begin{document}, or the whole file
    dm = re.search(r"\\begin\{document\}", text)
    if dm:
        body, _ = extract_env(text, dm.start(), "document")
    else:
        body = re.sub(r"\\documentclass[^\n]*\n", "", text)
        body = re.sub(r"\\usepackage(\[[^\]]*\])?\{[^}]*\}", "", body)

    meta["body_tex"] = body
    meta["source"] = path
    return meta


def parse_date(s: str):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d",
                "%Y-%m", "%Y"):
        try:
            return datetime.strptime(s, fmt), ("%H" in fmt)
        except ValueError:
            continue
    return None, False


RANGE_SEPS = (" to ", " -- ", " – ", " - ", "--", "..", "–")


def split_range(s: str):
    r"""\date{2025-07-26 to 2025-07-28} -> ("2025-07-26", "2025-07-28")."""
    s = (s or "").strip()
    for sep in RANGE_SEPS:
        if sep in s:
            a, _, b = s.partition(sep)
            return a.strip(), b.strip()
    return s, None


def fmt_range(a: datetime, b: datetime) -> str:
    """July 26–28, 2025 / March 30 – April 2, 2026 / across years."""
    if (a.year, a.month) == (b.year, b.month):
        return (a.strftime("%B ") + str(a.day) + "–" + str(b.day)
                + a.strftime(", %Y"))
    if a.year == b.year:
        return (a.strftime("%B ") + str(a.day) + " – "
                + b.strftime("%B ") + str(b.day) + b.strftime(", %Y"))
    return (a.strftime("%B ") + str(a.day) + a.strftime(", %Y") + " – "
            + b.strftime("%B ") + str(b.day) + b.strftime(", %Y"))


def fmt_date(dt: datetime, with_time: bool, precision: str) -> str:
    day = str(dt.day)
    if precision == "%Y":
        return dt.strftime("%Y")
    if precision == "%Y-%m":
        return dt.strftime("%B %Y")
    out = dt.strftime("%B ") + day + dt.strftime(", %Y")
    if with_time:
        hour = dt.hour % 12 or 12
        out += f" \u00b7 {hour}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"
    return out


def date_label(dt, dt_end, with_time, raw_start, raw_end) -> str:
    if dt == datetime.min:
        return "undated"
    if (dt_end and date_precision(raw_start) == "full"
            and date_precision(raw_end) == "full" and dt_end > dt):
        return fmt_range(dt, dt_end)
    return fmt_date(dt, with_time, date_precision(raw_start))


def date_precision(s: str) -> str:
    s = (s or "").strip()
    if re.fullmatch(r"\d{4}", s):
        return "%Y"
    if re.fullmatch(r"\d{4}-\d{2}", s):
        return "%Y-%m"
    return "full"


def split_tags(s: str) -> list[str]:
    return [t.strip().lower() for t in re.split(r"[,;]", s or "") if t.strip()]


# ---------------------------------------------------------------------------
# Page chrome
# ---------------------------------------------------------------------------

def nav_html(prefix: str, active: str) -> str:
    items = [
        ("Home", f"{prefix}index.html", "home"),
        ("Journal", f"{prefix}blog/blog.html" if prefix == "" else
                    ("blog.html" if active == "blog" else f"{prefix}blog/blog.html"), "blog"),
        ("Projects", f"{prefix}projects/projects_main.html" if prefix == "" else
                     ("projects_main.html" if active == "projects" else
                      f"{prefix}projects/projects_main.html"), "projects"),
        ("Resume", f"{prefix}{RESUME_PAGE}", "resume"),
    ]
    lis = []
    for label, href, key in items:
        cls = ' class="active"' if key == active else ""
        blank = (' target="_blank" rel="noopener noreferrer"'
                 if key == "resume" and active != "resume" else "")
        lis.append(f'<li><a href="{attr(href)}"{cls}{blank}>{label}</a></li>')
    return '<nav class="site-nav"><ul>\n  ' + "\n  ".join(lis) + "\n</ul></nav>"


def page_head(title: str, prefix: str, description: str, math: bool) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{attr(description)}">
<link rel="icon" type="image/svg+xml" href="{prefix}favicon.svg">
{FONTS}
<link rel="stylesheet" href="{prefix}CSS/site.css">
<link rel="stylesheet"
      href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.2/css/all.min.css"
      crossorigin="anonymous" referrerpolicy="no-referrer">
{MATHJAX if math else ""}
</head>"""


def footer_html(credit: bool = True) -> str:
    c = ('\n  <div class="credit">Layout owes a debt to '
         '<a href="https://parkzer.com" target="_blank" rel="noopener noreferrer">'
         'Adam Parkzer\u2019s site</a>.</div>') if credit else ""
    return (f'<footer class="site-footer">\n'
            f'  <div>\u00a9 <span class="year">{date.today().year}</span> '
            f'{esc(SITE_NAME)}</div>{c}\n</footer>')


NO_COPY_JS = """
<script>
(function () {
  var stop = function (e) { e.preventDefault(); return false; };
  ['copy', 'cut', 'contextmenu', 'dragstart', 'selectstart'].forEach(function (evt) {
    document.addEventListener(evt, function (e) {
      if (e.target.closest && e.target.closest('input, textarea')) return;
      return stop(e);
    });
  });
})();
</script>"""


FILTER_JS = """
<script>
(function () {
  var feed  = document.getElementById('feed');
  if (!feed) return;
  var items = Array.prototype.slice.call(feed.querySelectorAll('.entry'));
  var note  = document.getElementById('filter-note');
  var what  = document.getElementById('filter-what');
  var tally = document.getElementById('filter-tally');
  var empty = document.getElementById('empty-note');

  function apply(tag) {
    tag = (tag || '').toLowerCase();
    var shown = 0;
    items.forEach(function (el) {
      var tags = (el.dataset.tags || '').split(',');
      var hit  = !tag || tags.indexOf(tag) !== -1;
      el.hidden = !hit;
      if (hit) shown++;
    });
    document.querySelectorAll('.tagbar .tag').forEach(function (a) {
      a.classList.toggle('is-active', !!tag && a.dataset.tag === tag);
    });
    if (note) {
      note.classList.toggle('is-on', !!tag);
      if (tag) {
        var pill = document.querySelector('.tagbar .tag[data-tag="' + tag + '"]');
        what.textContent  = (pill && pill.dataset.label) || tag;
        tally.textContent = shown + (shown === 1 ? ' entry' : ' entries');
      }
    }
    if (empty) empty.classList.toggle('is-on', !!tag && shown === 0);
    document.title = document.title.replace(/ \\u2014 filtered.*$/, '') +
                     (tag ? ' \\u2014 filtered: ' + tag : '');
  }

  function fromUrl() {
    return new URLSearchParams(window.location.search).get('tag') || '';
  }

  document.addEventListener('click', function (e) {
    var a = e.target.closest('a.tag, .clear');
    if (!a) return;
    e.preventDefault();
    var tag = a.dataset.tag || '';
    if (tag && tag === fromUrl()) tag = '';          // click again to clear
    var url = tag ? '?tag=' + encodeURIComponent(tag) : window.location.pathname;
    history.pushState({ tag: tag }, '', url);
    apply(tag);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });

  window.addEventListener('popstate', function () { apply(fromUrl()); });
  apply(fromUrl());
})();
</script>"""


def tagbar_html(counts: dict, order: list[str]) -> str:
    keys = [t for t in order if t in counts] + \
           sorted(t for t in counts if t not in order)
    pills = "\n    ".join(tag_html(t, counts[t]) for t in keys)
    return (
        '  <div class="tagbar">\n'
        '    <span class="tagbar-label">Filter</span>\n'
        f"    {pills}\n"
        "  </div>\n"
        '  <div class="filter-note" id="filter-note">\n'
        '    <span>Showing only <span class="what" id="filter-what"></span></span>\n'
        '    <span class="tally" id="filter-tally"></span>\n'
        '    <a class="clear" href="#" data-tag="">show everything</a>\n'
        "  </div>"
    )


def footnotes_html(ctx: Ctx) -> str:
    if not ctx.footnotes:
        return ""
    lis = "\n".join(f'<li id="fn{i + 1}">{t}</li>'
                    for i, t in enumerate(ctx.footnotes))
    return f'<ol class="footnotes">\n{lis}\n</ol>'


# ---------------------------------------------------------------------------
# Blog
# ---------------------------------------------------------------------------

def build_blog() -> int:
    src_dir = os.path.join(ROOT, "blog", "src")
    if not os.path.isdir(src_dir):
        warn("blog/src does not exist — skipping the blog")
        return 0

    intro_html, intro_ctx = "", None
    intro_path = os.path.join(src_dir, "_intro.tex")
    if os.path.exists(intro_path):
        intro_ctx = Ctx(src_dir, "blog", "assets/_intro")
        meta = parse_doc(intro_path, intro_ctx)
        intro_html = intro_ctx.unstash(render_body(meta["body_tex"], intro_ctx))

    posts = []
    has_math = bool(intro_ctx and intro_ctx.has_math)
    for name in sorted(os.listdir(src_dir)):
        if not name.endswith(".tex") or name.startswith("_"):
            continue
        path = os.path.join(src_dir, name)
        stem = name[:-4]
        slug = slugify(re.sub(r"^\d{4}-\d{2}-\d{2}-", "", stem))
        ctx = Ctx(src_dir, "blog", f"assets/{slug}")
        meta = parse_doc(path, ctx)
        meta["slug"] = meta.get("slug") or slug

        raw_date = meta.get("date", "")
        if not raw_date:
            fm = re.match(r"^(\d{4}-\d{2}-\d{2})", stem)
            raw_date = fm.group(1) if fm else ""
        raw_start, raw_end = split_range(raw_date)
        dt, with_time = parse_date(raw_start)   # sorting uses the start
        dt_end, _ = parse_date(raw_end) if raw_end else (None, False)
        if raw_end and dt_end is None:
            warn(f"{name}: unreadable end of date range {raw_end!r}")
        if dt is None:
            warn(f"{name}: no readable \\date{{...}} — sorted last")
            dt, with_time = datetime.min, False

        body = ctx.unstash(render_body(meta["body_tex"], ctx))
        notes = ctx.unstash(footnotes_html(ctx))
        has_math = has_math or ctx.has_math

        raw_title = meta.get("title") or slug.replace("-", " ").title()
        posts.append({
            "title": ctx.unstash(convert_inline(raw_title, ctx)),
            "slug": meta["slug"],
            "dt": dt,
            "date_label": date_label(dt, dt_end, with_time, raw_start, raw_end),
            "iso": dt.isoformat() if dt != datetime.min else "",
            "iso_end": dt_end.date().isoformat() if dt_end else "",
            "location": ctx.unstash(convert_inline(meta.get("location", ""), ctx)),
            "tags": split_tags(meta.get("tags", "")),
            "links": [(l, ctx.resolve(u)) for l, u in meta["links"]],
            "html": body + notes,
        })

    posts.sort(key=lambda p: p["dt"], reverse=True)   # newest first

    counts: dict = {t: 0 for t in BLOG_TAGS}
    for p in posts:
        for t in p["tags"]:
            counts[t] = counts.get(t, 0) + 1

    entries = []
    for p in posts:
        pills = ('<span class="dot">\u00b7</span>'
                 + "".join(tag_html(t) for t in p["tags"])) if p["tags"] else ""
        where = ('<span class="dot">\u00b7</span>'
                 f'<span class="where">{p["location"]}</span>') if p["location"] else ""
        links = ""
        if p["links"]:
            links = ('<div class="linkrow">'
                     + "".join(f'<a class="btn" href="{attr(u)}" target="_blank" '
                               f'rel="noopener noreferrer">{esc(l)}</a>'
                               for l, u in p["links"])
                     + "</div>")
        dend = f' data-date-end="{attr(p["iso_end"])}"' if p["iso_end"] else ""
        time_el = (f'<time datetime="{attr(p["iso"])}"{dend}>'
                   f'{esc(p["date_label"])}</time>'
                   if p["iso"] else f'<span>{esc(p["date_label"])}</span>')
        entries.append(f"""<article class="entry" id="{attr(p['slug'])}"
         data-tags="{attr(','.join(p['tags']))}">
  <h2 class="entry-title"><a href="#{attr(p['slug'])}">{p['title']}</a></h2>
  <div class="meta-bar">
    {time_el}{where}{pills}
    <a class="anchor" href="#{attr(p['slug'])}" aria-label="Link to this entry">#</a>
  </div>
  <div class="entry-body">
{p['html']}
  </div>
  {links}
  <hr class="rule">
</article>""")

    page = f"""{page_head(f"{SITE_NAME} \u2014 Journal", "../",
                          "Notes on food, travel, friends, hobbies and life.",
                          has_math)}
<body class="no-select">
{nav_html("../", "blog")}
<div class="wrap">

  <header class="masthead">
    <h1 class="brand"><a href="../index.html"><img class="brand-mark"
       src="../favicon.svg" alt=""><span>{SITE_BRAND}</span></a></h1>
    <div class="tagline">Journal</div>
  </header>

  <section class="lead narrow">
{intro_html}
  </section>

{tagbar_html(counts, BLOG_TAGS)}

  <hr class="rule">

  <main id="feed">
{chr(10).join(entries) if entries else
 '<p class="center" style="color:var(--muted)">Nothing published yet.</p>'}
  </main>

  <div class="empty-note" id="empty-note">
    No entries carry that tag yet.
  </div>

{footer_html()}
</div>
{NO_COPY_JS}
{FILTER_JS}
</body>
</html>
"""
    write(os.path.join(ROOT, "blog", "blog.html"), page)
    return len(posts)


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

def build_projects() -> int:
    src_dir = os.path.join(ROOT, "projects", "src")
    if not os.path.isdir(src_dir):
        warn("projects/src does not exist — skipping projects")
        return 0

    intro_html, intro_ctx = "", None
    intro_path = os.path.join(src_dir, "_intro.tex")
    if os.path.exists(intro_path):
        intro_ctx = Ctx(src_dir, "projects", "assets/_intro")
        meta = parse_doc(intro_path, intro_ctx)
        intro_html = intro_ctx.unstash(render_body(meta["body_tex"], intro_ctx))

    projects = []
    has_math = bool(intro_ctx and intro_ctx.has_math)
    for name in sorted(os.listdir(src_dir)):
        folder = os.path.join(src_dir, name)
        if not os.path.isdir(folder) or name.startswith("_"):
            continue
        tex = os.path.join(folder, "project.tex")
        if not os.path.exists(tex):
            cands = [f for f in os.listdir(folder) if f.endswith(".tex")]
            if not cands:
                warn(f"projects/src/{name} has no .tex file — skipped")
                continue
            tex = os.path.join(folder, cands[0])

        slug = slugify(name)
        ctx = Ctx(folder, "projects", f"assets/{slug}")
        meta = parse_doc(tex, ctx)
        slug = slugify(meta.get("slug") or slug)

        dt, _ = parse_date(meta.get("date", ""))
        body = ctx.unstash(render_body(meta["body_tex"], ctx))
        notes = ctx.unstash(footnotes_html(ctx))
        # NB: no `has_math` roll-up here — project bodies do not appear on the
        # listing, so its need for MathJax depends on the intro alone.

        try:
            order = int(meta.get("order", "999"))
        except ValueError:
            order = 999

        raw_title = meta.get("title") or name.replace("-", " ").title()
        projects.append({
            "title": ctx.unstash(convert_inline(raw_title, ctx)),
            "title_text": plain(raw_title),
            "subtitle": ctx.unstash(convert_inline(meta.get("subtitle", ""), ctx)),
            "period": plain(meta.get("period", "")),
            "status": plain(meta.get("status", "")),
            "slug": slug,
            "order": order,
            "dt": dt or datetime.min,
            "tags": split_tags(meta.get("tags", "")),
            "links": [(l, ctx.resolve(u)) for l, u in meta["links"]],
            "attachments": [resolve_attachment(ctx, l, u)
                            for l, u in meta["attachments"]],
            "html": body + notes,
            "math": ctx.has_math,
        })

    projects.sort(key=lambda p: (p["order"], -p["dt"].toordinal()
                                 if p["dt"] != datetime.min else 0))

    counts: dict = {}
    for p in projects:
        for t in p["tags"]:
            counts[t] = counts.get(t, 0) + 1

    def entry_html(p: dict, standalone: bool) -> str:
        pills = ('<span class="dot">\u00b7</span>'
                 + "".join(tag_html(t) for t in p["tags"])) if p["tags"] else ""
        bits = []
        if p["period"]:
            bits.append(f'<span>{esc(p["period"])}</span>')
        if p["status"]:
            bits.append(f'<span class="honor">{esc(p["status"])}</span>')
        meta_left = "".join(bits) or "<span></span>"

        btns = [f'<a class="btn{" primary" if n == 0 else ""}" href="{attr(u)}" '
                f'target="_blank" rel="noopener noreferrer">{esc(l)}</a>'
                for n, (l, u) in enumerate(p["links"])]
        if not standalone:
            # The listing carries no write-up, so the documents join the same
            # row and point at the project page, where they are embedded.
            btns += [f'<a class="btn" href="{attr(p["slug"])}.html#documents">'
                     f'{esc(a["label"])}</a>' for a in p["attachments"]]
        links = f'<div class="linkrow">{"".join(btns)}</div>' if btns else ""
        # The write-up lives on the project's own page only; the listing is an
        # index — title, meta and the buttons that lead into it.
        body = ("  <div class=\"entry-body\">\n"
                f"{p['html']}\n{attachments_html(p['attachments'], p['slug'])}\n"
                "  </div>") if standalone else ""

        title = (p["title"] if standalone else
                 f'<a href="{attr(p["slug"])}.html">{p["title"]}</a>')
        sub = f'<div class="entry-sub">{p["subtitle"]}</div>' if p["subtitle"] else ""
        rule = "" if standalone else '\n  <hr class="rule">'
        anchor = "" if standalone else (
            f'\n    <a class="anchor" href="{attr(p["slug"])}.html" '
            'aria-label="Permalink">#</a>')
        return f"""<article class="entry" id="{attr(p['slug'])}"
         data-tags="{attr(','.join(p['tags']))}">
  <h2 class="entry-title">{title}</h2>
  {sub}
  <div class="meta-bar">
    {meta_left}{pills}{anchor}
  </div>
  {links}
{body}{rule}
</article>"""

    # ---- index page --------------------------------------------------------
    page = f"""{page_head(f"{SITE_NAME} \u2014 Projects", "../",
                          "Power electronics projects, papers and hardware.",
                          has_math)}
<body>
{nav_html("../", "projects")}
<div class="wrap">

  <header class="masthead">
    <h1 class="brand"><a href="../index.html"><img class="brand-mark"
       src="../favicon.svg" alt=""><span>{SITE_BRAND}</span></a></h1>
    <div class="tagline">Projects</div>
  </header>

  <section class="lead narrow">
{intro_html}
  </section>

{tagbar_html(counts, PROJECT_TAGS)}

  <hr class="rule">

  <main id="feed" class="index-feed">
{chr(10).join(entry_html(p, False) for p in projects)}
  </main>

  <div class="empty-note" id="empty-note">
    Nothing here carries that tag yet.
  </div>

{footer_html(credit=False)}
</div>
{FILTER_JS}
</body>
</html>
"""
    write(os.path.join(ROOT, "projects", "projects_main.html"), page)

    # ---- one standalone page per project -----------------------------------
    for p in projects:
        sp = f"""{page_head(f"{p['title_text']} \u2014 {SITE_NAME}", "../",
                            re.sub(r"<[^>]+>", "", p["subtitle"])[:180],
                            p["math"])}
<body>
{nav_html("../", "projects")}
<div class="wrap">

  <header class="masthead">
    <h1 class="brand"><a href="../index.html"><img class="brand-mark"
       src="../favicon.svg" alt=""><span>{SITE_BRAND}</span></a></h1>
    <div class="tagline"><a href="projects_main.html"
       style="color:inherit;text-decoration:none">\u2190 All projects</a></div>
  </header>

  <hr class="rule">

  <main>
{entry_html(p, True)}
  </main>

  <hr class="rule">
  <p class="center"><a class="btn" href="projects_main.html">Back to all projects</a></p>

{footer_html(credit=False)}
</div>
</body>
</html>
"""
        write(os.path.join(ROOT, "projects", f"{p['slug']}.html"), sp)

    return len(projects)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print(f"  wrote {os.path.relpath(path, ROOT).replace(os.sep, '/')}")


def build_resume() -> None:
    """A real HTML page around the resume PDF.

    The nav used to link straight at the PDF. A browser set to "download PDFs
    instead of opening them" turns that click into a save dialog, so the nav
    now points here: an HTML page cannot download, and the PDF is embedded with
    direct-open and download links beside it for anything that will not render.
    """
    page = f"""{page_head(f"Résumé — {SITE_NAME}", "",
                          "Resume of Soham Manjrekar, power electronics engineer.",
                          False)}
<body>
{nav_html("", "resume")}
<div class="wrap">

  <header class="masthead">
    <h1 class="brand"><a href="index.html"><img class="brand-mark"
       src="favicon.svg" alt=""><span>{SITE_BRAND}</span></a></h1>
    <div class="tagline">Résumé</div>
  </header>

  <div class="linkrow">
    <a class="btn" href="{RESUME_PDF}" target="_blank"
       rel="noopener noreferrer">Open the PDF in a new tab</a>
    <a class="btn" href="{RESUME_PDF}" download>Download the PDF</a>
  </div>

  <main class="resume-view">
    <iframe class="resume-frame" src="{RESUME_PDF}#view=FitH"
            title="Résumé of {esc(SITE_NAME)}"></iframe>
    <div class="pdf-fallback">Not rendering in your browser?
      <a href="{RESUME_PDF}" target="_blank" rel="noopener noreferrer">Open the
      PDF directly</a>.</div>
  </main>

{footer_html(credit=False)}
</div>
</body>
</html>
"""
    write(os.path.join(ROOT, RESUME_PAGE), page)


def build() -> None:
    del WARNINGS[:]
    del DEFERRED_CHECKS[:]
    print("building sohammjkr.github.io")
    n_posts = build_blog()
    n_proj = build_projects()
    build_resume()
    if not os.path.exists(os.path.join(ROOT, RESUME_PDF)):
        warn(f"{RESUME_PAGE} embeds {RESUME_PDF}, which does not exist")

    for abs_path, as_written, where in DEFERRED_CHECKS:
        if not os.path.exists(abs_path):
            rel = os.path.relpath(where, ROOT).replace(os.sep, "/")
            warn(f"{rel} links to {as_written}, which does not exist")

    print(f"\n{n_posts} post(s), {n_proj} project(s)")
    if WARNINGS:
        print("\nwarnings:")
        for w in sorted(set(WARNINGS)):
            print(f"  ! {w}")
    print("\nopen index.html, or run:  python build.py --serve")


def serve(port: int = 8000) -> None:
    import http.server
    import socketserver
    os.chdir(ROOT)
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"\nserving {ROOT} at http://localhost:{port}/  (ctrl-c to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")


def watch() -> None:
    import time
    watched = [os.path.join(ROOT, "blog", "src"),
               os.path.join(ROOT, "projects", "src"),
               os.path.join(ROOT, "CSS")]

    def stamp():
        out = {}
        for base in watched:
            for dirpath, _, files in os.walk(base):
                for f in files:
                    p = os.path.join(dirpath, f)
                    try:
                        out[p] = os.path.getmtime(p)
                    except OSError:
                        pass
        return out

    last = stamp()
    print("watching blog/src, projects/src and CSS — ctrl-c to stop")
    try:
        while True:
            time.sleep(1)
            now = stamp()
            if now != last:
                last = now
                print("\n--- change detected ---")
                build()
    except KeyboardInterrupt:
        print("\nstopped")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build sohammjkr.github.io")
    ap.add_argument("--serve", action="store_true",
                    help="build, then serve the site on localhost")
    ap.add_argument("--watch", action="store_true",
                    help="rebuild automatically when sources change")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    build()
    if args.watch:
        watch()
    elif args.serve:
        serve(args.port)


if __name__ == "__main__":
    sys.exit(main())
