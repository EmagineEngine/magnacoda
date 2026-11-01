import pytest

from magnacoda.config import ScanConfig as _ScanConfig
from magnacoda.orchestrator import run_scan

pytestmark = pytest.mark.integration


def ScanConfig(**settings):  # noqa: N802 - stands in for the real one
    """Quick scans by default, to keep these tests fast: only the tests of the slow checks (moving
    content, hovering, clicking, single keys), the steps and the review page's own scan say quick=False."""
    settings.setdefault("quick", True)
    return _ScanConfig(**settings)


def test_scan_static_violations(fixture_server):
    config = ScanConfig(url=f"{fixture_server}/static_violations.html")
    report = run_scan(config)
    rule_ids = {f.rule_id for f in report.findings}
    assert {"image-alt", "label", "html-has-lang", "color-contrast"} <= rule_ids
    assert all(f.fix is not None for f in report.findings)


def test_scan_clean_page_has_no_violations(fixture_server):
    config = ScanConfig(url=f"{fixture_server}/clean_page.html")
    report = run_scan(config)
    assert report.findings == []


def test_scan_spa_dynamic_catches_late_rendered_violation(fixture_server):
    config = ScanConfig(url=f"{fixture_server}/spa_dynamic.html")
    report = run_scan(config)
    assert any(f.rule_id == "image-alt" for f in report.findings)
    assert report.meta.stability_settled


def test_color_scheme_flag_scans_dark_mode_separately(fixture_server):
    url = f"{fixture_server}/dark_mode.html"
    light = run_scan(ScanConfig(url=url, color_scheme="light"))
    dark = run_scan(ScanConfig(url=url, color_scheme="dark"))
    assert not any(f.rule_id == "color-contrast" for f in light.findings)
    assert any(f.rule_id == "color-contrast" for f in dark.findings)
    assert dark.meta.color_scheme == "dark"


def test_clean_page_reports_what_passed(fixture_server):
    report = run_scan(ScanConfig(url=f"{fixture_server}/clean_page.html"))
    assert report.findings == []
    passed_ids = {r.rule_id for r in report.passed}
    assert {"document-title", "html-has-lang", "image-alt"} <= passed_ids
    assert report.inapplicable_count > 0


def test_page_features_are_detected_from_the_live_dom(fixture_server):
    report = run_scan(ScanConfig(url=f"{fixture_server}/features.html"))
    f = report.page_features
    assert f is not None
    assert f.video == 1 and f.audio == 1 and f.autoplay_media == 1
    assert f.iframes == 1 and f.canvas == 1 and f.images == 1
    assert f.forms == 1 and f.inputs == 2 and f.password_inputs == 1 and f.captcha == 1
    assert f.custom_widgets == 1 and f.live_regions == 1 and f.draggable == 1
    assert f.labelled_controls == 1 and f.popups >= 1
    assert f.fixed_elements >= 1 and f.animated >= 1 and f.meta_refresh == 1
    tiers = {e.num: e.tier for e in report.checklist}
    assert tiers["3.3.8"] == "relevant" and tiers["2.5.7"] == "relevant"
    assert tiers["2.4.11"] == "automated"  # the fixed element is there, but Tab found nothing hidden by it
    # Where to look: each feature keeps a few examples, with a selector and a recognizable hint.
    password = f.examples["password_inputs"][0]
    assert password.selector and password.hint == "Password"
    entries = {e.num: e for e in report.checklist}
    assert entries["3.3.8"].examples


def test_page_without_features_marks_media_criteria_not_applicable(fixture_server):
    report = run_scan(ScanConfig(url=f"{fixture_server}/clean_page.html"))
    tiers = {e.num: e.tier for e in report.checklist}
    assert tiers["1.2.5"] == "not_applicable" and tiers["1.2.2"] == "not_applicable"  # no media at all
    assert tiers["3.3.8"] == "likely_na" and tiers["2.5.7"] == "likely_na"


def _has_image_alt(report) -> bool:
    return any(f.rule_id == "image-alt" for f in report.findings)


def test_screen_flag_scans_the_mobile_layout_separately(fixture_server):
    url = f"{fixture_server}/responsive.html"
    desktop = run_scan(ScanConfig(url=url, screen="desktop"))
    mobile = run_scan(ScanConfig(url=url, screen="mobile"))
    assert not _has_image_alt(desktop)
    assert _has_image_alt(mobile)
    assert (desktop.meta.screen, mobile.meta.screen) == ("desktop", "mobile")


def test_no_screen_flag_behaves_like_the_old_desktop_default(fixture_server):
    report = run_scan(ScanConfig(url=f"{fixture_server}/responsive.html"))
    assert not _has_image_alt(report) and report.meta.screen is None


def test_an_explicit_viewport_overrides_the_screen_preset(fixture_server):
    url = f"{fixture_server}/responsive.html"
    wide_phone = run_scan(ScanConfig(url=url, screen="mobile", viewport_width=1200, viewport_height=800))
    narrow_desktop = run_scan(ScanConfig(url=url, screen="desktop", viewport_width=400, viewport_height=800))
    assert not _has_image_alt(wide_phone)  # mobile preset, but a wide window
    assert _has_image_alt(narrow_desktop)  # desktop preset, but a narrow window


def test_an_explicit_device_overrides_the_screen_preset(fixture_server):
    url = f"{fixture_server}/responsive.html"
    phone = run_scan(ScanConfig(url=url, screen="desktop", device="Pixel 5"))
    assert _has_image_alt(phone)


def test_images_are_photographed_with_their_text_alternatives_when_asked(fixture_server):
    report = run_scan(ScanConfig(url=f"{fixture_server}/images.html", capture_images=True))
    by_selector = {image.selector: image for image in report.images}
    assert report.images_total == 7  # the image that isn't shown isn't counted
    hidden = {image.selector: image.hidden for image in report.images if image.hidden}
    assert sorted(hidden.values()) == [
        'aria-hidden="true"',
        'aria-hidden="true" around it',
        'role="presentation"',
    ]
    assert by_selector["#team"].hidden is None and by_selector["#chart"].hidden is None
    assert by_selector["#team"].alt == "Our team at the office" and by_selector["#team"].kind == "img"
    logo = next(image for image in report.images if "logo" in image.selector)
    assert logo.alt is None
    spacer = next(image for image in report.images if "spacer" in image.selector)
    assert spacer.alt == ""
    assert by_selector["#chart"].kind == "svg" and by_selector["#chart"].label == "Sales chart"
    assert all(image.png and image.png.startswith(b"\x89PNG") for image in report.images)
    assert '"png"' not in report.model_dump_json()  # screenshots never go into the JSON report


def test_without_a_checklist_no_screenshots_are_taken(fixture_server):
    report = run_scan(ScanConfig(url=f"{fixture_server}/images.html"))
    assert report.images == [] and report.images_total == 0


def test_what_axe_reports_and_magnacodas_own_checks_land_under_the_same_element(fixture_server):
    from magnacoda.report.markdown_export import to_markdown

    report = run_scan(ScanConfig(url=f"{fixture_server}/features.html"))
    assert report.element_names  # axe's selectors, named the way magnacoda names elements
    md = to_markdown(report)
    video = md[md.index("`video`") :].split("\n### ")[0]
    assert "- [ ] **Checked:**" in video  # one box for the element
    assert "- **Review**" in video and "video-caption" in video  # axe-core couldn't decide
    assert "- **Check** **[1.2.3 " in video  # magnacoda's own media check
    assert md.count("`video`") == 1  # the element is listed once


def test_elements_hidden_visually_but_reachable_are_flagged_and_skip_links_are_not(fixture_server):
    from magnacoda.report.markdown_export import to_markdown

    report = run_scan(ScanConfig(url=f"{fixture_server}/hidden_focusable.html"))
    found = report.page_features.examples["hidden_reachable"]
    assert report.page_features.hidden_reachable == 3
    assert [(e.selector, e.hint) for e in found] == [
        ("div.hp:nth-of-type(1) > label > input", "Leave this field empty"),  # off-screen honeypot
        ("span.clipped > button", "Secret button"),  # clipped to nothing
        ("a.ghost", "Invisible link"),  # fully transparent
    ]  # not the skip link (visible on focus), the aria-hidden honeypot, the field in a [hidden] box,
    # or the visible fields
    md = to_markdown(report)
    honeypot = md[md.index("`div.hp:nth-of-type(1) > label > input`") :].split("\n### ")[0]
    lines = honeypot.split("\n")
    assert lines[2].startswith("- [ ] **Checked:**")  # its box, then the items
    assert lines[3].startswith("- **Check** **[2.4.7 Focus Visible]")  # hidden but reachable: listed first


def test_the_review_page_itself_passes_magnacodas_own_scan_at_level_aaa(tmp_path):
    """The page that shows reports must set the example: no automated failures, even at AAA, in light
    and dark."""
    from magnacoda import review_server
    from tests.unit.test_review import _scan_folder, _variants

    folder = _scan_folder(tmp_path, ("light", "dark"))
    server = review_server.ReviewServer(folder, _variants(folder))
    server.start()
    try:
        for scheme in ("light", "dark"):
            report = run_scan(
                ScanConfig(url=server.url + "?variant=dark", level="AAA", color_scheme=scheme, quick=False)
            )
            assert [(f.rule_id, f.selector) for f in report.findings] == [], scheme
    finally:
        server.stop()


def test_a_scan_announces_its_steps_in_order(fixture_server):
    from magnacoda import progress

    heard: list[str] = []
    with progress.listening(heard.append):
        run_scan(ScanConfig(url=f"{fixture_server}/images.html", capture_images=True, quick=False))
    assert heard == [
        "loading the page",
        "waiting for the page to settle",
        "running the accessibility checks",
        "looking at what's on the page",
        "photographing the page's images",
        "watching for content that moves by itself",
        "checking the layout when zoomed in",
        "pressing Tab through the page",
        "looking at the form fields",
        "sending the forms empty",
        "trying the form fields",
        "hovering, clicking and pressing single keys",
        "finding the CSS behind the problems",
    ]


def test_form_fields_that_change_the_context_are_found_and_nothing_reaches_the_site():
    import functools
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    from tests.conftest import FIXTURES_DIR

    requests: list[str] = []

    class Recording(SimpleHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002
            requests.append(self.requestline)

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Recording, directory=str(FIXTURES_DIR)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        report = run_scan(ScanConfig(url=f"http://127.0.0.1:{server.server_address[1]}/on_input.html"))
    finally:
        server.shutdown()
    assert report.on_input is not None and report.on_input.tested == 6
    effects = {p.element.selector: p.effect for p in report.on_input.problems}
    assert effects == {
        "#language": "started loading another page",
        "#news": "submitted the form",
        "#search": "opened a new window",
        "#code": "moved the focus somewhere else",
    }
    on_input = [f for f in report.findings if f.rule_id == "magnacoda/on-input"]
    assert len(on_input) == 4 and all(f.wcag_criteria == ["3.2.2"] and f.fix for f in on_input)
    assert all(f.html_snippet.startswith("<") and "magnacoda" not in f.html_snippet for f in on_input)
    entry = next(e for e in report.checklist if e.num == "3.2.2")
    assert entry.status == "failed" and entry.tier == "automated"
    # Only the page itself was loaded: the form, the other page and the new window were all blocked.
    assert all("/on_input.html" in line for line in requests), requests


def test_form_fields_that_change_nothing_pass_3_2_2(fixture_server):
    report = run_scan(ScanConfig(url=f"{fixture_server}/features.html"))
    assert report.on_input is not None and report.on_input.tested >= 1 and not report.on_input.problems
    entry = next(e for e in report.checklist if e.num == "3.2.2")
    assert entry.status == "passed" and entry.tier == "automated" and not entry.examples
    assert entry.follow_up and "beforehand" in entry.follow_up


def test_forms_sent_empty_show_how_their_errors_are_handled_and_nothing_reaches_the_site():
    import functools
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    from tests.conftest import FIXTURES_DIR

    requests: list[str] = []

    class Recording(SimpleHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002
            requests.append(self.requestline)

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Recording, directory=str(FIXTURES_DIR)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        report = run_scan(ScanConfig(url=f"http://127.0.0.1:{server.server_address[1]}/form_errors.html"))
    finally:
        server.shutdown()
    result = report.empty_submit
    assert result is not None and result.tested == 5
    forms = {check.form.selector: check for check in result.forms}
    assert {selector: check.outcome for selector, check in forms.items()} == {
        "#native": "browser",
        "#good": "page",
        "#bad": "page",
        "#quiet": "page",
        "#search": "sent",
    }
    assert forms["#native"].fields[0].message  # the browser's own message, in its language
    good = forms["#good"]
    assert good.announced and good.fields[0].invalid
    assert good.fields[0].message == "Enter your name, for example Ana Silva."
    assert forms["#quiet"].messages == ["Fill in your phone number."] and not forms["#quiet"].announced
    found = {(f.rule_id, f.selector) for f in report.findings if f.rule_id.startswith("magnacoda/error-")}
    assert found == {("magnacoda/error-without-text", "#b-card"), ("magnacoda/error-not-announced", "#quiet")}
    assert all("/form_errors.html" in line for line in requests), requests


def _scan_recording(page: str, quick: bool = True):
    """Scan a test page with a server of its own that records every request it gets."""
    import functools
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    from tests.conftest import FIXTURES_DIR

    requests: list[str] = []

    class Recording(SimpleHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002
            requests.append(self.requestline)

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Recording, directory=str(FIXTURES_DIR)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        report = run_scan(ScanConfig(url=f"http://127.0.0.1:{server.server_address[1]}/{page}", quick=quick))
    finally:
        server.shutdown()
    return report, requests


def test_pressing_tab_through_the_page_finds_what_keyboard_users_meet():
    report, requests = _scan_recording("keyboard.html")
    keyboard = report.keyboard
    assert keyboard is not None and keyboard.complete and keyboard.stops == 9
    problems = {(p.element.selector, p.kind): p.detail for p in keyboard.problems}
    assert problems == {
        ("#no-ring", "focus-not-visible"): "",
        ("#leaves", "on-focus"): "started loading another page",
        ("#jumpy", "on-focus"): "moved the focus somewhere else",
        ("#last", "focus-obscured"): 'covered by #banner ("Cookies? Accept")',
    }
    assert keyboard.skip_link == "works" and not keyboard.jumps
    entries = {e.num: e for e in report.checklist}
    assert entries["2.4.7"].status == "failed" and entries["2.4.11"].status == "failed"
    assert entries["3.2.1"].status == "failed"
    assert entries["2.1.2"].status == "passed" and "all 9 elements" in entries["2.1.2"].follow_up
    assert all(line.split()[1].startswith("/keyboard.html") for line in requests), requests


def test_a_keyboard_trap_and_a_broken_skip_link_are_found():
    report, requests = _scan_recording("keyboard_trap.html")
    keyboard = report.keyboard
    assert keyboard is not None and not keyboard.complete
    kinds = {(p.element.selector, p.kind) for p in keyboard.problems}
    assert ("#t1", "keyboard-trap") in kinds and keyboard.skip_link == "broken"
    rules = {f.rule_id for f in report.findings}
    assert {"magnacoda/keyboard-trap", "magnacoda/skip-link-broken"} <= rules
    entries = {e.num: e for e in report.checklist}
    assert entries["2.1.2"].status == "failed" and entries["2.4.1"].status == "failed"
    assert entries["2.4.7"].tier == "every_page"  # the rest of the page wasn't reached: left to a person
    assert all("/keyboard_trap.html" in line for line in requests), requests


def test_the_layout_is_tried_narrow_with_more_spacing_and_zoomed(fixture_server):
    report, _ = _scan_recording("layout.html")
    layout = report.layout
    assert layout is not None and layout.tested and layout.overflow > 0
    problems = {(p.element.selector, p.kind) for p in layout.problems}
    assert problems == {
        ("#wide", "reflow"),
        ("#loose", "reflow-table"),
        ("#tight", "spacing-clipped"),
        ("#spill", "spacing-spills"),
        ("#half", "spacing-clipped"),
        ("#half", "resize-clipped"),
    }  # the table in its own scrolling box (#fine) and the normal paragraph are fine
    entries = {e.num: e for e in report.checklist}
    assert all(entries[num].status == "failed" for num in ("1.4.10", "1.4.12", "1.4.4"))
    clean = run_scan(ScanConfig(url=f"{fixture_server}/keyboard.html"))
    entries = {e.num: e for e in clean.checklist}
    assert entries["1.4.10"].status == "passed" and "320 px" in entries["1.4.10"].follow_up


def test_password_pasting_and_autocomplete_values_are_checked():
    report, requests = _scan_recording("fields.html")
    fields = report.fields
    assert fields is not None and fields.tested == 9 and fields.secrets == 3
    problems = {(p.element.selector, p.kind, p.detail) for p in fields.problems}
    assert problems == {
        ("#password", "paste-blocked", ""),
        ("#password", "password-autocomplete-off", ""),
        ("#first", "missing-autocomplete", "given-name"),
        ("#phone", "missing-autocomplete", "tel"),
    }  # #where is in a search form, #colour isn't personal, the rest have their values
    first = next(f for f in report.findings if f.selector == "#first")
    assert first.html_snippet == '<input id="first" name="firstName">'  # as the page wrote it
    assert all("/fields.html" in line for line in requests), requests


def test_hovering_clicking_moving_content_tracks_and_single_keys():
    report, requests = _scan_recording("interaction.html", quick=False)
    result = report.interaction
    assert result is not None
    problems = {(p.element.selector, p.kind) for p in result.problems}
    assert problems == {
        ("#ticker", "moving-no-pause"),
        ("#bad-tip", "hover-not-hoverable"),
        ("#bad-tip", "hover-not-dismissible"),
        ("#stale", "expanded-stale"),
        ("#bare", "toggle-no-expanded"),
        ("#mouse-only", "click-only"),
        ("#no-keys", "keys-dont-work"),
        ("#search", "single-key-shortcut"),
    }  # the good tooltip, the right toggle, the working custom button and the paused ticker pass
    notes = {(n.element.selector, n.num) for n in result.notes}
    assert {
        ("#news", "2.2.2"),
        ("#good-tip", "1.4.13"),
        ("#described", "1.2.3"),
        ("#undescribed", "1.2.5"),
    } <= notes
    entries = {e.num: e for e in report.checklist}
    assert all(entries[num].status == "failed" for num in ("1.4.13", "4.1.2", "2.1.1", "2.2.2", "2.1.4"))
    assert all("/interaction.html" in line for line in requests), requests


def test_a_quick_scan_leaves_out_the_slow_checks(fixture_server):
    from magnacoda import progress

    heard: list[str] = []
    with progress.listening(heard.append):
        report = run_scan(ScanConfig(url=f"{fixture_server}/interaction.html"))
    assert report.meta.quick and report.interaction is not None and not report.interaction.problems
    assert "hovering, clicking and pressing single keys" not in heard
    assert "watching for content that moves by itself" not in heard
    assert any(note.num == "1.2.3" for note in report.interaction.notes)  # quick checks still run


def test_axe_core_runs_in_its_own_world_so_a_page_that_changes_built_ins_cant_break_it(fixture_server):
    # changed_builtins.html replaces Array.prototype.find, as an old library on a real page did; run in
    # the page's own world, axe-core then fails with "Result for unknown rule".
    report = run_scan(ScanConfig(url=f"{fixture_server}/changed_builtins.html", quick=False))
    assert any(f.rule_id == "image-alt" for f in report.findings)
    assert report.keyboard is not None and report.layout is not None and report.layout.tested
    # Deque's rule pages are told the visit came from magnacoda, not "axeAPI".
    links = {f.help_url for f in report.findings if f.source == "axe-core"}
    assert links and all(link and link.endswith("?application=magnacoda") for link in links)


def test_radio_and_checkbox_groups_are_listed_once_with_their_options(fixture_server):
    from magnacoda.report.markdown_export import to_markdown

    report = run_scan(ScanConfig(url=f"{fixture_server}/groups.html"))
    groups = {g.element.hint: [o.hint for o in g.options] for g in report.option_groups}
    assert groups == {
        "How do you meet?": ["Online", "In person", "Hybrid"],
        "Small, Large": ["Small", "Large"],  # no group name: called by its options
        "Topics": ["Agendas", "Notes"],
        "Mostly\u2026 (required)": ["Online", "Hybrid"],  # named by aria-labelledby, as real sites often do
    }  # "I agree" stands alone
    unnamed = [f for f in report.findings if f.rule_id == "magnacoda/group-without-name"]
    assert [f.selector for f in unnamed] == ["div.sizes:nth-of-type(1)"]  # only "Small, Large" has no name
    assert next(e for e in report.checklist if e.num == "1.3.1").status == "failed"
    text = to_markdown(report)
    assert text.count('("How do you meet?")') == 1 and '- options: "Online", "In person", "Hybrid"' in text
    assert '> input` ("Online")' not in text and '("I agree")' in text
