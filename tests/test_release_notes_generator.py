"""Tests for the release-notes generator (scripts/release_notes.py).

Why this file exists: the generated body is not an internal artefact.
build.yml publishes it as the GitHub release body, and app/updater.py
downloads that body and shows it in the in-app update dialog. Before
this generator, the "## Other" section published raw development
commits to end users, prefix included ("Test: rename unused
QApplication holder to satisfy CodeQL", "Refactor(window): extract
auto-update subsystem into UpdateController").

The categorisation used to be bash inlined in the workflow YAML, which
is why it was never tested. It now lives in a stdlib-only Python module
that the workflow calls, so it can be exercised directly. These tests
import that module rather than re-implementing its rules, and a
separate test asserts the workflow really invokes it.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release_notes.py"
WORKFLOW = ROOT / ".github" / "workflows" / "build.yml"
TRANSLATIONS = ROOT / "app" / "translations.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("_release_notes", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Module-level on purpose, eyes-open about the failure mode: if the
# script ever grows a non-stdlib import, an *uninstalled* one raises here
# during collection and takes all the tests in this file with it, rather
# than failing test_script_is_stdlib_only as a clean assertion (an
# installed one does fail cleanly). Deliberately not made lazy: the
# import is the thing under test, CI goes red either way, and the
# traceback names the offending import and line. Making it lazy would
# cost a fixture threaded through 60-odd tests to soften a signal that is
# already loud and unambiguous.
rn = _load_module()


# -- Development noise must not reach end users -----------------------

class TestDroppedTypes:
    """The regression this change exists for."""

    # Real subjects taken verbatim from v1.14.4..HEAD, which the old
    # bash generator published under "## Other" with the prefix intact.
    REAL_NOISE = [
        "test: rename unused QApplication holder to satisfy CodeQL",
        "refactor(window): extract auto-update subsystem into UpdateController",
        "test(editor): assert writer closed before os.replace in atomic write",
        "refactor(editor): reuse shared atomic PDF write in TabEditar._run",
        "test: close file handles in test_pdfapps to satisfy CodeQL",
        "test(editor): cover image and highlight branches of apply_pending_edits",
        "refactor(editor): extract pure apply_pending_edits dispatcher "
        "from TabEditar._run",
        "refactor(editor): extract pure text-reinsertion helpers to "
        "text_reinsert module",
    ]

    @pytest.mark.parametrize("subject", REAL_NOISE)
    def test_test_and_refactor_are_dropped(self, subject):
        assert rn.classify(subject) is None

    def test_real_interval_publishes_no_noise(self):
        body = rn.build_notes(
            self.REAL_NOISE + [
                "feat(editor): commit inline edits on focus-out",
                "fix(flatpak): pin cryptography and bump pypdf past six CVEs",
            ]
        )
        assert "TabEditar" not in body
        assert "CodeQL" not in body
        assert "text_reinsert" not in body
        assert "## Other" not in body
        assert "- Commit inline edits on focus-out" in body

    @pytest.mark.parametrize("subject", [
        "chore: tidy up",
        "ci(build): retry macOS job",
        "build: bump pyinstaller",
        "docs: rewrite README",
        "docs(deps): note the pypdf floor",
        "style(tools): satisfy CodeQL empty-except and unused-var notes",
        "seo(docs): add OG/Twitter cards, canonical, JSON-LD",
        "Merge pull request #175 from nelsonduarte/chore/bump",
        "chore(deps): bump pillow from 12.2.0 to 12.3.0",
        "Bump actions/checkout from 4 to 5",
    ])
    def test_other_non_user_facing_subjects_are_dropped(self, subject):
        assert rn.classify(subject) is None


# -- Prefix stripping now covers every surviving type -----------------

class TestCleanSubject:
    @pytest.mark.parametrize("subject,expected", [
        ("feat: add thing", "Add thing"),
        ("fix(editor): repair thing", "Repair thing"),
        ("security: bump ghostscript", "Bump ghostscript"),
        ("security(deps): align qtawesome floor to 1.4.2",
         "Align qtawesome floor to 1.4.2"),
        ("perf: faster render", "Faster render"),
        ("a11y: focus indicators", "Focus indicators"),
        ("i18n: translate updater errors", "Translate updater errors"),
        ("feat!: breaking change", "Breaking change"),
        ("feat(editor)!: breaking scoped change", "Breaking scoped change"),
        ("Splash image with no background", "Splash image with no background"),
    ])
    def test_prefix_stripped_and_capitalised(self, subject, expected):
        assert rn.clean_subject(subject) == expected

    def test_no_surviving_bullet_keeps_a_raw_prefix(self):
        """The old sed only knew feat|fix|perf|a11y|docs."""
        subjects = [
            "security(deps): bump pillow floor to 12.3.0",
            "i18n: translate updater SHA256 error messages",
            "design: novo icone com documento PDF",
            "a11y: accessible names, focus indicators, keyboard navigation",
            "perf: run compress off the UI thread",
        ]
        body = rn.build_notes(subjects)
        for line in body.splitlines():
            if line.startswith("- "):
                assert not re.match(
                    r"- [A-Za-z0-9]+(\([^)]*\))?!?:", line
                ), f"raw conventional prefix published: {line!r}"

    def test_unicode_subject_survives(self):
        body = rn.build_notes(["fix(i18n): corrigir acentuação e ícones"])
        assert "- Corrigir acentuação e ícones" in body


# -- Security is its own section, and it leads ------------------------

class TestSecuritySection:
    # All the security commits in main's history (arrow normalised).
    REAL_SECURITY = [
        "security(deps): align qtawesome floor to 1.4.2",
        "security(deps): bump pillow floor to 12.3.0 and update "
        "vulnerable flatpak pins",
        "security: bump bundled Ghostscript 10.05.0 to 10.07.0 (#32)",
        "security: verify SHA256 of bundled Tesseract and Ghostscript downloads",
        "security: upgrade PDF encryption to AES-256 and fix toast use-after-free",
        "security: harden updater hash verification and uninstaller "
        "BAT generation",
        "security: fix ZIP/TAR slip, temp perms, batch injection, " +
        "path validation",
    ]

    @pytest.mark.parametrize("subject", REAL_SECURITY)
    def test_security_commits_get_their_own_heading(self, subject):
        assert rn.classify(subject) == "## Security"

    def test_security_deps_survives_but_docs_deps_does_not(self):
        """Both match /deps/, only one is a user-facing fix."""
        assert rn.classify("security(deps): bump pillow") == "## Security"
        assert rn.classify("docs(deps): note the pypdf floor") is None

    def test_hand_written_bump_not_eaten_by_dependabot_heuristic(self):
        """'bump.*from.*to' is the dependabot filter. Applied blindly it
        also swallows a real security note phrased the same way, which
        is the worst possible thing for it to drop."""
        assert rn.classify(
            "security(deps): bump pillow floor from 12.2.0 to 12.3.0"
        ) == "## Security"
        assert rn.classify(
            "fix(flatpak): bump pypdf from 6.1.0 to 6.10.0"
        ) == "## Fixes & improvements"
        # Untyped and chore-typed dependabot subjects still go.
        assert rn.classify("Bump actions/checkout from 4 to 5") is None
        assert rn.classify(
            "chore(deps): bump pillow from 12.2.0 to 12.3.0"
        ) is None

    def test_security_section_comes_first(self):
        body = rn.build_notes([
            "fix: a fix",
            "feat: a feature",
            "perf: a perf win",
            "security: a security fix",
        ])
        headings = [ln for ln in body.splitlines() if ln.startswith("## ")]
        assert headings[0] == "## Security"
        assert headings == [
            "## Security", "## New features",
            "## Performance", "## Fixes & improvements",
        ]


# -- "Other" is now only the forgotten-prefix safety net --------------

class TestOtherSection:
    def test_typed_commit_never_lands_in_other(self):
        for subject in [
            "feat: x", "fix: x", "perf: x", "security: x",
            "a11y: x", "i18n: x", "design: x",
        ]:
            assert rn.classify(subject) != "## Other"

    def test_unprefixed_commit_is_kept_as_other(self):
        """A real user-facing change whose prefix was forgotten must not
        be dropped silently."""
        assert rn.classify("Splash image with no background") == "## Other"
        body = rn.build_notes(["Splash image with no background"])
        assert "## Other" in body
        assert "- Splash image with no background" in body

    def test_prose_that_merely_sounds_like_a_bump_is_kept(self):
        """The safety net promised more than it delivered.

        The old noise filter was the unanchored "bump.*from.*to", which
        substring-matches an ordinary sentence. A real user-facing
        change with a forgotten prefix was therefore dropped in
        silence, which is precisely what "## Other" exists to prevent.
        """
        assert rn.classify(
            "Bump minimum zoom from 50 to 400 percent"
        ) == "## Other"
        assert rn.classify(
            "Raise the page limit from 500 to 2000 pages"
        ) == "## Other"
        body = rn.build_notes(["Bump minimum zoom from 50 to 400 percent"])
        assert "- Bump minimum zoom from 50 to 400 percent" in body

    def test_machine_generated_dependency_subjects_still_dropped(self):
        """Narrowing the filter must not let dependabot back in.

        "Bumps <pkg> from X to Y" (plural) is the form dependabot uses in
        PR bodies and squash-merge subjects. It does not occur in this
        repo's history, so it is a forward-looking case rather than a
        regression: an earlier "^bump\\s" required a space straight after
        "bump" and published the plural under "## Other".
        """
        for subject in [
            "Bump actions/checkout from 4 to 5",
            "Bump pypdf from 6.1.0 to 6.10.0",
            "Bumps pillow from 12.2.0 to 12.3.0",
            "chore(deps): bump pillow from 12.2.0 to 12.3.0",
            "build(deps): bump pyinstaller from 6.0 to 6.1",
            "Bumped by dependabot[bot]",
        ]:
            assert rn.classify(subject) is None, subject

    def test_prose_mentioning_dependabot_is_kept(self):
        """The bot filter is anchored, so it cannot eat ordinary prose.

        As a bare substring "dependabot" dropped any subject that merely
        named it. Both of these are plausible user-facing commits with a
        forgotten prefix, and "## Other" exists precisely to catch those.
        """
        assert rn.classify(
            "Move the dependabot config into .github"
        ) == "## Other"
        assert rn.classify(
            "Document the dependabot workflow for contributors"
        ) == "## Other"
        # The trailing-account form stays caught: it is not a prefix, so
        # "\\[bot\\]" is deliberately left unanchored.
        assert rn.classify("Bumped by dependabot[bot]") is None
        # A typed commit naming the bot is dropped by its type, not by
        # the noise filter; this is the real subject from this history.
        assert rn.classify(
            "ci: add dependabot config for github-actions and pip"
        ) is None

    def test_unrecognised_type_is_published_as_a_fix(self):
        """The _TYPE_DESTINATION lookup has a default, and it is reached.

        A prefix nobody registered ("hotfix:") must still reach users
        rather than vanish. Flipping the default to HEADING_OTHER used
        to leave every test green, so this pins it.
        """
        assert rn.classify(
            "hotfix: repair crash on open"
        ) == "## Fixes & improvements"
        assert rn.classify("wip: half a feature") == "## Fixes & improvements"

    def test_docs_is_dropped_unconditionally(self):
        """Pins the S-3 decision: docs is maintenance, scope or not.

        The old code had an unreachable `ctype == "docs" and scope ==
        "deps"` branch sitting below the drop-set check. Asserting both
        arms here means a future change that publishes plain `docs:`
        has to face this test rather than silently resurrect the
        ambiguity.
        """
        assert rn.classify("docs: rewrite README") is None
        assert rn.classify("docs(deps): note the pypdf floor") is None
        assert rn.classify("docs(website): update tool list") is None

    def test_other_absent_from_typical_release(self):
        body = rn.build_notes([
            "feat: something new",
            "fix: something fixed",
            "test: something tested",
            "refactor: something moved",
            "chore: something tidied",
        ])
        assert "## Other" not in body


# -- Body assembly ----------------------------------------------------

class TestBuildNotes:
    def test_empty_input_falls_back(self):
        assert rn.build_notes([]).strip() == "Bug fixes and improvements."

    def test_all_dropped_falls_back(self):
        body = rn.build_notes(["chore: a", "test: b", "refactor: c"])
        assert body.strip() == "Bug fixes and improvements."

    def test_blank_and_whitespace_subjects_ignored(self):
        assert rn.build_notes(["", "   ", "\t"]).strip() == \
            "Bug fixes and improvements."

    def test_duplicate_subjects_squashed(self):
        body = rn.build_notes(["fix: same thing", "fix(scope): same thing"])
        assert body.count("- Same thing") == 1

    def test_empty_subject_after_prefix_is_dropped(self):
        assert "- \n" not in rn.build_notes(["fix:", "fix: real one"])

    def test_body_ends_with_newline(self):
        assert rn.build_notes(["fix: a"]).endswith("\n")

    def test_headings_are_markdown_h2(self):
        body = rn.build_notes(["fix: a", "feat: b"])
        for line in body.splitlines():
            if line.startswith("#"):
                assert line.startswith("## ")


# -- Contract with the downstream consumers ---------------------------

class TestDownstreamContract:
    def test_every_heading_has_an_updater_i18n_mapping(self):
        """A heading emitted here but missing from _SECTION_MAP degrades
        to English in the update dialog, silently."""
        from app.updater import _SECTION_MAP
        for heading in rn._SECTION_ORDER:
            assert heading in _SECTION_MAP, heading

    def test_every_updater_key_exists_in_all_eight_languages(self):
        from app.updater import _SECTION_MAP
        data = json.loads(TRANSLATIONS.read_text(encoding="utf-8"))
        assert len(data) == 8, sorted(data)
        for heading, key in _SECTION_MAP.items():
            for lang, table in data.items():
                assert key in table, f"{key} missing in {lang}"
                assert table[key].strip(), f"{key} empty in {lang}"

    def test_security_heading_translated_in_every_language(self):
        data = json.loads(TRANSLATIONS.read_text(encoding="utf-8"))
        values = {
            lang: table["update.section.security"]
            for lang, table in data.items()
        }
        assert values["en"] == "## Security"
        for lang, value in values.items():
            assert value.startswith("## "), (lang, value)
        # English aside, a copy-pasted English string means an
        # untranslated heading shipped by accident.
        non_en = [v for lang, v in values.items() if lang != "en"]
        assert "## Security" not in non_en

    def test_localize_notes_translates_the_security_heading(self):
        from app import i18n
        from app.updater import _localize_notes
        original = i18n._LANG
        try:
            i18n._LANG = "pt"
            out = _localize_notes(rn.build_notes(["security: corrigir X"]))
        finally:
            i18n._LANG = original
        assert "SEGURAN" in out.upper()
        assert "## Security" not in out

    def test_checksums_heading_is_not_emitted_by_the_generator(self):
        """build.yml appends '## Checksums (SHA256)' after this body;
        the updater parses it. The generator must not collide."""
        assert "Checksums" not in rn.build_notes(["fix: a", "feat: b"])


# -- The workflow really uses the module ------------------------------

class TestWorkflowWiring:
    def test_build_yml_invokes_the_script(self):
        """A comment mentioning the script must not satisfy this test.

        The previous version asserted the bare substring
        "scripts/release_notes.py" against the whole file, and build.yml
        names the script in an explanatory comment right above the run
        line. Replacing the invocation with a hardcoded
        `echo ... > release_notes.md` therefore left this green: the
        workflow would have stopped generating notes with nothing going
        red. Comment lines are stripped before matching.
        """
        run_lines = [
            ln.strip()
            for ln in WORKFLOW.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        assert any(
            re.search(
                r"python3?\s+scripts/release_notes\.py\s+\S+\s+-o\s+release_notes\.md",
                ln,
            )
            for ln in run_lines
        ), "build.yml has no uncommented invocation of the generator"

    def test_workflow_no_longer_categorises_inline(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        assert 'OTHER="${OTHER}- ${clean}' not in text

    def test_script_is_stdlib_only(self):
        """The release job has no setup-python step; it uses the runner's
        bare system interpreter.

        Parsed, not substring-matched. The previous denylist of five
        names missed every third-party import outside that list
        ("import packaging", "import tomlkit") and every
        "from X import Y" form, so it failed 3 of 5 probe cases. Walking
        the AST and checking against sys.stdlib_module_names catches any
        non-stdlib import, named or not. Note __future__ is itself in
        stdlib_module_names, so the real import at the top of the script
        is not a false positive.
        """
        import ast

        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    offenders.append(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                # level > 0 is a relative import; the script is a
                # standalone file with no package to be relative to.
                if node.level == 0 and node.module:
                    offenders.append(node.module.split(".")[0])

        assert offenders, "no imports parsed; the AST walk is not looking"
        non_stdlib = sorted(
            {n for n in offenders if n not in sys.stdlib_module_names}
        )
        assert not non_stdlib, (
            f"release_notes.py imports non-stdlib module(s): {non_stdlib}. "
            "The release job runs it with the runner's bare python3."
        )

    def test_cli_writes_a_file(self, tmp_path):
        out = tmp_path / "notes.md"
        first = subprocess.run(
            ["git", "rev-list", "--max-parents=0", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip().splitlines()[0]
        result = subprocess.run(
            [sys.executable, str(SCRIPT), f"{first}..HEAD", "-o", str(out)],
            cwd=ROOT, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        assert out.read_text(encoding="utf-8").strip()
