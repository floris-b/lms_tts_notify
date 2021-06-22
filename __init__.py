"""The Logitech Squeezebox TTS notify."""
import logging
from typing import Optional

from homeassistant.const import EVENT_HOMEASSISTANT_START, EVENT_HOMEASSISTANT_STOP
from homeassistant.const import CONF_NAME, ATTR_ENTITY_ID
from homeassistant.core import split_entity_id
import homeassistant.helpers.config_validation as cv

from threading import Thread
from queue import Queue
import time
import voluptuous as vol

DOMAIN = "lms_tts_notify"
_LOGGER = logging.getLogger(__name__)

CONF_MEDIA_PLAYER = "media_player"
CONF_TTS_SERVICE = "tts_service"
CONF_REPEAT = "repeat"
CONF_VOLUME = "volume"
CONF_ALERT_SOUND = "alert_sound"

ATTR_SYNC_GROUP = "sync_group"
ATTR_VOLUME = "volume_level"
ATTR_POSITION = "media_position"

GEN_ATTRS = [ATTR_VOLUME, ATTR_SYNC_GROUP, ATTR_POSITION]

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.comp_entity_ids,
        vol.Required("message"): cv.string,
        vol.Optional(CONF_REPEAT): cv.positive_int,
        vol.Optional(CONF_ALERT_SOUND): cv.string,
        vol.Optional(CONF_VOLUME): cv.small_float,
    }
)


async def async_setup(hass, config):
    """Load configurations."""

    _LOGGER.debug("The %s component is ready!", DOMAIN)
    queue_listener = {}
    for myconfig in config["notify"]:
        if myconfig["platform"] == "lms_tts_notify":
            _LOGGER.debug("config %s", myconfig)
            media_player = myconfig["media_player"]

            queue_listener[media_player] = QueueListener(hass, myconfig)

            hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_START, queue_listener[media_player].start_handler
            )
            hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STOP, queue_listener[media_player].stop_handler
            )

    async def async_service_send_message(call):
        """Call TTS service to speak the notification"""
        _LOGGER.debug("call %s", call.data)
        if isinstance(call.data["entity_id"], list):
            for media_player in call.data["entity_id"]:
                data = dict(call.data)
                data["entity_id"] = media_player
                hass.bus.async_fire(DOMAIN + "_event", data)
        else:
            hass.bus.async_fire(DOMAIN + "_event", call.data)

    async def handle_event(event):
        _LOGGER.debug("event %s", event)
        if event.data["entity_id"] in queue_listener:
            queue_listener[event.data["entity_id"]].queue.put(event.data)

    hass.bus.async_listen(DOMAIN + "_event", handle_event)

    hass.services.async_register(
        DOMAIN, "queue", async_service_send_message, SERVICE_SCHEMA
    )

    return True


class QueueListener(Thread):
    """Play tts notify events from queue to mediaplayer"""

    def __init__(self, hass, config):
        """Create queue."""
        super().__init__()
        self._hass = hass
        self._queue = Queue()
        self._repeat = config.get(CONF_REPEAT)
        self._alert_sound = config.get(CONF_ALERT_SOUND)
        self._volume = config.get(CONF_VOLUME)
        self._media_player = config[CONF_MEDIA_PLAYER]
        self._config = config
        _, self._tts_service = split_entity_id(config[CONF_TTS_SERVICE])

    def run(self):
        """Listen to queue events, and play them to mediaplayer"""
        _LOGGER.debug("Running QueueListener")
        self.skip_save = False
        self.force_play = False
        while True:
            event = self._queue.get()
            if event is None:
                break

            self._message = event["message"].replace("<br>", "")
            self._repeat = event.get("repeat", self._config.get(CONF_REPEAT))
            self._volume = event.get("volume", self._config.get(CONF_VOLUME))
            self._alert_sound = event.get(
                "alert_sound", self._config.get(CONF_ALERT_SOUND)
            )
            self.force_play = event.get("force_play", False)

            home = self._hass.states.get("group.all_persons").state
            if home == "home" or self.force_play:
                if not self.skip_save:
                    _LOGGER.debug("Save playlist and state")
                    self.save_state()
                    service_data = {
                        "entity_id": self._media_player,
                        "command": "playlist",
                        "parameters": ["save", "Save-" + self._media_player],
                    }
                    self._hass.services.call("squeezebox", "call_method", service_data)
                _LOGGER.debug("playing event %s", event)
                self.audio_alert()
                if self._queue.empty():
                    _LOGGER.debug("Restore playlist and state")
                    service_data = {
                        "entity_id": self._media_player,
                        "command": "playlist",
                        "parameters": ["resume", "Save-" + self._media_player],
                    }
                    self._hass.services.call("squeezebox", "call_method", service_data)
                    self.restore_state()
                    self.skip_save = False
                else:
                    self.skip_save = True

    @property
    def queue(self):
        """Return wrapped queue."""
        return self._queue

    def stop(self):
        """Stop run by putting None into queue and join the thread."""
        _LOGGER.debug("Stopping QueueListener")
        self._queue.put(None)
        self.join()
        _LOGGER.debug("Stopped QueueListener")

    def start_handler(self, _):
        """Start handler helper method."""
        self.start()

    def stop_handler(self, _):
        """Stop handler helper method."""
        self.stop()

    def save_state(self):
        """Save state of media_player"""
        service_data = {"entity_id": self._media_player}
        self._hass.services.call("homeassistant", "update_entity", service_data)
        cur_state = self._hass.states.get(self._media_player)
        if cur_state is None:
            _LOGGER.debug("Could not get state of {}.".format(self._media_player))
        else:
            attributes = {}
            if cur_state.state == "on" or cur_state.state == "playing":
                for attr in GEN_ATTRS:
                    if attr in cur_state.attributes:
                        attributes[attr] = cur_state.attributes[attr]
                        if attr == ATTR_SYNC_GROUP:
                            if len(cur_state.attributes[attr]):
                                _LOGGER.debug("UnSync %s", cur_state.attributes[attr])
                                self._hass.services.call(
                                    "squeezebox",
                                    "unsync",
                                    {"entity_id": self._media_player},
                                )
            self.state = {"state": cur_state.state, "attributes": attributes}

    def restore_state(self):
        """Restore state of media player"""
        if self.state["state"] == None:
            _LOGGER.debug("No saved state for {}.".format(self._media_player))
        else:
            turn_on = self.state["state"]
            service_data = {"entity_id": self._media_player}
            if turn_on:
                if "volume_level" in self.state["attributes"]:
                    volume = self.state["attributes"]["volume_level"]
                    self._hass.services.call(
                        "media_player",
                        "volume_set",
                        {"entity_id": self._media_player, "volume_level": volume},
                    )
                if ATTR_SYNC_GROUP in self.state["attributes"]:
                    sync_list = self.state["attributes"][ATTR_SYNC_GROUP]
                    if len(sync_list):
                        _LOGGER.debug(
                            "Sync %s", self.state["attributes"][ATTR_SYNC_GROUP]
                        )
                        if self._media_player in sync_list:
                            sync_list.remove(self._media_player)
                        for player in sync_list:
                            self._hass.services.call(
                                "squeezebox",
                                "sync",
                                {
                                    "entity_id": self._media_player,
                                    "other_player": player,
                                },
                            )
                if "media_position" in self.state["attributes"]:
                    media_position = self.state["attributes"]["media_position"]
                    self._hass.services.call(
                        "media_player",
                        "media_seek",
                        {
                            "entity_id": self._media_player,
                            "seek_position": media_position,
                        },
                    )

            self._hass.services.call(
                "media_player",
                "turn_on"
                if (turn_on == "playing") or (turn_on == "on")
                else "turn_off",
                service_data,
            )

    def wait_on_idle(self):
        # Wait until player is done playing
        time.sleep(1)
        while True:
            # Force update status of the media player
            service_data = {"entity_id": self._media_player}
            self._hass.services.call("homeassistant", "update_entity", service_data)
            state = self._hass.states.get(self._media_player).state
            if state in ["idle", "paused", "off"]:
                break
            time.sleep(0.5)

    def audio_alert(self):
        # Plan notify message
        self._hass.services.call(
            "media_player", "media_pause", {"entity_id": self._media_player}
        )
        time.sleep(0.5)

        # Set alert volume
        if self._volume:
            service_data = {
                "entity_id": self._media_player,
                "volume_level": self._volume,
            }
            self._hass.services.call("media_player", "volume_set", service_data)
        for step in range(self._repeat):
            # Play alert sound
            if self._alert_sound:
                # service_data = { 'entity_id': self._media_player, 'media_content_id': self._alert_sound, 'media_content_type': 'music'  }
                # self._hass.services.call( 'media_player', 'play_media' , service_data)
                service_data = {
                    "entity_id": self._media_player,
                    "command": "playlist",
                    "parameters": ["resume", self._alert_sound],
                }
                self._hass.services.call("squeezebox", "call_method", service_data)
                self.wait_on_idle()
            # Play message
            service_data = {"entity_id": self._media_player, "message": self._message}
            self._hass.services.call("tts", self._tts_service, service_data)
            self.wait_on_idle()
