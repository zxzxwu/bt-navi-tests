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

"""Extended BQR implementation from Bumble."""

from __future__ import annotations

from collections.abc import Callable
import dataclasses
import enum
from typing import ClassVar, TypeVar

from bumble import hci


class Version(enum.IntEnum):
  """BQR version enum for firmware local info support."""

  V1 = 256
  V2 = 257
  V3_4 = 258
  V5 = 259
  V6 = 260
  V7 = 261


# Define an Enum for BQR_Report_Action
class BqrReportAction(enum.IntEnum):
  """Enumeration for the BQR_Report_Action parameter.

  see
  https://source.android.com/docs/core/connect/bluetooth/hci_requirements#bluetooth-quality-report-command.
  """

  ADD = 0x00  # Add configuration or start reporting based on context
  DELETE = 0x01  # Delete configuration or stop reporting based on context
  CLEAR = 0x02  # Clear existing BQR configurations or status
  ONE_TIME_QUERY = 0x03  # Perform a one-time query for BQR information


# Define an Enum for BQR_Quality_Event_Mask
class BqrQualityEventMask(enum.IntFlag):
  """Represents the BQR_Quality_Event_Mask as a set of controllable flags.

  see
  https://source.android.com/docs/core/connect/bluetooth/hci_requirements#bluetooth-quality-report-command.
  .

  Provides named access to each bit's meaning. Use bitwise OR (|) to combine
  flags. Access .value to get the integer result. Defaults to 0 (no flags set)
  if initialized with 0 or empty.
  """

  # Bit 0: Set to enable quality monitoring mode.
  QUALITY_MONITORING_MODE = 1 << 0
  # Bit 1: Set to enable Approaching LSTO event.(For ACL/(e)SCO/ISO)
  APPROACHING_LSTO = 1 << 1
  # Bit 2: Set to enable A2DP Audio Choppy event.
  A2DP_AUDIO_CHOPPY = 1 << 2
  # Bit 3: Set to enable (e)SCO Voice Choppy event.
  ESCO_VOICE_CHOPPY = 1 << 3
  # Bit 4: Set to enable Root inflammation event.
  ROOT_INFLAMMATION = 1 << 4
  # Bit 5: Set to enable Energy Monitoring mode.
  ENERGY_MONITORING_MODE = 1 << 5
  # Bit 6: Set to enable LE Audio Choppy event.
  LE_AUDIO_CHOPPY = 1 << 6
  # Bit 7: Set to enable Connect Fail event.
  CONNECT_FAIL = 1 << 7
  # Bit 8: Set to enable Advance RF Stats mode event trigger.
  ADV_RF_STATS_TRIGGER = 1 << 8
  # Bit 9: Set to enable Advance RF Stats periodically report.
  ADV_RF_STATS_PERIODIC = 1 << 9
  # Bit 10: Set to enable controller health monitoring mechanism event trigger.
  CTRL_HEALTH_TRIGGER = 1 << 10
  # Bit 11: Set to enable controller health monitoring mechanism
  # periodically report.
  CTRL_HEALTH_PERIODIC = 1 << 11
  # Bit 12: Set to enable LE Audio Broadcast Source event
  LE_AUDIO_BROADCAST_SRC = 1 << 12
  # Bit 13 ~ 14: Reserved. (No flag defined)
  # Bit 15: Set to enable Vendor Specific Quality event(s).
  VENDOR_SPECIFIC_QUALITY = 1 << 15
  # Bit 16: Set to enable LMP/LL message trace.
  LMP_LL_MESSAGE_TRACE = 1 << 16
  # Bit 17: Set to enable Bluetooth Multi-link/Coex scheduling trace.
  MULTILINK_COEX_SCHEDULING_TRACE = 1 << 17
  # Bit 18: Set to enable the Controller Debug Information mechanism.
  CONTROLLER_DEBUG_INFO = 1 << 18
  # Bit 19 ~ 30: Reserved. (No flags defined)
  # Bit 31: Set to enable Vendor Specific trace.
  VENDOR_SPECIFIC_TRACE = 1 << 31

  NONE = 0


# Define an Enum for Quality_Report_Id
class QualityReportId(enum.IntEnum):
  """Enumeration for the Quality_Report_Id parameter.

  See
  https://source.android.com/docs/core/connect/bluetooth/hci_requirements#bluetooth-quality-report-command.
  """

  QUALITY_REPORTING_ON_THE_MONITORING_MODE = 0x01  # Monitoring mode Id.
  APPROACHING_LSTO = 0x02  # Approaching LSTO Id.
  A2DP_AUDIO_CHOPPY = 0x03  # A2DP Audio Choppy Id.
  ESCO_VOICE_CHOPPY = 0x04  # (e)SCO Voice Choppy Id.
  ROOT_INFLAMMATION = 0x05  # Root inflammation Id.
  ENERGY_MONITORING_EVENT = 0x06  # Energy Monitoring event Id.
  LE_AUDIO_CHOPPY = 0x07  # LE audio choppy Id.
  CONNECT_FAIL = 0x08  # Connection fail Id.
  ADV_RF_STATUS_BY_TRIGGER = 0x09  # Advance RF Stats By Trigger
  ADV_RF_STATUS_BY_MONITOR = 0x0A  # Advance RF Stats By Monitor


@dataclasses.dataclass
class HciBqrLeGetVendorCapabilitiesCommandReturnParameters(
    hci.HCI_StatusReturnParameters
):
  """HCI BQR LE Get Vendor Capabilities Vendor Command Return Parameters.

  Attributes:
    le_capabilities_offset_0: The first part of the LE capabilities offset.
    version_supported: The version of the LE capabilities supported.
    le_capabilities_offset_1: The second part of the LE capabilities offset.
  """

  le_capabilities_offset_0: int = dataclasses.field(metadata=hci.metadata(8))
  version_supported: int = dataclasses.field(metadata=hci.metadata(2))
  le_capabilities_offset_1: int = dataclasses.field(metadata=hci.metadata(15))


@hci.HCI_SyncCommand.sync_command(
    HciBqrLeGetVendorCapabilitiesCommandReturnParameters
)
@dataclasses.dataclass
class HciBqrLeGetVendorCapabilitiesCommand(
    hci.HCI_SyncCommand[HciBqrLeGetVendorCapabilitiesCommandReturnParameters]
):
  """HCI BQR LE Get Vendor Capabilities Vendor Command.

  See
  https://source.android.com/docs/core/connect/bluetooth/hci_requirements#vendor-specific-capabilities.
  """

  op_code = hci.hci_vendor_command_op_code(0x153)
  name = 'HCI_BQR_LE_GET_VENDOR_CAPABILITIES_COMMAND'


@dataclasses.dataclass
class HciBqrBluetoothQualityReportCommandReturnParameters(
    hci.HCI_StatusReturnParameters
):
  """HCI BQR Bluetooth Quality Report Vendor Command Return Parameters.

  Attributes:
    current_quality_event_mask: The currently active standard quality event mask
      on the controller.
    current_vendor_specific_quality_event_mask: The currently active
      vendor-specific quality event mask on the controller.
    current_vendor_specific_trace_mask_1: The first part of the currently active
      vendor-specific trace mask (interpretation is vendor-specific).
    bqr_report_interval: The actual reporting interval currently configured in
      the controller.
  """

  current_quality_event_mask: int = dataclasses.field(metadata=hci.metadata(4))
  current_vendor_specific_quality_event_mask: int = dataclasses.field(
      metadata=hci.metadata(4)
  )
  current_vendor_specific_trace_mask_1: int = dataclasses.field(
      metadata=hci.metadata(4)
  )
  bqr_report_interval: int = dataclasses.field(metadata=hci.metadata(4))


@hci.HCI_SyncCommand.sync_command(
    HciBqrBluetoothQualityReportCommandReturnParameters
)
@dataclasses.dataclass
class HciBqrBluetoothQualityReportCommand(
    hci.HCI_SyncCommand[HciBqrBluetoothQualityReportCommandReturnParameters]
):
  """HCI BQR Bluetooth Quality Report Vendor Command.

  See
  https://source.android.com/docs/core/connect/bluetooth/hci_requirements#bluetooth-quality-report-command.

  Attributes:
    bqr_report_action: Controls the BQR reporting action.
    bqr_quality_event_mask: Bitmask specifying which standard quality events
      should trigger a report.
    bqr_minimum_report_interval: The minimum time interval between consecutive
      quality reports.
    bqr_vendor_specific_quality_event_mask: Bitmask specifying which
      vendor-specific quality events should trigger a report.
    bqr_vendor_specific_trace_mask: Bitmask for controlling vendor-specific
      tracing related to quality.
    report_interval_multiple: Multiplier for the minimum report interval for
      periodic reporting.
  """

  op_code = hci.hci_vendor_command_op_code(0x15E)
  name = 'HCI_BQR_BLUETOOTH_QUALITY_REPORT_COMMAND'

  bqr_report_action: int = dataclasses.field(metadata=hci.metadata(1))
  bqr_quality_event_mask: int = dataclasses.field(metadata=hci.metadata(4))
  bqr_minimum_report_interval: int = dataclasses.field(metadata=hci.metadata(2))
  bqr_vendor_specific_quality_event_mask: int = dataclasses.field(
      metadata=hci.metadata(4)
  )
  bqr_vendor_specific_trace_mask: int = dataclasses.field(
      metadata=hci.metadata(4)
  )
  report_interval_multiple: int = dataclasses.field(metadata=hci.metadata(4))


class BluetoothQualityReportEvent(hci.HCI_Event):
  """Bluetooth Quality Report Sub event."""

  SUBEVENT_CODE = 0x58
  event_code = hci.HCI_VENDOR_EVENT
  name = 'BLUETOOTH_QUALITY_REPORT_EVENT'
  quality_report_id: int
  subclasses: ClassVar[dict[int, type[BluetoothQualityReportEvent]]] = {}

  @classmethod
  def try_from_bytes(cls, data: bytes) -> BluetoothQualityReportEvent | None:
    """Creates a BluetoothQualityReportEvent from bytes."""
    if data[0] != cls.SUBEVENT_CODE:
      return None
    if subclass := cls.subclasses.get(data[1]):
      return subclass.from_parameters(data[1:])
    return None

  _BQR_EVENT = TypeVar('_BQR_EVENT', bound='BluetoothQualityReportEvent')

  @classmethod
  def subevent(
      cls, *quality_report_ids: QualityReportId
  ) -> Callable[[type[_BQR_EVENT]], type[_BQR_EVENT]]:
    """Returns a decorator for subclassing BluetoothQualityReportEvent."""

    _BQR_EVENT = TypeVar('_BQR_EVENT', bound='BluetoothQualityReportEvent')

    def decorator(subclass: type[_BQR_EVENT]) -> type[_BQR_EVENT]:
      for quality_report_id in quality_report_ids:
        subclass.subclasses[quality_report_id] = subclass
      # Filter out field from base class.
      subclass.fields = hci.HCI_Object.fields_from_dataclass(subclass)
      return subclass

    return decorator


@BluetoothQualityReportEvent.subevent(
    QualityReportId.QUALITY_REPORTING_ON_THE_MONITORING_MODE,
    QualityReportId.APPROACHING_LSTO,
    QualityReportId.A2DP_AUDIO_CHOPPY,
    QualityReportId.ESCO_VOICE_CHOPPY,
)
@dataclasses.dataclass
class BqrLinkQualityRelatedSubevent(BluetoothQualityReportEvent):
  """Link Quality related subevent."""

  name = 'BQR_LINK_QUALITY_RELATED_SUBEVENT'

  quality_report_id: int = dataclasses.field(metadata=hci.metadata(1))
  packet_types: int = dataclasses.field(metadata=hci.metadata(1))
  connection_handle: int = dataclasses.field(metadata=hci.metadata(2))
  connection_role: int = dataclasses.field(metadata=hci.metadata(1))
  tx_power_level: int = dataclasses.field(metadata=hci.metadata(1))
  rssi: int = dataclasses.field(metadata=hci.metadata(1))
  snr: int = dataclasses.field(metadata=hci.metadata(1))
  unused_afh_channel_count: int = dataclasses.field(metadata=hci.metadata(1))
  afh_select_unideal_channel_count: int = dataclasses.field(
      metadata=hci.metadata(1)
  )
  lsto: int = dataclasses.field(metadata=hci.metadata(2))
  connection_piconet_clock: int = dataclasses.field(metadata=hci.metadata(4))
  retransmission_count: int = dataclasses.field(metadata=hci.metadata(4))
  no_rx_count: int = dataclasses.field(metadata=hci.metadata(4))
  nak_count: int = dataclasses.field(metadata=hci.metadata(4))
  last_tx_ack_timestamp: int = dataclasses.field(metadata=hci.metadata(4))
  flow_off_count: int = dataclasses.field(metadata=hci.metadata(4))
  last_flow_on_timestamp: int = dataclasses.field(metadata=hci.metadata(4))
  buffer_overflow_bytes: int = dataclasses.field(metadata=hci.metadata(4))
  buffer_underflow_bytes: int = dataclasses.field(metadata=hci.metadata(4))
  bdaddr: int = dataclasses.field(metadata=hci.metadata(6))
  cal_failed_item_count: int = dataclasses.field(metadata=hci.metadata(1))
  tx_total_packets: int = dataclasses.field(metadata=hci.metadata(4))
  tx_unacked_packets: int = dataclasses.field(metadata=hci.metadata(4))
  tx_flushed_packets: int = dataclasses.field(metadata=hci.metadata(4))
  tx_last_subevent_packets: int = dataclasses.field(metadata=hci.metadata(4))
  crc_error_packets: int = dataclasses.field(metadata=hci.metadata(4))
  rx_duplicate_packets: int = dataclasses.field(metadata=hci.metadata(4))
  rx_unreceived_packets: int = dataclasses.field(metadata=hci.metadata(4))
  coex_info_mask: int = dataclasses.field(metadata=hci.metadata(2))
  vendor_specific_parameter: bytes = dataclasses.field(
      metadata=hci.metadata('*')
  )


@BluetoothQualityReportEvent.subevent(QualityReportId.ROOT_INFLAMMATION)
@dataclasses.dataclass
class BqrRootInflammationSubevent(BluetoothQualityReportEvent):
  """Root Inflammation related subevent."""

  name = 'BQR_ROOT_INFLAMMATION_SUBEVENT'

  quality_report_id: int = dataclasses.field(metadata=hci.metadata(1))
  error_code: int = dataclasses.field(metadata=hci.metadata(1))
  vendor_specific_error_code: int = dataclasses.field(metadata=hci.metadata(1))
  vendor_specific_parameter: bytes = dataclasses.field(
      metadata=hci.metadata('*')
  )


@BluetoothQualityReportEvent.subevent(QualityReportId.ENERGY_MONITORING_EVENT)
@dataclasses.dataclass
class BqrEnergyMonitorSubevent(BluetoothQualityReportEvent):
  """Energy Monitoring related subevent."""

  name = 'BQR_ENERGY_MONITOR_SUBEVENT'

  quality_report_id: int = dataclasses.field(metadata=hci.metadata(1))
  average_current_consumption: int = dataclasses.field(metadata=hci.metadata(2))
  idle_total_time_sleep: int = dataclasses.field(metadata=hci.metadata(4))
  idle_state_enter_count: int = dataclasses.field(metadata=hci.metadata(4))
  active_total_time: int = dataclasses.field(metadata=hci.metadata(4))
  active_state_enter_count: int = dataclasses.field(metadata=hci.metadata(4))
  br_rdr_tx_total_time: int = dataclasses.field(metadata=hci.metadata(4))
  br_rdr_tx_state_enter_count: int = dataclasses.field(metadata=hci.metadata(4))
  br_rdr_tx_average_power_level: int = dataclasses.field(
      metadata=hci.metadata(1)
  )
  br_rdr_rx_total_time: int = dataclasses.field(metadata=hci.metadata(4))
  br_rdr_rx_state_enter_count: int = dataclasses.field(metadata=hci.metadata(4))
  le_tx_total_time: int = dataclasses.field(metadata=hci.metadata(4))
  le_tx_state_enter_count: int = dataclasses.field(metadata=hci.metadata(4))
  le_tx_average_power_level: int = dataclasses.field(metadata=hci.metadata(1))
  le_rx_total_time: int = dataclasses.field(metadata=hci.metadata(4))
  le_rx_state_enter_count: int = dataclasses.field(metadata=hci.metadata(4))
  report_time_duration_total_time: int = dataclasses.field(
      metadata=hci.metadata(4)
  )
  rx_active_one_chain_time: int = dataclasses.field(metadata=hci.metadata(4))
  rx_active_two_chain_time: int = dataclasses.field(metadata=hci.metadata(4))
  tx_ipa_active_one_chain_time: int = dataclasses.field(
      metadata=hci.metadata(4)
  )
  tx_ipa_active_two_chain_time: int = dataclasses.field(
      metadata=hci.metadata(4)
  )
  tx_epa_active_one_chain_time: int = dataclasses.field(
      metadata=hci.metadata(4)
  )
  tx_epa_active_two_chain_time: int = dataclasses.field(
      metadata=hci.metadata(4)
  )
  bredr_rx_active_scan_total_time: int = dataclasses.field(
      metadata=hci.metadata(4)
  )
  le_rx_active_scan_total_time: int = dataclasses.field(
      metadata=hci.metadata(4)
  )


@BluetoothQualityReportEvent.subevent(
    QualityReportId.ADV_RF_STATUS_BY_TRIGGER,
    QualityReportId.ADV_RF_STATUS_BY_MONITOR,
)
@dataclasses.dataclass
class BqrAdvancedRfStatsEvent(BluetoothQualityReportEvent):
  """Advanced RF Stats event."""

  name = 'BQR_ADVANCED_RF_STATS_EVENT'

  quality_report_id: int = dataclasses.field(metadata=hci.metadata(1))
  extension_info: int = dataclasses.field(metadata=hci.metadata(1))
  report_time_period: int = dataclasses.field(metadata=hci.metadata(4))
  tx_power_ipa_bf: int = dataclasses.field(metadata=hci.metadata(4))
  tx_power_epa_bf: int = dataclasses.field(metadata=hci.metadata(4))
  tx_power_ipa_div: int = dataclasses.field(metadata=hci.metadata(4))
  tx_power_epa_div: int = dataclasses.field(metadata=hci.metadata(4))
  rssi_chain_50: int = dataclasses.field(metadata=hci.metadata(4))
  rssi_chain_50_55: int = dataclasses.field(metadata=hci.metadata(4))
  rssi_chain_55_60: int = dataclasses.field(metadata=hci.metadata(4))
  rssi_chain_60_65: int = dataclasses.field(metadata=hci.metadata(4))
  rssi_chain_65_70: int = dataclasses.field(metadata=hci.metadata(4))
  rssi_chain_70_75: int = dataclasses.field(metadata=hci.metadata(4))
  rssi_chain_75_80: int = dataclasses.field(metadata=hci.metadata(4))
  rssi_chain_80_85: int = dataclasses.field(metadata=hci.metadata(4))
  rssi_chain_85_90: int = dataclasses.field(metadata=hci.metadata(4))
  rssi_chain_90: int = dataclasses.field(metadata=hci.metadata(4))
  rssi_delta_2: int = dataclasses.field(metadata=hci.metadata(4))
  rssi_delta_2_5: int = dataclasses.field(metadata=hci.metadata(4))
  rssi_delta_5_8: int = dataclasses.field(metadata=hci.metadata(4))
  rssi_delta_8_11: int = dataclasses.field(metadata=hci.metadata(4))
  rssi_delta_11: int = dataclasses.field(metadata=hci.metadata(4))
  antenna_switch_count: int = dataclasses.field(metadata=hci.metadata(4))
  retx_ipa_bf: int = dataclasses.field(metadata=hci.metadata(4))
  retx_epa_bf: int = dataclasses.field(metadata=hci.metadata(4))
  retx_ipa_div: int = dataclasses.field(metadata=hci.metadata(4))
  retx_epa_div: int = dataclasses.field(metadata=hci.metadata(4))
  channel_count_good: int = dataclasses.field(metadata=hci.metadata(1))
  channel_count_ok: int = dataclasses.field(metadata=hci.metadata(1))
  channel_count_bad: int = dataclasses.field(metadata=hci.metadata(1))
  channel_count_verybad: int = dataclasses.field(metadata=hci.metadata(1))
  tx_buffer_queue_count: int = dataclasses.field(metadata=hci.metadata(4))
