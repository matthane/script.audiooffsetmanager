"""Script-side onboarding: the test-video flow, the bypass, and settings.

The composition glue for the ``RunScript`` entry point (``script.py``),
replacing the legacy ``script_handler.py`` + ``test_video.py``. Like
``runtime.py`` it sits at the ``aom`` package root, outside the layered
subpackages, and wires the Kodi adapters for its own process: the service
and the script run as SEPARATE processes whose only shared state is the live
on-disk settings store (settings doctrine — no manual reload exists or is
needed).

Write-ordering doctrine (unchanged, and load-bearing): the bypass button in
settings.xml uses ``<close>true</close>``, so the settings dialog is already
CLOSED when ``bypass_test_video`` writes ``new_install`` — writing while the
dialog is open would let its save-on-close overwrite us. The short sleep
afterwards lets the write settle before the dialog reopens and re-reads it.

User-facing strings resolve through ``getLocalizedString`` (the legacy
modules used ``$ADDON[...]`` label macros — a Phase 7 work item).
"""

import sys

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from resources.lib.aom.kodi.log import KodiLogger
from resources.lib.aom.kodi.settings import Settings

ADDON_ID = 'script.audiooffsetmanager'

STRING_ERROR = 32094
STRING_TEST_VIDEO_NOT_FOUND = 32095
STRING_PLEASE_WAIT = 32096
STRING_TEST_VIDEO_COMPLETED = 32097
STRING_BYPASSED = 32098
STRING_BYPASS_FAILED = 32099

TEST_VIDEO_RELATIVE_PATH = '/resources/media/test-video.mp4'


def handle_script_call():
    """Route the RunScript argument (the script process's entry point)."""
    if len(sys.argv) > 1 and sys.argv[1] == 'play_test_video':
        _Onboarding().play_test_video()
    elif len(sys.argv) > 1 and sys.argv[1] == 'bypass_test_video':
        _Onboarding().bypass_test_video()
    else:
        # No (or unknown) argument: just open the addon settings.
        xbmcaddon.Addon(ADDON_ID).openSettings()


class _Onboarding:
    """One script invocation's worth of wiring (constructed per call)."""

    def __init__(self):
        self._addon = xbmcaddon.Addon(ADDON_ID)
        self._name = self._addon.getAddonInfo('name')
        self._icon = self._addon.getAddonInfo('icon')
        self._log = KodiLogger()
        self._settings = Settings(log=self._log)
        self._log.debug_escalation = self._settings.debug_logging_enabled()
        addon_path = xbmcvfs.translatePath(self._addon.getAddonInfo('path'))
        self._test_video_path = xbmcvfs.translatePath(
            addon_path + TEST_VIDEO_RELATIVE_PATH)

    def play_test_video(self):
        """Play the test video for 5 seconds and return to addon settings.

        The blocking sleep is fine HERE: this is the short-lived script
        process, not the service's dispatcher thread.
        """
        if not xbmcvfs.exists(self._test_video_path):
            self._notify(self._localized(STRING_TEST_VIDEO_NOT_FOUND),
                         duration_ms=5000,
                         title=self._localized(STRING_ERROR),
                         icon=xbmcgui.NOTIFICATION_ERROR)
            return

        xbmc.Player().play(self._test_video_path)
        self._notify(f"{self._localized(STRING_PLEASE_WAIT)}...",
                     duration_ms=10000)

        xbmc.sleep(5000)
        xbmc.Player().stop()

        self._notify(self._localized(STRING_TEST_VIDEO_COMPLETED),
                     duration_ms=10000)
        xbmc.executebuiltin(f'Addon.OpenSettings({ADDON_ID})')

    def bypass_test_video(self):
        """Clear new_install without playing the test video.

        Runs from the bypass action button, which uses ``<close>true</close>``
        so the settings dialog is already closed by the time we write — the
        ordering that makes the write stick (see the module docstring).
        """
        if not self._settings.store_boolean_if_changed('new_install', False):
            self._log("AOM_Onboarding: Failed to bypass test video "
                      "requirement", xbmc.LOGWARNING)
            self._notify(self._localized(STRING_BYPASS_FAILED),
                         duration_ms=3000,
                         title=self._localized(STRING_ERROR),
                         icon=xbmcgui.NOTIFICATION_ERROR)
            return

        self._log("AOM_Onboarding: Successfully bypassed test video "
                  "requirement", xbmc.LOGINFO)
        self._notify(self._localized(STRING_BYPASSED), duration_ms=3000)

        # Let the write settle to disk before the dialog reopens and reads it.
        xbmc.sleep(500)
        xbmc.executebuiltin(f'Addon.OpenSettings({ADDON_ID})')

    # -- internals ----------------------------------------------------------------

    def _localized(self, string_id):
        try:
            return self._addon.getLocalizedString(string_id)
        except Exception as e:
            self._log(f"AOM_Onboarding: Error reading localized string "
                      f"{string_id}: {str(e)}", xbmc.LOGERROR)
            return ''

    def _notify(self, message, duration_ms, title=None, icon=None):
        try:
            xbmcgui.Dialog().notification(
                title if title is not None else self._name,
                message,
                icon if icon is not None else self._icon,
                duration_ms)
        except Exception as e:
            self._log(f"AOM_Onboarding: Error raising notification: "
                      f"{str(e)}", xbmc.LOGERROR)
