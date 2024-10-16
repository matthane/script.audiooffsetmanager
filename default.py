import xbmc
from resources.lib.stream_info import StreamInfo
from resources.lib.event_manager import EventManager
from resources.lib.settings_manager import SettingsManager
from resources.lib.offset_manager import OffsetManager
from resources.lib.seek_backs import SeekBacks

# Initialize the event manager
event_manager = EventManager()

# Initialize the settings manager
settings_manager = SettingsManager()

# Initialize stream info module and subscribe to playback events
stream_info = StreamInfo(event_manager)
stream_info.start()

# Initialize offset manager and subscribe to playback events
offset_manager = OffsetManager(event_manager, stream_info)
offset_manager.start()

# Initialize seek backs and subscribe to playback events
seek_backs = SeekBacks(event_manager)
seek_backs.start()

# Keep the script running
xbmc.Monitor().waitForAbort()

# On script exit, stop the stream info, offset manager, and seek backs modules
stream_info.stop()
offset_manager.stop()
seek_backs.stop()