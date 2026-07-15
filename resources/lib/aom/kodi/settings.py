"""Kodi settings adapter: typed reads/writes plus intent-level accessors.

Replaces the legacy ``SettingsManager`` singleton + ``SettingsFacade`` pair
(Phase 7 deletes them) with a plain, injected class. There is no singleton
here: the runtime constructs exactly one ``Settings`` and injects it into every
component that needs settings (required constructor deps are the house rule,
same as ``KodiGateway``).

Why one instance is enough — and not a correctness barrier: Kodi's
``xbmcaddon.Addon(ADDON_ID).getSettings()`` returns a LIVE proxy onto the
in-process settings store, not a frozen snapshot (see the repo CLAUDE.md
settings doctrine). Every read sees current values and every write is visible
everywhere at once, so the store cannot drift out of sync with itself. Holding
one proxy per process is a tidiness convenience, not the thing that makes
reads/writes consistent.

Faithful port of the legacy semantics, with two deliberate upgrades noted as
Phase 7 work: the bare ``except:`` clauses become ``except Exception`` here, and
the ``AOM_SettingsManager`` log prefix becomes ``AOM_Settings``. The
read-before-write skip in the ``store_*_if_changed`` helpers is load-bearing and
preserved verbatim: it keeps the settings-dialog clobber surface minimal (no
write means nothing for a dialog save-on-close to fight over) per the doctrine.

This layer may import ``xbmc*``/``xbmcaddon`` and ``resources.lib.aom.*`` only;
importing any legacy ``resources.lib.<module>`` fails
``tests/contract/test_architecture.py``.
"""

import xbmc
import xbmcaddon

ADDON_ID = 'script.audiooffsetmanager'


class Settings:
    """Typed access to the addon settings store over Kodi's live proxy."""

    def __init__(self, *, log):
        """``log`` is a REQUIRED ``(message, level)`` sink (same convention as
        ``KodiGateway``)."""
        self._log = log
        self._settings = xbmcaddon.Addon(ADDON_ID).getSettings()

    # --- typed primitives ---------------------------------------------------

    def get_bool(self, setting_id, default=False):
        """Read a boolean setting; on ANY error, log and return ``default``."""
        try:
            return self._settings.getBool(setting_id)
        except Exception:
            self._log(
                f"AOM_Settings: Error getting boolean setting '{setting_id}'. "
                f"Using default: {default}", xbmc.LOGWARNING)
            return default

    def get_int(self, setting_id, default=0):
        """Read an integer setting; on ANY error, log and return ``default``."""
        try:
            return self._settings.getInt(setting_id)
        except Exception:
            self._log(
                f"AOM_Settings: Error getting integer setting '{setting_id}'. "
                f"Using default: {default}", xbmc.LOGWARNING)
            return default

    def store_boolean_if_changed(self, setting_id, value):
        """Write a boolean only if it differs from the stored value.

        Returns True when the store succeeds or is skipped (already equal);
        False when the underlying write raises. A failed pre-read falls through
        to the write attempt, like legacy.
        """
        try:
            if self.get_bool(setting_id) == value:
                return True
        except Exception:
            pass
        return self._store(self._settings.setBool, setting_id, value, "boolean")

    def store_integer_if_changed(self, setting_id, value):
        """Write an integer only if it differs from the stored value.

        Returns True when the store succeeds or is skipped (already equal);
        False when the underlying write raises. A failed pre-read falls through
        to the write attempt, like legacy.
        """
        try:
            if self.get_int(setting_id) == value:
                return True
        except Exception:
            pass
        return self._store(self._settings.setInt, setting_id, value, "integer")

    def _store(self, operation, setting_id, value, value_type):
        """Log the store at LOGDEBUG and write; on error log LOGWARNING."""
        try:
            self._log(
                f"AOM_Settings: Storing {value_type} setting {setting_id}: "
                f"{value}", xbmc.LOGDEBUG)
            operation(setting_id, value)
            return True
        except Exception:
            self._log(
                f"AOM_Settings: Error storing {value_type} setting "
                f"'{setting_id}'.", xbmc.LOGWARNING)
            return False

    # --- intent-level reads (SettingsFacade parity) -------------------------

    def is_hdr_enabled(self, hdr_type):
        return self.get_bool(f"enable_{hdr_type}")

    def fps_override_enabled(self, hdr_type):
        return self.get_bool(f"enable_fps_{hdr_type}")

    def active_monitoring_enabled(self):
        return self.get_bool('enable_active_monitoring')

    def seek_back_config(self, reason):
        """Return ``(enabled, seconds)`` for a seek-back reason; seconds >= 0."""
        return (self.get_bool(f"enable_seek_back_{reason}"),
                max(self.get_int(f"seek_back_{reason}_seconds"), 0))

    def notifications_enabled(self):
        return self.get_bool('enable_notifications')

    def notification_duration_ms(self):
        return self.get_int('notification_seconds') * 1000

    def debug_logging_enabled(self):
        return self.get_bool('enable_debug_logging')

    def is_new_install(self):
        return self.get_bool('new_install')


class OffsetTable:
    """Per-profile offset storage. tools/generate_settings.py guarantees every
    <hdr>_<fps>_<audio> setting id exists, so get() always answers an int (the
    legacy 'delay_ms is None' branch is not a state). The setting key is
    derived from the profile AT CALL TIME (settings doctrine: never a captured
    key)."""

    def __init__(self, settings):
        self._settings = settings

    def get(self, profile):
        return self._settings.get_int(profile.setting_id())

    def store(self, profile, ms):
        return self._settings.store_integer_if_changed(profile.setting_id(), ms)
