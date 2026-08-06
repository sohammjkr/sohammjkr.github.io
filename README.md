# sohammjkr.github.io

Personal site. Three sections — home, journal, projects — sharing one
stylesheet. Posts and projects are written in LaTeX and rendered to HTML by a
small Python script.

## Build it

```bash
python build.py
```

No dependencies beyond the Python standard library. Two other modes:

```bash
python build.py --serve
```

serves the site at `http://localhost:8000` so you can click through it, and

```bash
python build.py --watch
```

rebuilds every time you save a `.tex` file — leave it running while you write.

Open `index.html` and read the whole thing before pushing. The generated HTML is
committed to the repo; GitHub Pages serves the files as-is.

## Layout

```
index.html                      home page — HAND-WRITTEN, not generated
build.py                        the generator
CSS/site.css                    the only stylesheet; all three pages use it

blog/
  blog.html                     GENERATED — do not edit
  src/
    _intro.tex                  the standing text at the top of the page
    _template.tex               copy this to start a post
    2026-08-06-starting-the-journal.tex
  assets/                       GENERATED — images copied in from src/

projects/
  projects_main.html            GENERATED — do not edit
  <slug>.html                   GENERATED — one page per project
  src/
    _intro.tex                  intro + the publications and patents list
    _template/project.tex       copy this folder to start a project
    regenerative-clamp-converter/project.tex
    ...
  assets/                       GENERATED — files copied in from each src folder

files/                          résumés, reports, slide decks
  <name>.docx / .pptx           the original document
  <name>.pdf                    its rendition, for embedding — see below
thesis/                         the MS thesis PDF
assets/                         photos used by the home page
tools/convert_docs_to_pdf.ps1   makes those .pdf renditions (Windows only)
```

Anything marked GENERATED is overwritten on every build. Edit the `.tex` sources
instead.

## Writing a post

1. Copy `blog/src/_template.tex` to `blog/src/YYYY-MM-DD-short-slug.tex`.
2. Fill in `\title`, `\date` and `\tags`, then write.
3. `python build.py`.

The slug part of the filename becomes the entry's anchor, so the post above is
reachable at `blog/blog.html#short-slug`.

Tags are free text, but the five that appear in the filter bar regardless of
post count are set by `BLOG_TAGS` in `build.py`: **food, travel, friends,
hobbies, life**. Any other tag you use still works — it just joins the bar once
something carries it.

Files whose names start with `_` are never published, so the template and the
intro stay out of the feed.

## Adding a project

1. Copy the whole `projects/src/_template/` folder to
   `projects/src/your-project-slug/`.
2. Put any supplementary PDFs, images or data files in that same folder.
3. Fill in the metadata, write the body, `python build.py`.

The folder name becomes the URL: `projects/your-project-slug.html`. Each project
appears twice — in full on the continuous index page, and on its own page for
linking to directly.

`\order{N}` controls position on the index; lower sorts higher, default 999.

### Filter tags

The project filter bar is fixed, in this order, by `PROJECT_TAGS` in
`build.py`: **converters, sensors, control, uiuc, gt, ml/ai, product**. Tags are matched
lower-cased; `TAG_LABELS` beside it sets the casing the pill actually reads as,
so `gt` shows up as **GT**. A tag outside the list still works — it just sorts
to the end of the bar.

### Attached documents

`\attach{Label}{path}` marks a document as belonging to the project. Every
attachment is embedded, already expanded, in a **Documents** block at the end of
the project's own page, each with a button that opens it in a new tab. On the
projects listing the same block collapses to buttons that jump to the project
page. Use `\link` instead for anything hosted elsewhere — a DOI, a repo.

Browsers cannot render `.docx` or `.pptx`, so build.py embeds a PDF rendition
sitting beside the file under the same basename, and offers the original as a
download underneath the viewer. Generate the renditions with:

```bash
powershell -ExecutionPolicy Bypass -File tools/convert_docs_to_pdf.ps1
```

That script drives Word and PowerPoint over COM, so it is Windows-only and is
**not** part of the build — `build.py` stays pure stdlib and runs anywhere. It
skips PDFs that are already newer than their source, so re-running is cheap.
Commit the generated PDFs. Elsewhere, LibreOffice does the same job:

```bash
soffice --headless --convert-to pdf --outdir files "files/Some Report.docx"
```

Miss the step and nothing breaks: the document falls back to a download button
and the build prints a warning naming the file.

### Where files live

There are two kinds of path, and the difference matters:

| You write | What happens |
|---|---|
| `\pdf{/thesis/thesis.pdf}{...}` | Leading `/` means **repo root**. Linked in place, nothing is copied. Use this for large files already in the repo. |
| `\pdf{report.pdf}{...}` | No leading `/` means **next to this `.tex`**. The file is copied into `projects/assets/<slug>/` at build time. |

Both end up as correct relative links, so the site works over `file://` as well
as over HTTP.

## The LaTeX subset

`build.py` is not LaTeX — it understands a documented subset, listed here in
full. Anything it does not recognise has its braces stripped and its text kept,
so an unknown command degrades to plain text rather than breaking the build.

**Metadata** (anywhere in the file, before or inside `document`):

| Command | Used by | Meaning |
|---|---|---|
| `\title{}` | both | entry title |
| `\date{}` | both | `YYYY`, `YYYY-MM`, `YYYY-MM-DD`, or `YYYY-MM-DD HH:MM`. Sorts the feed. |
| `\tags{a, b}` | both | comma-separated, lower-cased |
| `\link{Label}{url}` | both | a button under the title; repeatable |
| `\attach{Label}{path}` | projects | a document embedded at the end of the page; repeatable |
| `\subtitle{}` | projects | the line under the title |
| `\period{}` | projects | free text, e.g. `Aug 2024 -- Present` |
| `\status{}` | projects | short pill, e.g. `Published` |
| `\order{}` | projects | sort position, lower first |
| `\slug{}` | both | override the slug derived from the filename |

**Text**: `\textbf` `\textit` `\emph` `\texttt` `\underline` `\sout` `\textsc`
`\textsuperscript` `\textsubscript` `\href{url}{text}` `\url{}` `\footnote{}`
`\verb|...|` `\\` (line break) `~` (non-breaking space).

**Blocks**: `\section` `\subsection` `\lead{}` `\pullquote{}` `\callout{}`
`\sep` (an Ω spacer inside the entry) `\img{path}{caption}`
`\pdf{path}{caption}` (a PDF viewer embedded mid-body, open by default and
collapsible). For documents that belong to the project, prefer `\attach`.

**Environments**: `itemize` `enumerate` `quote` `quotation` `center` `abstract`
`figure` (with `\includegraphics` and `\caption`) `table` `tabular` `verbatim`
`lstlisting` and the math environments.

**Math** works through MathJax: `$...$`, `\(...\)`, `\[...\]`, `$$...$$`,
`equation`, `align`, `gather`. The MathJax script is only loaded on pages that
actually contain math.

**Typography** follows LaTeX convention — `---` becomes an em dash, `--` an en
dash, `` `` `` and `''` become curly quotes, `'` becomes a right single quote.

**Escapes**: write `\%` `\&` `\_` `\#` `\$` for literal characters, including
inside URLs — `\href{...?q=a\%20b}{...}` produces the right link.

Two small extras: `\age{}` prints my current age, computed from `DOB` in
`build.py`, and `%` starts a comment as usual.

## Things to know

- **The résumé link is in two places.** `RESUME_PDF` at the top of `build.py`
  feeds the nav on generated pages; `index.html` has its own copy in the nav and
  in the intro. Change both when a newer PDF lands in `files/`.
- **Organisation colours live in one place.** The work/study cards on the home
  page are coloured by a `job-<org>` class, and each class sets three values in
  `CSS/site.css` — `--org` (light: left rail and timeline dot), `--org-deep`
  (dark: year pill and organisation name) and `--org-tint` (the card wash).
  Currently GridTran `#7799a6`, Georgia Tech gold `#b3a369` over navy `#003057`,
  Illinois orange `#ff5f05` over blue `#13294b`. To add an organisation, copy a
  block and swap the three values — nothing else needs touching.
- **Card bullets use three kinds of emphasis**, all keyed to the card's colour:

  | Markup | Meaning | Looks like |
  |---|---|---|
  | `<strong>` | a title or position | bold, card colour, never a link |
  | `<span class="person">` | a person's name | underlined, normal weight |
  | `<a class="inst" href="…">` | an institution or group | bold, card colour, underlined link |

  So a bullet reads `<strong>My position</strong> at the
  <a class="inst" href="…">Some Group</a>`, with the advisor on a nested `<ul>`
  underneath: `Research Advisor: <span class="person">Their Name</span>,
  <strong>Their Title</strong>`. Positions are never hyperlinked — only the
  organisations they were held at.
- **The nav says "Journal", the folder is still `blog/`.** Only the label
  changed, so existing links to `blog/blog.html` keep working.
- **The journal blocks copying.** `blog/blog.html` gets `class="no-select"` on
  `<body>`, which turns off text selection and blocks copy, cut, right-click and
  drag. It is a deterrent, not protection — the text is still in the page source
  and reachable through view-source, reader mode or JavaScript off. The projects
  and home pages stay selectable on purpose, so people can copy a citation.
- **The favicon is `favicon.svg`** — an Ω on aubergine, matching the rules
  between sections. Replace the file if you want something else.
- **The projects landing page is `projects/projects_main.html`.** It used to be
  `projects/projects.html`; the old path is gone, so any external link pointing
  at it now 404s. Add a redirect stub there if that matters.
- **One deploy workflow.** `.github/workflows/static.yml` uploads the repo to
  GitHub Pages on every push to `main`. The two Jekyll workflows that used to
  sit beside it were removed — all three targeted the same `pages` concurrency
  group, so which one won a given push was a coin flip. `.nojekyll` is present
  so Pages never tries to process the site.
- **Delete the starter post.** `blog/src/2026-08-06-starting-the-journal.tex`
  exists to prove the pipeline works and to show every construct rendering.
  Replace it when you have something real.
