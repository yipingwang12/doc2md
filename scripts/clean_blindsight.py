"""Convert the archive.org djvu text of Peter Watts' Blindsight into reader chapters.

The input is the <pre> text of the archive.org "Full text" page
(PeterWatts_Blindsight_djvu.html), an OCR of the Tor hardcover released by the
author under CC BY-NC-SA 2.5. Raw line numbers below refer to that text.

Usage:
    python scripts/clean_blindsight.py PeterWatts_Blindsight_djvu.html results/
Writes results/blindsight/Blindsight.txt and
results/blindsight/<NNN_slug>/chapter_01_<slug>.md (one folder per chapter).
Then run: python reader/build_library.py
"""
import html
import re
import sys
from collections import Counter
from pathlib import Path

BODY_START = 192          # first epigraph page ("This is what fascinates me ...")
SHORT = 56                # a line shorter than this can end a paragraph
TERMINAL = tuple('.!?"\'”’)…:')

# Raw line numbers (1-based) of real epigraph attribution lines.
ATTRIB = {196, 202, 223, 504, 1035, 2022, 3094, 4238, 5127, 6007, 6823, 8292,
          9372, 9871, 10450, 11435, 11815, 12891, 13577, 14212, 14965, 15476,
          15990, 16992, 18232}
# Raw line number of a part / section title -> (kind, title).
SECTIONS = {218: ("part", "Prologue"), 488: ("part", "Theseus"),
            6803: ("part", "Rorschach"), 18215: ("part", "Charybdis"),
            18543: ("back", "Acknowledgments"),
            18636: ("back", "Notes and References"),
            19989: ("back", "Creative Commons Licensing Information")}
VERSE = range(10441, 10449)   # r-selectors poem: keep line breaks

# OCR errors fixed by hand after review of the cleaned text.
FIXES = [
    ("Put that downl", "Put that down!"), ("your brainl", "your brain!"),
    ("vivisectionl", "vivisection!"), ("do they wantl", "do they want?"),
    ("coming backl", "coming back?"), ("verbal ordersl", "verbal orders?"),
    ("see whatl", "see what?"), ("alone with herl", "alone with her!"),
    ("based on herl", "based on her!"), ("Can you seel", "Can you see?"),
    ("Saschal", "Sascha!"), ("Jamesl", "James!"), ('"BatesV', '"Bates!"'),
    ("nonsentientV", "nonsentient?\""), ("How do you knowT", 'How do you know?"'),
    ("telling us nowT", 'telling us now?"'), ("They were stealthed/", "They were stealthed!"),
    ("Blindszg/^.", "Blindsight."), ("FreezsA.", "Freeish."), ("Kurzweill", "Kurzweil"),
    ("Kliiver", "Klüver"), ("Cygnus X-l", "Cygnus X-1"), ("Cunningam's", "Cunningham's"),
    ("Robert Paglini", "Robert Paglino"), ("21 -cm", "21-cm"), ("though.. .", "though..."),
    ("blindfowc/z", "blindtouch"), ("blindswe//", "blindsmell"), ("kindoflOU", "kind of IOU"),
    ("bifmgered", "bifingered"), ("viewfmder", "viewfinder"), ("into fiatline", "into flatline"),
    ("massed 1.8T0 10 kg", "massed 1.8×10¹⁰ kg"), ("volume of 2.3 10 8 cubic", "volume of 2.3×10⁸ cubic"),
    ("exceeds critical 77 Natural", "exceeds critical T. Natural"),
    ("http :", "http:"), (".conV", ".com/"), ("http: / /", "http://"),
    ("©creative commons", "Creative Commons"), ("L E G A L CO D i:", "Legal Code:"),
    ("what it's fori", "what it's for?"), ("call themselves /.", "call themselves I."),
    ("Are — are you saying /was?", "Are — are you saying I was?"),
]
# Italic capital I read as "/" between words or at a paragraph start.
SLASH_I_RE = re.compile(r"(?:(?<=^)|(?<=[\s\"—]))/(?= [a-z']|\s*$)")
APOS_RE = re.compile(r"(\w) '(t|re|ll|ve)\b")


def drop_figure(paras):
    """Replace the OCR residue of the Necker cube figure ('/' lines) with a note."""
    out, seen = [], False
    for n, t, v in paras:
        if t == "II" and out:                      # OCR of a dash + close quote
            pn, pt, pv = out.pop()
            out.append((pn, pt + '—"', pv))
            continue
        if t == "/":
            if not seen:
                out.append((n, "[Figure: Necker cube]", v))
            seen = True
            continue
        out.append((n, t, v))
    return out


def fix_ocr(text: str) -> str:
    """Apply the hand-checked OCR fixes to one paragraph."""
    for old, new in FIXES:
        text = text.replace(old, new)
    if "http" not in text:
        text = SLASH_I_RE.sub("I", text)
    text = re.sub(r" ii$", '—"', text)
    text = re.sub(r"([⁰¹²³⁴⁵⁶⁷⁸⁹]) ([.,;:)])", r"\1\2", text)
    text = re.sub(r"(?<=\w) ([,;:])(?=\s)", r"\1", text)
    text = APOS_RE.sub(r"\1'\2", text)
    return text


HEADER_RE = re.compile(r"^(Peter Watts( [\d ]+)?( Blindsight)?|Blindsight|[\d ]+)$")


NOTES = (18637, 19989)
ENTRY_RE = re.compile(r"^(\d{1,3} )?(https?|[A-Z][\w'’\-]+(,| et| [A-Z]\.|\.)|[A-Z][\w'’\-]+ [A-Z][\w'’\-]+,)")
YEAR_RE = re.compile(r"(1[89]|20)\d\d|http")
REF_RE = re.compile(r"(?<=[\w)\"'’.,]) (\d{1,3})(?!,\d|%|\d)(?= ?[.,;:)'’\"]| [a-z(—]|\s*$)")


def pages(lines):
    """Split (n, s) lines into pages at PB markers."""
    cur = []
    for n, s in lines:
        if s == "PB":
            if cur: yield cur
            cur = []
        else:
            cur.append((n, s))
    if cur: yield cur


def split_page(page):
    """Return (body lines, footnote entries) for one page."""
    # footnote block starts after a blank at the first entry-like line with a year in 2 lines
    for i, (n, s) in enumerate(page):
        if s and i and not page[i - 1][1] and ENTRY_RE.match(s):
            window = " ".join(x for _, x in page[i:i + 2])
            if YEAR_RE.search(window) and all(
                    (not x) or ENTRY_RE.match(x) or not page[j - 1][1] is None
                    for j, (_, x) in enumerate(page[i:], i)):
                body, foot = page[:i], page[i:]
                entries = []
                for j, (m, x) in enumerate(foot):
                    if not x: continue
                    prev = foot[j - 1][1] if j else ""
                    if ENTRY_RE.match(x) and (not prev or prev.endswith((".", "/")) or prev.startswith("http")):
                        entries.append([m, x])
                    elif entries:
                        entries[-1][1] += ("" if entries[-1][1].endswith("-") else " ") + x
                    else:
                        entries.append([m, x])
                return body, entries
    return page, []


SUPER = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")


def extract_notes(lines):
    """Remove page-bottom citations from the Notes section.

    Returns (lines without citations, {last body raw line: [citations]}),
    with inline reference numbers turned into superscripts.
    """
    in_notes = [(n, s) for n, s in lines if NOTES[0] <= n < NOTES[1]]
    drop, blocks, rewrite, expected = set(), {}, {}, 0
    for pg in pages(in_notes):
        body, ents = split_page(pg)
        if ents:
            drop |= {n for n, _ in pg[len(body):]}
            last = max(n for n, x in body if x) if any(x for _, x in body) else pg[0][0]
            blocks[last] = [e[1] for e in ents]
        for n, x in body:
            def sup(m):
                nonlocal expected
                v = int(m.group(1))
                if expected < v <= expected + 10:
                    expected = v
                    return m.group(1).translate(SUPER)
                return m.group(0)
            new = REF_RE.sub(sup, " " + x)[1:] if x else x
            if new != x:
                rewrite[n] = new
    out = [(n, rewrite.get(n, s)) for n, s in lines if n not in drop]
    return out, blocks


def attach_notes(paras, blocks):
    """Insert citation blocks after the paragraph that holds each page end."""
    out = []
    starts = [p[0] for p in paras] + [10**9]
    for i, p in enumerate(paras):
        out.append(p)
        for last in sorted(k for k in blocks if starts[i] <= k < starts[i + 1]):
            out.append((p[0], "\n".join(blocks[last]), "cite"))
    return out


def load_dictionary(text: str) -> set[str]:
    """Return known words: system dictionary plus words seen whole in the text."""
    words = {w.lower() for w in Path("/usr/share/dict/words").read_text().split()}
    words |= {w.lower() for w in re.findall(r"[A-Za-z]+(?=[\s.,;:!?\"')])", text)}
    return words


SUFFIXES = ("", "s", "es", "ed", "d", "ing", "ly", "er", "est", "ies", "ied")


def is_word(w: str, known: set[str]) -> bool:
    """Check a word against the known set, allowing common suffixes."""
    w = w.lower()
    for suf in SUFFIXES:
        if w.endswith(suf) and (w[: len(w) - len(suf)] if suf else w) in known:
            return True
    return w.endswith("ies") and w[:-3] + "y" in known


def join_hyphen(left: str, right: str, known: set[str], hyphenated: Counter) -> str:
    """Join a word split at a line end hyphen; keep the hyphen if it is real."""
    head = left.rsplit(None, 1)[-1][:-1]          # word part before the hyphen
    tail = right.split(None, 1)[0] if right else ""
    head_w = re.sub(r"^\W+", "", head)
    tail_w = re.sub(r"\W+$", "", tail)
    if "-" in head_w:
        return left + right
    if hyphenated[f"{head_w}-{tail_w}".lower()] and (head_w + tail_w).lower() not in known:
        return left + right
    if tail_w[:1].isupper():
        return left + right
    joined = (head_w + tail_w).lower()
    if (len(head_w) >= 3 and len(tail_w) >= 3 and is_word(head_w, known)
            and is_word(tail_w, known) and not is_word(joined, known)):
        return left + right
    return left[:-1] + right


def read_lines(raw: list[str]) -> list[tuple[int, str]]:
    """Return (raw line number, text) pairs; page headers become 'PB', blanks ''."""
    out = []
    for n, line in enumerate(raw, 1):
        if n < BODY_START:
            continue
        s = line.strip()
        if s and HEADER_RE.match(s) and n not in SECTIONS:
            out.append((n, "PB"))
        else:
            out.append((n, s))
    return out


def gap_kind(gap: list[str]) -> str:
    """Classify the lines between two text lines: none, blank or page."""
    if not gap:
        return "none"
    return "page" if "PB" in gap else "blank"


def is_break(prev: str, nxt: str, gap: str, n_prev: int, n_next: int) -> bool:
    """Decide whether a paragraph ends between two text lines."""
    if n_prev in ATTRIB or n_next in ATTRIB or n_prev in SECTIONS or n_next in SECTIONS:
        return True
    if n_prev in VERSE and n_next in VERSE:
        return False
    if prev.endswith(("-", "—")) or nxt[:1].islower():
        return False
    ends = prev.endswith(TERMINAL)
    if gap == "blank":
        return True
    return ends and (len(prev) < SHORT or nxt.startswith(('"', '“')))


def build_paragraphs(lines, known, hyphenated):
    """Group lines into paragraphs; return list of (first raw line, text, is_verse)."""
    text_lines = [(n, s) for n, s in lines if s and s != "PB"]
    idx = {n: i for i, (n, _) in enumerate(lines)}
    paras, cur, cur_n = [], "", None
    for k, (n, s) in enumerate(text_lines):
        if cur == "":
            cur, cur_n = s, n
            continue
        pn = text_lines[k - 1][0]
        gap = gap_kind([t for _, t in lines[idx[pn] + 1: idx[n]]])
        prev_line = text_lines[k - 1][1]
        if is_break(prev_line, s, gap, pn, n):
            paras.append((cur_n, cur, pn in VERSE))
            cur, cur_n = s, n
        elif n in VERSE:
            cur += "\n" + s
        elif cur.endswith("-") and re.search(r"[A-Za-z]-$", cur):
            cur = join_hyphen(cur, s, known, hyphenated)
        else:
            cur += " " + s
    paras.append((cur_n, cur, False))
    return paras


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:40]


def split_chapters(paras):
    """Split paragraphs into chapters at section titles and epigraphs."""
    epigraph_starts = {i - 1 for i, (n, _, _) in enumerate(paras) if n in ATTRIB}
    chapters, part, current = [], None, None
    for i, (n, text, verse) in enumerate(paras):
        if n in SECTIONS:
            kind, part = SECTIONS[n]
            current = {"title": part, "kind": kind, "paras": []}
            chapters.append(current)
            continue
        if (i in epigraph_starts and part not in (None, "Prologue")
                and current["paras"]):
            current = {"title": None, "kind": "chapter", "paras": []}
            chapters.append(current)
        if current is None:
            current = {"title": "Blindsight", "kind": "book_epigraphs", "paras": []}
            chapters.append(current)
        current["paras"].append((n, text, verse))
    return number_chapters(chapters)


def number_chapters(chapters):
    """Give each chapter a title of the form '<Part> N: <epigraph start>'."""
    part, count, out = None, 0, []
    for ch in chapters:
        if ch["kind"] == "part":
            part, count = ch["title"], 0
        if ch["kind"] in ("part", "chapter") and part != "Prologue":
            count += 1
            quote = ch["paras"][0][1].split("\n")[0] if ch["paras"] else ""
            hint = re.split(r'(?<=\w)[.,!?]?["”]|\. ', quote.lstrip('"“'))[0].strip()
            hint = hint if len(hint) < 50 else hint[:47].rsplit(" ", 1)[0] + "…"
            ch["title"] = f"{part} {count}: {hint}"
            ch["part"] = part if count == 1 else None
        out.append(ch)
    for ch in out:                      # a part with one chapter needs no number
        if ch.get("part") and sum(c["title"].startswith(ch["part"] + " ") for c in out) == 1:
            ch["title"] = ch["part"]
    return out


def render_md(ch) -> str:
    """Render one chapter as Markdown with the epigraph as a blockquote."""
    lines = [f"# {ch['title']}", ""]
    if ch.get("part"):
        lines += [f"*Part: {ch['part']}*", ""]
    in_notes = ch["title"] == "Notes and References"
    for n, text, verse in ch["paras"]:
        is_epi = any(m in ATTRIB for m in (n,)) or _next_is_attrib(ch, n)
        if n in ATTRIB and '" —' in text:
            quote, who = text.split('" —', 1)
            lines += [f'> {quote}"', ">", f"> —{who.strip()}", ""]
            continue
        if verse is True or is_epi or n in ATTRIB:
            body = text.replace("\n", "  \n> ")
            lines += [f"> {body}", ">"] if not n in ATTRIB else [f"> {text}", ""]
            continue
        if in_notes and re.match(r"\d+ http", text):
            lines += [f"> {text}", ""]
            continue
        if in_notes and len(text) < 60 and not text.endswith(TERMINAL) and "\n" not in text:
            lines += [f"## {text}", ""]
            continue
        if verse == "cite":
            lines += ["> " + "  \n> ".join(text.split("\n")), ""]
            continue
        if text == "*":
            lines += ["* * *", ""]
            continue
        text = re.sub(r"^(\d+)\. ", r"\1\\. ", text)
        lines += [text, ""]
    return "\n".join(lines).rstrip() + "\n"


def _next_is_attrib(ch, n) -> bool:
    ns = [p[0] for p in ch["paras"]]
    i = ns.index(n)
    return i + 1 < len(ns) and ns[i + 1] in ATTRIB


def render_txt(chapters) -> str:
    """Render the whole book as plain text."""
    out = ["BLINDSIGHT", "Peter Watts", ""]
    for ch in chapters:
        if ch["kind"] != "book_epigraphs":
            out += ["", "", ch["title"].upper(), ""]
        for _, text, kind in ch["paras"]:
            if kind == "cite":
                text = "\n".join("    " + t for t in text.split("\n"))
            out += [text, ""]
    return "\n".join(out).rstrip() + "\n"


def extract_pre_text(html_text: str) -> str:
    """Return the unescaped text of the first <pre> block of an archive.org page."""
    m = re.search(r"<pre[^>]*>(.*?)</pre>", html_text, re.S)
    return html.unescape(re.sub(r"<[^>]+>", "", m.group(1)))


def main(src_path: str, out_dir: str) -> None:
    src = Path(src_path).read_text(encoding="utf-8")
    raw = (extract_pre_text(src) if src_path.endswith(".html") else src).split("\n")
    body = "\n".join(raw[BODY_START - 1:])
    known = load_dictionary(body)
    hyphenated = Counter(w.lower() for w in re.findall(r"[A-Za-z]+-[A-Za-z]+", body))
    lines, blocks = extract_notes(read_lines(raw))
    paras = attach_notes(drop_figure(build_paragraphs(lines, known, hyphenated)), blocks)
    paras = [(n, fix_ocr(t), v) for n, t, v in paras]
    chapters = split_chapters(paras)
    out = Path(out_dir)
    book = out / "blindsight"
    book.mkdir(parents=True, exist_ok=True)
    (book / "Blindsight.txt").write_text(render_txt(chapters), encoding="utf-8")
    for i, ch in enumerate(chapters):
        name = f"{(i + 1) * 10:03d}_{slug(ch['title'].replace('Acknowledgments', 'Acknowledgements'))}"
        d = book / name
        d.mkdir(parents=True, exist_ok=True)
        (d / f"chapter_01_{slug(ch['title'])}.md").write_text(render_md(ch), encoding="utf-8")
    print(f"{len(paras)} paragraphs, {len(chapters)} chapters")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
