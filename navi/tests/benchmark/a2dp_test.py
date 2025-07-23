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

import statistics

from bumble import core
from mobly import test_runner

from navi.bumble_ext import a2dp as a2dp_ext
from navi.tests import navi_test_base
from navi.tests.benchmark import performance_tool
from navi.utils import android_constants
from navi.utils import bl4a_api


_A2DP_SERVICE_RECORD_HANDLE = 1
_DEFAULT_REPEAT_TIMES = 30
_PROPERTY_CODEC_PRIORITY = "bluetooth.a2dp.source.%s_priority.config"
_VALUE_CODEC_DISABLED = -1
_DEFAULT_TIMEOUT_SECONDS = 10.0

_Callback = bl4a_api.CallbackHandler
_A2dpCodec = a2dp_ext.A2dpCodec


class A2dpTest(navi_test_base.TwoDevicesTestBase):

  async def pair_and_connect(self) -> None:
    """Tests A2DP connection establishment right after a pairing session."""
    with self.dut.bl4a.register_callback(bl4a_api.Module.A2DP) as dut_cb:
      a2dp_ext.setup_sink_server(
          self.ref.device,
          [a2dp_ext.A2dpCodec.SBC.get_default_capabilities()],
          _A2DP_SERVICE_RECORD_HANDLE,
      )
      await self.classic_connect_and_pair()
      await dut_cb.wait_for_event(
          bl4a_api.ProfileConnectionStateChanged(
              self.ref.address,
              state=android_constants.ConnectionState.CONNECTED,
          )
      )

  async def test_a2dp_connection_outgoing(self) -> None:
    """Test make outgoing A2DP connections."""
    success_count = 0
    latency_list = list[float]()
    await self.pair_and_connect()
    await performance_tool.terminate_connection_from_ref(self.dut, self.ref)
    for i in range(_DEFAULT_REPEAT_TIMES):
      try:
        with self.dut.bl4a.register_callback(bl4a_api.Module.A2DP) as dut_cb:
          self.logger.info("[DUT] Reconnect.")
          with performance_tool.Stopwatch() as stop_watch:
            self.dut.bt.connect(self.ref.address)
            self.logger.info("[DUT] Wait for A2DP connected.")
            await dut_cb.wait_for_event(
                bl4a_api.ProfileActiveDeviceChanged(self.ref.address),
                timeout=_DEFAULT_TIMEOUT_SECONDS,
            )
          latency_seconds = stop_watch.elapsed_time.total_seconds()
          self.logger.info(
              "Success connection in %.2f seconds", latency_seconds
          )
          self.logger.info("Test%d Success", i + 1)
          latency_list.append(latency_seconds)
        success_count += 1
      except (core.BaseBumbleError, AssertionError):
        self.logger.exception("Failed to make A2DP connection")
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
