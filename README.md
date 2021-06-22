# Logitech Media Server TTS Notify Queue

The LMS Notify TTS platform lets you use the TTS integration Service Say and a LMS media_player to alert you of important events. This integration provides a simple interface to use in your automations and alerts.

- restores the state, volume, sync group, playlist and media possition after playing the notify message
- queue messages for each player so new messages do not interrupt the current playing one
- option alert sound before the message
- option how many times to repeat the tts message
- option volume for the tts message

Default options can be set in the confiration file or overidden with each message

In order to use this integration, you must already have a TTS platform installed and configured, and a Logitech Media Server working with the TTS platform.

`group.all_persons` needs to be added containing persons or device_trackers, messages will only be played when someone is home  

To enable this platform in your installation, consider the following example using google_translate and an example media_player.kitchen.

## Installation

Copy this folder to `<config_dir>/custom_components/lms_tts_notify/`

Add the following entry in your `configuration.yaml`:

```yaml
tts:
    - platform: google_translate
      service_name: google_say

notify:
    - platform: lms_tts_notify
      name: kitchen
      tts_service: tts.google_say
      media_player: media_player.kitchen
      alert_sound: Alert
      volume: 0.4
```

Please note that the `tts_service` parameter, must match the `service_name` defined in the TTS integration.

## CONFIGURATION VARIABLES
___

### name: `string` REQUIRED
The name of the notify service

### tts_service: `string` REQUIRED
The service_name of a TTS platform

### media_player: `string` REQUIRED
The entity_id of a LMS media_player

### volume: `float` (optional)
Default volume to play the alert_sound and message

### alert_sound: `string` (optional)
Default name of the playlist in LMS to play before the message

### repeat: `number` (optional)
Default value to repeat the message

## SERVICE QUEUE
---
A service is also added (besides the notify service for each player) for easy use with the automations gui