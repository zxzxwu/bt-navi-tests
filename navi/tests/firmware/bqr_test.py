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

from __future__ import annotations

import asyncio

from bumble import company_ids
from bumble import core
from bumble import hci
from mobly import test_runner
from typing_extensions import override

from navi.bumble_ext import bqr
from navi.tests import navi_test_base
from navi.tests.firmware import test_base


_DEFAULT_TIMEOUT = 10.0


# Register the Bluetooth Quality Report Subevent factory.
hci.HCI_Event.add_vendor_factory(bqr.BluetoothQualityReportEvent.try_from_bytes)


class BqrTest(test_base.DualDeviceTestBase):
  """Test Class for Bluetooth Quality Report (BQR) tests.

  This class provides tests that verify the BQR feature of the device.

  Attributes:
    _bqr_version: The BQR version supported by the device.
    _manufacturer_name: The manufacturer name of the Bluetooth Firmware.
  """

  _bqr_version: tuple[int, int] = (0, 0)
  _manufacturer_name: str = 'Unknown'

  @override
  async def async_setup_class(self) -> None:
    await super().async_setup_class()
    await self._get_firmware_manufacturer_name()
    await self._device_bqr_version_verify()

  async def _get_firmware_manufacturer_name(self) -> None:
    """get the manufacturer name."""
    if self._manufacturer_name != 'Unknown':
      return

    response = await self.dut.device.send_sync_command(
        hci.HCI_Read_Local_Version_Information_Command()
    )

    self.logger.info('send_firmware_version_info_command:')
    self.logger.info('status: %s', response.status)
    self.logger.info(
        'company_identifier: %s',
        response.company_identifier,
    )

    self._manufacturer_name = company_ids.COMPANY_IDENTIFIERS.get(
        response.company_identifier, 'Unknown'
    )

    self.logger.info('manufacturer_name: %s', self._manufacturer_name)

  async def _device_bqr_version_verify(self) -> None:
    """Verifies the BQR version of the device."""
    self.logger.info('_device_bqr_version_verify')
    response = await self.dut.device.send_sync_command(
        bqr.HciBqrLeGetVendorCapabilitiesCommand()
    )

    self._bqr_version = response.version_supported
    self.logger.info(
        '_device_bqr_version_verify _bqr_version: %s',
        self._bqr_version,
    )

  @navi_test_base.named_parameterized(
      quality_monitoring_mode_one_time_query=dict(
          bqr_eventmask=bqr.BqrQualityEventMask.QUALITY_MONITORING_MODE,
          expected_report_id=bqr.QualityReportId.QUALITY_REPORTING_ON_THE_MONITORING_MODE,
          bqr_report_action=bqr.BqrReportAction.ONE_TIME_QUERY,
          bqr_minimum_report_interval=0,
          event_received_times=1,
          connection_required=True,
          min_bqr_version=bqr.Version.V1,
      ),
      quality_monitoring_mode_periodically=dict(
          bqr_eventmask=bqr.BqrQualityEventMask.QUALITY_MONITORING_MODE,
          expected_report_id=bqr.QualityReportId.QUALITY_REPORTING_ON_THE_MONITORING_MODE,
          bqr_report_action=bqr.BqrReportAction.ADD,
          bqr_minimum_report_interval=1000,
          event_received_times=5,
          connection_required=True,
          min_bqr_version=bqr.Version.V1,
      ),
      energy_monitoring_mode_one_time_query=dict(
          bqr_eventmask=bqr.BqrQualityEventMask.ENERGY_MONITORING_MODE,
          expected_report_id=bqr.QualityReportId.ENERGY_MONITORING_EVENT,
          bqr_report_action=bqr.BqrReportAction.ONE_TIME_QUERY,
          bqr_minimum_report_interval=0,
          event_received_times=1,
          connection_required=True,
          min_bqr_version=bqr.Version.V3,
      ),
      energy_monitoring_mode_periodically=dict(
          bqr_eventmask=bqr.BqrQualityEventMask.ENERGY_MONITORING_MODE,
          expected_report_id=bqr.QualityReportId.ENERGY_MONITORING_EVENT,
          bqr_report_action=bqr.BqrReportAction.ADD,
          bqr_minimum_report_interval=1000,
          event_received_times=5,
          connection_required=True,
          min_bqr_version=bqr.Version.V3,
      ),
      advance_rf_status_one_time_query=dict(
          bqr_eventmask=bqr.BqrQualityEventMask.ADV_RF_STATS_TRIGGER,
          expected_report_id=bqr.QualityReportId.ADV_RF_STATUS_BY_TRIGGER,
          bqr_report_action=bqr.BqrReportAction.ONE_TIME_QUERY,
          bqr_minimum_report_interval=0,
          event_received_times=1,
          connection_required=True,
          min_bqr_version=bqr.Version.V7,
      ),
      # TODO: The test case is blocked due to the AOSP HAL hijack
      # ADV_RF_STATUS_BY_MONITOR Vendor event.
      # advance_rf_status_periodically=dict(
      #     bqr_eventmask=bqr.BqrQualityEventMask.ADV_RF_STATS_PERIODIC,
      #     expected_report_id=bqr.QualityReportId.ADV_RF_STATUS_BY_MONITOR,
      #     bqr_report_action=bqr.BqrReportAction.ADD,
      #     bqr_minimum_report_interval=1000,
      #     event_received_times=5,
      #     connection_required=True,
      #     min_bqr_version=bqr.Version.V6,
      # ),
  )
  async def test_receive(
      self,
      bqr_eventmask: int,
      expected_report_id: bqr.QualityReportId,
      bqr_report_action: bqr.BqrReportAction,
      bqr_minimum_report_interval: int,
      event_received_times: int,
      connection_required: bool,
      min_bqr_version: bqr.Version = bqr.Version.V1,
  ) -> None:
    """Tests the BQR function.

    Args:
      bqr_eventmask: The bitmask specifying which standard quality events should
        trigger a report.
      expected_report_id: The specific BQR QualityReportId to look for.
      bqr_report_action: The BQR reporting action.
      bqr_minimum_report_interval: The minimum time interval between consecutive
        quality reports.
      event_received_times: The number of expected vendor events received.
      connection_required: The flag to verify the connection before sending the
        command.
      min_bqr_version: The minimum BQR version supported by the device.
    """

    if self._bqr_version < bqr.min_supported_vendor_version(min_bqr_version):
      self.skipTest(
          f'BQR {min_bqr_version.name}+ is not supported on this device.'
      )
    if connection_required:
      await self.create_connection(
          self.dut.device, self.ref.device, core.BT_BR_EDR_TRANSPORT
      )

    pending_event_queue = asyncio.Queue[bqr.BluetoothQualityReportEvent]()

    def on_bqr_event(event: bqr.BluetoothQualityReportEvent):
      if event.quality_report_id == expected_report_id:
        pending_event_queue.put_nowait(event)

    setattr(
        self.dut.device.host,
        f'on_{bqr.BluetoothQualityReportEvent.subclasses[expected_report_id].name.lower()}',
        on_bqr_event,
    )

    self.logger.info('Send BQR command...')
    await self.dut.device.send_sync_command(
        bqr.HciBqrBluetoothQualityReportCommand(
            bqr_report_action=bqr_report_action,
            bqr_quality_event_mask=bqr_eventmask,
            bqr_minimum_report_interval=bqr_minimum_report_interval,
            bqr_vendor_specific_quality_event_mask=0,
            bqr_vendor_specific_trace_mask=0,
            report_interval_multiple=0,
        ),
    )

    # --- Wait for Bluetooth Quality Report Vendor Event ---
    self.logger.info(
        'Waiting for BQR vendor event (ID: %r)...', expected_report_id
    )
    timeout_message = (
        f'Waiting for vendor event (ID: {expected_report_id.name})'
        f' {event_received_times} times within the'
        f' {_DEFAULT_TIMEOUT}-seconds.'
    )
    async with self.assert_not_timeout(_DEFAULT_TIMEOUT, timeout_message):
      # Wait for an item to appear in the queue inside the context manager
      for i in range(event_received_times):
        await pending_event_queue.get()
        # This code runs only if the await completed within the timeout
        self.logger.info(
            'Received matching vendor event %d times via queue.', i + 1
        )

  async def test_device_bqr_delete_command_function(self) -> None:
    """Tests the BQR function of Delete Command.

    Test steps:
      1. Send BQR command with quality monitoring mode.
      2. Received Command Complete event and verify the status.
      3. Send BQR command with delete quality monitoring mode.
      4. Received Command Complete event and verify no more quality monitoring
      mode related vendor event.
    """
    if self._bqr_version < bqr.min_supported_vendor_version(bqr.Version.V1):
      self.skipTest('BQR v1+ is not supported on this device.')

    bqr_eventmask = bqr.BqrQualityEventMask.QUALITY_MONITORING_MODE
    expected_report_id = (
        bqr.QualityReportId.QUALITY_REPORTING_ON_THE_MONITORING_MODE
    )
    bqr_report_action = bqr.BqrReportAction.ADD  # Periodically
    bqr_minimum_report_interval = 1000  # 1000 ms
    event_received_times = 5  # 5 times events should be received
    await self.test_receive(
        bqr_eventmask,
        expected_report_id,
        bqr_report_action,
        bqr_minimum_report_interval,
        event_received_times,
        connection_required=True,
        min_bqr_version=bqr.Version.V1,
    )

    # Delete the BQR reporting mode and verify the status.
    pending_event_queue = asyncio.Queue[hci.HCI_Event]()

    await self.dut.device.send_sync_command(
        bqr.HciBqrBluetoothQualityReportCommand(
            bqr_report_action=bqr.BqrReportAction.DELETE,  # Delete Command
            bqr_quality_event_mask=bqr_eventmask,
            bqr_minimum_report_interval=0,
            bqr_vendor_specific_quality_event_mask=0,
            bqr_vendor_specific_trace_mask=0,
            report_interval_multiple=0,
        ),
    )

    def on_bqr_event(event: bqr.BluetoothQualityReportEvent):
      if event.quality_report_id == expected_report_id:
        pending_event_queue.put_nowait(event)

    setattr(
        self.dut.device.host,
        f'on_{bqr.BluetoothQualityReportEvent.subclasses[expected_report_id].name.lower()}',
        on_bqr_event,
    )

    # --- Verify that Bluetooth Quality Report Vendor Event Deleted ---
    self.logger.info(
        'Verify for BQR vendor event after delete command (ID: %r)...',
        expected_report_id,
    )
    async with self.assert_timeout(
        _DEFAULT_TIMEOUT, 'Received unexpected vendor event', with_log=False
    ):
      # Wait for an item to appear in the queue inside the context manager
      event = await pending_event_queue.get()
      self.logger.info('Received vendor event: %s', event)


if __name__ == '__main__':
  test_runner.main()
