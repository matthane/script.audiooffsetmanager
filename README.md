<img src="https://raw.githubusercontent.com/matthane/script.audiooffsetmanager/refs/heads/main/resources/icon.png" width="256" height="256" alt="Audio Offset Manager">

# Audio Offset Manager

Audio Offset Manager is a service add-on for Kodi (v20.0+) that dynamically adjusts the audio offset to user configured values based on the currently playing video and audio stream format. By default, Kodi manages audio offsets on an individual video or all video basis. This add-on increases the scope and flexibility of offset management to a per audio/video format basis.

Designed to alleviate frustrations related to decoding times of various audio formats/codecs and video playback synchronization across different home theater setups. This add-on also features an active offset monitoring mode which monitors the audio offset values during playback and saves any changes made by the user back into the configuration setting for that audio/video format—very useful for initial AV sync calibration across different media types.

<img src="https://raw.githubusercontent.com/matthane/script.audiooffsetmanager/refs/heads/main/resources/screenshot-1.jpg" width="49%" float="left" alt="Audio Offset Manager screenshot 1">
<img src="https://raw.githubusercontent.com/matthane/script.audiooffsetmanager/refs/heads/main/resources/screenshot-2.jpg" width="49%" float="right" alt="Audio Offset Manager screenshot 2">

## Features

**Customizable audio latency offsets for individual audio formats based on detected video format**

- Currently supported audio formats:
  - Dolby Atmos / TrueHD
  - Dolby Digital Plus (E-AC-3)
  - Dolby Digital (AC-3)
  - DTS:X / DTS-HD MA (8+ channels)
  - DTS-HD MA (6 channels)
  - DTS (DCA)

- Currently detected video formats:
  - Dolby Vision
  - HDR10
  - HDR10+
  - HLG
  - SDR

**AV Calibration help**

- Active offset monitoring mode to continually check and save any adjustments made to audio offset during playback

**Automatic seek back to keep audio and video streams synchronized**

- Controls to enable automatic seek back in the following conditions:

  - When audio stream changes during playback (e.g. user changes audio stream from TrueHD to Dolby Digital during playback)
  - When playback is first initiated (e.g. title is opened for the first time or resumed from a previous session)
  - When player is unpaused (for more in-depth control, you can look at the [Unpause Jumpback](https://github.com/bossanova808/script.xbmc.unpausejumpback) plugin from [bossanova808](https://github.com/bossanova808))

### Attributions

Icon designed by [Freepik](http://www.freepik.com/)