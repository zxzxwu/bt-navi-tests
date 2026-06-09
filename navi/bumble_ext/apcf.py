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

"""Advertising Packet Content Filter (APCF) commands.

See
https://source.android.com/docs/core/connect/bluetooth/hci_requirements#advertising-packet-content-filter.
"""

from __future__ import annotations
import dataclasses
import enum
from typing import TypeVar
from bumble import hci

_APCF_OCF = 0x0157
APCF_OPCODE = hci.hci_vendor_command_op_code(_APCF_OCF)


class ApcfOpcode(enum.IntEnum):
  ENABLE = 0x00
  SET_FILTERING_PARAMETERS = 0x01
  BROADCASTER_ADDRESS = 0x02
  SERVICE_UUID = 0x03
  SERVICE_SOLICITATION_UUID = 0x04
  LOCAL_NAME = 0x05
  MANUFACTURER_DATA = 0x06
  SERVICE_DATA = 0x07
  TRANSPORT_DISCOVERY_SERVICE = 0x08
  AD_TYPE_FILTER = 0x09
  READ_EXTENDED_FEATURES = 0xFF


class ApcfAction(enum.IntEnum):
  ADD = 0x00
  DELETE = 0x01
  CLEAR = 0x02


class ApcfFeatureSelection(enum.IntFlag):
  BROADCAST_ADDRESS = 1 << 0
  SERVICE_DATA_CHANGE = 1 << 1
  SERVICE_UUID = 1 << 2
  SERVICE_SOLICITATION_UUID = 1 << 3
  LOCAL_NAME = 1 << 4
  MANUFACTURER_DATA = 1 << 5
  SERVICE_DATA = 1 << 6
  TRANSPORT_DISCOVERY_SERVICE = 1 << 7
  AD_TYPE = 1 << 8


class ApcfFilterLogicType(enum.IntEnum):
  OR = 0x00
  AND = 0x01


# Return Parameters
@dataclasses.dataclass
class HciApcfEnableCommandReturnParameters(hci.HCI_StatusReturnParameters):
  apcf_opcode: int = dataclasses.field(metadata=hci.metadata(1))
  apcf_enable: int = dataclasses.field(metadata=hci.metadata(1))


@dataclasses.dataclass
class HciApcfCommandReturnParameters(hci.HCI_StatusReturnParameters):
  apcf_opcode: int = dataclasses.field(metadata=hci.metadata(1))
  apcf_action: int = dataclasses.field(metadata=hci.metadata(1))
  apcf_available_spaces: int = dataclasses.field(metadata=hci.metadata(1))


@dataclasses.dataclass
class HciApcfReadExtendedFeaturesCommandReturnParameters(
    hci.HCI_StatusReturnParameters
):
  apcf_opcode: int = dataclasses.field(metadata=hci.metadata(1))
  apcf_extended_features: int = dataclasses.field(metadata=hci.metadata(2))


# Base Command / Dispatcher
@hci.HCI_Command.command
class HciApcfCommand(hci.HCI_SyncCommand[hci.HCI_ReturnParameters]):
  """Base command for APCF vendor commands."""

  op_code = APCF_OPCODE
  name = 'HCI_APCF_COMMAND'

  @classmethod
  def from_parameters(cls, parameters: bytes) -> hci.HCI_Command:
    apcf_opcode = parameters[0]
    subclass = _APCF_COMMAND_CLASSES.get(apcf_opcode)
    if subclass:
      return subclass.from_parameters(parameters)
    return super().from_parameters(parameters)

  @classmethod
  def parse_return_parameters(
      cls, parameters: bytes
  ) -> hci.HCI_ReturnParameters:
    if len(parameters) < 2:
      return hci.HCI_GenericReturnParameters(parameters)

    apcf_opcode = parameters[1]  # parameters[0] is status
    if apcf_opcode == ApcfOpcode.ENABLE:
      return HciApcfEnableCommandReturnParameters.from_parameters(parameters)
    elif apcf_opcode == ApcfOpcode.READ_EXTENDED_FEATURES:
      return HciApcfReadExtendedFeaturesCommandReturnParameters.from_parameters(
          parameters
      )
    elif apcf_opcode in (
        ApcfOpcode.SET_FILTERING_PARAMETERS,
        ApcfOpcode.BROADCASTER_ADDRESS,
        ApcfOpcode.SERVICE_UUID,
        ApcfOpcode.SERVICE_SOLICITATION_UUID,
        ApcfOpcode.LOCAL_NAME,
        ApcfOpcode.MANUFACTURER_DATA,
        ApcfOpcode.SERVICE_DATA,
        ApcfOpcode.TRANSPORT_DISCOVERY_SERVICE,
        ApcfOpcode.AD_TYPE_FILTER,
    ):
      return HciApcfCommandReturnParameters.from_parameters(parameters)

    return hci.HCI_GenericReturnParameters(parameters)


_APCF_COMMAND_CLASSES: dict[int, type[HciApcfCommand]] = {}

_T = TypeVar('_T', bound=type[HciApcfCommand])


def apcf_subcommand(subclass: _T) -> _T:
  """Decorator to register APCF subcommands."""
  for field in dataclasses.fields(subclass):  # type: ignore[arg-type]
    if field.name == 'apcf_opcode':
      apcf_opcode = field.default
      if isinstance(apcf_opcode, ApcfOpcode):
        apcf_opcode = apcf_opcode.value
      if isinstance(apcf_opcode, int):
        _APCF_COMMAND_CLASSES[apcf_opcode] = subclass
      break
  subclass.fields = hci.HCI_Object.fields_from_dataclass(subclass)
  return subclass


# Subcommands
@apcf_subcommand
@dataclasses.dataclass
class HciApcfEnableCommand(HciApcfCommand):
  apcf_opcode: int = dataclasses.field(
      default=ApcfOpcode.ENABLE, metadata=hci.metadata(1)
  )
  apcf_enable: int = dataclasses.field(default=1, metadata=hci.metadata(1))


@apcf_subcommand
@dataclasses.dataclass
class HciApcfReadExtendedFeaturesCommand(HciApcfCommand):
  apcf_opcode: int = dataclasses.field(
      default=ApcfOpcode.READ_EXTENDED_FEATURES, metadata=hci.metadata(1)
  )


@apcf_subcommand
@dataclasses.dataclass
class HciApcfSetFilteringParametersCommand(HciApcfCommand):
  """HCI APCF Set Filtering Parameters Command."""

  apcf_opcode: int = dataclasses.field(
      default=ApcfOpcode.SET_FILTERING_PARAMETERS, metadata=hci.metadata(1)
  )
  apcf_action: int = dataclasses.field(
      default=ApcfAction.ADD, metadata=hci.metadata(1)
  )
  apcf_filter_index: int = dataclasses.field(
      default=0, metadata=hci.metadata(1)
  )
  apcf_feature_selection: int = dataclasses.field(
      default=0, metadata=hci.metadata(2)
  )
  apcf_list_logic_type: int = dataclasses.field(
      default=0, metadata=hci.metadata(2)
  )
  apcf_filter_logic_type: int = dataclasses.field(
      default=ApcfFilterLogicType.AND, metadata=hci.metadata(1)
  )
  rssi_high_thresh: int = dataclasses.field(
      default=0, metadata=hci.metadata(-1)
  )
  delivery_mode: int = dataclasses.field(default=0, metadata=hci.metadata(1))
  onfound_timeout: int = dataclasses.field(default=0, metadata=hci.metadata(2))
  onfound_timeout_cnt: int = dataclasses.field(
      default=0, metadata=hci.metadata(1)
  )
  rssi_low_thresh: int = dataclasses.field(default=0, metadata=hci.metadata(-1))
  onlost_timeout: int = dataclasses.field(default=0, metadata=hci.metadata(2))
  num_of_tracking_entries: int = dataclasses.field(
      default=0, metadata=hci.metadata(2)
  )

  def __post_init__(self) -> None:
    self._parameters: bytes = b''

  @property
  def parameters(self) -> bytes:
    if self._parameters:
      return self._parameters

    if self.apcf_action == ApcfAction.ADD:
      fields_to_serialize = self.fields
    elif self.apcf_action == ApcfAction.DELETE:
      fields_to_serialize = self.fields[:3]
    else:  # CLEAR
      fields_to_serialize = self.fields[:2]

    self._parameters = hci.HCI_Object.dict_to_bytes(
        self.__dict__, fields_to_serialize
    )
    return self._parameters

  @parameters.setter
  def parameters(self, parameters: bytes) -> None:
    self._parameters = parameters


@apcf_subcommand
@dataclasses.dataclass
class HciApcfLocalNameCommand(HciApcfCommand):
  """HCI APCF Local Name Command."""

  apcf_opcode: int = dataclasses.field(
      default=ApcfOpcode.LOCAL_NAME, metadata=hci.metadata(1)
  )
  apcf_action: int = dataclasses.field(
      default=ApcfAction.ADD, metadata=hci.metadata(1)
  )
  apcf_filter_index: int = dataclasses.field(
      default=0, metadata=hci.metadata(1)
  )
  local_name: bytes = dataclasses.field(default=b'', metadata=hci.metadata('*'))


@apcf_subcommand
@dataclasses.dataclass
class HciApcfBroadcasterAddressCommand(HciApcfCommand):
  """HCI APCF Broadcaster Address Command."""

  apcf_opcode: int = dataclasses.field(
      default=ApcfOpcode.BROADCASTER_ADDRESS, metadata=hci.metadata(1)
  )
  apcf_action: int = dataclasses.field(
      default=ApcfAction.ADD, metadata=hci.metadata(1)
  )
  apcf_filter_index: int = dataclasses.field(
      default=0, metadata=hci.metadata(1)
  )
  broadcaster_address: bytes = dataclasses.field(
      default=b'\x00\x00\x00\x00\x00\x00', metadata=hci.metadata(6)
  )
  application_address_type: int = dataclasses.field(
      default=0x02, metadata=hci.metadata(1)
  )


@apcf_subcommand
@dataclasses.dataclass
class HciApcfServiceUuidCommand(HciApcfCommand):
  """HCI APCF Service UUID Command."""

  apcf_opcode: int = dataclasses.field(
      default=ApcfOpcode.SERVICE_UUID, metadata=hci.metadata(1)
  )
  apcf_action: int = dataclasses.field(
      default=ApcfAction.ADD, metadata=hci.metadata(1)
  )
  apcf_filter_index: int = dataclasses.field(
      default=0, metadata=hci.metadata(1)
  )
  # Combined UUID and Mask. They must be of the same length (2, 4, or 16 bytes).
  uuid_and_mask: bytes = dataclasses.field(
      default=b'', metadata=hci.metadata('*')
  )


@apcf_subcommand
@dataclasses.dataclass
class HciApcfServiceDataCommand(HciApcfCommand):
  """HCI APCF Service Data Command."""

  apcf_opcode: int = dataclasses.field(
      default=ApcfOpcode.SERVICE_DATA, metadata=hci.metadata(1)
  )
  apcf_action: int = dataclasses.field(
      default=ApcfAction.ADD, metadata=hci.metadata(1)
  )
  apcf_filter_index: int = dataclasses.field(
      default=0, metadata=hci.metadata(1)
  )
  # Combined Service Data and Mask. They must be of the same length.
  service_data_and_mask: bytes = dataclasses.field(
      default=b'', metadata=hci.metadata('*')
  )


# Initialize fields for return parameters
HciApcfEnableCommandReturnParameters.fields = (
    hci.HCI_Object.fields_from_dataclass(HciApcfEnableCommandReturnParameters)
)
HciApcfCommandReturnParameters.fields = hci.HCI_Object.fields_from_dataclass(
    HciApcfCommandReturnParameters
)
HciApcfReadExtendedFeaturesCommandReturnParameters.fields = (
    hci.HCI_Object.fields_from_dataclass(
        HciApcfReadExtendedFeaturesCommandReturnParameters
    )
)


@dataclasses.dataclass
class LeAdvertisementTrackingSubevent(hci.HCI_Event):
  """LE Advertisement Tracking Subevent."""

  SUBEVENT_CODE = 0x56
  event_code = hci.HCI_VENDOR_EVENT
  name = 'LE_ADVERTISEMENT_TRACKING_SUBEVENT'

  subevent_code: int = dataclasses.field(metadata=hci.metadata(1))
  apcf_filter_index: int = dataclasses.field(metadata=hci.metadata(1))
  advertiser_state: int = dataclasses.field(metadata=hci.metadata(1))
  advt_info_present: int = dataclasses.field(metadata=hci.metadata(1))
  advertiser_address_bytes: bytes = dataclasses.field(metadata=hci.metadata(6))
  advertiser_address_type: int = dataclasses.field(metadata=hci.metadata(1))
  advt_info: bytes = dataclasses.field(metadata=hci.metadata('*'))

  @property
  def advertiser_address(self) -> hci.Address:
    return hci.Address(
        self.advertiser_address_bytes,
        hci.AddressType(self.advertiser_address_type),
    )

  @classmethod
  def try_from_bytes(
      cls, data: bytes
  ) -> LeAdvertisementTrackingSubevent | None:
    """Creates a LeAdvertisementTrackingSubevent from bytes."""
    if len(data) < 1 or data[0] != cls.SUBEVENT_CODE:
      return None
    return cls.from_parameters(data)


LeAdvertisementTrackingSubevent.fields = hci.HCI_Object.fields_from_dataclass(
    LeAdvertisementTrackingSubevent
)
