"""Support notifications through TTS service."""
import logging
from typing import Optional

import voluptuous as vol

from homeassistant.components.notify import PLATFORM_SCHEMA, BaseNotificationService
from homeassistant.const import CONF_NAME
from homeassistant.core import split_entity_id
import homeassistant.helpers.config_validation as cv


from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.components.notify import ATTR_MESSAGE

from . import (
    DOMAIN,
    CONF_MEDIA_PLAYER,
    CONF_TTS_SERVICE,
    CONF_REPEAT,
    CONF_VOLUME,
    CONF_ALERT_SOUND,
    CONF_DEVICE_GROUP,
    CONF_PAUSE,
)

ATTR_LANGUAGE = "language"

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_TTS_SERVICE): cv.entity_id,
        vol.Required(CONF_MEDIA_PLAYER): cv.entity_id,
        vol.Required(CONF_DEVICE_GROUP): cv.entity_id,
        vol.Optional(ATTR_ENTITY_ID): cv.entity_id,
        vol.Optional(ATTR_LANGUAGE): cv.string,
        vol.Optional(CONF_REPEAT, default=1): cv.positive_int,
        vol.Optional(CONF_ALERT_SOUND, default=""): cv.string,
        vol.Optional(CONF_VOLUME, default=""): cv.positive_float,
        vol.Optional(CONF_PAUSE, default=0.5): cv.positive_float,
    }
)


async def async_get_service(hass, config, discovery_info=None):
    """Return the notify service."""
    _LOGGER.debug("Setting up tts notify %s", config)
    return TTSNotificationService(hass, config)


class TTSNotificationService(BaseNotificationService):
    """The TTS Notification Service."""

    def __init__(self, hass, config):
        """Initialize the service."""
        self._media_player = config[CONF_MEDIA_PLAYER]
        self.hass = hass

    async def async_send_message(self, message="", **kwargs):
        """Call TTS service to speak the notification."""
        if kwargs["data"]:
            self.hass.bus.async_fire(
                DOMAIN + "_event",
                {"message": message, "entity_id": self._media_player, **kwargs["data"]},
            )
        else:
            self.hass.bus.async_fire(
                DOMAIN + "_event", {"message": message, "entity_id": self._media_player}
            )
