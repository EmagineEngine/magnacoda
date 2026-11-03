"""Tab through a page's links in the pager, and through the section list; Enter follows one."""

import io

import pytest

from magnacoda.pager import browser, links, markdown
from magnacoda.pager import screen as pager
from magnacoda.pager.screen import Action, PagerState

PAGE = (
    "Read [the guide](https://docs.test/guide) and https://a.test/x, or see Usage (section 2).\n\n"
    "A long [link that wraps over two lines of text for sure](https://docs.test/long) end."
)


def _state(height=12, extra_lines=()) -> PagerState:
    lines = links.wrapper(markdown.render)(PAGE, 30) + list(extra_lines)
    return PagerState([("One", lines), ("Usage", ["usage text"]), ("Three", ["three"])], height=height)


def test_the_links_of_a_page_in_reading_order_one_that_wraps_counted_once():
    found = _state().links
    assert [(link.url, link.section) for link in found] == [
        ("https://docs.test/guide", 0),
        ("https://a.test/x", 0),
        ("", 2),
        ("https://docs.test/long", 0),
    ]
    assert len(found[3].parts) == 2  # on two lines, one link


def test_tab_and_shift_tab_go_round_the_links_and_the_one_on_is_shown_in_reverse():
    state = _state()
    assert state.handle("tab") is Action.REDRAW and state.focus == 0
    assert "\x1b[7m" in state.render(30)[0] and links.visible(state.render(30)[0]) == "Read the guide and"
    state.handle("tab")
    state.handle("tab")
    state.handle("tab")
    assert state.handle("tab") is Action.REDRAW and state.focus == 0  # round again
    state.handle("shift-tab")
    assert state.focus == 3


def test_enter_on_a_web_link_opens_it_and_on_a_section_link_goes_there():
    state = _state()
    state.handle("tab")
    assert state.handle("enter") is Action.OPEN_LINK and state.opening == "https://docs.test/guide"
    assert state.focus is None
    for _ in range(3):
        state.handle("tab")
    assert state.handle("enter") is Action.REDRAW and state.index == 1  # (section 2): Usage


def test_esc_lets_go_of_the_link_first_and_quits_only_after():
    state = _state()
    state.handle("tab")
    assert state.handle("esc") is Action.REDRAW and state.focus is None
    assert state.handle("esc") is Action.QUIT_RESTORE


def test_other_keys_let_go_of_the_link_and_do_their_own_job():
    state = _state()
    state.handle("tab")
    assert state.handle("space") is Action.REDRAW and state.index == 1 and state.focus is None
    state = _state()
    state.handle("tab")
    assert state.handle("x") is Action.REDRAW and state.focus is None  # redrawn without the highlight


def test_a_link_below_the_screen_is_scrolled_into_view():
    state = _state(height=6, extra_lines=[f"filler {n}" for n in range(20)] + ["https://far.test/down"])
    for _ in range(5):
        state.handle("tab")
    assert state.links[state.focus].url == "https://far.test/down"
    assert state.top <= state.links[state.focus].parts[0][0] < state.top + state.body_height


def test_the_hint_row_says_where_the_link_goes():
    state = _state()
    state.handle("tab")
    assert (
        state.status_rows(120)[0]
        == "Links 1 of 4: https://docs.test/guide | Open: Enter | Next: Tab | Esc: cancel"
    )
    state.handle("tab")
    state.handle("tab")
    assert state.status_rows(120)[0].startswith("Links 3 of 4: section 2, Usage | Go: Enter")


def test_a_page_without_links_ignores_tab():
    state = PagerState([("One", ["plain"])], height=12)
    assert state.handle("tab") is Action.NOTHING and state.focus is None


def test_tab_in_the_section_list_highlights_a_section_and_enter_goes_there():
    state = _state()
    state.handle("g")
    state.handle("tab")
    state.handle("tab")
    assert state.menu_pick == 1
    rows = state.render(60)
    assert any("\x1b[7m› 2  Usage\x1b[27m" in row for row in rows)
    assert state.status_rows(100)[0].startswith("Links: 2, Usage | Go: Enter")
    state.handle("shift-tab")
    state.handle("shift-tab")
    assert state.menu_pick == 2  # round to the last
    assert state.handle("enter") is Action.REDRAW and state.index == 2 and not state.menu


def test_a_typed_number_wins_over_the_highlight_in_the_list():
    sections = [(f"S{n}", ["x"]) for n in range(12)]
    state = PagerState(sections, height=20)
    state.handle("g")
    state.handle("tab")
    state.handle("1")  # 12 sections: waits for a second digit
    assert state.handle("enter") is Action.REDRAW and state.index == 0


def test_the_keys_tab_and_shift_tab_are_read():
    def reader(data):
        chunks = iter(bytes([b]) for b in data)
        return lambda timeout: next(chunks, b"")

    assert pager.read_key(reader(b"\t")) == "tab"
    assert pager.read_key(reader(b"\x1b[Z")) == "shift-tab"


def test_the_cut_closes_reverse_video_too():
    assert pager._cut("ab\x1b[7mcdef\x1b[27mgh", 4) == "ab\x1b[7mcd\x1b[27m"


def test_the_pager_opens_the_link_and_shows_what_happened(monkeypatch):
    opened = []
    keys = iter(["tab", "enter", "q"])
    monkeypatch.setattr(pager, "alternate_screen_codes", lambda env=None: ("", ""))
    monkeypatch.setattr(pager, "_terminal_size", lambda: (60, 12))
    out = io.StringIO()
    pager.page_sections(
        [("One", "See https://a.test/page now.")],
        out=out,
        key_source=lambda: next(keys),
        open_link=lambda url: opened.append(url) or "Opened in your browser.",
    )
    assert opened == ["https://a.test/page"] and "Opened in your browser." in out.getvalue()


def test_start_section_opens_on_that_section_instead_of_the_list(monkeypatch):
    keys = iter(["q"])
    monkeypatch.setattr(pager, "alternate_screen_codes", lambda env=None: ("", ""))
    monkeypatch.setattr(pager, "_terminal_size", lambda: (60, 12))
    out = io.StringIO()
    pager.page_sections(
        [("One", "first"), ("Two", "second")],
        out=out,
        key_source=lambda: next(keys),
        open_list=True,
        start_section=1,
    )
    assert "second" in out.getvalue() and "Go to section" not in out.getvalue()


# --- opening -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "javascript:alert(1)", "mailto:a@b.test", "ftp://x.test"]
)
def test_only_web_addresses_are_ever_opened(url, monkeypatch):
    monkeypatch.setattr(browser, "open_in_browser", lambda *a, **k: pytest.fail("opened"))
    assert browser.open_link(url) == "Only web addresses (http and https) open from here."


def test_without_a_graphical_browser_nothing_is_opened(monkeypatch):
    monkeypatch.setattr(browser, "browser_available", lambda: False)
    monkeypatch.setattr(browser, "open_in_browser", lambda *a, **k: pytest.fail("opened"))
    assert browser.open_link("https://a.test") == "No browser to open it in here."


def test_a_browser_that_runs_in_the_terminal_does_not_count(monkeypatch):
    monkeypatch.setattr(browser.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(browser.webbrowser, "get", lambda: browser.webbrowser.GenericBrowser("lynx"))
    assert browser.browser_available() is False
    monkeypatch.setattr(browser.webbrowser, "get", lambda: browser.webbrowser.BackgroundBrowser("xdg-open"))
    assert browser.browser_available() is True


def test_opening_goes_through_the_quiet_opener(monkeypatch):
    seen = []
    monkeypatch.setattr(browser, "browser_available", lambda: True)
    monkeypatch.setattr(browser, "open_in_browser", lambda url, *a, **k: seen.append(url))
    assert browser.open_link("https://a.test/x") == "Opened in your browser." and seen == ["https://a.test/x"]


def test_tab_skips_code_and_placeholder_addresses_also_with_hyperlinks_off():
    text = "Go to https://real.test/a or https://example.com/b, `https://code.test/c`.\n\n```\nhttps://api.test/d\n```"
    for hyperlinks in (True, False):
        lines = links.wrapper(markdown.render, hyperlinks=hyperlinks)(text, 60)
        state = PagerState([("One", lines)], height=12)
        assert [link.url for link in state.links] == ["https://real.test/a"], hyperlinks


# --- arrows in the section list, and arrows while on a link ------------------------------------------


def _grid(count=7, height=6):
    """A section list of `count` short names in columns of 3 rows (height 6: 3 rows for the list)."""
    state = PagerState([(f"Part {n}", ["text"]) for n in range(1, count + 1)], height)
    state.width = 60
    state.handle("g")
    assert state._menu_layout()[:2] == (3, 3)
    return state


def test_arrows_in_the_section_list_move_through_rows_and_columns_and_stop_at_the_edges():
    state = _grid()  # columns: 1 2 3 | 4 5 6 | 7
    assert state.handle("down") is Action.NOTHING and state.menu_pick is None  # Tab starts picking
    assert state.handle("tab") is Action.REDRAW and state.menu_pick == 0
    assert state.handle("up") is Action.NOTHING  # top of the column
    state.handle("down"), state.handle("down")
    assert state.menu_pick == 2 and state.handle("down") is Action.NOTHING  # bottom of the column
    assert state.handle("right") is Action.REDRAW and state.menu_pick == 5  # same row, next column
    assert state.handle("right") is Action.NOTHING  # no 9th entry
    state.handle("up"), state.handle("up")
    assert state.menu_pick == 3 and state.handle("right") is Action.REDRAW and state.menu_pick == 6
    assert state.handle("left") is Action.REDRAW and state.menu_pick == 3
    assert state.handle("enter") is Action.REDRAW and state.index == 3 and not state.menu


def test_shift_tab_first_picks_the_last_entry_and_tab_still_wraps():
    state = _grid()
    state.handle("shift-tab")
    assert state.menu_pick == 6
    assert state.handle("tab") is Action.REDRAW and state.menu_pick == 0


def test_esc_closes_the_list_even_with_a_pick():
    state = _grid()
    state.handle("tab")
    assert state.status_rows(100)[0].endswith("Back: Esc")
    assert state.handle("esc") is Action.REDRAW and not state.menu and state.menu_pick is None


def test_a_typed_number_wins_over_the_pick():
    state = _grid()
    state.handle("tab")
    for key in "5", "enter":
        state.handle(key)
    assert not state.menu and state.index == 4


def test_arrows_keep_a_tall_list_s_pick_in_view():
    state = PagerState([(f"A rather long section name {n}", ["x"]) for n in range(1, 13)], 6)
    state.width = 60
    state.handle("g")
    columns, rows, _ = state._menu_layout()
    room = state._menu_room()
    assert rows > room  # it scrolls
    state.handle("tab")  # entry 1
    for _ in range(rows - 1):
        state.handle("down")
    assert state.menu_pick == rows - 1 and state.menu_top == rows - room


def test_on_a_link_the_arrows_scroll_and_keep_it_and_tab_goes_on_from_it():
    text = ["See https://docs.test/a here.", *["filler"] * 20, "And https://docs.test/b too."]
    state = PagerState([("One", text)], 8)
    state.handle("tab")
    assert state.focus == 0
    assert state.handle("down") is Action.REDRAW and state.top == 1 and state.focus == 0
    assert state.handle("k") is Action.REDRAW and state.top == 0 and state.focus == 0
    assert state.handle("tab") is Action.REDRAW and state.focus == 1
    assert state.handle("space") is not Action.NOTHING and state.focus is None  # other keys let go


def test_the_link_bar_starts_with_links_and_ends_with_esc_cancel_at_every_width():
    state = PagerState([("One", ["See https://docs.test/a here.", "and https://docs.test/b."])], 8)
    state.handle("tab")
    for width in (120, 80, 50):
        row = state.status_rows(width)[0]
        assert row.startswith("Links 1") and row.endswith(("Esc: cancel", "Esc cancel")), row
    assert state.status_rows(20)[0] == "1/2 Enter Tab Esc"
