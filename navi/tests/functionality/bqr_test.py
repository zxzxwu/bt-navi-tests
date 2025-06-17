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

"""Tests for Bluetooth Quality Report."""

import enum
from unittest import mock

from bumble import core
from bumble import hci
from mobly import test_runner
from mobly import signals
from typing_extensions import override

from navi.tests import navi_test_base
from navi.utils import android_constants
from navi.utils import bl4a_api


_DEFAULT_STEP_TIMEOUT_SECONDS = 5.0
_MASKED_ADDRESS = "FF:FF:FF:FF:FF:FF"


class BqrEventMaskBitIndex(enum.IntFlag):
  """BQR event mask bit index."""
  APPROACH_LSTO = 1 << 1
  RF_STATS = 1 << 8


class BluetoothQualityReportTest(navi_test_base.TwoDevicesTestBase):
  """Tests Bluetooth Quality Report."""
  bqr_event_mask: int

  @override
  async def async_setup_class(self) -> None:
    await super().async_setup_class()
    bqr_event_mask_str = self.dut.getprop("persist.bluetooth.bqr.event_mask")
    if not bqr_event_mask_str:
      raise signals.TestAbortClass("BQR is not enabled on DUT.")
    self.bqr_event_mask = int(bqr_event_mask_str)

  async def test_approach_lsto_classic_connection(self) -> None:
    """Tests classic connection approach LSTO."""

    bqr_cb = self.dut.bl4a.register_callback(bl4a_api.Module.BQR)
    adapter_cb = self.dut.bl4a.register_callback(bl4a_api.Module.ADAPTER)
    self.test_case_context.push(bqr_cb)
    self.test_case_context.push(adapter_cb)

    self.logger.info("[REF] Connect to DUT.")
    ref_dut_acl = await self.ref.device.connect(
        self.dut.address,
        transport=core.PhysicalTransport.BR_EDR,
        timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
    )
    await adapter_cb.wait_for_event(
        bl4a_api.AclConnected(
            address=self.ref.address,
            transport=android_constants.Transport.CLASSIC,
        )
    )

    self.logger.info("[REF] Disconnect to trigger LSTO.")
    # Reason must be power off, or else LSTO will not be triggered.
    await ref_dut_acl.disconnect(
        reason=hci.HCI_REMOTE_DEVICE_TERMINATED_CONNECTION_DUE_TO_POWER_OFF_ERROR
    )

    if self.bqr_event_mask & BqrEventMaskBitIndex.APPROACH_LSTO:
      self.logger.info("[DUT] Wait for BQR event: APPROACH_LSTO.")
      await bqr_cb.wait_for_event(
          bl4a_api.BluetoothQualityReportReady(
              device=self.ref.address,
              quality_report_id=android_constants.BluetoothQualityReportId.APPROACH_LSTO,
              status=0,
              common=mock.ANY,
          ),
          timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
      )
    if self.bqr_event_mask & BqrEventMaskBitIndex.RF_STATS:
      self.logger.info("[DUT] Wait for BQR event: RF_STATS.")
      await bqr_cb.wait_for_event(
          bl4a_api.BluetoothQualityReportReady(
              device=_MASKED_ADDRESS,
              quality_report_id=android_constants.BluetoothQualityReportId.RF_STATS,
              status=0,
              common=mock.ANY,
          ),
          timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
      )

  async def test_energy_monitoring_when_power_unplug(self) -> None:
    """Tests power unplug will trigger energy monitoring."""

    if int(self.dut.getprop("ro.build.version.sdk")) < 36:
      self.skipTest(
          "Energy monitor event is not supported before SDK API level: 36."
      )

    bqr_cb = self.dut.bl4a.register_callback(bl4a_api.Module.BQR)
    self.test_case_context.push(bqr_cb)

    self.logger.info("[DUT] Set battery unplug and battery level to low.")
    self.dut.shell("cmd battery unplug")
    self.dut.shell("cmd battery set level 9")
    self.test_case_context.callback(lambda: self.dut.shell("cmd battery reset"))

    self.logger.info("[DUT] Wait for BQR event.")
    await bqr_cb.wait_for_event(
        bl4a_api.BluetoothQualityReportReady(
            device=_MASKED_ADDRESS,
            quality_report_id=android_constants.BluetoothQualityReportId.ENERGY_MONITOR,
            status=0,
            common=mock.ANY,
        ),
        timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
    )

if __name__ == "__main__":
  test_runner.main()
