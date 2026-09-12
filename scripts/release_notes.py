#!/usr/bin/env python3
"""Build the release-notes body from conventional-commit subjects.

Used by the "Generate release notes" step of .github/workflows/build.yml.
The output is published as the GitHub release body, which the in-app
auto-updater downloads and shows to end users (app/updater.py:
_localize_notes translates the "## ..." headings). Anything emitted here
is read by users, not by reviewers, so development-only commit types are
dropped rather than dumped into a catch-all section.

Stdlib only, on purpose: the release job has no setup-python step and
runs this with the runner's system interpreter.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

# Heading text must stay byte-identical to the keys of
# app/updater.py:_SECTION_MAP, otherwise the in-app update dialog shows
# the English heading instead of the translated one (the replace is a
# plain string match, and a miss degrades silently).
HEADING_SECURITY = "## Security"
HEADING_FEATURES = "## New features"
HEADING_PERFORMANCE = "## Performance"
HEADING_FIXES = "## Fixes & improvements"
HEADING_OTHER = "## Other"

FALLBACK_BODY = "Bug fixes and improvements."

# Single source of truth for what each commit type does: a heading to
# publish under, or None to drop. One table instead of a drop-set plus a
# routing map, because the two-structure version grew a branch that
# could never run (a type in the drop-set was re-tested for a scope
# further down) and a test that passed through the wrong arm of the
# chain. Here a type has exactly one entry, so that class of bug cannot
# be expressed.
#
# Dropped types never reach end users: "test"/"refactor" describe
# internal churn ("extract pure dispatcher from TabEditar._run"); docs,
# chore, ci, build, style and seo are repo maintenance. "docs" is
# dropped unconditionally and deliberately: all 44 docs subjects in this
# repo's history are README/website/changelog upkeep, with no
# user-facing change among them. The nearest miss, "docs: document
# bookmarks/TOC and night reading mode", touches only CONTRIBUTING.md,
# README.md and TODO.txt and describes features that already publish
# their own notes via feat:, so publishing it would duplicate.
_TYPE_DESTINATION = {
    "security": HEADING_SECURITY,
    "feat": HEADING_FEATURES,
    "perf": HEADING_PERFORMANCE,
    "fix": HEADING_FIXES,
    "a11y": HEADING_FIXES,
    "i18n": HEADING_FIXES,
    "design": HEADING_FIXES,
    "chore": None,
    "ci": None,
    "build": None,
    "docs": None,
    "test": None,
    "refactor": None,
    "style": None,
    "seo": None,
}

# A recognised type is one the table knows about, whatever its verdict.
# An unrecognised type ("hotfix:") is treated as a fix rather than
# dropped, so a new prefix nobody registered here still reaches users.
_KNOWN_TYPES = frozenset(_TYPE_DESTINATION)

# Section order in the published body. Security first: for a PDF tool it
# is the change users most need to see.
_SECTION_ORDER = (
    HEADING_SECURITY,
    HEADING_FEATURES,
    HEADING_PERFORMANCE,
    HEADING_FIXES,
    HEADING_OTHER,
)

# "type(scope)!: subject"; scope and the breaking-change "!" are optional.
_CONVENTIONAL_RE = re.compile(
    r"^(?P<type>[A-Za-z0-9]+)(?:\((?P<scope>[^)]*)\))?!?:\s*(?P<subject>.*)$"
)

# Machine-generated dependency subjects, matched only against subjects
# with no recognised type. Anchored on purpose: the previous
# "bump.*from.*to" was unanchored and substring-matched, so an ordinary
# sentence that happens to contain those three words ("Bump minimum
# zoom from 50 to 400 percent") was dropped in silence, which is the
# exact failure mode the "## Other" safety net exists to prevent.
#
# "^bumps? <token> from " requires the single-token package/action name
# that dependabot always emits ("Bump actions/checkout from 4 to 5"),
# which prose with a multi-word object does not satisfy. The plural is
# accepted because "Bumps <pkg> from X to Y" is the form dependabot uses
# in PR bodies and in squash-merge subjects.
#
# The bot alternative is anchored too: as a bare substring, "dependabot"
# swallowed ordinary prose that merely mentions it ("Move the dependabot
# config into .github"), the same silent-drop failure mode the "## Other"
# safety net exists to prevent. "\[bot\]" stays unanchored because it is
# a trailing account suffix, not a prefix.
#
# Deliberately NOT applied to a subject that already carries a
# user-facing type: a hand-written "security: bump pillow from 12.2.0
# to 12.3.0" is precisely the note users must see.
_NOISE_RE = re.compile(
    r"^(?:chore|build|ci)?\(?deps\)?:|^bumps?\s+\S+\s+from\s|^dependabot|\[bot\]",
    re.IGNORECASE,
)
_MERGE_RE = re.compile(r"^(Merge|Revert)\b", re.IGNORECASE)


def classify(subject: str) -> str | None:
    """Return the heading a commit subject belongs under, or None to drop.

    "## Other" is reserved for subjects with no recognised type: a
    safety net for a commit whose prefix was forgotten, so a real
    user-facing change is never silently dropped. A subject is only
    dropped from that branch when it is recognisably machine-generated
    (see _NOISE_RE), never merely for containing bump-like wording. A
    *typed* commit never lands in "## Other", which is what used to
    publish raw "Test:" / "Refactor(window):" prefixes to end users.

    Evaluation order is significant and each step is disjoint from the
    next, so no step can shadow one below it:

    1. structural rejects (empty, merge/revert) - never user-facing;
    2. recognised type -> whatever _TYPE_DESTINATION says, full stop.
       A recognised type is decided by that table alone, so no scope or
       wording heuristic can second-guess it (this is what keeps a
       hand-written "security(deps): bump ..." published);
    3. everything else (unrecognised type, or no type at all) -> drop
       if it looks machine-generated, otherwise "## Other".
    """
    subject = subject.strip()
    if not subject:
        return None
    if _MERGE_RE.match(subject):
        return None

    match = _CONVENTIONAL_RE.match(subject)
    ctype = (match.group("type") or "").lower() if match else ""

    if ctype in _KNOWN_TYPES:
        return _TYPE_DESTINATION[ctype]

    if _NOISE_RE.search(subject):
        return None
    # An unrecognised *type* is still a deliberate prefix, so it is a
    # fix rather than an unclassified "## Other" line.
    return HEADING_FIXES if match else HEADING_OTHER


def clean_subject(subject: str) -> str:
    """Strip any conventional-commit prefix and capitalise the first letter.

    The old sed only knew feat|fix|perf|a11y|docs, so every other type
    reached users as "Test: ..." / "Refactor(window): ...".
    """
    subject = subject.strip()
    match = _CONVENTIONAL_RE.match(subject)
    if match:
        subject = match.group("subject").strip()
    if not subject:
        return subject
    return subject[0].upper() + subject[1:]


def build_notes(subjects) -> str:
    """Render the full release-notes body for an iterable of subjects."""
    sections: dict[str, list[str]] = {h: [] for h in _SECTION_ORDER}

    for subject in subjects:
        heading = classify(subject)
        if heading is None:
            continue
        entry = clean_subject(subject)
        if not entry:
            continue
        bullet = f"- {entry}"
        # Squash duplicate subjects (cherry-picks, reverted-then-redone
        # work) so the same line is not published twice.
        if bullet not in sections[heading]:
            sections[heading].append(bullet)

    parts = []
    for heading in _SECTION_ORDER:
        if sections[heading]:
            parts.append(heading + "\n" + "\n".join(sections[heading]) + "\n")

    if not parts:
        return FALLBACK_BODY + "\n"
    return "\n".join(parts)


def _git_subjects(rev_range: str) -> list[str]:
    out = subprocess.run(
        ["git", "log", "--pretty=format:%s", "--no-merges", rev_range],
        check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout
    return out.splitlines()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rev_range", help="git revision range, e.g. v1.0.0..v1.1.0")
    parser.add_argument("-o", "--output", help="write to this file instead of stdout")
    args = parser.parse_args(argv)

    body = build_notes(_git_subjects(args.rev_range))
    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
    else:
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
