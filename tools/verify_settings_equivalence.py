#!/usr/bin/env python3
"""One-shot transition proof: regenerated settings.xml == hand-written baseline.

Phase 1 replaces the hand-maintained ``resources/settings.xml`` with the output
of ``tools/generate_settings.py``. Before adopting that normalization we must
prove it changes nothing that Kodi cares about. This script compares the
last hand-written baseline blob (pinned: ``BASELINE_REV`` below, the final
commit before "Normalize settings.xml to generator output") against the
file now on disk and asserts they are *semantically* identical:

- **Skeleton** (ordered, because it is the on-screen layout):
  section -> categories (id/label/help) -> groups (id/label/help) ->
  the ordered list of setting ids in each group.
- **Every setting** via a generic, whole-subtree canonical comparison: same
  attributes (order-independent) and the same tree of child elements — tags,
  attributes, and whitespace-stripped text, in document order. This is not a
  hand-picked field whitelist, so it catches *anything*: constraints, options,
  dependencies (including nested ``<and>``/``<or>``), controls, ``<data>``,
  ``<enable>``, ``<close>``, ``<popup>``, defaults, levels, parents.

Comments and insignificant whitespace (indentation, trailing spaces, blank
lines, attribute ordering) are intentionally ignored — those are the only things
the normalization is allowed to change.

Exit code 0 and "PASS" on equivalence; 1 and a precise first-mismatch report
otherwise. Stdlib only; Python 3.8 compatible.

NOTE: this is a ONE-SHOT transition proof, already spent — the permanent
lockstep guard is tests/contract/test_settings_generated.py. The baseline
defaults to the pinned pre-normalization commit so re-runs still compare
against the true hand-written file (comparing against HEAD would be vacuous
now that HEAD's settings.xml *is* generator output). Pass an explicit rev as
argv[1] to compare against a different baseline.

RETIRED: since the onboarding removal (new_install, the test-video buttons,
and their dependencies were deleted from the generator), a re-run against the
pinned baseline FAILS BY DESIGN — the divergence is intentional, not a
regression. Kept only as the historical record of the Phase 1 proof.
"""
from __future__ import print_function

import os
import subprocess
import sys
import xml.etree.ElementTree as ET

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_REL = os.path.join("resources", "settings.xml")
SETTINGS_PATH = os.path.join(REPO_ROOT, SETTINGS_REL)

# Last commit whose resources/settings.xml is the hand-written original
# ("Add settings.xml generator with equivalence proof tool"). The very next
# commit normalized the file to generator output.
BASELINE_REV = "ed0b2a1"


def _load_baseline(rev):
    """The committed hand-written file, as text (<rev>:resources/settings.xml).

    encoding='utf-8' explicitly: universal_newlines/text mode would decode with
    the locale codec (cp1252 on Windows) while the regenerated file is read as
    UTF-8 — an asymmetry that would misfire the moment a non-ASCII character
    enters the file.
    """
    return subprocess.check_output(
        ["git", "-C", REPO_ROOT, "show", rev + ":" + SETTINGS_REL.replace(os.sep, "/")],
        encoding="utf-8",
    )


def _load_regenerated():
    with open(SETTINGS_PATH, "r", encoding="utf-8") as handle:
        return handle.read()


def _section(text):
    root = ET.fromstring(text)
    section = root.find("section")
    if section is None:
        raise ValueError("no <section> element found")
    return section


def _canon(element):
    """Canonical, comment-free, whitespace-normalized form of an element tree.

    Attributes are order-independent (sorted); child elements keep document
    order (it is meaningful for <option>/<condition> sequences); text is
    stripped. Comments are dropped by ElementTree's parser before we get here.
    """
    return (
        element.tag,
        tuple(sorted(element.attrib.items())),
        (element.text or "").strip(),
        tuple(_canon(child) for child in element),
    )


def _first_canon_diff(want, got, path="setting"):
    """Return a human-readable description of the first difference, or None."""
    if want[0] != got[0]:
        return "{0}: tag {1!r} != {2!r}".format(path, want[0], got[0])
    here = "{0}<{1}>".format(path, want[0])
    if want[1] != got[1]:
        return "{0}: attributes {1} != {2}".format(here, list(want[1]), list(got[1]))
    if want[2] != got[2]:
        return "{0}: text {1!r} != {2!r}".format(here, want[2], got[2])
    if len(want[3]) != len(got[3]):
        return "{0}: child count {1} != {2} (child tags {3} != {4})".format(
            here, len(want[3]), len(got[3]),
            [c[0] for c in want[3]], [c[0] for c in got[3]])
    for index, (want_child, got_child) in enumerate(zip(want[3], got[3])):
        if want_child != got_child:
            return _first_canon_diff(want_child, got_child,
                                     "{0}/{1}[{2}]".format(here, want_child[0], index))
    return None


def _skeleton(section):
    """Ordered skeleton: [(cat_id, label, help, [(grp_id, label, help, [sid...])])]."""
    skeleton = []
    for category in section.findall("category"):
        groups = []
        for group in category.findall("group"):
            setting_ids = [s.get("id") for s in group.findall("setting")]
            groups.append((group.get("id"), group.get("label"),
                           group.get("help"), setting_ids))
        skeleton.append((category.get("id"), category.get("label"),
                         category.get("help"), groups))
    return skeleton


def _compare_skeletons(base, regen, failures):
    if base.get("id") != regen.get("id"):
        failures.append("section id {0!r} != {1!r}".format(
            base.get("id"), regen.get("id")))
        return

    base_skeleton = _skeleton(base)
    regen_skeleton = _skeleton(regen)

    base_cat_ids = [c[0] for c in base_skeleton]
    regen_cat_ids = [c[0] for c in regen_skeleton]
    if base_cat_ids != regen_cat_ids:
        failures.append("category order/set differs:\n  baseline:  {0}\n  regen:     {1}"
                        .format(base_cat_ids, regen_cat_ids))
        return

    for base_cat, regen_cat in zip(base_skeleton, regen_skeleton):
        cid = base_cat[0]
        if base_cat[:3] != regen_cat[:3]:
            failures.append("category {0!r} header differs: "
                            "(id,label,help) {1} != {2}"
                            .format(cid, base_cat[:3], regen_cat[:3]))
        base_groups, regen_groups = base_cat[3], regen_cat[3]
        base_grp_ids = [g[0] for g in base_groups]
        regen_grp_ids = [g[0] for g in regen_groups]
        if base_grp_ids != regen_grp_ids:
            failures.append("category {0!r} group order/set differs:\n"
                            "  baseline:  {1}\n  regen:     {2}"
                            .format(cid, base_grp_ids, regen_grp_ids))
            continue
        for base_grp, regen_grp in zip(base_groups, regen_groups):
            gid = base_grp[0]
            if base_grp[:3] != regen_grp[:3]:
                failures.append("group {0!r} header differs: (id,label,help) {1} != {2}"
                                .format(gid, base_grp[:3], regen_grp[:3]))
            if base_grp[3] != regen_grp[3]:
                failures.append("group {0!r} setting-id list differs:\n"
                                "  baseline:  {1}\n  regen:     {2}"
                                .format(gid, base_grp[3], regen_grp[3]))


def _compare_settings(base, regen, failures):
    base_settings = {s.get("id"): s for s in base.iter("setting")}
    regen_settings = {s.get("id"): s for s in regen.iter("setting")}

    base_ids = set(base_settings)
    regen_ids = set(regen_settings)
    if base_ids != regen_ids:
        only_base = sorted(base_ids - regen_ids)
        only_regen = sorted(regen_ids - base_ids)
        if only_base:
            failures.append("settings only in baseline: {0}".format(only_base))
        if only_regen:
            failures.append("settings only in regenerated: {0}".format(only_regen))

    # Compare in the baseline's document order for stable, readable output.
    reported = 0
    for setting in base.iter("setting"):
        sid = setting.get("id")
        if sid not in regen_settings:
            continue
        want = _canon(setting)
        got = _canon(regen_settings[sid])
        if want != got:
            detail = _first_canon_diff(want, got, "setting[{0!r}]".format(sid))
            failures.append("setting {0!r} subtree differs -> {1}".format(sid, detail))
            reported += 1
            if reported >= 10:
                failures.append("... (further setting diffs suppressed)")
                break
    return len(base_settings), len(regen_settings)


def verify(rev=BASELINE_REV):
    """Return (ok, report_lines)."""
    base = _section(_load_baseline(rev))
    regen = _section(_load_regenerated())

    failures = []
    _compare_skeletons(base, regen, failures)
    base_count, regen_count = _compare_settings(base, regen, failures)

    categories = len(base.findall("category"))
    groups = sum(len(c.findall("group")) for c in base.findall("category"))

    report = []
    if failures:
        report.append("FAIL: regenerated settings.xml is NOT equivalent to baseline")
        report.append("")
        for failure in failures:
            report.append("  - {0}".format(failure))
        return False, report

    report.append("PASS: regenerated settings.xml is semantically identical to the "
                  "hand-written baseline ({0}:resources/settings.xml)".format(rev))
    report.append("  compared: {0} settings, {1} categories, {2} groups"
                  .format(base_count, categories, groups))
    report.append("  method:   ordered skeleton (section/category/group/setting-id "
                  "lists) + per-setting canonical subtree "
                  "(attributes + child tree + text, comments/whitespace ignored)")
    if base_count != regen_count:
        # Should be impossible given the id-set check above, but be explicit.
        report.append("  note: baseline has {0} settings, regenerated has {1}"
                      .format(base_count, regen_count))
    return True, report


def main():
    rev = sys.argv[1] if len(sys.argv) > 1 else BASELINE_REV
    ok, report = verify(rev)
    print("\n".join(report))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
