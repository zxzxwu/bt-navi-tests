#  Copyright 2026 Google LLC
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

"""Tests for LE Channel Sounding."""

import asyncio

from bumble import core
from bumble import hci
from mobly import test_runner
from mobly import signals
from typing_extensions import override

from navi.tests import navi_test_base
from navi.tests.firmware import test_base
from navi.utils import constants

_DEFAULT_TIMEOUT_SECONDS = 10.0


# From
# https://cs.android.com/android/platform/superproject/main/+/main:packages/modules/Bluetooth/system/gd/hci/distance_measurement_manager.cc.
_CS_TONE_ANTENNA_CONFIG_MAPPING_TABLE = [
    [0, 4, 5, 6],
    [1, 7, 7, 7],
    [2, 7, 7, 7],
    [3, 7, 7, 7],
]
_CS_PREFERRED_PEER_ANTENNA_MAPPING_TABLE = [1, 1, 1, 1, 3, 7, 15, 3]


class ChannelSoundingTest(test_base.DualDeviceTestBase):

  @override
  async def async_setup_class(self) -> None:
    await super().async_setup_class()
    if not self.dut.device.supports_le_features(
        hci.LeFeatureMask.CHANNEL_SOUNDING
    ):
      raise signals.TestAbortClass('Channel Sounding is not supported on DUT')
    if not self.ref.device.supports_le_features(
        hci.LeFeatureMask.CHANNEL_SOUNDING
    ):
      raise signals.TestAbortClass('Channel Sounding is not supported on REF')
    self.dut.config.channel_sounding_enabled = True
    self.ref.config.channel_sounding_enabled = True

  @navi_test_base.named_parameterized(
      initiate=constants.Direction.INCOMING,
      reflect=constants.Direction.OUTGOING,
  )
  async def test_mode_2(self, direction: constants.Direction) -> None:
    """Test Channel Sounding from DUT."""
    if direction == constants.Direction.INCOMING:
      central, peripheral = self.ref, self.dut
      central_tag = 'REF'
      peripheral_tag = 'DUT'
    else:
      central, peripheral = self.dut, self.ref
      central_tag = 'DUT'
      peripheral_tag = 'REF'

    connections = await self.create_connection(
        central=central.device,
        peripheral=peripheral.device,
        link_type=core.PhysicalTransport.LE,
    )
    await self.encrypt_connection(connections)

    subevent_results = [
        asyncio.Queue[hci.HCI_LE_CS_Subevent_Result_Event]() for _ in range(2)
    ]
    central.device.host.on('cs_subevent_result', subevent_results[0].put_nowait)
    peripheral.device.host.on(
        'cs_subevent_result', subevent_results[1].put_nowait
    )
    if not (central_cs_capabilities := central.device.cs_capabilities):
      self.fail(f'{central_tag} does not support Channel Sounding.')

    self.logger.info('Setup Channel Sounding')
    async with self.assert_not_timeout(_DEFAULT_TIMEOUT_SECONDS):
      self.logger.info('[%s] Set default CS settings', central_tag)
      await central.device.set_default_cs_settings(connections[0])
      self.logger.info('[%s] Set default CS settings', peripheral_tag)
      await peripheral.device.set_default_cs_settings(connections[1])

      # Wait for CS settings to be ready.
      await asyncio.sleep(1)

      self.logger.info('[%s] Get remote CS capabilities', central_tag)
      peripheral_cs_capabilities = (
          await central.device.get_remote_cs_capabilities(connections[0])
      )

      self.logger.info('[%s] Create CS config', central_tag)
      config = await central.device.create_cs_config(
          connections[0], main_mode_type=0x02
      )
      self.logger.info('[%s] Enable CS security', central_tag)
      await central.device.enable_cs_security(connections[0])
      tone_antenna_config_selection = _CS_TONE_ANTENNA_CONFIG_MAPPING_TABLE[
          central_cs_capabilities.num_antennas_supported - 1
      ][peripheral_cs_capabilities.num_antennas_supported - 1]
      self.logger.info('[%s] Set CS procedure parameters', central_tag)
      await central.device.set_cs_procedure_parameters(
          connection=connections[0],
          config=config,
          tone_antenna_config_selection=tone_antenna_config_selection,
          preferred_peer_antenna=_CS_PREFERRED_PEER_ANTENNA_MAPPING_TABLE[
              tone_antenna_config_selection
          ],
      )

      self.logger.info('[%s] Enable CS Procedure', central_tag)
      await central.device.enable_cs_procedure(
          connection=connections[0], config=config
      )
      self.logger.info('[%s] Wait for Subevent Result', central_tag)
      await subevent_results[0].get()
      self.logger.info('[%s] Wait for Subevent Result', peripheral_tag)
      await subevent_results[1].get()


if __name__ == '__main__':
  test_runner.main()
