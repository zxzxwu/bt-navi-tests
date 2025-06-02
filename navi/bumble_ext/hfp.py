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

"""Extended Bumble implementation of HFP protocol."""

import asyncio
import logging

from bumble import hci
from bumble import hfp
from bumble import rfcomm
import bumble.device
from typing_extensions import override

from navi.bumble_ext import rfcomm as rfcomm_ext

_logger = logging.getLogger(__name__)


# TODO: Remove this once the bug is fixed in Bumble.
hfp.RESPONSE_CODES.discard("+BCS")

ESCO_PARAMETERS_LC3_T2 = hfp.EscoParameters(
    transmit_coding_format=hci.CodingFormat(hci.CodecID.LC3),
    receive_coding_format=hci.CodingFormat(hci.CodecID.LC3),
    max_latency=0x000D,
    packet_type=(
        hci.HCI_Enhanced_Setup_Synchronous_Connection_Command.PacketType.NO_3_EV3
        | hci.HCI_Enhanced_Setup_Synchronous_Connection_Command.PacketType.NO_2_EV5
        | hci.HCI_Enhanced_Setup_Synchronous_Connection_Command.PacketType.NO_3_EV5
    ),
    input_bandwidth=64000,
    output_bandwidth=64000,
    retransmission_effort=hci.HCI_Enhanced_Setup_Synchronous_Connection_Command.RetransmissionEffort.OPTIMIZE_FOR_QUALITY,
)

ESCO_PARAMETERS_T2_TRANSPARENT = hfp.EscoParameters(
    transmit_coding_format=hci.CodingFormat(hci.CodecID.TRANSPARENT),
    receive_coding_format=hci.CodingFormat(hci.CodecID.TRANSPARENT),
    max_latency=0x000D,
    packet_type=(
        hci.HCI_Enhanced_Setup_Synchronous_Connection_Command.PacketType.NO_3_EV3
        | hci.HCI_Enhanced_Setup_Synchronous_Connection_Command.PacketType.NO_2_EV5
        | hci.HCI_Enhanced_Setup_Synchronous_Connection_Command.PacketType.NO_3_EV5
    ),
    input_coding_format=hci.CodingFormat(hci.CodecID.TRANSPARENT),
    output_coding_format=hci.CodingFormat(hci.CodecID.TRANSPARENT),
    input_bandwidth=8000,
    output_bandwidth=8000,
    retransmission_effort=hci.HCI_Enhanced_Setup_Synchronous_Connection_Command.RetransmissionEffort.OPTIMIZE_FOR_QUALITY,
)


class HfProtocol(hfp.HfProtocol):
  """Customized HF Protocol."""

  controller_supported_codecs: list[hci.CodecID] | None = None

  @classmethod
  def setup_server(
      cls,
      device: bumble.device.Device,
      sdp_handle: int,
      configuration: hfp.HfConfiguration,
      auto_accept_sco_request: bool = True,
  ) -> asyncio.Queue["HfProtocol"]:
    """Creates a HFP server on the given device.

    Args:
      device: The device to create the HFP server on.
      sdp_handle: The SDP handle to use for the HFP server.
      configuration: The configuration to use for the HFP server.
      auto_accept_sco_request: Whether to automatically accept SCO requests.

    Returns:
      A queue of HFP protocols.
    """
    protocol_queue = asyncio.Queue[HfProtocol]()

    def on_dlc(dlc: rfcomm.DLC) -> None:
      _logger.info("[REF] HFP DLC connected %s.", dlc)
      hfp_protocol = HfProtocol(dlc, configuration, auto_accept_sco_request)
      protocol_queue.put_nowait(hfp_protocol)
      dlc.multiplexer.l2cap_channel.connection.abort_on(
          "disconnection", hfp_protocol.run()
      )

    # Create and register a server.
    rfcomm_server = rfcomm_ext.get_rfcomm_server(device) or rfcomm.Server(
        device
    )

    # Listen for incoming DLC connections.
    channel_number = rfcomm_server.listen(on_dlc)
    _logger.info(
        "[REF] Listening for RFCOMM connection on channel %s.", channel_number
    )
    device.sdp_service_records[sdp_handle] = hfp.make_hf_sdp_records(
        service_record_handle=sdp_handle,
        rfcomm_channel=channel_number,
        configuration=configuration,
    )
    return protocol_queue

  def __init__(
      self,
      dlc: rfcomm.DLC,
      configuration: hfp.HfConfiguration,
      auto_accept_sco_request: bool = True,
  ) -> None:
    self.auto_accept_sco_request = auto_accept_sco_request
    if auto_accept_sco_request:
      device = dlc.multiplexer.l2cap_channel.connection.device
      device.on(device.EVENT_SCO_REQUEST, self._on_sco_request)
    super().__init__(dlc=dlc, configuration=configuration)

  @override
  async def setup_codec_connection(self, codec_id: int) -> None:
    self.active_codec = hfp.AudioCodec(codec_id)
    self.emit("codec_negotiation", self.active_codec)

    # Answer codec negotiation in the background, because ACL packets cannot be
    # sent during SCO setup.
    connection = self.dlc.multiplexer.l2cap_channel.connection
    connection.abort_on(
        "disconnection", self.execute_command(f"AT+BCS={codec_id}")
    )

  async def _on_sco_request(
      self, connection: bumble.device.Connection, link_type: int
  ) -> None:
    """Called when a SCO request is received."""
    del link_type
    await self.accept_sco_request(connection)

  async def accept_sco_request(
      self, connection: bumble.device.Connection | None = None
  ) -> None:
    """Accepts Bumble SCO request."""
    connection = connection or self.dlc.multiplexer.l2cap_channel.connection
    await connection.device.send_command(
        hci.HCI_Enhanced_Accept_Synchronous_Connection_Request_Command(
            bd_addr=connection.peer_address,
            **(await self.get_esco_parameters()).asdict(),
        )
    )

  async def _get_controller_supported_codecs(self) -> list[hci.CodecID]:
    """Returns codecs supported by the controller."""
    device = self.dlc.multiplexer.l2cap_channel.connection.device
    try:
      response = await device.send_command(
          hci.HCI_Read_Local_Supported_Codecs_Command(), check_result=True
      )
    except hci.HCI_Error:
      _logger.debug("Failed to read supported codecs")
      return []

    controller_supported_codecs = list(
        hci.CodecID(codec)
        for codec in response.return_parameters.standard_codec_ids
    )
    _logger.debug("Supported codecs: %s", controller_supported_codecs)
    return controller_supported_codecs

  async def get_esco_parameters(self) -> hfp.EscoParameters:
    """Returns the ESCO parameters for the active codec.

    Returns:
      The ESCO parameters for the active codec.

    Raises:
      ValueError: If the active codec is not supported.
    """
    if self.controller_supported_codecs is None:
      self.controller_supported_codecs = (
          await self._get_controller_supported_codecs()
      )

    match self.active_codec:
      case hfp.AudioCodec.CVSD:
        # It's not common that the controller doesn't support CVSD.
        return hfp.ESCO_PARAMETERS[hfp.DefaultCodecParameters.ESCO_CVSD_S4]
      case hfp.AudioCodec.MSBC:
        if hci.CodecID.MSBC in self.controller_supported_codecs:
          return hfp.ESCO_PARAMETERS[hfp.DefaultCodecParameters.ESCO_MSBC_T2]
        else:
          return ESCO_PARAMETERS_T2_TRANSPARENT
      case hfp.AudioCodec.LC3_SWB:
        if hci.CodecID.LC3 in self.controller_supported_codecs:
          return ESCO_PARAMETERS_LC3_T2
        else:
          return ESCO_PARAMETERS_T2_TRANSPARENT
      case _:
        raise ValueError(f"Unsupported codec: {self.active_codec}")
