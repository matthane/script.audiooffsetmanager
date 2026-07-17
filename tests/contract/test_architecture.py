"""Contract test: aom layering rules (import purity).

DESIGN layering: `aom.domain` is pure Python (no Kodi, no legacy modules);
`aom.app` imports only stdlib + aom — with the Phase 7 removal of the
legacy_router MIGRATION shim, the exemption set is EMPTY and construction is
complete; `aom.kodi` is the only package allowed to import xbmc*.
`aom/runtime.py` and `aom/onboarding.py` are composition roots (per-process
entry glue) and exempt by design (they sit outside the three checked
subpackages).
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AOM = REPO_ROOT / "resources" / "lib" / "aom"

# The ONLY aom.app modules allowed to import xbmc*/legacy resources.lib code.
# Empty since Phase 7: every app module is pure.
APP_IMPURITY_EXEMPTIONS = set()


def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _py_files(folder):
    files = sorted(folder.glob("*.py"))
    assert files, "no python files found under {0}".format(folder)
    return files


def test_domain_is_pure():
    for path in _py_files(AOM / "domain"):
        for name in _imports(path):
            assert not name.startswith("xbmc"), \
                "{0} imports Kodi module {1}".format(path.name, name)
            if name.startswith("resources.lib."):
                assert name.startswith("resources.lib.aom.domain"), \
                    "{0} imports outside the domain layer: {1}".format(path.name, name)


def test_app_is_pure_except_explicit_exemptions():
    for path in _py_files(AOM / "app"):
        if path.name in APP_IMPURITY_EXEMPTIONS:
            continue
        for name in _imports(path):
            assert not name.startswith("xbmc"), \
                "{0} imports Kodi module {1}".format(path.name, name)
            if name.startswith("resources.lib."):
                assert name.startswith("resources.lib.aom."), \
                    "{0} imports legacy module {1}".format(path.name, name)


def test_app_exemption_list_is_exact():
    # A deleted shim must not leave a stale exemption behind.
    app_files = {p.name for p in (AOM / "app").glob("*.py")}
    missing = APP_IMPURITY_EXEMPTIONS - app_files
    assert not missing, \
        "stale APP_IMPURITY_EXEMPTIONS entries for deleted files: {0}".format(missing)


def test_kodi_adapters_import_only_aom_and_kodi():
    for path in _py_files(AOM / "kodi"):
        for name in _imports(path):
            if name.startswith("resources.lib."):
                assert name.startswith("resources.lib.aom."), \
                    "{0} imports legacy module {1}".format(path.name, name)
