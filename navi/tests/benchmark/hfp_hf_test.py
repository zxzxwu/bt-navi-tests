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

from bumble import core
from bumble import hci
from bumble import hfp
from bumble import rfcomm
from mobly import test_runner
from mobly import signals
from typing_extensions import override

from navi.bumble_ext import hfp as hfp_ext
from navi.tests.benchmark import performance_tool
from navi.tests.benchmark import test_base
from navi.utils import android_constants
from navi.utils import bl4a_api


_Callback = bl4a_api.CallbackHandler
_DEFAULT_STEP_TIMEOUT_SECONDS = 5.0
_HFP_AG_SDP_HANDLE = 1
_HFP_HF_ENABLED_PROPERTY = "bluetooth.profile.hfp.hf.enabled"
_DEFAULT_REPEAT_TIMES = 50
_HfpState = android_constants.ConnectionState


class HfpHfTest(test_base.PerformanceTestBase):

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
    self._setup_ag_device(hfp_ext.make_ag_configuration())

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
          self.success_attempt_record(
              test_round=i + 1,
              latency=latency_seconds,
              latency_list=latency_list,
          )
      except (core.BaseBumbleError, AssertionError):
        self.logger.exception("Failed to make HFP connection")
      finally:
        await performance_tool.terminate_connection_from_ref(self.dut, self.ref)
    self.record_sponge_data(
        repeat_times=_DEFAULT_REPEAT_TIMES, latency_list=latency_list
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
    latency_list = list[float]()
    await self.pair_and_connect()
    await performance_tool.terminate_connection_from_ref(self.dut, self.ref)
    for i in range(_DEFAULT_REPEAT_TIMES):
      try:
        with self.dut.bl4a.register_callback(bl4a_api.Module.HFP_HF) as dut_cb:
          self.logger.info("[DUT] Reconnect.")
          with performance_tool.Stopwatch() as stop_watch:
            await self._connect_hfp_from_ref(hfp_ext.make_ag_configuration())
            self.logger.info("[DUT] Wait for HFP connected.")
            await self._wait_for_hfp_state(dut_cb, _HfpState.CONNECTED)
          latency_seconds = stop_watch.elapsed_time.total_seconds()
          self.success_attempt_record(
              test_round=i + 1,
              latency=latency_seconds,
              latency_list=latency_list,
          )
      except (core.BaseBumbleError, AssertionError):
        self.logger.exception("Failed to make HFP connection")
      finally:
        await performance_tool.terminate_connection_from_ref(self.dut, self.ref)
    self.record_sponge_data(
        repeat_times=_DEFAULT_REPEAT_TIMES, latency_list=latency_list
    )


if __name__ == "__main__":
  test_runner.main()
