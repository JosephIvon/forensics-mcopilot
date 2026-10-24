# -*- coding: utf-8 -*-
"""Validation tests for the real-world Modbus/S7 communication failure corpus.

Corpus: knowledge/protocols/real_corpora/issues_corpus.jsonl
Docs:   knowledge/protocols/real_corpora/sources.md

Discipline enforced here (anti-fabrication):
  * every entry carries a traceable GitHub source_url
  * verbatim_excerpt must be a non-empty, non-garbage verbatim copy of issue
    page text (no rewriting/completion/translation)
  * error_class / root_cause_status are closed enums
  * corpus size and per-library coverage floors

Run with pytest (``pytest tests/test_real_corpora.py``) or standalone
(``python tests/test_real_corpora.py``); standalone mode needs pytest absent.
"""

import json
import re
from pathlib import Path

CORPUS_PATH = (
    Path(__file__).resolve().parents[1]
    / "knowledge"
    / "protocols"
    / "real_corpora"
    / "issues_corpus.jsonl"
)

ERROR_CLASS_ENUM = {
    "timeout",
    "crc",
    "reset",
    "refused",
    "exception",
    "short_read",
    "malformed",
    "other",
}
ROOT_CAUSE_STATUS_ENUM = {"confirmed", "reported"}

REQUIRED_FIELDS = (
    "id",
    "source_url",
    "repo",
    "issue_title",
    "verbatim_excerpt",
    "error_class",
    "root_cause_status",
    "root_cause_note",
    "device_context",
    "collected_at",
)

# https://github.com/<owner>/<repo>/issues/<n>  (or /discussions/<n>)
GITHUB_URL_RE = re.compile(
    r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(?:issues|discussions)/\d+$"
)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

MIN_TOTAL_ENTRIES = 30
MIN_LIBRARIES = 4
MIN_ENTRIES_PER_LIBRARY = 4


def _load_entries():
    assert CORPUS_PATH.is_file(), f"corpus file missing: {CORPUS_PATH}"
    entries = []
    with CORPUS_PATH.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append((lineno, json.loads(line)))
            except json.JSONDecodeError as exc:  # pragma: no cover - guard rail
                raise AssertionError(f"line {lineno} is not valid JSON: {exc}")
    return entries


ENTRIES = _load_entries()


# ---------------------------------------------------------------------------
# corpus size / coverage
# ---------------------------------------------------------------------------


def test_corpus_meets_minimum_entry_count():
    assert len(ENTRIES) >= MIN_TOTAL_ENTRIES, (
        f"corpus has {len(ENTRIES)} entries, need >= {MIN_TOTAL_ENTRIES}"
    )


def test_library_coverage_floors():
    counts = {}
    for _, entry in ENTRIES:
        counts[entry["repo"]] = counts.get(entry["repo"], 0) + 1
    assert len(counts) >= MIN_LIBRARIES, (
        f"only {len(counts)} libraries covered, need >= {MIN_LIBRARIES}"
    )
    for repo, count in counts.items():
        assert count >= MIN_ENTRIES_PER_LIBRARY, (
            f"library {repo} has only {count} entries, "
            f"need >= {MIN_ENTRIES_PER_LIBRARY}"
        )


# ---------------------------------------------------------------------------
# per-entry schema
# ---------------------------------------------------------------------------


def test_every_entry_has_all_required_fields_as_nonempty_strings():
    for lineno, entry in ENTRIES:
        for field in REQUIRED_FIELDS:
            assert field in entry, f"line {lineno} missing required field {field!r}"
            value = entry[field]
            assert isinstance(value, str), (
                f"line {lineno} field {field!r} is {type(value).__name__}, want str"
            )
            assert value.strip(), f"line {lineno} field {field!r} is empty"


def test_mapping_notes_present_and_cites_excerpt_basis():
    for lineno, entry in ENTRIES:
        notes = entry.get("mapping_notes")
        assert isinstance(notes, str) and notes.strip(), (
            f"line {lineno} mapping_notes missing (error_class mapping must be justified)"
        )
        assert len(notes) >= 10, f"line {lineno} mapping_notes too short"


def test_error_class_within_enum():
    for lineno, entry in ENTRIES:
        assert entry["error_class"] in ERROR_CLASS_ENUM, (
            f"line {lineno} illegal error_class {entry['error_class']!r}"
        )


def test_root_cause_status_within_enum():
    for lineno, entry in ENTRIES:
        status = entry["root_cause_status"]
        assert status in ROOT_CAUSE_STATUS_ENUM, (
            f"line {lineno} illegal root_cause_status {status!r} "
            "(only confirmed/reported allowed; no self-inferred conclusions)"
        )


def test_source_url_format_and_uniqueness():
    seen = set()
    for lineno, entry in ENTRIES:
        url = entry["source_url"]
        assert GITHUB_URL_RE.match(url), (
            f"line {lineno} source_url not a github issue url: {url!r}"
        )
        assert url not in seen, f"line {lineno} duplicate source_url {url!r}"
        seen.add(url)


def test_ids_unique():
    seen = set()
    for lineno, entry in ENTRIES:
        assert entry["id"] not in seen, f"line {lineno} duplicate id {entry['id']!r}"
        seen.add(entry["id"])


def test_collected_at_is_iso_date():
    for lineno, entry in ENTRIES:
        assert DATE_RE.match(entry["collected_at"]), (
            f"line {lineno} collected_at not YYYY-MM-DD: {entry['collected_at']!r}"
        )


# ---------------------------------------------------------------------------
# verbatim excerpt quality (non-empty, not mojibake/garbage)
# ---------------------------------------------------------------------------


def test_verbatim_excerpt_is_nontrivial_text():
    for lineno, entry in ENTRIES:
        excerpt = entry["verbatim_excerpt"]
        assert len(excerpt) >= 15, f"line {lineno} excerpt too short ({len(excerpt)} ch)"
        alphanumeric = sum(ch.isalnum() for ch in excerpt)
        assert alphanumeric >= 3, f"line {lineno} excerpt lacks readable characters"
        distinct = set(excerpt.replace(" ", "").replace("\n", "").replace("\r", ""))
        assert len(distinct) >= 5, (
            f"line {lineno} excerpt looks degenerate (only {len(distinct)} distinct chars)"
        )


def test_verbatim_excerpt_has_no_replacement_or_control_garbage():
    for lineno, entry in ENTRIES:
        excerpt = entry["verbatim_excerpt"]
        assert "\ufffd" not in excerpt, (
            f"line {lineno} excerpt contains U+FFFD replacement char (decode garbage)"
        )
        for ch in excerpt:
            assert ch == "\n" or ch == "\r" or ch == "\t" or ord(ch) >= 0x20, (
                f"line {lineno} excerpt contains control char U+{ord(ch):04X}"
            )


def test_verbatim_excerpt_line_count_reasonable():
    for lineno, entry in ENTRIES:
        excerpt = entry["verbatim_excerpt"]
        lines = [ln for ln in excerpt.splitlines() if ln.strip()]
        assert 1 <= len(lines) <= 60, (
            f"line {lineno} excerpt has {len(lines)} non-empty lines, "
            "expected a focused log/description slice"
        )


def test_excerpts_distinguishable_across_entries():
    seen = {}
    for lineno, entry in ENTRIES:
        key = (entry["source_url"], entry["verbatim_excerpt"])
        assert key not in seen, (
            f"line {lineno} duplicates excerpt of line {seen[key]} (same url + same text)"
        )
        seen[key] = lineno


if __name__ == "__main__":
    import sys

    _tests = [
        (name, fn)
        for name, fn in sorted(globals().items())
        if name.startswith("test_") and callable(fn)
    ]
    _failed = 0
    for _name, _fn in _tests:
        try:
            _fn()
            print(f"PASS {_name}")
        except AssertionError as _exc:
            _failed += 1
            print(f"FAIL {_name}: {_exc}")
    print(f"\n{len(_tests) - _failed}/{len(_tests)} checks passed "
          f"on {len(ENTRIES)} corpus entries at {CORPUS_PATH}")
    sys.exit(1 if _failed else 0)
