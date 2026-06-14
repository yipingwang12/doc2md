"""Fixtures for reader e2e tests: temp served root + http.server session server.

Mirrors src/doc2md/desktop.py: SimpleHTTPRequestHandler with directory=<root>,
reader page at /reader/index.html, library.json and chapter paths at the root.
"""
import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
READER_PAGE = "reader/index.html"

BOOK_ID = "tom_jerry"
BOOK_TITLE = "Tom & Jerry <Vol 1>"
PAPER_TITLE = "Methods & <Results>"

ALPHA, ALPHA_MARKER = "Alpha Chapter", "ALPHA-FIRST-LINE"
BETA, BETA_MARKER = "Beta Chapter", "BETA-FIRST-LINE"
GAMMA, GAMMA_MARKER = "Gamma Chapter", "GAMMA-FIRST-LINE"

_SENTENCE = "The quick brown fox jumps over the lazy dog beside the quiet old riverbank. "


def _filler(words: int) -> str:
    para = (_SENTENCE * 12).strip()
    return "\n\n".join([para] * max(1, round(words / len(para.split()))))


def _chapter_md(heading: str, marker: str, words: int) -> str:
    return f"# {heading}\n\n{marker}\n\n{_filler(words)}\n"


# Gamma: YAML front matter (escaped paper-meta title), in-context citations,
# bare prose digits that must NOT linkify, and a references section in the
# "N. text" paragraph form reader.js's refMap fallback parser expects
# (escaped dot keeps markdown-it from turning them into an <ol>).
GAMMA_MD = f"""---
title: {PAPER_TITLE}
authors:
  - Doe, J.
journal: Journal of Testing
year: 2024
---

{GAMMA_MARKER}

Prior work established the effect [1]. Later studies confirmed the finding [1, 2].

In 1923 we found 3 samples near the riverbank dig site.

{_filler(2500)}

## References

1\\. Smith, J. & Jones, K. Foundational results in feline-rodent dynamics. Journal of Testing. 1990.

2\\. Brown, A. <Replication> of foundational results. Journal of Testing. 1995.
"""


@pytest.fixture(scope="session")
def served_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("served-root")
    shutil.copytree(REPO_ROOT / "reader", root / "reader",
                    ignore=shutil.ignore_patterns("__pycache__"))

    chapters = []
    for cid, title, text in [
        ("ch_alpha", ALPHA, _chapter_md("Alpha", ALPHA_MARKER, 4000)),
        ("ch_beta", BETA, _chapter_md("Beta", BETA_MARKER, 4000)),
        ("ch_gamma", GAMMA, GAMMA_MD),
    ]:
        rel = f"results/{BOOK_ID}/{cid}/chapter_01.md"
        md = root / rel
        md.parent.mkdir(parents=True)
        md.write_text(text)
        (md.parent / "figures.json").write_text("[]")  # avoid 404 console noise
        chapters.append({"id": cid, "title": title, "path": rel,
                         "paths": None, "words": len(text.split())})

    book = {"id": BOOK_ID, "title": BOOK_TITLE, "chapters": chapters,
            "words": sum(c["words"] for c in chapters)}
    (root / "library.json").write_text(json.dumps({"books": [book]}))
    return root


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def base_url(served_root: Path):
    """URL of the reader page, served like desktop.py serves it."""
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port),
         "--bind", "127.0.0.1", "--directory", str(served_root)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}/{READER_PAGE}"
    deadline = time.time() + 10
    while True:
        try:
            urllib.request.urlopen(url, timeout=1).close()
            break
        except OSError:
            if time.time() > deadline:
                proc.terminate()
                raise RuntimeError("reader http.server did not start")
            time.sleep(0.05)
    yield url
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture
def console_errors(page) -> list[str]:
    """Collects uncaught page errors and console.error messages."""
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
    page.on("console", lambda msg: (
        msg.type == "error" and "favicon" not in msg.text
        and errors.append(f"console: {msg.text}")))
    return errors
