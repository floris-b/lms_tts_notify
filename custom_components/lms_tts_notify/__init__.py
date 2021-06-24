"""The Logitech Squeezebox TTS notify."""
import logging
from typing import Optional

from homeassistant.const import EVENT_HOMEASSISTANT_START, EVENT_HOMEASSISTANT_STOP
from homeassistant.components.notify import ATTR_MESSAGE
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
CONF_FORCE_PLAY = "force_play"
CONF_DEVICE_GROUP = "device_group"
CONF_PAUSE = "pause"

ATTR_SYNC_GROUP = "sync_group"
ATTR_VOLUME = "volume_level"
ATTR_POSITION = "media_position"

GEN_ATTRS = [ATTR_VOLUME, ATTR_SYNC_GROUP, ATTR_POSITION]

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.comp_entity_ids,
        vol.Required(ATTR_MESSAGE): cv.string,
        vol.Optional(CONF_REPEAT): cv.positive_int,
        vol.Optional(CONF_ALERT_SOUND): cv.string,
        vol.Optional(CONF_VOLUME): cv.positive_float,
        vol.Optional(CONF_FORCE_PLAY): cv.boolean,
        vol.Optional(CONF_DEVICE_GROUP): cv.entity_id,
        vol.Optional(CONF_PAUSE): cv.positive_float,
    }
)


async def async_setup(hass, config):
    """Load configurations"""

    _LOGGER.debug("The %s component is ready!", DOMAIN)
    queue_listener = {}
    for myconfig in config["notify"]:
        if myconfig["platform"] == "lms_tts_notify":
            #create queue for each media_player
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
        """Forward queue service data to eventbus"""
        #_LOGGER.debug("call %s", call.data)
        if isinstance(call.data["entity_id"], list):
            for media_player in call.data["entity_id"]:
                data = dict(call.data)
                data["entity_id"] = media_player
                hass.bus.async_fire(DOMAIN + "_event", data)
        else:
            hass.bus.async_fire(DOMAIN + "_event", call.data)

    async def handle_event(event):
        """listen to event bus and put message in media_player queue from notify and queue service"""
        _LOGGER.debug("Received on event bus: %s", event.data)
        if event.data["entity_id"] in queue_listener:
            queue_listener[event.data["entity_id"]].queue.put(event.data)
        else:
            _LOGGER.warn("LMS player not configured in %s : %s", DOMAIN, event.data["entity_id"])

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
        self._pause = config.get(CONF_PAUSE)
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

            self._message = event[ATTR_MESSAGE].replace("<br>", "")
            self._repeat = event.get(CONF_REPEAT, self._config.get(CONF_REPEAT))
            self._volume = event.get(CONF_VOLUME, self._config.get(CONF_VOLUME))
            self._pause = event.get(CONF_PAUSE, self._config.get(CONF_PAUSE))
            self._device_group = event.get(CONF_DEVICE_GROUP, self._config.get(CONF_DEVICE_GROUP))
            self._alert_sound = event.get(
                CONF_ALERT_SOUND, self._config.get(CONF_ALERT_SOUND)
            )
            self.force_play = event.get(CONF_FORCE_PLAY, False)

            home = self._hass.states.get(self._device_group).state
            if home == "home" or self.force_play:
                if not self.skip_save:
                    #Only save state the first message and skip when there are message in queue
                    self.save_state()
                    _LOGGER.debug("Save playlist: %s", self._media_player )
                    service_data = {
                        "entity_id": self._media_player,
                        "command": "playlist",
                        "parameters": ["save", "Save-" + self._media_player],
                    }
                    self._hass.services.call("squeezebox", "call_method", service_data)
                self.audio_alert()
                if self._queue.empty():
                    _LOGGER.debug("Restore playlist: %s", self._media_player)
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
            else:
                _LOGGER.debug("Not playing: %s state != \'home\' and not force_play", self._device_group) 

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
            if cur_state.state in ["on", "playing", "idle", "paused"]:
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
                            else:
                                del attributes[attr]
            _LOGGER.debug("Save state: %s", self._media_player)
            self.state = {"state": cur_state.state, "attributes": attributes}
            

    def restore_state(self):
        """Restore state of media player"""
        if self.state["state"] == None:
            _LOGGER.debug("No saved state for {}.".format(self._media_player))
        else:
            _LOGGER.debug("Restore state: %s : %s", self._media_player, self.state)
            turn_on = self.state["state"]
            service_data = {"entity_id": self._media_player}
            if turn_on in ['idle', 'playing', 'paused']:
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

            self._hass.services.call("homeassistant", "update_entity", service_data)
            if turn_on in ["off", "paused", "idle" ]:
                self._hass.services.call( "media_player", "turn_off", service_data )

    def wait_on_idle(self):
        """Wait until player is done playing"""
        time.sleep(self._pause)
        while True:
            # Force update status of the media_player
            service_data = {"entity_id": self._media_player}
            self._hass.services.call("homeassistant", "update_entity", service_data)
            state = self._hass.states.get(self._media_player).state
            if state in ["idle", "paused", "off"]:
                break
            time.sleep(0.2)

    def audio_alert(self):
        """Play tts message"""
        self._hass.services.call(
            "media_player", "media_pause", {"entity_id": self._media_player}
        )
        time.sleep(0.5)
        _LOGGER.debug("Playing message \"%s\" : %s", self._message, self._media_player)
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
