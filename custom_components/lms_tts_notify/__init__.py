'''Logitech Squeezebox TTS notify queue.'''
import logging
from threading import Thread
from queue import Queue
import time
import voluptuous as vol

from homeassistant.const import EVENT_HOMEASSISTANT_START, EVENT_HOMEASSISTANT_STOP
from homeassistant.components.notify import ATTR_MESSAGE
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import split_entity_id
import homeassistant.helpers.config_validation as cv



DOMAIN = 'lms_tts_notify'
_LOGGER = logging.getLogger(__name__)

CONF_MEDIA_PLAYER = 'media_player'
CONF_TTS_SERVICE = 'tts_service'
CONF_REPEAT = 'repeat'
CONF_VOLUME = 'volume'
CONF_ALERT_SOUND = 'alert_sound'
CONF_FORCE_PLAY = 'force_play'
CONF_DEVICE_GROUP = 'device_group'
CONF_PAUSE = 'pause'
CONF_PLAYBACK_TIMEOUT = 'playback_timeout'

# ChimeTTS options
CONF_CHIMETTS_OPTION_CHIME_PATH = 'chimetts_chime_path'
CONF_CHIMETTS_OPTION_END_CHIME_PATH = 'chimetts_end_chime_path'
CONF_CHIMETTS_OPTION_OFFSET = 'chimetts_offset'
CONF_CHIMETTS_FINAL_DELAY = 'chimetts_final_delay'
CONF_CHIMETTS_TTS_SPEED = 'chimetts_tts_speed'
CONF_CHIMETTS_TTS_PITCH = 'chimetts_tts_pitch'

ATTR_SYNC_GROUP = 'group_members'
ATTR_VOLUME = 'volume_level'
ATTR_POSITION = 'media_position'

GEN_ATTRS = [ATTR_VOLUME, ATTR_SYNC_GROUP, ATTR_POSITION]

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.comp_entity_ids,
        vol.Optional(ATTR_MESSAGE): cv.string,
        vol.Optional(CONF_REPEAT): cv.positive_int,
        vol.Optional(CONF_ALERT_SOUND): cv.string,
        vol.Optional(CONF_VOLUME): cv.positive_float,
        vol.Optional(CONF_FORCE_PLAY): cv.boolean,
        vol.Optional(CONF_DEVICE_GROUP): cv.entity_id,
        vol.Optional(CONF_PAUSE): cv.positive_float,
        vol.Optional(CONF_PLAYBACK_TIMEOUT): cv.positive_int,
        vol.Optional(CONF_CHIMETTS_OPTION_CHIME_PATH): cv.string,
        vol.Optional(CONF_CHIMETTS_OPTION_END_CHIME_PATH): cv.string,
        vol.Optional(CONF_CHIMETTS_OPTION_OFFSET): vol.All(vol.Coerce(int), vol.Range(min=-10000, max=10000)),
        vol.Optional(CONF_CHIMETTS_FINAL_DELAY): cv.positive_int,
        vol.Optional(CONF_CHIMETTS_TTS_SPEED): vol.All(vol.Coerce(int), vol.Range(min=1, max=500)),
        vol.Optional(CONF_CHIMETTS_TTS_PITCH): vol.All(vol.Coerce(int), vol.Range(min=-100, max=100)),
    }
)


async def async_setup(hass, config):
    '''Load configurations'''

    _LOGGER.debug('The %s component is ready!', DOMAIN)
    coordinator = Coordinator(hass, config)
    hass.bus.async_listen_once(
        EVENT_HOMEASSISTANT_START, coordinator.start_handler
    )
    hass.bus.async_listen_once(
        EVENT_HOMEASSISTANT_STOP, coordinator.stop_handler
    )

    async def async_service_send_message(call):
        '''Forward queue service data to eventbus'''
        if isinstance(call.data['entity_id'], list):
            for media_player in call.data['entity_id']:
                data = dict(call.data)
                data['entity_id'] = media_player
                hass.bus.async_fire(DOMAIN + '_event', data)
        else:
            hass.bus.async_fire(DOMAIN + '_event', call.data)

    async def handle_event(event):
        '''listen to event bus and put message in coordinator queue from notify and queue service'''
        _LOGGER.debug('Received on event bus: %s', event.data)
        if event.data['entity_id'] in coordinator.queue_listener:
            coordinator.queue.put(event.data)
        else:
            _LOGGER.warning('LMS player not configured in %s : %s', DOMAIN, event.data['entity_id'])

    hass.bus.async_listen(DOMAIN + '_event', handle_event)

    hass.services.async_register(
        DOMAIN, 'queue', async_service_send_message, SERVICE_SCHEMA
    )

    return True


class Coordinator(Thread):
    '''Coordinator for save and restore state sync_groups, recieving tts messages and dispatching to media_players queues'''
    def __init__(self, hass, config):
        super().__init__()
        self._name = 'Coordinator'
        self._hass = hass
        self._queue = Queue()
        self.queue_listener = {}
        self.skip_save = False
        self.playing = 'idle'
        self.sync_group = set()
        self.players = set()

        for myconfig in config['notify']:
            if myconfig['platform'] == 'lms_tts_notify':
                # create queue and thread for each media_player
                _LOGGER.debug('config %s', myconfig)
                media_player = myconfig['media_player']

                self.queue_listener[media_player] = QueueListener(hass, myconfig)

                self._hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_START, self.queue_listener[media_player].start_handler
                )
                self._hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STOP, self.queue_listener[media_player].stop_handler
                )

    def run(self):
        '''Listen to queue events, and put them in media_player queue'''
        _LOGGER.debug('Running Coordinator')
        while True:
            if not self._queue.empty():
                event = self._queue.get()
                if event is None:
                    break
                if not self.skip_save:
                # Only save state the first message and skip when there are message in queue or stil playing
                    self.skip_save = True
                    self.save_state()
                    self.save_playlists()
                # unsync players
                _LOGGER.debug('UnSync %s', event['entity_id'])
                # self._hass.services.call(
                #     'squeezebox',
                #     'unsync',
                #     {'entity_id': event['entity_id']},
                #     )
                self._hass.services.call('media_player', 'unjoin', {'entity_id': event['entity_id']})
                self._hass.services.call('media_player', 'shuffle_set', {'entity_id': event['entity_id'], 'shuffle': False})
                self._hass.services.call('media_player', 'repeat_set', {'entity_id': event['entity_id'], 'repeat': 'off'})

                self._hass.services.call(
                    'squeezebox',
                    'call_query',
                    {'entity_id': list(self.queue_listener), 'command': 'playerpref', 'parameters': ['plugin.dontstopthemusic:provider', "0"]}
                )
                # send to media_player queue
                self.queue_listener[event['entity_id']].queue.put(event)
                # keep track of players used
                self.players.add(event['entity_id'])
            else:
                self.playing = 'waiting'
                time.sleep(0.2)
                if self.check_done():
                    _LOGGER.debug('Players all done: %s', self.players)
                    self.skip_save = False
                    for player in self.players:
                        self.queue_listener[player].status = 'idle'
                    self.players = set()
                    self.sync_group = set()

    def check_done(self):
        if len(self.players) > 0:
            waiting = 0
            for player in self.players:
                if self.queue_listener[player].status == 'done':
                    self.restore_volume(player)
                    self.restore_state(player)
                    self.queue_listener[player].status = 'waiting'
                    waiting += 1
                elif self.queue_listener[player].status == 'waiting':
                    waiting += 1
            if len(self.players) == waiting:
                #restore playlist of active players not in sync group
                for player in self.players:
                    if not any(player in sublist for sublist in self.sync_group) and self.queue_listener[player].state_save["state"] == 'playing':
                        self.restore_playlist(player)
                        self.restore_media_possition(player)
                #restore sync_groups and playlist of first active player in sync group
                for group in self.sync_group:
                    playing = False
                    for player in group:
                        if player in self.queue_listener and player in self.players:
                            if self.queue_listener[player].state_save['state'] == 'playing' and not playing:
                                self.restore_sync(group,player)
                                self.restore_playlist(player)
                                playing = True
                                break
                    if playing is False:
                        self.restore_sync(group,player)


                return True
            else:
                return False
        else:
            return False

    @property
    def queue(self):
        '''Return wrapped queue.'''
        return self._queue

    def stop(self):
        '''Stop run by putting None into queue and join the thread.'''
        _LOGGER.debug('Stopping Coordinator')
        self._queue.put(None)
        self.join()
        _LOGGER.debug('Stopped Coordinator')

    def start_handler(self, _):
        '''Start handler helper method.'''
        self.start()

    def stop_handler(self, _):
        '''Stop handler helper method.'''
        self.stop()

    def restore_playlist(self, player):
        _LOGGER.debug('Restore playlist: %s', player)
        service_data = {
            'entity_id': player,
            'command': 'playlist',
            'parameters': ['resume', 'Save-' + player],
        }
        self._hass.services.call('squeezebox', 'call_method', service_data)

    def save_playlists(self):
        for player, _ in self.queue_listener.items():
            _LOGGER.debug('Save playlists: %s', player)
            service_data = {
                'entity_id': player,
                'command': 'playlist',
                'parameters': ['save', 'Save-' + player],
            }
            self._hass.services.call('squeezebox', 'call_method', service_data)

    def restore_sync(self, group, player):
        sync_list = list(group)

        if len(sync_list) == 2:
            if any(item in self.players for item in sync_list ):
                sync_list.remove(player)
                _LOGGER.debug(
                    'ReSync %s->%s', player, sync_list[0]
                )
                self._hass.services.call('media_player', 'join', {'entity_id': player, 'group_members': sync_list[0] })
                # self._hass.services.call(
                #     'squeezebox',
                #     'sync',
                #     {
                #         'entity_id': player,
                #         'other_player': sync_list[0],
                #     },
                # )
        else:
            masters = [ item for item in sync_list if item not in self.players ]
            _LOGGER.debug(
                'Masters %s', masters
            )

            if masters:
                master = masters[0]
            else:
                master = player
                self.players.remove(player)
            for slave in self.players:
                if slave in sync_list:
                    _LOGGER.debug(
                        'ReSync %s->%s', master, slave
                    )
                    self._hass.services.call('media_player', 'join', {'entity_id': master, 'group_members': slave })
                    # self._hass.services.call(
                    #     'squeezebox',
                    #     'sync',
                    #     {
                    #         'entity_id': master,
                    #         'other_player': slave,
                    #     },
                    # )

    def save_state(self):
        '''Save state of media_player'''
        self._hass.services.call(
            'squeezebox',
            'call_query',
            {'entity_id': list(self.queue_listener), 'command': 'playerpref', 'parameters': ['plugin.dontstopthemusic:provider', "?"]}
            )
        for player, _ in self.queue_listener.items():
            service_data = {'entity_id': player}
            self._hass.services.call('homeassistant', 'update_entity', service_data)
            time.sleep(0.2)
            cur_state = self._hass.states.get(player)
            if cur_state is None:
                _LOGGER.debug('Could not get state of {}.'.format(player))
            elif cur_state.state == 'unavailable':
                attributes = {}
                attributes[ATTR_SYNC_GROUP] = []
                self.queue_listener[player].state_save = {'state': cur_state.state, 'attributes': attributes}
            else:
                attributes = cur_state.attributes.copy()
                if ATTR_SYNC_GROUP in cur_state.attributes:
                    if len(cur_state.attributes[ATTR_SYNC_GROUP]):
                        _LOGGER.debug('Add Sync Group %s', cur_state.attributes[ATTR_SYNC_GROUP])
                        self.sync_group.add(frozenset(cur_state.attributes[ATTR_SYNC_GROUP]))
                    else:
                        attributes[ATTR_SYNC_GROUP] = []
                else:
                    attributes[ATTR_SYNC_GROUP] = []
                # if ATTR_VOLUME in cur_state.attributes:
                #     attributes[ATTR_VOLUME] = cur_state.attributes[ATTR_VOLUME]
                # if ATTR_POSITION in cur_state.attributes:
                #     attributes[ATTR_POSITION] = cur_state.attributes[ATTR_POSITION]

                #attributes['repeat'] = cur_state.attributes['query_result']['_repeat']
                # self._hass.services.call(
                #         'squeezebox',
                #         'call_query',
                #         {'entity_id': player, 'command': 'syncgroups', 'parameters': ["?"]}
                #     )
                # cur_state = self._hass.states.get(player)
                # attributes['sync'] = cur_state.attributes['query_result']['syncgroups_loop']

                _LOGGER.debug('Save state: %s -> %s', player, {'state': cur_state.state, 'attributes': attributes})
                self.queue_listener[player].state_save = {'state': cur_state.state, 'attributes': attributes}

    def restore_state(self, player):
        '''Restore state'''
        _LOGGER.debug('Restore state: %s -> %s ', player, self.queue_listener[player].state_save)
        turn_on = self.queue_listener[player].state_save['state']
        try:
            repeat = self.queue_listener[player].state_save['attributes']['repeat']
        except:
            repeat = 'off'
        try:
            shuffle = self.queue_listener[player].state_save['attributes']['shuffle']
        except:
            shuffle = False
        try:
            dstm = self.queue_listener[player].state_save['attributes']['query_result']['_p2']
        except:
            dstm = 0
        # self._hass.services.call(
        #     'squeezebox',
        #     'call_method',
        #     {'entity_id': player, 'command': 'playlist', 'parameters': ['repeat', self.queue_listener[player].state_save['attributes']['repeat']]}
        # )

        self._hass.services.call('media_player', 'shuffle_set', {'entity_id': player, 'shuffle': shuffle})
        self._hass.services.call('media_player', 'repeat_set', {'entity_id': player, 'repeat': repeat})
        self._hass.services.call('squeezebox', 'call_query',
            {'entity_id': list(self.queue_listener), 'command': 'playerpref', 'parameters': [ 'plugin.dontstopthemusic:provider' , dstm ] })

        if turn_on == 'off':
            self._hass.services.call('media_player', 'turn_off', {'entity_id': player})

    def restore_volume(self, player):
        '''Restore volume'''
        _LOGGER.debug('Restore volume: %s', player)
        turn_on = self.queue_listener[player].state_save['state']
        if turn_on in ['on', 'playing', 'idle', 'paused']:
            if 'volume_level' in self.queue_listener[player].state_save['attributes']:
                volume = self.queue_listener[player].state_save['attributes']['volume_level']
                self._hass.services.call(
                    'media_player',
                    'volume_set',
                    {'entity_id': player, 'volume_level': volume},
                )

    def restore_media_possition(self, player):
        '''Restore media position'''
        _LOGGER.debug('Restore media_position: %s', player)
        turn_on = self.queue_listener[player].state_save['state']
        if turn_on in ['on', 'playing', 'idle', 'paused']:      
            if 'media_position' in self.queue_listener[player].state_save['attributes']:
                media_position = self.queue_listener[player].state_save['attributes']['media_position']
                self._hass.services.call(
                    'media_player',
                    'media_seek',
                    {
                        'entity_id': player,
                        'seek_position': media_position,
                    },
                )

class QueueListener(Thread):
    '''Play tts notify events from queue to mediaplayer'''

    def __init__(self, hass, config):
        '''Create queue.'''
        super().__init__()
        self._hass = hass
        self.state2 = 'idle'
        self._queue = Queue()
        self._repeat = config.get(CONF_REPEAT)
        self._alert_sound = config.get(CONF_ALERT_SOUND)
        self._volume = config.get(CONF_VOLUME)
        self._pause = config.get(CONF_PAUSE)
        self._playback_timeout = config.get(CONF_PLAYBACK_TIMEOUT)
        self._media_player = config[CONF_MEDIA_PLAYER]
        self._tts_engine = config.get(ATTR_ENTITY_ID)
        self._config = config
        self._sync_group = []
        self._tts_group, self._tts_service = split_entity_id(config[CONF_TTS_SERVICE])
        _, name = split_entity_id(self._media_player)
        self._name = name + '_queue'
        self.skip_save = False
        self.force_play = False
        self.status = 'idle'
        self._message = ''
        self._device_group = ''
        self._chimetts_option_chime_path = config.get(CONF_CHIMETTS_OPTION_CHIME_PATH)
        self._chimetts_option_end_chime_path = config.get(CONF_CHIMETTS_OPTION_END_CHIME_PATH)
        self._chimetts_option_offset = config.get(CONF_CHIMETTS_OPTION_OFFSET)
        self._chimetts_final_delay = config.get(CONF_CHIMETTS_FINAL_DELAY)
        self._chimetts_tts_speed = config.get(CONF_CHIMETTS_TTS_SPEED)
        self._chimetts_tts_pitch = config.get(CONF_CHIMETTS_TTS_PITCH)


    def run(self):
        '''Listen to queue events, and play them to mediaplayer'''
        _LOGGER.debug('Running QueueListener')

        while True:
            event = self._queue.get()
            if event is None:
                break
            self.status = 'playing'
            self._message = event.get(ATTR_MESSAGE, '').replace('<br>', '')
            self._repeat = event.get(CONF_REPEAT, self._config.get(CONF_REPEAT))
            self._volume = event.get(CONF_VOLUME, self._config.get(CONF_VOLUME))
            self._pause = event.get(CONF_PAUSE, self._config.get(CONF_PAUSE))
            self._playback_timeout = event.get(CONF_PLAYBACK_TIMEOUT, self._config.get(CONF_PLAYBACK_TIMEOUT))
            self._device_group = event.get(CONF_DEVICE_GROUP, self._config.get(CONF_DEVICE_GROUP))
            self._alert_sound = event.get(
                CONF_ALERT_SOUND, self._config.get(CONF_ALERT_SOUND)
            )
            self.force_play = event.get(CONF_FORCE_PLAY, False)

            self._chimetts_options = {
                'chime_path': event.get(CONF_CHIMETTS_OPTION_CHIME_PATH, self._chimetts_option_chime_path),
                'end_chime_path': event.get(CONF_CHIMETTS_OPTION_END_CHIME_PATH, self._chimetts_option_end_chime_path),
                'offset': event.get(CONF_CHIMETTS_OPTION_OFFSET, self._chimetts_option_offset),
                'final_delay': event.get(CONF_CHIMETTS_FINAL_DELAY, self._chimetts_final_delay),
                'tts_speed': event.get(CONF_CHIMETTS_TTS_SPEED, self._chimetts_tts_speed),
                'tts_pitch': event.get(CONF_CHIMETTS_TTS_PITCH, self._chimetts_tts_pitch),
            }

            home = self._hass.states.get(self._device_group)
            if not home or home.state == 'home' or self.force_play:
                self.audio_alert()
                if self._queue.empty():
                    self.wait_on_finished()
            else:
                _LOGGER.debug('Not playing: %s state != \'home\' and not force_play', self._device_group) 

    @property
    def queue(self):
        '''Return wrapped queue.'''
        return self._queue

    def stop(self):
        '''Stop run by putting None into queue and join the thread.'''
        _LOGGER.debug('Stopping QueueListener')
        self._queue.put(None)
        self.join()
        _LOGGER.debug('Stopped QueueListener')

    def start_handler(self, _):
        '''Start handler helper method.'''
        self.start()

    def stop_handler(self, _):
        '''Stop handler helper method.'''
        self.stop()

    def wait_on_idle(self):
        '''Wait until player is done playing'''
        timeout = time.time() + self._playback_timeout  #break is media player is stuck
        while True:
            # Force update status of the media_player
            service_data = {'entity_id': self._media_player}
            self._hass.services.call('homeassistant', 'update_entity', service_data)
            time.sleep(0.2)
            state = self._hass.states.get(self._media_player).state
            if time.time() > timeout:
                _LOGGER.debug('Player stuck')
                break
            if state in ['idle', 'paused', 'off', 'unavailable']:
                break

    def wait_on_finished(self):
        '''Wait for player to finish'''
        _LOGGER.debug('Waiting for %s to finish', self._media_player)
        timeout = time.time() + 2
        while True:
            service_data = {'entity_id': self._media_player}
            self._hass.services.call('homeassistant', 'update_entity', service_data)
            time.sleep(0.2)
            if self._hass.states.get(self._media_player).state in ['off', 'idle', 'unavailable']:
                self.status = 'done'
                break
            else:
                _LOGGER.debug('Player: %s not done', self._media_player)
            if time.time() > timeout:
                _LOGGER.debug('Player: %s stuck', self._media_player)
                self.status = 'done'
                break

    def audio_alert(self):
        '''Play tts message'''
        self._hass.services.call(
            'media_player', 'media_pause', {'entity_id': self._media_player}
        )
        # stop media player before changing volume
        time.sleep(self._pause)
        _LOGGER.debug('Playing message \'%s\' ', self._message)
        # Set alert volume
        if self._volume:
            service_data = {
                'entity_id': self._media_player,
                'volume_level': self._volume,
            }
            self._hass.services.call('media_player', 'volume_set', service_data)
        for _ in range(self._repeat):
            # Play alert sound
            if self._alert_sound:
                # service_data = { 'entity_id': self._media_player, 'media_content_id': self._alert_sound, 'media_content_type': 'music'  }
                # self._hass.services.call( 'media_player', 'play_media' , service_data)
                service_data = {
                    'entity_id': self._media_player,
                    'command': 'playlist',
                    'parameters': ['resume', self._alert_sound],
                }
                self._hass.services.call('squeezebox', 'call_method', service_data)
                time.sleep(self._pause)
                self.wait_on_idle()

            # Play message
            if self._message:
                if 'speak' in self._tts_service:
                    service_data = {
                        'entity_id': self._tts_engine,
                        'media_player_entity_id': self._media_player,
                        'message': self._message,
                    }
                elif 'chime_tts' in self._tts_group:

                    _chimetts_options = {k: v for k, v in self._chimetts_options.items() if v is not None}
                    _LOGGER.debug('ChimeTTS options: %s', _chimetts_options)

                    service_data = {
                        'tts_platform': self._tts_engine,
                        'entity_id': self._media_player,
                        'message': self._message,
                        **_chimetts_options,
                    }
                else:
                    service_data = {
                        ATTR_ENTITY_ID: self._media_player,
                        'message': self._message,
                    }

                _LOGGER.debug('Playing message on %s.%s', self._tts_group, self._tts_service)
                self._hass.services.call(self._tts_group, self._tts_service, service_data)
                time.sleep(self._pause)
            self.wait_on_idle()
