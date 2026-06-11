"""E2E tests for the doc2md web reader (fixtures in e2e/conftest.py)."""
import json
import re

from playwright.sync_api import Page, expect

from conftest import (
    ALPHA, ALPHA_MARKER, BETA, BETA_MARKER, BOOK_TITLE,
    GAMMA, GAMMA_MARKER, PAPER_TITLE,
)

PAGE_INFO = "#page-info"


# --- Helpers ---

def load_library(page: Page, base_url: str) -> None:
    page.goto(base_url)
    expect(page.locator(".book-card")).to_have_count(1)


def open_book(page: Page) -> None:
    page.locator(".book-card-header").click()  # expands collapsed chapter list


def open_chapter(page: Page, title: str, marker: str) -> None:
    page.locator(".chapter-item", has_text=title).click()
    expect(page.locator("#reader-content")).to_contain_text(marker)


def goto_chapter(page: Page, title: str, marker: str) -> None:
    """Navigate via the TOC sidebar, opening it first if hidden."""
    if "hidden" in (page.locator("#sidebar").get_attribute("class") or ""):
        page.locator("#btn-toc").click()
    page.locator(".toc-item", has_text=title).click()
    expect(page.locator("#reader-content")).to_contain_text(marker)


def expect_page_number(page: Page, n: int) -> None:
    """Visible indicator shows page n of a multi-page (total > 1) chapter."""
    expect(page.locator(PAGE_INFO)).to_contain_text(
        re.compile(rf"Page {n} of (?!1\b)\d+"))


def wait_min_pages(page: Page, n: int) -> None:
    """Wait for pagination recalc before driving keyboard page turns."""
    page.wait_for_function(f"() => state.totalPages >= {n}")


# --- Tests ---

def test_titles_render_escaped(page: Page, base_url: str):
    load_library(page, base_url)
    expect(page.locator(".book-card-header span").first).to_have_text(BOOK_TITLE)

    open_book(page)
    open_chapter(page, GAMMA, GAMMA_MARKER)
    expect(page.locator("#book-title-text")).to_have_text(BOOK_TITLE)
    expect(page.locator(".paper-meta-title")).to_have_text(PAPER_TITLE)


def test_per_chapter_position(page: Page, base_url: str):
    load_library(page, base_url)
    open_book(page)
    open_chapter(page, ALPHA, ALPHA_MARKER)
    wait_min_pages(page, 4)
    for _ in range(3):
        page.keyboard.press("ArrowRight")
    expect_page_number(page, 4)

    goto_chapter(page, BETA, BETA_MARKER)
    expect_page_number(page, 1)

    goto_chapter(page, ALPHA, ALPHA_MARKER)
    expect_page_number(page, 4)


def test_reload_resumes_position(page: Page, base_url: str):
    load_library(page, base_url)
    open_book(page)
    open_chapter(page, ALPHA, ALPHA_MARKER)
    wait_min_pages(page, 3)
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowRight")
    expect_page_number(page, 3)

    page.reload()
    expect(page.locator("#reader-content")).to_contain_text(ALPHA_MARKER)
    expect(page.locator("#book-title-text")).to_have_text(BOOK_TITLE)
    expect_page_number(page, 3)


def test_citations_linkify_in_context_only(page: Page, base_url: str):
    load_library(page, base_url)
    open_book(page)
    open_chapter(page, GAMMA, GAMMA_MARKER)

    cites = page.locator("#reader-content .cite-ref")
    expect(cites).to_have_text(["[1]", "[1, 2]"])

    prose = page.locator("#reader-content p",
                         has_text="In 1923 we found 3 samples")
    expect(prose).to_have_count(1)
    expect(prose.locator(".cite-ref")).to_have_count(0)

    popover = page.locator(".footnote-popover")
    cites.first.hover()
    expect(popover).to_contain_text("Smith, J. & Jones, K.")

    page.mouse.move(0, 0)  # mouseout dismisses
    expect(popover).to_have_count(0)

    cites.nth(1).hover()
    expect(popover).to_contain_text("Smith, J. & Jones, K.")
    expect(popover).to_contain_text("<Replication> of foundational results")


def test_toc_boundaries_and_page_clamping(page: Page, base_url: str,
                                          console_errors: list[str]):
    load_library(page, base_url)
    open_book(page)
    open_chapter(page, ALPHA, ALPHA_MARKER)

    page.locator("#btn-toc").click()
    expect(page.locator(".toc-item")).to_have_text([ALPHA, BETA, GAMMA])

    wait_min_pages(page, 2)
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("ArrowLeft")
    expect_page_number(page, 1)  # clamped at first page

    goto_chapter(page, GAMMA, GAMMA_MARKER)
    for _ in range(30):  # far beyond Gamma's page count
        page.keyboard.press("ArrowRight")
    expect(page.locator(PAGE_INFO)).to_contain_text(
        re.compile(r"Page (\d+) of \1\b"))  # clamped at last page
    nums = re.search(r"Page (\d+) of (\d+)",
                     page.locator(PAGE_INFO).inner_text())
    assert nums[1] == nums[2] and int(nums[2]) > 1

    assert console_errors == []


def test_old_prefs_shape_ignored(page: Page, base_url: str,
                                 console_errors: list[str]):
    old_prefs = {
        "fontSize": 20, "theme": "dark",
        "currentBook": None, "currentChapter": None,
        "currentPage": 50, "scrollFraction": 0.5, "mode": "page",
    }
    page.add_init_script(
        f"localStorage.setItem('doc2md-reader', {json.dumps(json.dumps(old_prefs))})")

    load_library(page, base_url)  # boots, library renders
    open_book(page)
    open_chapter(page, ALPHA, ALPHA_MARKER)
    wait_min_pages(page, 2)
    expect_page_number(page, 1)  # old top-level currentPage:50 ignored

    assert console_errors == []
