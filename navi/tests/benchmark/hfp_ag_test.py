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

"""Tests related to Bluetooth HFP(Hands-Free Profile) AG role on Pixel."""

import statistics

from bumble import core
from bumble import hfp
from bumble import rfcomm
from mobly import test_runner
from mobly import signals
from typing_extensions import override

from navi.bumble_ext import hfp as hfp_ext
from navi.tests import navi_test_base
from navi.tests.benchmark import performance_tool
from navi.utils import android_constants
from navi.utils import bl4a_api


_DEFAULT_STEP_TIMEOUT_SECONDS = 30.0
_HFP_SDP_HANDLE = 1
_DEFAULT_REPEAT_TIMES = 50

_AudioCodec = hfp.AudioCodec
_Module = bl4a_api.Module


class HfpAgTest(navi_test_base.TwoDevicesTestBase):

  @override
  async def async_setup_class(self) -> None:
    await super().async_setup_class()
    if self.dut.getprop(android_constants.Property.HFP_AG_ENABLED) != "true":
      raise signals.TestAbortClass("HFP(AG) is not enabled on DUT.")
    # Make sure Bumble is on.
    await self.ref.open()

  @override
  async def async_teardown_test(self) -> None:
    await super().async_teardown_test()
    # Make sure Bumble is off to cancel any running tasks.
    async with self.assert_not_timeout(_DEFAULT_STEP_TIMEOUT_SECONDS):
      await self.ref.close()

  @classmethod
  def _default_hfp_configuration(cls) -> hfp.HfConfiguration:
    return hfp.HfConfiguration(
        supported_hf_features=[],
        supported_hf_indicators=[],
        supported_audio_codecs=[
            _AudioCodec.CVSD,
            _AudioCodec.MSBC,
        ],
    )

  async def _terminate_connection_from_dut(self) -> None:
    with (self.dut.bl4a.register_callback(_Module.ADAPTER) as dut_cb,):
      self.logger.info("[DUT] Terminate connection.")
      self.dut.bt.disconnect(self.ref.address)
      await dut_cb.wait_for_event(
          bl4a_api.AclDisconnected(
              address=self.ref.address,
              transport=android_constants.Transport.CLASSIC,
          ),
      )

  async def _test_pair_and_connect(self) -> None:
    """Tests HFP connection establishment right after a pairing session.

    Test steps:
      1. Setup HFP on REF.
      2. Create bond from DUT.
      3. Wait HFP connected on DUT.(Android should autoconnect HFP as AG)
    """
    with (self.dut.bl4a.register_callback(_Module.HFP_AG) as dut_cb,):
      hfp_ext.HfProtocol.setup_server(
          self.ref.device,
          sdp_handle=_HFP_SDP_HANDLE,
          configuration=self._default_hfp_configuration(),
      )

      self.logger.info("[DUT] Connect and pair REF.")
      await self.classic_connect_and_pair()

      self.logger.info("[DUT] Wait for HFP connected.")
      await dut_cb.wait_for_event(
          bl4a_api.ProfileActiveDeviceChanged(address=self.ref.address),
          timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
      )

  async def test_paired_connect_outgoing(self) -> None:
    """Tests HFP connection establishment where pairing is not involved.

    Test steps:
      1. Setup pairing between DUT and REF.
      2. Terminate ACL connection.
      3. Trigger connection from DUT.
      4. Wait HFP connected on DUT.
      5. Disconnect from DUT.
      6. Wait HFP disconnected on DUT.
    """
    success_count = 0
    latency_list = list[float]()
    await self._test_pair_and_connect()
    await self._terminate_connection_from_dut()
    for i in range(_DEFAULT_REPEAT_TIMES):
      try:
        with (self.dut.bl4a.register_callback(_Module.HFP_AG) as dut_cb,):
          self.logger.info("[DUT] Reconnect.")
          with performance_tool.Stopwatch() as stop_watch:
            self.dut.bt.connect(self.ref.address)
            self.logger.info("[DUT] Wait for HFP connected.")
            await dut_cb.wait_for_event(
                bl4a_api.ProfileActiveDeviceChanged(address=self.ref.address),
                timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
            )
          latency_seconds = stop_watch.elapsed_time.total_seconds()
          self.logger.info(
              "Success connection in %.2f seconds", latency_seconds
          )
          self.logger.info("Test%d Success", i + 1)
          latency_list.append(latency_seconds)
        success_count += 1
      except (core.BaseBumbleError, AssertionError):
        self.logger.exception("Failed to make HFP connection")
      finally:
        await self._terminate_connection_from_dut()
    self.logger.info(
        "[success rate] Passes: %d / Attempts: %d",
        success_count,
        _DEFAULT_REPEAT_TIMES,
    )
    self.logger.info(
        "[connection time] avg: %.2f, min: %.2f, max: %.2f, stdev: %.2f",
        statistics.mean(latency_list),
        min(latency_list),
        max(latency_list),
        statistics.stdev(latency_list),
    )
    self.record_data(
        navi_test_base.RecordData(
            test_name=self.current_test_info.name,
            properties={
                "passes": success_count,
                "attempts": _DEFAULT_REPEAT_TIMES,
                "avg_latency": statistics.mean(latency_list),
                "min_latency": min(latency_list),
                "max_latency": max(latency_list),
                "stdev_latency": statistics.stdev(latency_list),
            },
        )
    )

  async def test_paired_connect_incoming(self) -> None:
    """Tests HFP connection establishment where pairing is not involved.

    Test steps:
      1. Setup pairing between DUT and REF.
      2. Terminate ACL connection.
      3. Trigger connection from REF.
      4. Wait HFP connected on DUT.
      5. Disconnect from REF.
      6. Wait HFP disconnected on DUT.
    """
    success_count = 0
    latency_list = list[float]()
    await self._test_pair_and_connect()
    await self._terminate_connection_from_dut()
    for i in range(_DEFAULT_REPEAT_TIMES):
      try:
        with (self.dut.bl4a.register_callback(_Module.HFP_AG) as dut_cb,):

          self.logger.info("[DUT] Reconnect.")
          with performance_tool.Stopwatch() as stop_watch:
            dut_ref_acl = await self.ref.device.connect(
                self.dut.address,
                core.BT_BR_EDR_TRANSPORT,
                timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
            )

            self.logger.info("[REF] Authenticate and encrypt connection.")
            await dut_ref_acl.authenticate()
            await dut_ref_acl.encrypt()

            rfcomm_channel = await rfcomm.find_rfcomm_channel_with_uuid(
                dut_ref_acl, core.BT_HANDSFREE_AUDIO_GATEWAY_SERVICE
            )
            if rfcomm_channel is None:
              self.fail("No HFP RFCOMM channel found on REF.")
            self.logger.info(
                "[REF] Found HFP RFCOMM channel %s.", rfcomm_channel
            )

            self.logger.info("[REF] Open RFCOMM Multiplexer.")
            async with self.assert_not_timeout(_DEFAULT_STEP_TIMEOUT_SECONDS):
              multiplexer = await rfcomm.Client(dut_ref_acl).start()

            self.logger.info("[REF] Open RFCOMM DLC.")
            async with self.assert_not_timeout(_DEFAULT_STEP_TIMEOUT_SECONDS):
              dlc = await multiplexer.open_dlc(rfcomm_channel)

            self.logger.info("[REF] Establish SLC.")
            ref_hfp_protocol = hfp_ext.HfProtocol(
                dlc, self._default_hfp_configuration()
            )
            async with self.assert_not_timeout(_DEFAULT_STEP_TIMEOUT_SECONDS):
              await ref_hfp_protocol.initiate_slc()

            self.logger.info("[DUT] Wait for HFP connected.")
            await dut_cb.wait_for_event(
                bl4a_api.ProfileActiveDeviceChanged(address=self.ref.address),
                timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
            )
          latency_seconds = stop_watch.elapsed_time.total_seconds()
          self.logger.info(
              "Success connection in %.2f seconds", latency_seconds
          )
          self.logger.info("Test%d Success", i + 1)
          latency_list.append(latency_seconds)
        success_count += 1
      except (core.BaseBumbleError, AssertionError):
        self.logger.exception("Failed to make HFP connection")
      finally:
        await self._terminate_connection_from_dut()
    self.logger.info(
        "[success rate] Passes: %d / Attempts: %d",
        success_count,
        _DEFAULT_REPEAT_TIMES,
    )
    self.logger.info(
        "[connection time] avg: %.2f, min: %.2f, max: %.2f, stdev: %.2f",
        statistics.mean(latency_list),
        min(latency_list),
        max(latency_list),
        statistics.stdev(latency_list),
    )
    self.record_data(
        navi_test_base.RecordData(
            test_name=self.current_test_info.name,
            properties={
                "passes": success_count,
                "attempts": _DEFAULT_REPEAT_TIMES,
                "avg_latency": statistics.mean(latency_list),
                "min_latency": min(latency_list),
                "max_latency": max(latency_list),
                "stdev_latency": statistics.stdev(latency_list),
            },
        )
    )


if __name__ == "__main__":
  test_runner.main()
