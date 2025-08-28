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

from bumble import core
from bumble import hci
from mobly import test_runner

from navi.tests.benchmark import performance_tool
from navi.tests.benchmark import test_base
from navi.utils import android_constants
from navi.utils import bl4a_api

_DEFAULT_REPEAT_TIMES = 100
_ADVERTISING_INTERVAL_MIN = 20
_SETUP_TIMEOUT_SEC = 10.0

_Callback = bl4a_api.CallbackHandler
_OwnAddressType = hci.OwnAddressType


class LeGapTest(test_base.PerformanceTestBase):

  async def test_le_connection_outgoing(self) -> None:
    """Test make outgoing LE connections."""
    latency_list = list[float]()
    for i in range(_DEFAULT_REPEAT_TIMES):
      try:
        await self.ref.device.start_advertising(
            own_address_type=hci.OwnAddressType.RANDOM,
            auto_restart=False,
            advertising_interval_min=_ADVERTISING_INTERVAL_MIN,
            advertising_interval_max=_ADVERTISING_INTERVAL_MIN,
        )
        with performance_tool.Stopwatch() as stop_watch:
          client = await self.dut.bl4a.connect_gatt_client(
              self.ref.random_address,
              transport=android_constants.Transport.LE,
              address_type=android_constants.AddressTypeStatus.RANDOM,
              retry_count=0,
          )
        latency_seconds = stop_watch.elapsed_time.total_seconds()
        await client.disconnect()
        client.close()
        self.success_attempt_record(
            test_round=i + 1,
            latency=latency_seconds,
            latency_list=latency_list,
        )
      except (core.BaseBumbleError, AssertionError):
        self.logger.exception("Failed to make LE connection")
      finally:
        await performance_tool.cleanup_connections(self.dut, self.ref)
    self.record_sponge_data(
        repeat_times=_DEFAULT_REPEAT_TIMES, latency_list=latency_list
    )

  async def test_le_connection_incoming(self) -> None:
    """Test make incoming LE connections."""
    latency_list = list[float]()
    for i in range(_DEFAULT_REPEAT_TIMES):
      try:
        self.logger.info("[DUT] Start advertising")
        await self.dut.bl4a.start_legacy_advertiser(
            bl4a_api.LegacyAdvertiseSettings(
                own_address_type=_OwnAddressType.PUBLIC
            ),
        )
        with self.dut.bl4a.register_callback(bl4a_api.Module.ADAPTER) as dut_cb:
          with performance_tool.Stopwatch() as stop_watch:
            self.logger.info("[REF] Connect GATT")
            ref_dut_acl = await self.ref.device.connect(
                f"{self.dut.address}/P",
                core.BT_LE_TRANSPORT,
                own_address_type=_OwnAddressType.PUBLIC,
            )
            await ref_dut_acl.get_remote_le_features()
            self.logger.info("[DUT] Wait for LE-ACL connected")
            await dut_cb.wait_for_event(
                event=bl4a_api.AclConnected(
                    address=self.ref.address,
                    transport=android_constants.Transport.LE,
                ),
            )
          latency_seconds = stop_watch.elapsed_time.total_seconds()
          self.success_attempt_record(
              test_round=i + 1,
              latency=latency_seconds,
              latency_list=latency_list,
          )
          self.logger.info("[REF] Disconnect")
          await ref_dut_acl.disconnect()
          self.logger.info("[DUT] Wait for LE-ACL disconnected")
          await dut_cb.wait_for_event(
              bl4a_api.AclDisconnected(
                  address=self.ref.address,
                  transport=android_constants.Transport.LE,
              ),
          )
      except (core.BaseBumbleError, AssertionError):
        self.logger.exception("Failed to make LE connection")
      finally:
        await performance_tool.cleanup_connections(self.dut, self.ref)
    self.record_sponge_data(
        repeat_times=_DEFAULT_REPEAT_TIMES, latency_list=latency_list
    )


if __name__ == "__main__":
  test_runner.main()
