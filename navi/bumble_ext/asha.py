#  Copyright 2025 Google LLC
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

"""Audio Streaming for Hearing Aid(ASHA) GATT Service Implementation.

See more: https://source.android.com/docs/core/connect/bluetooth/asha
"""

import enum
import logging
import struct
from typing import Any, Callable

from bumble import core
from bumble import device as bumble_device
from bumble import gatt
from bumble import gatt_client
from bumble import l2cap
from bumble import utils

_logger = logging.getLogger(__name__)


class DeviceCapabilities(enum.IntFlag):
  IS_RIGHT = 0x01
  IS_DUAL = 0x02
  CSIS_SUPPORTED = 0x04


class FeatureMap(enum.IntFlag):
  LE_COC_AUDIO_OUTPUT_STREAMING_SUPPORTED = 0x01


class AudioType(utils.OpenIntEnum):
  UNKNOWN = 0x00
  RINGTONE = 0x01
  PHONE_CALL = 0x02
  MEDIA = 0x03


class OpCode(utils.OpenIntEnum):
  START = 1
  STOP = 2
  STATUS = 3


class Codec(utils.OpenIntEnum):
  G_722_16KHZ = 1


class SupportedCodecs(enum.IntFlag):
  G_722_16KHZ = 1 << Codec.G_722_16KHZ


class PeripheralStatus(utils.OpenIntEnum):
  """Status update on the other peripheral."""

  OTHER_PERIPHERAL_DISCONNECTED = 1
  OTHER_PERIPHERAL_CONNECTED = 2
  CONNECTION_PARAMETER_UPDATED = 3


class AudioStatus(utils.OpenIntEnum):
  """Status report field for the audio control point."""

  OK = 0
  UNKNOWN_COMMAND = -1
  ILLEGAL_PARAMETERS = -2


# -----------------------------------------------------------------------------
class AshaService(gatt.TemplateService):
  """ASHA GATT Service."""

  UUID = gatt.GATT_ASHA_SERVICE

  audio_sink: Callable[[bytes], Any] | None = None
  active_codec: Codec | None = None
  audio_type: AudioType | None = None
  volume: int | None = None
  other_state: int | None = None

  class Event(enum.StrEnum):
    STARTED = 'started'
    STOPPED = 'stopped'
    VOLUME_CHANGED = 'volume_changed'

  def __init__(
      self,
      capability: int,
      hisyncid: bytes,
      device: bumble_device.Device,
      psm: int = 0,
      audio_sink: Callable[[bytes], Any] | None = None,
      feature_map: int = FeatureMap.LE_COC_AUDIO_OUTPUT_STREAMING_SUPPORTED,
      protocol_version: int = 0x01,
      render_delay_milliseconds: int = 0,
      supported_codecs: int = SupportedCodecs.G_722_16KHZ,
  ) -> None:
    if len(hisyncid) != 8:
      _logger.warning(
          'HiSyncId should have a length of 8, got %d', len(hisyncid)
      )

    self.hisyncid = bytes(hisyncid)
    self.capability = capability
    self.device = device
    self.audio_out_data = b''
    self.psm = psm  # a non-zero psm is mainly for testing purpose
    self.audio_sink = audio_sink
    self.protocol_version = protocol_version

    self.read_only_properties_characteristic = gatt.Characteristic[bytes](
        gatt.GATT_ASHA_READ_ONLY_PROPERTIES_CHARACTERISTIC,
        gatt.Characteristic.Properties.READ,
        gatt.Characteristic.READABLE,
        struct.pack(
            '<BB8sBH2sH',
            protocol_version,
            capability,
            self.hisyncid,
            feature_map,
            render_delay_milliseconds,
            b'\x00\x00',
            supported_codecs,
        ),
    )

    self.audio_control_point_characteristic = gatt.Characteristic[bytes](
        gatt.GATT_ASHA_AUDIO_CONTROL_POINT_CHARACTERISTIC,
        gatt.Characteristic.Properties.WRITE
        | gatt.Characteristic.Properties.WRITE_WITHOUT_RESPONSE,
        gatt.Characteristic.WRITEABLE,
        gatt.CharacteristicValue(write=self._on_audio_control_point_write),
    )
    self.audio_status_characteristic = gatt.Characteristic[bytes](
        gatt.GATT_ASHA_AUDIO_STATUS_CHARACTERISTIC,
        gatt.Characteristic.Properties.READ
        | gatt.Characteristic.Properties.NOTIFY,
        gatt.Characteristic.READABLE,
        bytes([AudioStatus.OK]),
    )
    self.volume_characteristic = gatt.Characteristic[bytes](
        gatt.GATT_ASHA_VOLUME_CHARACTERISTIC,
        gatt.Characteristic.Properties.WRITE_WITHOUT_RESPONSE,
        gatt.Characteristic.WRITEABLE,
        gatt.CharacteristicValue(write=self._on_volume_write),
    )

    # let the server find a free PSM
    self.psm = device.create_l2cap_server(
        spec=l2cap.LeCreditBasedChannelSpec(psm=self.psm, max_credits=8),
        handler=self._on_connection,
    ).psm
    self.le_psm_out_characteristic = gatt.Characteristic[bytes](
        gatt.GATT_ASHA_LE_PSM_OUT_CHARACTERISTIC,
        gatt.Characteristic.Properties.READ,
        gatt.Characteristic.READABLE,
        struct.pack('<H', self.psm),
    )

    characteristics = [
        self.read_only_properties_characteristic,
        self.audio_control_point_characteristic,
        self.audio_status_characteristic,
        self.volume_characteristic,
        self.le_psm_out_characteristic,
    ]

    super().__init__(characteristics)

  def get_advertising_data(self) -> bytes:
    # Advertisement only uses 4 least significant bytes of the HiSyncId.
    return bytes(
        core.AdvertisingData([
            (
                core.AdvertisingData.SERVICE_DATA_16_BIT_UUID,
                bytes(gatt.GATT_ASHA_SERVICE)
                + bytes([self.protocol_version, self.capability])
                + self.hisyncid[:4],
            ),
        ])
    )

  # Handler for audio control commands
  async def _on_audio_control_point_write(
      self, connection: bumble_device.Connection, value: bytes
  ) -> None:
    del connection
    _logger.debug('--- AUDIO CONTROL POINT Write:%s', value.hex())
    opcode = value[0]
    if opcode == OpCode.START:
      # Start
      self.active_codec = Codec(value[1])
      self.audio_type = AudioType(value[2])
      self.volume = struct.unpack_from('<b', value, 3)[0]
      self.other_state = value[4]
      _logger.debug(
          '### START: codec=%s, audio_type=%s, volume=%s, other_state=%s',
          self.active_codec.name,
          self.audio_type.name,
          self.volume,
          self.other_state,
      )
      self.emit(self.Event.STARTED)
    elif opcode == OpCode.STOP:
      _logger.debug('### STOP')
      self.active_codec = None
      self.audio_type = None
      self.volume = None
      self.other_state = None
      self.emit(self.Event.STOPPED)
    elif opcode == OpCode.STATUS:
      _logger.debug('### STATUS: %s', PeripheralStatus(value[1]).name)

    # OPCODE_STATUS does not need audio status point update
    if opcode != OpCode.STATUS:
      await self.device.notify_subscribers(
          self.audio_status_characteristic, force=True
      )

  # Handler for volume control
  def _on_volume_write(
      self, connection: bumble_device.Connection, value: bytes
  ) -> None:
    del connection
    volume = struct.unpack('<b', value)[0]
    _logger.debug('--- VOLUME Write:%s', volume)
    self.volume = volume
    self.emit(self.Event.VOLUME_CHANGED)

  # Register an L2CAP CoC server
  def _on_connection(self, channel: l2cap.LeCreditBasedChannel) -> None:
    def on_data(data: bytes) -> None:
      if self.audio_sink:  # pylint: disable=not-callable
        self.audio_sink(data)

    channel.sink = on_data


# -----------------------------------------------------------------------------
class AshaServiceProxy(gatt_client.ProfileServiceProxy):
  """ASHA GATT Service Client Proxy."""

  SERVICE_CLASS = AshaService
  read_only_properties_characteristic: gatt_client.CharacteristicProxy[bytes]
  audio_control_point_characteristic: gatt_client.CharacteristicProxy[bytes]
  audio_status_point_characteristic: gatt_client.CharacteristicProxy[bytes]
  volume_characteristic: gatt_client.CharacteristicProxy[bytes]
  psm_characteristic: gatt_client.CharacteristicProxy[bytes]

  _CHARACTERISTICS = {
      gatt.GATT_ASHA_READ_ONLY_PROPERTIES_CHARACTERISTIC: (
          'read_only_properties_characteristic'
      ),
      gatt.GATT_ASHA_AUDIO_CONTROL_POINT_CHARACTERISTIC: (
          'audio_control_point_characteristic'
      ),
      gatt.GATT_ASHA_AUDIO_STATUS_CHARACTERISTIC: (
          'audio_status_point_characteristic'
      ),
      gatt.GATT_ASHA_VOLUME_CHARACTERISTIC: 'volume_characteristic',
      gatt.GATT_ASHA_LE_PSM_OUT_CHARACTERISTIC: 'psm_characteristic',
  }

  def __init__(self, service_proxy: gatt_client.ServiceProxy) -> None:
    self.service_proxy = service_proxy

    for uuid, attribute_name in self._CHARACTERISTICS.items():
      if not (
          characteristics := self.service_proxy.get_characteristics_by_uuid(
              uuid
          )
      ):
        raise gatt.InvalidServiceError(f'Missing {uuid} Characteristic')
      setattr(self, attribute_name, characteristics[0])
