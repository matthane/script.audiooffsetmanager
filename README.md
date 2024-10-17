<img src="https://raw.githubusercontent.com/matthane/script.audiooffsetmanager/refs/heads/main/resources/icon.png" width="256" height="256" alt="Audio Offset Manager">

# Audio Offset Manager

Audio Offset Manager is a Kodi add-on designed to provide dynamic audio delay adjustments tailored to the content you're watching. This add-on intelligently adjusts the audio offset based on the detected HDR type and audio format according to user-configured settings. Key features include:

- Dynamic Audio Offset Application: Sets audio delay based on the HDR type and audio format of the current video, applying user-defined offsets to ensure consistent audio-visual sync without needing repeated manual adjustments.
- Active Monitoring Mode: Actively monitors when users manually adjust audio delay via Kodi's OSD settings, stores those adjustments, and applies them for future playback of similar content. This feature is particularly useful for initial AV calibration, allowing users to fine-tune audio sync and have those settings automatically applied to similar content in the future.
- Custom Seek-Backs: Offers user-configurable "seek-back" functionality to rewind a few seconds in specific playback situations, such as when playback starts, resumes, or the audio offset is adjusted. This helps synchronize the audio and video streams more accurately, ensuring a smoother viewing experience.

This add-on is designed to enhance your viewing experience by automating the process of audio delay adjustment, ensuring that once you've configured the appropriate offsets, they are dynamically applied for each type of content.

Whether you're watching a movie in Dolby Vision or an HDR10 video, Audio Offset Manager has got you covered, dynamically adapting to make sure everything stays in sync.

<img src="https://raw.githubusercontent.com/matthane/script.audiooffsetmanager/refs/heads/main/resources/screenshot-1.jpg" width="100%" alt="Audio Offset Manager screenshot 1">

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

<img src="https://raw.githubusercontent.com/matthane/script.audiooffsetmanager/refs/heads/main/resources/screenshot-3.jpg" width="100%" alt="Audio Offset Manager screenshot 2">

**AV Calibration help**

- Active offset monitoring mode to continually check and save any adjustments made to audio offset during playback

**Automatic seek back to keep audio and video streams synchronized**


- Controls to enable automatic seek back in the following conditions:

  - When audio stream changes during playback (e.g. user changes audio stream from TrueHD to Dolby Digital during playback)
  - When playback is first initiated (e.g. title is opened for the first time or resumed from a previous session)
  - When player is unpaused (for more in-depth control, you can look at the [Unpause Jumpback](https://github.com/bossanova808/script.xbmc.unpausejumpback) plugin from [bossanova808](https://github.com/bossanova808))

<img src="https://raw.githubusercontent.com/matthane/script.audiooffsetmanager/refs/heads/main/resources/screenshot-2.jpg" width="100%" alt="Audio Offset Manager screenshot 3">

### Attributions

Icon designed by [Freepik](http://www.freepik.com/)