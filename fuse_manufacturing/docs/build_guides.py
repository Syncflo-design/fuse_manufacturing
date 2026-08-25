"""Render the training guides from markdown into the HTML the app ships.

The guides are WRITTEN in `docs/training/*.md` and SERVED from
`public/files/training/*.html`. Markdown is the source because a guide is edited far more
often than it is written, and a diff on prose is only readable if the prose is plain text.

HTML rather than PDF for one practical reason: there is no PDF toolchain on the machines
these are built on, so a PDF step meant every guide waited on someone opening Word. Seven
guides sat written and unpublished for that reason. HTML opens in the tab the reader is
already in, prints from the browser when they want paper, and costs nothing to rebuild.

Run it from the app directory:

    python docs/build_guides.py

It rewrites every HTML file from its markdown. Do not edit the HTML by hand — the next
run will overwrite it.
"""

import os
import re
import sys

import markdown

HERE = os.path.dirname(os.path.abspath(__file__))

# Defaults to this app. Another Fuse app passes its own directory — Projects ships its own
# guides, and one build tool for all of them beats a copy per repo drifting apart.
#
#     python docs/build_guides.py C:/ClaudeCode/fuse_projects/fuse_projects
APP = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.abspath(os.path.join(HERE, ".."))
SOURCE = os.path.join(APP, "docs", "training")
TARGET = os.path.join(APP, "public", "files", "training")

# Screenshot placeholders read as an instruction to whoever inserts the picture. They are
# useful in the source and look like an unfinished document to a reader, so they are drawn
# as a labelled gap rather than left as a blockquote of editorial notes.
PLACEHOLDER = re.compile(
	# The line break between the label and the note is a plain newline, not a <br> —
	# markdown only emits <br> where the source ends a line with two spaces, and these do
	# not. Matching on <br> quietly matched nothing and left the editorial notes in place.
	r"<blockquote>\s*<p><strong>(Screenshot[^<]*)</strong>\s*(?:<br\s*/?>)?\s*<em>\[(.*?)\]</em></p>\s*</blockquote>",
	re.S,
)

STYLE = """
:root {
	--ink: #14202a;
	--soft: #55636e;
	--faint: #8a949d;
	--rule: #e3e7ea;
	--ground: #ffffff;
	--panel: #f6f8f9;
	--accent: #1a7a4c;
	--accent-soft: #e8f3ed;
}
@media (prefers-color-scheme: dark) {
	:root {
		--ink: #e8edf1;
		--soft: #a9b4bd;
		--faint: #7c868f;
		--rule: #2b3640;
		--ground: #141a20;
		--panel: #1b232b;
		--accent: #4cc088;
		--accent-soft: #16302380;
	}
}
* { box-sizing: border-box; }
body {
	margin: 0;
	padding: 0 24px 96px;
	background: var(--ground);
	color: var(--ink);
	font: 16px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
	-webkit-font-smoothing: antialiased;
}
main { max-width: 46rem; margin: 0 auto; }
header.guide {
	max-width: 46rem;
	margin: 0 auto;
	padding: 40px 0 20px;
	border-bottom: 2px solid var(--ink);
}
header.guide .eyebrow {
	font-size: 12px;
	font-weight: 700;
	letter-spacing: .14em;
	text-transform: uppercase;
	color: var(--accent);
	margin: 0 0 6px;
}
header.guide h1 { font-size: 2rem; line-height: 1.15; margin: 0; text-wrap: balance; }
header.guide .standfirst { color: var(--soft); margin: 8px 0 0; }
h2 {
	font-size: 1.25rem;
	margin: 2.4rem 0 .6rem;
	padding-top: 1.4rem;
	border-top: 1px solid var(--rule);
	text-wrap: balance;
}
h3 { font-size: 1.02rem; margin: 1.6rem 0 .4rem; text-wrap: balance; }
p, li { color: var(--soft); }
li { margin: .25rem 0; }
strong { color: var(--ink); font-weight: 600; }
ol, ul { padding-left: 1.3rem; }
code {
	background: var(--panel);
	border: 1px solid var(--rule);
	border-radius: 4px;
	padding: .08em .35em;
	font-size: .88em;
	color: var(--ink);
}
.table-scroll { overflow-x: auto; margin: 1rem 0; }
table { border-collapse: collapse; width: 100%; font-size: .93rem; }
th, td {
	text-align: left;
	padding: .5rem .7rem;
	border-bottom: 1px solid var(--rule);
	vertical-align: top;
	color: var(--soft);
}
th { color: var(--ink); font-weight: 600; background: var(--panel); }
blockquote {
	margin: 1.2rem 0;
	padding: .7rem 1rem;
	border-left: 3px solid var(--accent);
	background: var(--accent-soft);
	border-radius: 0 6px 6px 0;
}
blockquote p { margin: .3rem 0; }
figure.shot {
	margin: 1.4rem 0;
	padding: 1.6rem 1rem;
	border: 1px dashed var(--rule);
	border-radius: 8px;
	background: var(--panel);
	text-align: center;
}
figure.shot .label {
	display: block;
	font-size: 12px;
	font-weight: 700;
	letter-spacing: .1em;
	text-transform: uppercase;
	color: var(--accent);
}
figure.shot .what { display: block; margin-top: .3rem; color: var(--faint); font-size: .9rem; }
footer.guide {
	max-width: 46rem;
	margin: 3rem auto 0;
	padding-top: 1rem;
	border-top: 1px solid var(--rule);
	color: var(--faint);
	font-size: .85rem;
}
@media print {
	body { padding: 0; }
	figure.shot { break-inside: avoid; }
	h2 { break-after: avoid; }
}
"""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Fuse</title>
<style>{style}</style>
</head>
<body>
<header class="guide">
	<p class="eyebrow">Fuse user guide{number}</p>
	<h1>{title}</h1>
	{standfirst}
</header>
<main>
{body}
</main>
<footer class="guide">Fuse Manufacturing — Syncflo. Printed from the Guides page.</footer>
</body>
</html>
"""


def placeholder(match):
	"""Turn a screenshot note into a labelled gap rather than an editor's aside."""
	label, what = match.group(1), match.group(2)
	label = label.split("—")[0].strip()
	what = what.replace("to be inserted:", "").strip()
	return (
		f'<figure class="shot"><span class="label">{label}</span>'
		f'<span class="what">{what}</span></figure>'
	)


def build_one(path):
	"""Render one markdown guide. Returns (number, title, filename)."""
	raw = open(path, encoding="utf-8").read()

	# The first heading is the title and the first italic line under it is the standfirst.
	# Both are lifted into the page header, so they are stripped from the body to avoid
	# printing them twice.
	title_match = re.search(r"^#\s+(.+)$", raw, re.M)
	title = title_match.group(1).strip() if title_match else os.path.basename(path)
	raw = re.sub(r"^#\s+.+$", "", raw, count=1, flags=re.M)

	stand_match = re.search(r"^\*(.+?)\*\s*$", raw, re.M)
	standfirst = ""
	if stand_match:
		text = stand_match.group(1).strip()
		raw = raw.replace(stand_match.group(0), "", 1)
		standfirst = f'<p class="standfirst">{text}</p>'

	body = markdown.markdown(raw, extensions=["tables", "sane_lists"])
	body = PLACEHOLDER.sub(placeholder, body)
	# Wide tables scroll inside their own box; the page itself must never scroll sideways.
	body = body.replace("<table>", '<div class="table-scroll"><table>').replace(
		"</table>", "</table></div>"
	)

	name = os.path.basename(path)[: -len(".md")]
	number = name.split(" ", 1)[0]
	number = f" {number}" if number.isdigit() else ""

	html = PAGE.format(title=title, style=STYLE, number=number, standfirst=standfirst, body=body)
	out = os.path.join(TARGET, name + ".html")
	open(out, "w", encoding="utf-8", newline="\n").write(html)
	return name, title


def main():
	os.makedirs(TARGET, exist_ok=True)
	built = []
	for name in sorted(os.listdir(SOURCE)):
		if name.lower().endswith(".md"):
			built.append(build_one(os.path.join(SOURCE, name)))

	for name, title in built:
		print(f"{name}.html  <-  {title}")
	print(f"\n{len(built)} guide(s) into {TARGET}")


if __name__ == "__main__":
	main()
