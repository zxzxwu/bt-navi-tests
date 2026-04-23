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

"""Tests related to Bluetooth HFP(Hands-Free Profile) AG role on Pixel."""

import asyncio
import contextlib
from unittest import mock

from bumble import core
from bumble import device
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
from navi.utils import constants
from navi.utils import matcher


_DEFAULT_STEP_TIMEOUT_SECONDS = 30.0
_HFP_SDP_HANDLE = 1
_DEFAULT_REPEAT_TIMES = 50
_CALLER_NAME = "Pixel Bluetooth"
_CALLER_NUMBER = "123456789"

_CallState = android_constants.CallState
_AudioCodec = hfp.AudioCodec
_Module = bl4a_api.Module
_CallbackHandler = bl4a_api.CallbackHandler
_HfpAgAudioStateChange = bl4a_api.HfpAgAudioStateChanged
_ScoState = android_constants.ScoState


class HfpAgTest(test_base.PerformanceTestBase):

  @override
  async def async_setup_class(self) -> None:
    await super().async_setup_class()
    if self.dut.getprop(android_constants.Property.HFP_AG_ENABLED) != "true":
      raise signals.TestAbortClass("HFP(AG) is not enabled on DUT.")

  @override
  async def async_teardown_test(self) -> None:
    await super().async_teardown_test()
    # Make sure Bumble is off to cancel any running tasks.
    async with self.assert_not_timeout(_DEFAULT_STEP_TIMEOUT_SECONDS):
      await self.ref.close()

  async def pair_and_connect(self) -> None:
    with (self.dut.bl4a.register_callback(_Module.HFP_AG) as dut_cb,):
      hfp_ext.HfProtocol.setup_server(
          self.ref.device,
          sdp_handle=_HFP_SDP_HANDLE,
          configuration=hfp_ext.make_hf_configuration(),
      )

      self.logger.info("[DUT] Connect and pair REF.")
      await self.classic_connect_and_pair(connect_profiles=True)

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
      5. Repeat step 3-4.
    """
    latency_list = list[float]()
    await self.pair_and_connect()
    await performance_tool.terminate_connection_from_dut(self.dut, self.ref)
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
          self.success_attempt_record(
              test_round=i + 1,
              latency=latency_seconds,
              latency_list=latency_list,
          )
      except (core.BaseBumbleError, AssertionError):
        self.logger.exception("Failed to make HFP connection")
      finally:
        await performance_tool.terminate_connection_from_dut(self.dut, self.ref)
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
      5. Repeat step 3-4.
    """
    latency_list = list[float]()
    await self.pair_and_connect()
    await performance_tool.terminate_connection_from_dut(self.dut, self.ref)
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
                dlc, hfp_ext.make_hf_configuration()
            )
            async with self.assert_not_timeout(_DEFAULT_STEP_TIMEOUT_SECONDS):
              await ref_hfp_protocol.initiate_slc()

            self.logger.info("[DUT] Wait for HFP connected.")
            await dut_cb.wait_for_event(
                bl4a_api.ProfileActiveDeviceChanged(address=self.ref.address),
                timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
            )
          latency_seconds = stop_watch.elapsed_time.total_seconds()
          self.success_attempt_record(
              test_round=i + 1,
              latency=latency_seconds,
              latency_list=latency_list,
          )
      except (core.BaseBumbleError, AssertionError):
        self.logger.exception("Failed to make HFP connection")
      finally:
        await performance_tool.terminate_connection_from_dut(self.dut, self.ref)
    self.record_sponge_data(
        repeat_times=_DEFAULT_REPEAT_TIMES, latency_list=latency_list
    )

  async def test_audio_call_sco_connection(self) -> None:
    """Tests making an outgoing phone call, observing SCO connection status.

    Test steps:
      1. Setup HFP connection.
      2. Place an outgoing call.
      3. Verify SCO connected.
      4. Repeat step 2-3.
    """
    latency_list = list[float]()
    # [REF] Setup HFP.
    hfp_configuration = hfp.HfConfiguration(
        supported_hf_features=[hfp.HfFeature.CODEC_NEGOTIATION],
        supported_hf_indicators=[],
        supported_audio_codecs=[_AudioCodec.CVSD],
    )
    ref_hfp_protocol_queue = hfp_ext.HfProtocol.setup_server(
        self.ref.device,
        sdp_handle=_HFP_SDP_HANDLE,
        configuration=hfp_configuration,
    )
    preferred_codec = _AudioCodec.CVSD
    with self.dut.bl4a.register_callback(_Module.HFP_AG) as dut_hfp_cb:
      self.logger.info("[DUT] Connect and pair REF.")
      await self.classic_connect_and_pair(connect_profiles=True)

      self.logger.info("[DUT] Wait for HFP connected.")
      await dut_hfp_cb.wait_for_event(
          bl4a_api.ProfileActiveDeviceChanged(address=self.ref.address),
          timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
      )

    async with self.assert_not_timeout(
        _DEFAULT_STEP_TIMEOUT_SECONDS,
        msg="[REF] Wait for HFP connected.",
    ):
      ref_hfp_protocol = await ref_hfp_protocol_queue.get()

    self.dut.bt.audioSetRepeat(android_constants.RepeatMode.ONE)
    for i in range(_DEFAULT_REPEAT_TIMES):
      test_case_callbacks = contextlib.AsyncExitStack()
      sco_links = asyncio.Queue[device.ScoLink]()
      try:
        dut_hfp_cb = self.dut.bl4a.register_callback(_Module.HFP_AG)
        dut_telecom_cb = self.dut.bl4a.register_callback(_Module.TELECOM)
        test_case_callbacks.push(dut_hfp_cb)
        test_case_callbacks.push(dut_telecom_cb)
        self.ref.device.on(
            self.ref.device.EVENT_SCO_CONNECTION, sco_links.put_nowait
        )
        self.logger.info("[DUT] Add call.")
        with self.dut.bl4a.make_phone_call(
            _CALLER_NAME,
            _CALLER_NUMBER,
            constants.Direction.OUTGOING,
        ) as call:
          await dut_telecom_cb.wait_for_event(
              event=bl4a_api.CallStateChanged(
                  state=matcher.any_of(
                      _CallState.CONNECTING, _CallState.DIALING
                  ),
                  handle=mock.ANY,
                  name=mock.ANY,
              ),
              timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
          )
          with performance_tool.Stopwatch() as stop_watch:
            self.logger.info("[DUT] Start streaming.")
            await asyncio.to_thread(self.dut.bt.audioPlaySine)

            self.logger.info("[DUT] Wait for SCO connected.")
            await dut_hfp_cb.wait_for_event(
                _HfpAgAudioStateChange(
                    address=self.ref.address, state=_ScoState.CONNECTED
                ),
                timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
            )

            async with self.assert_not_timeout(_DEFAULT_STEP_TIMEOUT_SECONDS):
              self.logger.info("[REF] Wait for SCO connected.")
              await sco_links.get()

              self.assertEqual(ref_hfp_protocol.active_codec, preferred_codec)
          latency_seconds = stop_watch.elapsed_time.total_seconds()
          self.logger.info("[DUT] Terminate call.")
          call.close()
          await dut_telecom_cb.wait_for_event(
              event=bl4a_api.CallStateChanged(
                  state=_CallState.DISCONNECTED, handle=mock.ANY, name=mock.ANY
              ),
              predicate=lambda e: e.state in [_CallState.DISCONNECTED],
              timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
          )

        self.logger.info("[DUT] Wait for SCO disconnected.")
        await dut_hfp_cb.wait_for_event(
            _HfpAgAudioStateChange(
                address=self.ref.address, state=_ScoState.DISCONNECTED
            ),
            timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
        )
        self.success_attempt_record(
            test_round=i + 1,
            latency=latency_seconds,
            latency_list=latency_list,
        )
      except (core.BaseBumbleError, AssertionError):
        self.logger.exception("Failed to make HFP connection")
      finally:
        await test_case_callbacks.aclose()
    self.record_sponge_data(
        repeat_times=_DEFAULT_REPEAT_TIMES, latency_list=latency_list
    )


if __name__ == "__main__":
  test_runner.main()
