# Logitech Media Server TTS Notify Queue for Home Assistant

The LMS Notify TTS platform lets you use the TTS integration Service Say and a LMS media_player to alert you of important events. This integration provides a simple interface to use in your automations and alerts.

- restores the state, volume, sync group, playlist and media possition after playing the notify message
- queue messages for each player so new messages do not interrupt the current playing one
- option alert sound before the message
- option how many times to repeat the tts message
- option volume for the tts message

Default options can be set in the configuration file and/or overridden for each message

In order to use this integration, you must already have a TTS platform installed and configured, and a Logitech Media Server working with the TTS platform.

To enable this platform in your installation, consider the following example using google_translate and an example media_player.kitchen.

## Installation

Copy this folder to `<config_dir>/custom_components/lms_tts_notify/`

Or add a [custom repository](https://hacs.xyz/docs/faq/custom_repositories) in HACS: `https://github.com/floris-b/lms_tts_notify`

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
      device_group: group.all_persons
      alert_sound: Alert
      volume: 0.4
```

Please note that the `tts_service` parameter, must match the `service_name` defined in the TTS integration.

### CONFIGURATION VARIABLES & SERVICE OPTIONS
___

#### **name**: `string` | REQUIRED | CONFIG
The name of the notify service

#### **tts_service**: `string` | REQUIRED | CONFIG
The service_name of a TTS platform

#### **media_player**: `string` | REQUIRED | CONFIG & SERVICE QUEUE 
The entity_id of a LMS media_player (single or list for service queue)

#### **device_group**: `string` | REQUIRED | CONFIG | (optional) | SERVICE QUEUE & SERVICE NOTIFY
Specify which entity_id to track. Messages are not played when state != `home`
Can be any entities/groups when it has a `home` state 

#### **volume**: `float` (optional) | CONFIG & SERVICE QUEUE & SERVICE NOTIFY
Default volume to play the alert_sound and message

#### **pause**: `float` (optional, default=0.5) | CONFIG 
Seconds to pause before and after alert sound and after tts message

#### **alert_sound**: `string` (optional) | CONFIG & SERVICE QUEUE & SERVICE NOTIFY
Default name of the playlist in LMS to play before the message

#### **repeat**: `number` (optional) | CONFIG & SERVICE QUEUE & SERVICE NOTIFY
Default value to repeat the message

#### **force_play**: `boolean` | SERVICE QUEUE & SERVICE NOTIFY
Skip check `device_group` state is `home` 

### SERVICE QUEUE
---
A service `lms_tts_notify.queue` is also added (besides the notify service for each player) for easy use with the automations gui