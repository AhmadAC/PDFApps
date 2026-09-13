"""Guards against user-facing URLs in app/ pointing at a retired domain.

History of the bug this test exists for (verified with ``git log -S``):

* ``b14d11d`` (2026-03-25) added the Help ("?") button and, in the *same*
  commit, the ``<section id="guide">`` plus its ``<li><a href="#guide">``
  nav entry in ``docs/index.html``. The target the button pointed at was
  created alongside it, so the link worked.
* ``6847858`` (2026-03-27) rewrote the URL's repo path from ``PDFApps-en``
  to ``PDFApps``. That is the form that shipped in 1.15.0. (The original
  ``/PDFApps-en/`` path is a 404 today, so only this commit made the URL
  point at a live page.)
* ``350a419`` (2026-04-08) replaced the single-page site with the five-page
  layout and, in doing so, deleted both the ``#guide`` section and its nav
  link. Nothing has re-added them since.

So the Help button worked for about two weeks and broke in the *website
redesign*, not in the later migration to Cloudflare Pages. The migration
changed the canonical host to ``pdf-apps.com`` but was not the cause; do
not re-attribute this to Cloudflare.

Why the breakage is silent, and therefore why this test exists: the old
``nelsonduarte.github.io/PDFApps/`` host still answers **200**. It does not
404, and it is not a stale snapshot either: it now serves the current
five-page content, whose navigation no longer contains a ``#guide`` anchor.
An unknown fragment is not an error in HTTP or in any browser, so the user
silently landed at the top of a page that no longer had the section, with
nothing anywhere to signal the link was dead. No status code, no log, no
crash can catch this class of bug; only an assertion like the ones below.

These tests are deliberately scoped to the *host*, not to the full URL:
asserting the exact string would turn any legitimate anchor change (e.g.
``#first-steps`` -> ``#install``) into a red test, which would block a valid
edit. Matching ``github.io`` catches the whole class of stale-domain
regressions in one assertion and survives anchor churn.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"

# The retired documentation/website host. Note this is intentionally narrow:
# api.github.com and github.com/... links are live and legitimate (updater,
# OCR help), so only the Pages host is forbidden.
DEAD_HOST = "github.io"

CANONICAL_HOST = "pdf-apps.com"


def _python_sources() -> list[Path]:
    return sorted(p for p in APP.rglob("*.py") if "__pycache__" not in p.parts)


def test_no_app_source_references_the_retired_pages_domain():
    """No Python source under app/ may link to the old GitHub Pages host."""
    offenders: list[str] = []
    for path in _python_sources():
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if DEAD_HOST in line:
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")

    assert not offenders, (
        "app/ must not reference the retired "
        f"{DEAD_HOST!r} site (canonical host is {CANONICAL_HOST}).\n"
        + "\n".join(offenders)
    )


def _json_data_files() -> list[Path]:
    return sorted(p for p in APP.rglob("*.json") if "__pycache__" not in p.parts)


def test_no_json_data_file_references_the_retired_pages_domain():
    """Shipped JSON data under app/ must not carry the dead host either.

    Scoped to every ``*.json`` under app/ rather than to translations.json
    alone: today that glob resolves to exactly one file, so this does not
    change what is currently checked, but it makes the guard cover any JSON
    data file added later instead of silently exempting it. translations.json
    remains the motivating case, being the one place a help link could be
    reintroduced in 8 languages at once.
    """
    offenders: list[str] = []
    for path in _json_data_files():
        if DEAD_HOST in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(ROOT)))

    assert not offenders, (
        f"JSON data under app/ must not reference {DEAD_HOST!r} "
        f"(canonical host is {CANONICAL_HOST}): " + ", ".join(offenders)
    )


def test_help_button_opens_the_canonical_site():
    """The Help button's URL must live on the canonical host.

    Pinned to the host and the docs path only, so the section anchor stays
    free to change without breaking this test.
    """
    src = (APP / "window.py").read_text(encoding="utf-8")
    match = re.search(r'_help_btn\.clicked\.connect\([^\n]*?open\("([^"]+)"\)', src)
    assert match, "Could not locate the Help button's clicked->open(...) wiring."

    url = match.group(1)
    assert url.startswith(f"https://{CANONICAL_HOST}/"), (
        f"Help URL {url!r} must point at https://{CANONICAL_HOST}/"
    )
    assert "/docs" in url, (
        f"Help URL {url!r} should open the documentation page, not the landing page."
    )
