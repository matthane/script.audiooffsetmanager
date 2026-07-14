"""Contract test: resources/settings.xml is in lockstep with its generator.

`resources/settings.xml` is a generated file (see `tools/generate_settings.py`),
derived from the format vocabulary in `resources.lib.aom.domain.formats` plus an
embedded structural template. Committing an edit to `formats.py` or the template
without regenerating — or hand-editing `settings.xml` — would let the two drift,
and the drift silently means "no offset found" for some stream. This test runs
the generator and asserts its output matches the working-tree file, so any drift
fails the suite.

The comparison normalizes CRLF to LF (the generator emits LF, but a Windows
checkout with `autocrlf` may materialize CRLF) and is otherwise exact —
including the trailing newline, which a plain `splitlines()` comparison
would silently ignore.
"""

import functools
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_XML = REPO_ROOT / "resources" / "settings.xml"
GENERATOR = REPO_ROOT / "tools" / "generate_settings.py"


@functools.lru_cache(maxsize=1)
def _load_generator():
    # Cached: the one-off spec load isn't registered in sys.modules, so without
    # caching every test would re-exec the full generator module.
    spec = importlib.util.spec_from_file_location("generate_settings", str(GENERATOR))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _first_diff(expected_lines, actual_lines):
    for number, (want, got) in enumerate(zip(expected_lines, actual_lines), 1):
        if want != got:
            return "line {0}:\n  generated: {1!r}\n  on disk:   {2!r}".format(
                number, want, got)
    if len(expected_lines) != len(actual_lines):
        return "line count: generated {0}, on disk {1}".format(
            len(expected_lines), len(actual_lines))
    return "(texts are equal)"


def test_generator_module_exposes_builder():
    generator = _load_generator()
    assert hasattr(generator, "build_settings_text"), \
        "tools/generate_settings.py must expose build_settings_text()"


def test_settings_xml_is_in_lockstep_with_generator():
    generator = _load_generator()
    expected = generator.build_settings_text()
    # Normalize CRLF (Windows autocrlf checkouts) but stay byte-exact
    # otherwise — splitlines() alone would be blind to a lost trailing newline.
    actual = SETTINGS_XML.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert expected == actual, (
        "resources/settings.xml is out of sync with tools/generate_settings.py "
        "(and resources/lib/aom/domain/formats.py).\n"
        "Regenerate with: python tools/generate_settings.py\n"
        "First difference at {0}".format(
            _first_diff(expected.splitlines(), actual.splitlines()))
    )
