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

"""Tests related to Bluetooth HFP(Hands-Free Profile) HF role on Pixel."""

import statistics

from bumble import core
from bumble import hci
from bumble import hfp
from bumble import rfcomm
from mobly import test_runner
from mobly import signals
from typing_extensions import override

from navi.tests import navi_test_base
from navi.tests.benchmark import performance_tool
from navi.utils import android_constants
from navi.utils import bl4a_api


_Callback = bl4a_api.CallbackHandler
_DEFAULT_STEP_TIMEOUT_SECONDS = 5.0
_HFP_AG_SDP_HANDLE = 1
_HFP_HF_ENABLED_PROPERTY = "bluetooth.profile.hfp.hf.enabled"
_DEFAULT_REPEAT_TIMES = 50
_HfpState = android_constants.ConnectionState
_DEFAULT_AG_CONFIGURATION = hfp.AgConfiguration(
    supported_ag_features=[
        hfp.AgFeature.ENHANCED_CALL_STATUS,
    ],
    supported_ag_indicators=[
        hfp.AgIndicatorState.call(),
        hfp.AgIndicatorState.callsetup(),
        hfp.AgIndicatorState.service(),
        hfp.AgIndicatorState.signal(),
        hfp.AgIndicatorState.roam(),
        hfp.AgIndicatorState.callheld(),
        hfp.AgIndicatorState.battchg(),
    ],
    supported_hf_indicators=[],
    supported_ag_call_hold_operations=[],
    supported_audio_codecs=[hfp.AudioCodec.CVSD],
)


class HfpHfTest(navi_test_base.TwoDevicesTestBase):

  @override
  async def async_setup_class(self) -> None:
    await super().async_setup_class()
    if self.dut.getprop(_HFP_HF_ENABLED_PROPERTY) != "true":
      raise signals.TestAbortClass("DUT does not have HFP HF enabled.")

  def _setup_ag_device(self, configuration: hfp.AgConfiguration) -> None:
    def on_dlc(dlc: rfcomm.DLC):
      hfp.AgProtocol(dlc, configuration)

    self.ref.device.sdp_service_records = {
        _HFP_AG_SDP_HANDLE: hfp.make_ag_sdp_records(
            service_record_handle=_HFP_AG_SDP_HANDLE,
            rfcomm_channel=rfcomm.Server(self.ref.device).listen(on_dlc),
            configuration=configuration,
        )
    }

  async def _connect_hfp_from_ref(
      self, config: hfp.AgConfiguration
  ) -> hfp.AgProtocol:
    if not (
        dut_ref_acl := self.ref.device.find_connection_by_bd_addr(
            hci.Address(self.dut.address)
        )
    ):
      self.logger.info("[REF] Connect.")
      dut_ref_acl = await self.ref.device.connect(
          self.dut.address,
          core.BT_BR_EDR_TRANSPORT,
          timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
      )

      self.logger.info("[REF] Authenticate and encrypt connection.")
      await dut_ref_acl.authenticate()
      await dut_ref_acl.encrypt()

    sdp_record = await hfp.find_hf_sdp_record(dut_ref_acl)
    if not sdp_record:
      self.fail("DUT does not have HFP SDP record.")
    rfcomm_channel = sdp_record[0]

    self.logger.info("[REF] Found HFP RFCOMM channel %s.", rfcomm_channel)

    self.logger.info("[REF] Open RFCOMM Channel.")
    async with self.assert_not_timeout(_DEFAULT_STEP_TIMEOUT_SECONDS):
      multiplexer = await rfcomm.Client(dut_ref_acl).start()
      dlc = await multiplexer.open_dlc(rfcomm_channel)
    return hfp.AgProtocol(dlc, config)

  async def _wait_for_hfp_state(
      self, dut_cb: _Callback, state: _HfpState
  ) -> None:
    self.logger.info("[DUT] Wait for HFP state %s.", state)
    await dut_cb.wait_for_event(
        bl4a_api.ProfileConnectionStateChanged(
            address=self.ref.address,
            state=state,
        ),
    )

  async def pair_and_connect(self) -> None:
    """Tests HFP connection establishment right after a pairing session.

    Test steps:
      1. Setup HFP on REF.
      2. Create bond from DUT.
      3. Wait HFP connected on DUT.(Android should autoconnect HFP as HF)
    """
    self._setup_ag_device(_DEFAULT_AG_CONFIGURATION)

    self.logger.info("[DUT] Connect and pair REF.")
    with self.dut.bl4a.register_callback(bl4a_api.Module.HFP_HF) as dut_cb:
      await self.classic_connect_and_pair()

      self.logger.info("[DUT] Wait for HFP connected.")
      await self._wait_for_hfp_state(dut_cb, _HfpState.CONNECTED)

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
    await self.pair_and_connect()
    await performance_tool.terminate_connection_from_ref(self.dut, self.ref)
    for i in range(_DEFAULT_REPEAT_TIMES):
      try:
        with self.dut.bl4a.register_callback(bl4a_api.Module.HFP_HF) as dut_cb:
          self.logger.info("[DUT] Reconnect.")
          with performance_tool.Stopwatch() as stop_watch:
            self.dut.bt.connect(self.ref.address)
            self.logger.info("[DUT] Wait for HFP connected.")
            await self._wait_for_hfp_state(dut_cb, _HfpState.CONNECTED)

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
        await performance_tool.terminate_connection_from_ref(self.dut, self.ref)
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
    await self.pair_and_connect()
    await performance_tool.terminate_connection_from_ref(self.dut, self.ref)
    for i in range(_DEFAULT_REPEAT_TIMES):
      try:
        with self.dut.bl4a.register_callback(bl4a_api.Module.HFP_HF) as dut_cb:
          self.logger.info("[DUT] Reconnect.")
          with performance_tool.Stopwatch() as stop_watch:
            await self._connect_hfp_from_ref(_DEFAULT_AG_CONFIGURATION)
            self.logger.info("[DUT] Wait for HFP connected.")
            await self._wait_for_hfp_state(dut_cb, _HfpState.CONNECTED)
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
        await performance_tool.terminate_connection_from_ref(self.dut, self.ref)
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
