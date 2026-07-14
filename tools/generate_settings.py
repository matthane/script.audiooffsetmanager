#!/usr/bin/env python3
"""Generate resources/settings.xml from the format vocabulary.

`settings.xml` is a pure Cartesian product: one integer offset slider for every
`<hdr>_<fps>_<audio>` combination (315 of them), wrapped in a fixed structural
skeleton (onboarding, per-HDR enable toggles, seek-back, notifications,
platform-info and advanced categories). Hand-maintaining ~7,750 lines of that is
error-prone, so this generator emits the whole file instead:

- Everything *vocabulary-shaped* — the HDR types, audio formats, FPS buckets,
  the offset-slider matrix and its label/help ids — derives from
  ``resources.lib.aom.domain.formats`` (the single source of truth). The matrix
  is never re-hardcoded here.
- Everything *structural* — the non-grid categories, the per-HDR enable/FPS
  toggles, dependency shapes, control kinds, and the navigation comments — is
  encoded as template data in this module.

Output is deterministic and byte-stable (only tuples from ``formats`` are
iterated for ordering; the template maps are looked up by key, never iterated
for content order). It is written with LF line endings and UTF-8, matching the
canonical form the contract test pins.

Usage:
    python tools/generate_settings.py            # write resources/settings.xml
    python tools/generate_settings.py --check     # verify the file is current

Stdlib only; Python 3.8 compatible.
"""
from __future__ import print_function

import argparse
import os
import sys

# Make ``resources.lib.aom.domain.formats`` importable when run from anywhere.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from resources.lib.aom.domain import formats  # noqa: E402

SETTINGS_PATH = os.path.join(REPO_ROOT, "resources", "settings.xml")

XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
INDENT_UNIT = "    "  # 4 spaces


# --------------------------------------------------------------------------- #
# Template data (non-vocabulary structure).                                   #
# --------------------------------------------------------------------------- #

# Per-HDR enable-toggle label/help string ids.
HDR_ENABLE_STRING_IDS = {
    "dolbyvision": ("32026", "32027"),
    "hdr10": ("32028", "32029"),
    "hdr10plus": ("32042", "32043"),
    "hlg": ("32030", "32031"),
    "sdr": ("32032", "32033"),
}

# HDR10+ enable is gated on the detected platform capability instead of the
# usual "not a new install" visibility rule (see _enable_hdr_setting).
HDR_ENABLE_PLATFORM_GATED = {"hdr10plus"}

# Per-HDR category (label, help) string ids, in document order.
HDR_CATEGORY_LABELS = {
    "dolbyvision": ("32076", "32088"),
    "hdr10": ("32023", "32084"),
    "hdr10plus": ("32044", "32085"),
    "hlg": ("32025", "32086"),
    "sdr": ("32024", "32087"),
}

# Per-HDR group id (settings.xml numbers groups 1..10,12 — there is no group 11).
HDR_GROUP_IDS = {
    "dolbyvision": "2",
    "hdr10": "3",
    "hdr10plus": "4",
    "hlg": "5",
    "sdr": "6",
}

# --- Navigation comments (decorative; free to diverge from the vocabulary). --
# A comment printed just before a category (only the categories that carry one).
CATEGORY_COMMENT = {
    "dolbyvision": "Category for Dolby Vision",
    "seek_back_settings": "Category for Playback Behavior",
    "platform_info": "Category for information",
    "advanced": "Category for advanced",
}

# The HDR banner comment printed inside each HDR category, before its group.
HDR_GROUP_COMMENT = {
    "dolbyvision": "Dolby Vision",
    "hdr10": "HDR10",
    "hdr10plus": "HDR10+",
    "hlg": "HLG",
    "sdr": "SDR",
}

# FPS-section banner comment. Reproduces the hand-written labels verbatim,
# including the ".00" spellings for 29 and 59 (see the irregularity note in the
# equivalence report). Falls back to a plain label if the vocabulary grows an
# unmapped bucket.
FPS_SECTION_COMMENT = {
    formats.FPS_ALL: "ALL FPS TYPES",
    23: "23.98 FPS",
    24: "24.00 FPS",
    25: "25.00 FPS",
    29: "29.00 FPS",
    30: "30.00 FPS",
    50: "50.00 FPS",
    59: "59.00 FPS",
    60: "60.00 FPS",
}

# Per-audio row comment (decorative marketing names, verbatim from the source).
AUDIO_ROW_COMMENT = {
    "truehd": "Dolby TrueHD",
    "eac3": "Dolby Digital+ (EAC3)",
    "ac3": "Dolby Digital (AC3)",
    "dtshd_ma": "DTS-HD MA",
    "dtshd_hra": "DTS-HD HRA",
    "dca": "DTS (DCA)",
    "pcm": "Other/PCM",
}


# --------------------------------------------------------------------------- #
# Minimal XML node model + renderer (exact control over formatting).          #
# --------------------------------------------------------------------------- #

class Node(object):
    """A minimal XML element: ordered attributes, leaf text OR child elements."""

    __slots__ = ("tag", "attrs", "text", "children")

    def __init__(self, tag, attrs=None, text=None, children=None):
        self.tag = tag
        self.attrs = list(attrs or [])       # ordered (key, value) pairs
        self.text = text                     # leaf text, or None
        self.children = list(children or [])  # child Nodes


def _attrs_str(attrs):
    return "".join(' {0}="{1}"'.format(key, value) for key, value in attrs)


def _render(node, depth, out):
    """Append the rendered lines of *node* (at *depth*) to the list *out*.

    Empty elements self-close as ``<tag/>`` (no space), matching the source.
    Values are assumed free of XML metacharacters (true for this vocabulary).
    """
    pad = INDENT_UNIT * depth
    attrs = _attrs_str(node.attrs)
    if node.children:
        out.append("{0}<{1}{2}>".format(pad, node.tag, attrs))
        for child in node.children:
            _render(child, depth + 1, out)
        out.append("{0}</{1}>".format(pad, node.tag))
    elif node.text not in (None, ""):
        out.append("{0}<{1}{2}>{3}</{1}>".format(pad, node.tag, attrs, node.text))
    else:
        out.append("{0}<{1}{2}/>".format(pad, node.tag, attrs))


# --- Node construction helpers --------------------------------------------- #

def _level(value="0"):
    return Node("level", text=str(value))


def _default(value):
    return Node("default", text=str(value))


def _enable(value):
    return Node("enable", text=str(value))


def _data(text):
    return Node("data", text=text)


def _condition(setting, value):
    return Node("condition", [("setting", setting)], text=value)


def _dep_visible(setting, value):
    return Node("dependency", [("type", "visible"), ("setting", setting)], text=value)


def _dep_enable(setting, value):
    return Node("dependency", [("type", "enable"), ("setting", setting)], text=value)


def _dep_visible_group(operator, conditions):
    return Node("dependency", [("type", "visible")],
                children=[Node(operator, children=conditions)])


def _dependencies(*deps):
    return Node("dependencies", children=list(deps))


def _control_toggle():
    return Node("control", [("type", "toggle")])


def _control_button_action():
    return Node("control", [("type", "button"), ("format", "action")],
                children=[Node("close", text="true")])


def _control_slider_integer():
    return Node("control", [("type", "slider"), ("format", "integer")],
                children=[Node("popup", text="false")])


def _control_spinner_string():
    return Node("control", [("type", "spinner"), ("format", "string")])


def _constraints_range(minimum, step, maximum):
    return Node("constraints", children=[
        Node("minimum", text=str(minimum)),
        Node("step", text=str(step)),
        Node("maximum", text=str(maximum)),
    ])


def _constraints_options(options):
    return Node("constraints", children=[
        Node("options", children=[
            Node("option", [("label", label)], text=str(value))
            for label, value in options
        ]),
    ])


# --------------------------------------------------------------------------- #
# Setting builders.                                                           #
# --------------------------------------------------------------------------- #

def _offset_slider(hdr, fps, audio):
    """One `<hdr>_<fps>_<audio>` integer offset slider (the matrix cell)."""
    label, help_id = formats.AUDIO_STRING_IDS[audio]
    enable_id = "enable_" + hdr
    fps_enable_id = "enable_fps_" + hdr
    if fps == formats.FPS_ALL:
        conditions = [
            _condition(enable_id, "true"),
            _condition(fps_enable_id, "false"),
        ]
    else:
        conditions = [
            _condition(enable_id, "true"),
            _condition(fps_enable_id, "true"),
            _condition(hdr + "_fps", str(fps)),
        ]
    return Node(
        "setting",
        [("id", formats.setting_key(hdr, fps, audio)), ("type", "integer"),
         ("label", label), ("help", help_id), ("parent", enable_id)],
        children=[
            _dependencies(_dep_visible_group("and", conditions)),
            _level("0"),
            _default("0"),
            _constraints_range(-1000, 25, 1000),
            _control_slider_integer(),
        ],
    )


def _enable_hdr_setting(hdr):
    """The `enable_<hdr>` toggle (HDR10+ is gated on platform capability)."""
    label, help_id = HDR_ENABLE_STRING_IDS[hdr]
    if hdr in HDR_ENABLE_PLATFORM_GATED:
        deps = _dependencies(
            _dep_enable("platform_hdr_full", "true"),
            _dep_visible("platform_hdr_full", "true"),
        )
    else:
        deps = _dependencies(_dep_visible("new_install", "false"))
    return Node(
        "setting",
        [("id", "enable_" + hdr), ("type", "boolean"),
         ("label", label), ("help", help_id)],
        children=[deps, _level("0"), _default("false"), _control_toggle()],
    )


def _enable_fps_setting(hdr):
    """The `enable_fps_<hdr>` toggle (per-HDR FPS override)."""
    return Node(
        "setting",
        [("id", "enable_fps_" + hdr), ("type", "boolean"),
         ("label", "32074"), ("help", "32075")],
        children=[
            _dependencies(_dep_visible("enable_" + hdr, "true")),
            _level("0"),
            _default("false"),
            _control_toggle(),
        ],
    )


def _fps_spinner_setting(hdr):
    """The `<hdr>_fps` spinner selecting which FPS bucket to configure."""
    label, help_id = formats.FPS_SPINNER_STRING_IDS
    options = [(formats.FPS_OPTION_LABEL_IDS[bucket], bucket)
               for bucket in formats.FPS_BUCKETS]
    return Node(
        "setting",
        [("id", hdr + "_fps"), ("type", "integer"),
         ("label", label), ("help", help_id)],
        children=[
            _dependencies(_dep_visible_group("and", [
                _condition("enable_" + hdr, "true"),
                _condition("enable_fps_" + hdr, "true"),
            ])),
            _level("0"),
            _default("23"),
            _constraints_options(options),
            _control_spinner_string(),
        ],
    )


# --- Fixed structural settings (verbatim shapes, incl. child ordering). ----- #

def _new_install_setting():
    return Node(
        "setting", [("id", "new_install"), ("type", "boolean")],
        children=[_level("4"), _default("true"), _control_toggle()],
    )


def _action_button(setting_id, label, help_id, script_arg, dependencies):
    """An action button: level, data, control, then dependencies (source order)."""
    return Node(
        "setting",
        [("id", setting_id), ("type", "action"), ("label", label), ("help", help_id)],
        children=[
            _level("0"),
            _data("RunScript(script.audiooffsetmanager,{0})".format(script_arg)),
            _control_button_action(),
            dependencies,
        ],
    )


def _toggle_setting(setting_id, label, help_id, dependencies, default,
                    level_first=False):
    """A boolean toggle. Some source toggles put <level> before <dependencies>."""
    children = ([_level("0"), dependencies] if level_first
                else [dependencies, _level("0")])
    children += [_default(default), _control_toggle()]
    return Node(
        "setting",
        [("id", setting_id), ("type", "boolean"), ("label", label), ("help", help_id)],
        children=children,
    )


def _seconds_slider(setting_id, parent, label, help_id, dependencies, default):
    """A 1..10 second slider (parent attr before type; level before deps)."""
    return Node(
        "setting",
        [("id", setting_id), ("parent", parent), ("type", "integer"),
         ("label", label), ("help", help_id)],
        children=[
            _level("0"),
            dependencies,
            _default(default),
            _constraints_range(1, 1, 10),
            _control_slider_integer(),
        ],
    )


def _info_toggle(setting_id, label):
    """A read-only info toggle (label only, <enable>false</enable>)."""
    return Node(
        "setting",
        [("id", setting_id), ("type", "boolean"), ("label", label)],
        children=[
            _dependencies(_dep_visible("new_install", "false")),
            _level("0"),
            _enable("false"),
            _default("false"),
            _control_toggle(),
        ],
    )


# --------------------------------------------------------------------------- #
# Document assembly.                                                          #
# --------------------------------------------------------------------------- #

def _indent(depth):
    return INDENT_UNIT * depth


def _comment(depth, text):
    return "{0}<!-- {1} -->".format(_indent(depth), text)


def _emit_setting(out, node, comment=None, blank_before=False):
    if blank_before:
        out.append("")
    if comment is not None:
        out.append(_comment(4, comment))
    _render(node, 4, out)


def _emit_hdr_category(out, hdr):
    """Emit one HDR category: banner comment, group, 3 toggles, 63 sliders."""
    label, help_id = HDR_CATEGORY_LABELS[hdr]
    out.append('{0}<category id="{1}" label="{2}" help="{3}">'.format(
        _indent(2), hdr, label, help_id))
    out.append(_comment(3, HDR_GROUP_COMMENT.get(hdr, hdr)))
    out.append('{0}<group id="{1}" label="32077">'.format(
        _indent(3), HDR_GROUP_IDS[hdr]))

    _render(_enable_hdr_setting(hdr), 4, out)
    _render(_enable_fps_setting(hdr), 4, out)
    _render(_fps_spinner_setting(hdr), 4, out)

    for fps in (formats.FPS_ALL,) + formats.FPS_BUCKETS:
        section_comment = FPS_SECTION_COMMENT.get(fps, "{0} FPS".format(fps))
        for index, audio in enumerate(formats.AUDIO_FORMATS):
            out.append("")
            if index == 0:
                out.append(_comment(4, section_comment))
            out.append(_comment(4, "{0} (ms) Delay Setting".format(
                AUDIO_ROW_COMMENT.get(audio, audio))))
            _render(_offset_slider(hdr, fps, audio), 4, out)

    out.append("{0}</group>".format(_indent(3)))
    out.append("{0}</category>".format(_indent(2)))


def _emit_onboarding(out):
    out.append('{0}<category id="onboarding" label="32057" help="">'.format(_indent(2)))
    out.append('{0}<group id="1" label="32055" help="">'.format(_indent(3)))
    out.append(_comment(4, "Addon onboarding"))
    _render(_new_install_setting(), 4, out)
    _render(_action_button(
        "play_test_video", "32059", "32060", "play_test_video",
        _dependencies(_dep_visible("new_install", "true"))), 4, out)
    _render(_action_button(
        "bypass_test_video", "32082", "32083", "bypass_test_video",
        _dependencies(_dep_visible("new_install", "true"))), 4, out)
    out.append("{0}</group>".format(_indent(3)))
    out.append("{0}</category>".format(_indent(2)))


def _emit_seek_back(out):
    out.append('{0}<category id="seek_back_settings" label="32016" help="32017">'.format(
        _indent(2)))

    # Group 7 — notifications.
    out.append('{0}<group id="7" label="32081">'.format(_indent(3)))
    _emit_setting(out, _toggle_setting(
        "enable_notifications", "32079", "32080",
        _dependencies(_dep_visible("new_install", "false")), "true"),
        comment="Enable Notifications Toggle")
    _emit_setting(out, _seconds_slider(
        "notification_seconds", "enable_notifications", "32090", "32091",
        _dependencies(_dep_visible_group("and", [
            _condition("enable_notifications", "true"),
            _condition("new_install", "false"),
        ])), "5"),
        comment="Notification Duration (seconds) Slider", blank_before=True)
    out.append("{0}</group>".format(_indent(3)))

    # Group 8 — active monitoring.
    out.append('{0}<group id="8" label="32047">'.format(_indent(3)))
    _emit_setting(out, _toggle_setting(
        "enable_active_monitoring", "32045", "32046",
        _dependencies(_dep_visible("new_install", "false")), "true"),
        comment="Enable Active Monitoring Toggle")
    out.append("{0}</group>".format(_indent(3)))

    # Group 9 — seek-back behaviours.
    out.append('{0}<group id="9" label="32018">'.format(_indent(3)))
    _emit_setting(out, _toggle_setting(
        "enable_seek_back_adjust", "32019", "32020",
        _dependencies(_dep_visible("new_install", "false")), "true"),
        comment="Enable Seek Back on Adjust Behavior Toggle")
    _emit_setting(out, _seconds_slider(
        "seek_back_adjust_seconds", "enable_seek_back_adjust", "32021", "32022",
        _dependencies(_dep_visible_group("and", [
            _condition("enable_seek_back_adjust", "true"),
            _condition("new_install", "false"),
        ])), "4"),
        comment="Seek Back Adjust Amount (seconds) Slider", blank_before=True)
    _emit_setting(out, _toggle_setting(
        "enable_seek_back_change", "32048", "32049",
        _dependencies(_dep_visible_group("and", [
            _condition("enable_active_monitoring", "true"),
            _condition("new_install", "false"),
        ])), "false", level_first=True),
        comment="Enable Seek Back on Change Behavior Toggle", blank_before=True)
    _emit_setting(out, _seconds_slider(
        "seek_back_change_seconds", "enable_seek_back_change", "32021", "32050",
        _dependencies(_dep_visible_group("and", [
            _condition("enable_active_monitoring", "true"),
            _condition("enable_seek_back_change", "true"),
        ])), "4"),
        comment="Seek Back Change Amount (seconds) Slider", blank_before=True)
    _emit_setting(out, _toggle_setting(
        "enable_seek_back_resume", "32034", "32035",
        _dependencies(_dep_visible("new_install", "false")), "false",
        level_first=True),
        comment="Enable Seek Back on Start/resume Toggle", blank_before=True)
    _emit_setting(out, _seconds_slider(
        "seek_back_resume_seconds", "enable_seek_back_resume", "32036", "32037",
        _dependencies(_dep_visible("enable_seek_back_resume", "true")), "4"),
        comment="Seek Back on Start/resume Amount (seconds) Slider",
        blank_before=True)
    _emit_setting(out, _toggle_setting(
        "enable_seek_back_unpause", "32038", "32039",
        _dependencies(_dep_visible("new_install", "false")), "false",
        level_first=True),
        comment="Enable Seek Back on unpause Toggle", blank_before=True)
    _emit_setting(out, _seconds_slider(
        "seek_back_unpause_seconds", "enable_seek_back_unpause", "32040", "32041",
        _dependencies(_dep_visible("enable_seek_back_unpause", "true")), "4"),
        comment="Seek Back on unpause Amount (seconds) Slider", blank_before=True)
    out.append("{0}</group>".format(_indent(3)))

    out.append("{0}</category>".format(_indent(2)))


def _emit_platform_info(out):
    out.append('{0}<category id="platform_info" label="32053" help="32089">'.format(
        _indent(2)))
    out.append('{0}<group id="10" label="32051">'.format(_indent(3)))
    _render(_info_toggle("platform_hdr_full", "32052"), 4, out)
    _render(_info_toggle("advanced_hlg", "32054"), 4, out)
    _render(_action_button(
        "re-validate", "32063", "32064", "play_test_video",
        _dependencies(
            _dep_visible("new_install", "false"),
            _dep_visible_group("or", [
                _condition("platform_hdr_full", "false"),
                _condition("advanced_hlg", "false"),
            ]),
        )), 4, out)
    out.append("{0}</group>".format(_indent(3)))
    out.append("{0}</category>".format(_indent(2)))


def _emit_advanced(out):
    out.append('{0}<category id="advanced" label="32100" help="32101">'.format(
        _indent(2)))
    out.append('{0}<group id="12" label="32102">'.format(_indent(3)))
    _render(Node(
        "setting",
        [("id", "enable_debug_logging"), ("type", "boolean"),
         ("label", "32103"), ("help", "32104")],
        children=[_level("0"), _default("false"), _control_toggle()]), 4, out)
    out.append("{0}</group>".format(_indent(3)))
    out.append("{0}</category>".format(_indent(2)))


def build_settings_text():
    """Return the full settings.xml text (LF-terminated)."""
    out = [XML_DECLARATION, '<settings version="1">',
           '{0}<section id="script.audiooffsetmanager">'.format(_indent(1))]

    _emit_onboarding(out)

    for hdr in formats.HDR_TYPES:
        if hdr in CATEGORY_COMMENT:
            out.append(_comment(2, CATEGORY_COMMENT[hdr]))
        else:
            out.append("")
        _emit_hdr_category(out, hdr)

    out.append("")
    out.append(_comment(2, CATEGORY_COMMENT["seek_back_settings"]))
    _emit_seek_back(out)

    out.append("")
    out.append(_comment(2, CATEGORY_COMMENT["platform_info"]))
    _emit_platform_info(out)

    out.append("")
    out.append(_comment(2, CATEGORY_COMMENT["advanced"]))
    _emit_advanced(out)

    out.append("")
    out.append("{0}</section>".format(_indent(1)))
    out.append("</settings>")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# CLI.                                                                        #
# --------------------------------------------------------------------------- #

def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _check(path, text):
    """Return (ok, message). Compares line-by-line, ignoring line-ending style."""
    if not os.path.exists(path):
        return False, "{0} does not exist".format(path)
    with open(path, "r", encoding="utf-8") as handle:
        on_disk = handle.read()
    expected_lines = text.splitlines()
    actual_lines = on_disk.splitlines()
    if expected_lines == actual_lines:
        return True, "{0} is up to date ({1} lines)".format(path, len(actual_lines))
    for number, (want, got) in enumerate(zip(expected_lines, actual_lines), 1):
        if want != got:
            return False, (
                "mismatch at line {0}:\n  generated: {1!r}\n  on disk:   {2!r}"
                .format(number, want, got))
    return False, "line count differs: generated {0}, on disk {1}".format(
        len(expected_lines), len(actual_lines))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate resources/settings.xml.")
    parser.add_argument("--check", action="store_true",
                        help="verify the on-disk file matches (exit 1 on drift)")
    parser.add_argument("-o", "--output", default=SETTINGS_PATH,
                        help="output path (default: resources/settings.xml)")
    args = parser.parse_args(argv)

    text = build_settings_text()
    if args.check:
        ok, message = _check(args.output, text)
        print(message)
        return 0 if ok else 1
    _write(args.output, text)
    print("wrote {0} ({1} lines)".format(args.output, text.count("\n")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
