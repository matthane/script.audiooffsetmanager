"""Contract test: every referenced localized string id exists in strings.po.

Kodi silently renders a missing string id as blank text. This pins that every
numeric label/help id used by resources/settings.xml, and every 32xxx string id
referenced from Python source, is defined as a `msgctxt "#<id>"` entry in the
en_gb strings.po — so a dangling reference fails the build instead of shipping a
blank label.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_XML = REPO_ROOT / "resources" / "settings.xml"
STRINGS_PO = REPO_ROOT / "resources" / "language" / "resource.language.en_gb" / "strings.po"

_PO_ID_RE = re.compile(r'msgctxt\s+"#(\d+)"')
# 32xxx ids as used in Python (e.g. "$ADDON[script.audiooffsetmanager 32092]"),
# bounded so longer digit runs don't partially match.
_PY_STRING_ID_RE = re.compile(r"(?<!\d)(32\d{3})(?!\d)")

# Directories that are not addon source (dev tooling, venvs, caches).
_EXCLUDED_DIRS = {".venv", "venv", ".git", ".claude", "tests", "tools", "__pycache__"}


def _po_ids():
    text = STRINGS_PO.read_text(encoding="utf-8")
    return set(_PO_ID_RE.findall(text))


def _settings_label_help_ids():
    tree = ET.parse(str(SETTINGS_XML))
    ids = set()
    for element in tree.iter():
        for attr in ("label", "help"):
            value = element.get(attr)
            if value and value.isdigit():
                ids.add(value)
    return ids


def _python_string_ids():
    ids = set()
    for path in REPO_ROOT.rglob("*.py"):
        # Check dirs *relative to the repo root* — the repo may itself live under
        # an ancestor dir whose name (e.g. ".claude" for a git worktree) collides
        # with an excluded name.
        rel_parts = path.relative_to(REPO_ROOT).parts
        if _EXCLUDED_DIRS.intersection(rel_parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        ids.update(_PY_STRING_ID_RE.findall(text))
    return ids


PO_IDS = _po_ids()
SETTINGS_IDS = sorted(_settings_label_help_ids(), key=int)
PYTHON_IDS = sorted(_python_string_ids(), key=int)


def test_strings_po_defines_ids():
    assert PO_IDS, "no msgctxt ids parsed from strings.po"


def test_reference_collectors_are_non_empty():
    # Guard: if either collector silently found nothing, the membership tests
    # below would pass vacuously.
    assert SETTINGS_IDS, "no label/help ids collected from settings.xml"
    assert PYTHON_IDS, "no 32xxx ids collected from Python source"


@pytest.mark.parametrize("string_id", SETTINGS_IDS)
def test_settings_label_help_id_defined_in_po(string_id):
    assert string_id in PO_IDS, (
        "settings.xml references label/help #{0} not defined in strings.po"
        .format(string_id)
    )


@pytest.mark.parametrize("string_id", PYTHON_IDS)
def test_python_string_id_defined_in_po(string_id):
    assert string_id in PO_IDS, (
        "Python source references string #{0} not defined in strings.po"
        .format(string_id)
    )
