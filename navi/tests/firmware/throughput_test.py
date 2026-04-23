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

import asyncio
import logging

from bumble import core
from bumble import gatt
from bumble import gatt_client as gatt_client_module
from bumble import gatt_server
from bumble import hci
from bumble import host
from bumble import l2cap
from bumble import pairing
from bumble import rfcomm
from mobly import test_runner
from typing_extensions import override

from navi.tests import navi_test_base
from navi.tests.benchmark import performance_tool
from navi.tests.firmware import test_base

_PairingDelegate = pairing.PairingDelegate

_RX_THRESHOLD = 6
_DEFAULT_STEP_TIMEOUT_SECONDS = 10.0
_TRANSMISSION_TIMEOUT_SECONDS = 180.0
_BUMBLE_SPAM_MODULES = (
    l2cap,
    rfcomm,
    host,
    hci,
    gatt,
    gatt_client_module,
    gatt_server,
)


class ThroughputTest(test_base.DualDeviceTestBase):
  """Tests throughput of different transport.

  Note that the performance could be affected a lot by the HCI throughput and
  latency on Bumble. For example, running this test on a Cloudtop with Pontis
  might lead to lower bandwidth in comparison to running on a local machine.
  """

  @override
  async def async_setup_class(self) -> None:
    await super().async_setup_class()
    # Disable logging of bumble modules to avoid log spam.
    for module in _BUMBLE_SPAM_MODULES:
      module.logger.setLevel(logging.INFO)

  @override
  async def async_teardown_class(self) -> None:
    await super().async_teardown_class()
    # Re-enable logging of bumble modules.
    for module in _BUMBLE_SPAM_MODULES:
      module.logger.setLevel(logging.DEBUG)

  @override
  async def async_setup_test(self) -> None:
    await super().async_setup_test()

    # Using highest authentication level to allow secure sockets.
    self.ref.device.pairing_config_factory = lambda _: pairing.PairingConfig(
        delegate=_PairingDelegate(
            io_capability=(
                _PairingDelegate.IoCapability.DISPLAY_OUTPUT_AND_YES_NO_INPUT
            )
        )
    )

  @navi_test_base.retry(2)
  async def test_rfcomm(self) -> None:
    """Tests RFCOMM throughput."""

    connection = await self.create_connection(
        self.dut.device,
        self.ref.device,
        core.BT_BR_EDR_TRANSPORT,
    )

    ref_accept_future: asyncio.Future[rfcomm.DLC] = (
        asyncio.get_running_loop().create_future()
    )
    channel = rfcomm.Server(self.ref.device).listen(
        acceptor=ref_accept_future.set_result
    )
    self.logger.info("[REF] Listen RFCOMM on channel %d.", channel)

    self.logger.info("[DUT] Connect RFCOMM channel to REF.")
    rfcomm_multiplexer = await rfcomm.Client(connection[0]).start()
    async with self.assert_not_timeout(_DEFAULT_STEP_TIMEOUT_SECONDS):
      ref_dut_dlc, dut_ref_dlc = await asyncio.gather(
          ref_accept_future,
          rfcomm_multiplexer.open_dlc(channel)
      )

    # Store received SDUs in queue.
    ref_sdu_rx_queue = asyncio.Queue[bytes]()
    ref_dut_dlc.sink = ref_sdu_rx_queue.put_nowait
    # Set the threshold to 6 to avoid running out of buffer.
    ref_dut_dlc.rx_credits_threshold = _RX_THRESHOLD
    total_bytes = 4 * 1024 * 1024  # 4 MB

    async def ref_rx_task():
      bytes_received = 0
      while bytes_received < total_bytes:
        bytes_received += len(await ref_sdu_rx_queue.get())

    self.logger.info("Start sending data from DUT to REF")
    with performance_tool.Stopwatch() as tx_stopwatch:
      async with self.assert_not_timeout(_TRANSMISSION_TIMEOUT_SECONDS):
        dut_ref_dlc.write(bytes(total_bytes))
        await ref_rx_task()

    dut_sdu_rx_queue = asyncio.Queue[bytes]()
    dut_ref_dlc.sink = dut_sdu_rx_queue.put_nowait
    # Set the threshold to 6 to avoid running out of buffer.
    dut_ref_dlc.rx_credits_threshold = _RX_THRESHOLD

    async def dut_rx_task():
      bytes_received = 0
      while bytes_received < total_bytes:
        bytes_received += len(await dut_sdu_rx_queue.get())

    self.logger.info("Start sending data from REF to DUT")
    with performance_tool.Stopwatch() as rx_stopwatch:
      async with self.assert_not_timeout(_TRANSMISSION_TIMEOUT_SECONDS):
        ref_dut_dlc.write(bytes(total_bytes))
        await dut_rx_task()

    tx_throughput = total_bytes / (tx_stopwatch.elapsed_time).total_seconds()
    rx_throughput = total_bytes / (rx_stopwatch.elapsed_time).total_seconds()
    self.logger.info("Tx Throughput: %.2f KB/s", tx_throughput / 1024)
    self.logger.info("Rx Throughput: %.2f KB/s", rx_throughput / 1024)
    self.record_data(
        navi_test_base.RecordData(
            test_name=self.current_test_info.name,
            properties={
                "tx_throughput_bytes_per_second": tx_throughput,
                "rx_throughput_bytes_per_second": rx_throughput,
            },
        )
    )


if __name__ == "__main__":
  test_runner.main()
