<img src="https://raw.githubusercontent.com/matthane/script.audiooffsetmanager/refs/heads/main/resources/icon.png" width="256" height="256" alt="Audio Offset Manager">

# Audio Offset Manager

Audio Offset Manager is a utility addon for Kodi (v20.0+) designed to enhance your viewing experience by providing dynamic audio delay adjustments tailored to the content you're watching. This addon intelligently adjusts the audio offset based on the detected HDR type and audio format according to user-configured settings. 

## Features

- **Dynamic Audio Offset Application**: Automatically sets audio delay based on the HDR type and audio format of the current video, applying user-defined offsets to ensure consistent audio-visual sync without needing repeated manual adjustments.

- **Active Monitoring Mode**: Monitors when users manually adjust audio delay via Kodi's OSD settings, stores those adjustments, and applies them for future playback of similar content. This feature is particularly useful for initial AV calibration, allowing users to fine-tune audio sync and have those settings automatically applied to similar content in the future.

- **Custom Seek-Backs**: Offers user-configurable "seek-back" functionality to rewind a few seconds in specific playback situations, such as:
  - When playback starts or resumes
  - When the audio stream changes during playback
  - When the audio offset is adjusted
  - When the player is unpaused
  This helps synchronize the audio and video streams more accurately, ensuring a smoother viewing experience.

- **Modular Design**: The addon is built with a modular architecture, allowing for easy maintenance and future enhancements.

This addon streamlines your viewing experience by automating the process of audio delay adjustment, ensuring that once you've configured the appropriate offsets, they are dynamically applied for each type of content.

<img src="https://raw.githubusercontent.com/matthane/script.audiooffsetmanager/refs/heads/main/resources/screenshot-1.jpg" width="100%" alt="Audio Offset Manager screenshot 1">

## Supported Formats

### Audio Formats
- Dolby Atmos / TrueHD
- Dolby Digital Plus (E-AC-3)
- Dolby Digital (AC-3)
- DTS:X / DTS-HD MA (8+ channels)
- DTS-HD MA (6 channels)
- DTS (DCA)

### Video Formats
- Dolby Vision
- HDR10
- HDR10+
- HLG
- SDR

<img src="https://raw.githubusercontent.com/matthane/script.audiooffsetmanager/refs/heads/main/resources/screenshot-3.jpg" width="100%" alt="Audio Offset Manager screenshot 2">

<img src="https://raw.githubusercontent.com/matthane/script.audiooffsetmanager/refs/heads/main/resources/screenshot-2.jpg" width="100%" alt="Audio Offset Manager screenshot 3">

## Installation and Usage

1. Download the addon from the Kodi repository or install it manually.
2. Enable the addon in Kodi's addon settings.
3. Configure your desired audio offsets for different HDR types and audio formats in the addon settings.
4. If you want to perform initial AV calibration, enable the active monitoring mode in the addon settings. This will allow the addon to learn and store your manual audio offset adjustments for future use.
5. The addon will run as a background service, automatically applying your configured offsets during playback.

## Compatibility

This addon is designed for Kodi v20.0 and above. It may not function correctly with earlier versions of Kodi.

## Contributing and Reporting Issues

Contributions to improve Audio Offset Manager are welcome. If you encounter any issues or have suggestions for improvements, please open an issue on our GitHub repository.

### Attributions

Icon designed by [Freepik](http://www.freepik.com/)
