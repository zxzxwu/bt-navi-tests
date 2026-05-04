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

"""Tests related to Bluetooth A2DP Source role on Pixel."""

import asyncio
import enum
from typing import Literal

from bumble import a2dp
from bumble import avdtp
from bumble import avrcp
from bumble import core
from bumble import device as bumble_device
from bumble import hci
from mobly import test_runner
from mobly import signals
from typing_extensions import override

from navi.bumble_ext import a2dp as a2dp_ext
from navi.tests import navi_test_base
from navi.utils import android_constants
from navi.utils import bl4a_api

_A2DP_SERVICE_RECORD_HANDLE = 1
_DEFAULT_STEP_TIMEOUT_SECONDS = 15.0
_SHORT_STEP_TIMEOUT_SECONDS = 5.0
_DEFAULT_STREAM_DURATION_SECONDS = 2.0


_A2dpCodec = a2dp_ext.A2dpCodec
_Module = bl4a_api.Module


class OptionalCodecsPref(enum.IntEnum):
  DISABLED = 0
  ENABLED = 1
  UNKNOWN = -1


class A2dpSourceTest(navi_test_base.TwoDevicesTestBase):
  """A2DP Source (DUT) tests."""

  @override
  async def async_setup_class(self) -> None:
    await super().async_setup_class()
    if (
        self.dut.getprop(android_constants.Property.A2DP_SOURCE_ENABLED)
        != "true"
    ):
      raise signals.TestAbortClass("A2DP Source is not enabled on DUT.")

  def _setup_a2dp_sink_from_ref(
      self, codecs: list[_A2dpCodec]
  ) -> avdtp.Listener:
    """Sets up A2DP Sink profile on REF.

    Args:
      codecs: A2DP codecs supported by REF.

    Returns:
      An avdtp.Listener.
    """
    self.logger.info("[REF]setup_a2dp_sink_from_ref")
    return a2dp_ext.setup_sink_server(
        self.ref.device,
        [codec.get_default_capabilities() for codec in codecs],
        _A2DP_SERVICE_RECORD_HANDLE,
    )

  async def _pair_and_connect_from_dut(self) -> None:
    """Tests A2DP connection establishment right after a pairing session."""
    with self.dut.bl4a.register_callback(_Module.A2DP) as dut_cb:
      self._setup_a2dp_sink_from_ref([_A2dpCodec.SBC])
      self.logger.info("[DUT] Connect and pair REF.")
      await self.classic_connect_and_pair(connect_profiles=True)

      self.logger.info("[DUT] Wait for A2DP connected.")
      await dut_cb.wait_for_event(
          bl4a_api.ProfileConnectionStateChanged(
              address=self.ref.address,
              state=android_constants.ConnectionState.CONNECTED,
          ),
          timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
      )
      self.logger.info("[DUT] Wait for A2DP becomes active.")
      await dut_cb.wait_for_event(
          bl4a_api.ProfileActiveDeviceChanged(address=self.ref.address),
          timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
      )

  async def _find_or_connect_acl_from_ref(
      self, dut_address: str
  ) -> bumble_device.Connection:
    """Finds or creates an ACL connection from REF to DUT."""
    if not (
        dut_ref_acl := self.ref.device.find_connection_by_bd_addr(
            hci.Address(dut_address)
        )
    ):
      dut_ref_acl = await self.ref.device.connect(
          dut_address,
          core.BT_BR_EDR_TRANSPORT,
          timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
      )
      self.logger.info("[REF] Authenticate and encrypt connection.")
      await dut_ref_acl.authenticate()
      await dut_ref_acl.encrypt()
    return dut_ref_acl

  async def _connect_a2dp_from_dut(self, ref_address: str) -> None:
    """Initiates A2DP connection from DUT to REF."""
    self.logger.info("[DUT] Initiating A2DP connection.")
    self.dut.bt.connect(ref_address)

  async def _connect_a2dp_from_ref(
      self, dut_ref_acl: bumble_device.Connection
  ) -> None:
    """Initiates A2DP (AVDTP) connection from REF to DUT."""
    self.logger.info("[REF] Initiating AVDTP connection.")
    await avdtp.Protocol.connect(dut_ref_acl)

  async def _prepare_ref_collision_config(
      self, protocol: avdtp.Protocol, collision_codec: _A2dpCodec
  ) -> tuple[int, list[avdtp.ServiceCapabilities], avdtp.LocalStreamEndPoint]:
    """Prepares configuration for REF-initiated collision."""
    self.logger.info(
        "[REF] Doing preemptive Discover/GetCap for REF-initiated mode."
    )
    discover_response = await asyncio.wait_for(
        protocol.send_command(avdtp.Discover_Command()),
        timeout=_SHORT_STEP_TIMEOUT_SECONDS,
    )
    for endpoint_entry in discover_response.endpoints:
      if endpoint_entry.tsep == avdtp.AVDTP_TSEP_SRC:
        get_cap_response = await asyncio.wait_for(
            protocol.get_capabilities(endpoint_entry.seid),
            timeout=_SHORT_STEP_TIMEOUT_SECONDS,
        )

        remote_caps = next(
            (
                cap
                for cap in get_cap_response.capabilities
                if isinstance(cap, avdtp.MediaCodecCapabilities)
                and cap.media_codec_type == collision_codec.codec_type
            ),
            None,
        )
        if remote_caps:
          ref_target_seid = endpoint_entry.seid
          break
    else:
      raise AssertionError("[REF] No target SRC endpoint found during prep!")

    ref_config = a2dp_ext.select_configuration(collision_codec, remote_caps)

    # Find matching local SNK endpoint for this codec
    ref_local_source = next(
        (
            ep
            for ep in protocol.local_endpoints
            if ep.tsep == avdtp.AVDTP_TSEP_SNK
            and any(
                isinstance(cap, avdtp.MediaCodecCapabilities)
                and cap.media_codec_type == collision_codec.codec_type
                for cap in ep.capabilities
            )
        ),
        None,
    )

    if ref_local_source is None:
      raise AssertionError(
          f"[REF] No local SNK endpoint for {collision_codec.name}!"
      )

    self.logger.info(
        "[REF] Prep done. Waiting for AOSP to timeout and send"
        " SetConfiguration..."
    )
    return ref_target_seid, ref_config, ref_local_source

  async def _execute_collision_race(
      self,
      protocol: avdtp.Protocol,
      message: avdtp.Set_Configuration_Command,
      transaction_label: int,
      initiator: Literal["dut", "ref"],
      accept_aosp_config: bool,
      ref_target_seid: int | None,
      ref_config: list[avdtp.ServiceCapabilities] | None,
      ref_local_source: avdtp.LocalStreamEndPoint | None,
  ) -> None:
    """Executes the SetConfiguration collision race logic."""
    stream: avdtp.Stream | None = None
    if initiator == "dut":
      # Extract target details directly from DUT's fast command
      target_seid = message.int_seid
      config = message.capabilities
      local_source_seid = message.acp_seid

      local_source = next(
          (
              ep
              for ep in protocol.local_endpoints
              if ep.seid == local_source_seid
          ),
          None,
      )
    else:  # ref
      if ref_target_seid is None or ref_config is None:
        raise ValueError("Missing REF configuration for collision.")
      target_seid = ref_target_seid
      config = ref_config
      local_source = ref_local_source
      local_source_seid = local_source.seid if local_source else 0

    self.logger.info(
        "[REF] Dispatching unexpected SetConfiguration command: local %s"
        " remote %s",
        local_source_seid,
        target_seid,
    )

    target_endpoint_proxy = avdtp.StreamEndPointProxy(protocol, target_seid)

    # 1. Fire SetConfiguration IMMEDIATELY to hit socket first.
    tl, fut = await protocol.start_transaction()
    protocol.send_message(
        tl,
        avdtp.Set_Configuration_Command(
            acp_seid=local_source_seid,
            int_seid=target_seid,
            capabilities=config,
        ),
    )

    # Delay to prevent an immediate response from interrupting
    # AOSP's asynchronous state transitions and aborting the connection.
    await asyncio.sleep(0.5)

    # 2. Fire the response to AOSP's SetConfiguration SECOND.
    assert local_source is not None
    response: avdtp.Set_Configuration_Response | avdtp.Set_Configuration_Reject

    if accept_aosp_config:
      self.logger.info(
          "[REF] Returning Set_Configuration_Response (ACCEPT) back to AOSP."
      )
      # Manually transition Bumble state machine
      stream = avdtp.Stream(protocol, local_source, target_endpoint_proxy)
      # Register stream in Protocol
      index_seid = target_seid if initiator == "ref" else local_source_seid
      protocol.streams[index_seid] = stream

      if initiator == "dut":
        local_source.on_set_configuration_command(config)
      elif initiator == "ref":
        local_source.configuration = config

      stream.change_state(avdtp.State.CONFIGURED)

      response = avdtp.Set_Configuration_Response()
    else:
      self.logger.info(
          "[REF] Returning Set_Configuration_Reject (REJECT) back to AOSP."
      )
      response = avdtp.Set_Configuration_Reject(
          error_code=avdtp.AVDTP_BAD_STATE_ERROR
      )
    protocol.send_message(transaction_label, response)

    # Wait for DUT's response to our SetConfiguration
    await fut
    self.logger.info("[REF] SetConfiguration was accepted by DUT!")

    if stream is None:
      stream = avdtp.Stream(protocol, local_source, target_endpoint_proxy)
      protocol.streams[local_source_seid] = stream
      stream.change_state(avdtp.State.CONFIGURED)

    if initiator == "ref" and stream is not None:
      self.logger.info("[REF] Opening stream as exact Initiator...")
      await stream.open()

  async def test_avdtp_autoconnect_when_only_avctp_connected(self) -> None:
    """Tests AVDTP auto-connect when only AVCTP is connected.

    Test steps:
      1. Setup pairing and initial A2DP connection between DUT and REF.
      2. Terminate ACL connection from DUT.
      3. Setup AVRCP on REF.
      4. Connect ACL from REF.
      5. Connect AVRCP from REF (only AVCTP connected).
      6. Wait and verify that DUT initiates AVDTP connection.
    """
    with self.dut.bl4a.register_callback(_Module.A2DP) as dut_cb:
      # Setup pairing and initial A2DP connection
      avdtp_listener = self._setup_a2dp_sink_from_ref([_A2dpCodec.SBC])
      self.logger.info("[DUT] Connect and pair REF.")
      async with self.assert_not_timeout(_DEFAULT_STEP_TIMEOUT_SECONDS):
        await self.classic_connect_and_pair(connect_profiles=True)

      self.logger.info("[DUT] Wait for A2DP connected.")
      await dut_cb.wait_for_event(
          bl4a_api.ProfileConnectionStateChanged(
              address=self.ref.address,
              state=android_constants.ConnectionState.CONNECTED,
          ),
          timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
      )

      # Terminate ACL connection
      self.logger.info("[DUT] Terminate ACL connection.")
      await self.disconnect_with_check(
          self.ref.address, android_constants.Transport.CLASSIC
      )

      # Setup AVRCP on REF
      avrcp_protocol = avrcp.Protocol()
      avrcp_protocol.listen(self.ref.device)

      # Connect ACL from REF
      async with self.assert_not_timeout(
          _DEFAULT_STEP_TIMEOUT_SECONDS,
          msg="[REF] Find or connect ACL connection from DUT.",
      ):
        dut_ref_acl = await self._find_or_connect_acl_from_ref(self.dut.address)

      # Connect AVRCP from REF (only AVCTP connected)
      self.logger.info("[REF] Connect AVRCP (AVCTP only).")
      async with self.assert_not_timeout(
          _DEFAULT_STEP_TIMEOUT_SECONDS,
          msg="[REF] Connect AVRCP from REF.",
      ):
        await avrcp_protocol.connect(dut_ref_acl)

      # Wait for AVDTP connection from DUT
      avdtp_future: asyncio.Future[avdtp.Protocol] = (
          asyncio.get_running_loop().create_future()
      )
      avdtp_listener.once(
          avdtp_listener.EVENT_CONNECTION, avdtp_future.set_result
      )

      self.logger.info(
          "[REF] Waiting for incoming AVDTP connection from DUT..."
      )
      async with self.assert_not_timeout(
          _DEFAULT_STEP_TIMEOUT_SECONDS,
          msg=(
              "[REF] DUT did not initiate AVDTP connection after AVCTP"
              " connection."
          ),
          with_log=False,
      ):
        await avdtp_future

      self.logger.info("[REF] Received incoming AVDTP connection from DUT!")

      self.logger.info("[DUT] Wait for A2DP connected.")
      await dut_cb.wait_for_event(
          bl4a_api.ProfileConnectionStateChanged(
              address=self.ref.address,
              state=android_constants.ConnectionState.CONNECTED,
          ),
          timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
      )

  async def test_paired_connect_a2dp_simultaneous(self) -> None:
    """Tests A2DP connection establishment with simultaneous connection.

    Test steps:
      1. Setup pairing between DUT(A2DP Source) and REF(A2DP Sink).
      2. Terminate ACL connection from DUT.
      3. Setup ACL connection from REF.
      4. Trigger A2DP connection from DUT and REF at same time.
      5. Wait A2DP connected on DUT.
      6. Disconnect from DUT.
      7. Wait A2DP disconnected on DUT.

    Test Results:
      DUT should be able to establish A2DP connection successfully even in
      conflicting scenarios.
    """

    with self.dut.bl4a.register_callback(_Module.A2DP) as dut_cb:
      # Step 1: Setup pairing and initial A2DP connection
      async with self.assert_not_timeout(
          _DEFAULT_STEP_TIMEOUT_SECONDS,
          msg="[DUT] Setup pairing and initial A2DP connection.",
      ):
        await self._pair_and_connect_from_dut()

      # Step 2: Terminate ACL connection
      await self.disconnect_with_check(
          self.ref.address, android_constants.Transport.CLASSIC
      )

      # Step 3: Setup ACL connection from REF
      async with self.assert_not_timeout(
          _DEFAULT_STEP_TIMEOUT_SECONDS,
          msg="[REF] Find or connect ACL connection from DUT.",
      ):
        dut_ref_acl = await self._find_or_connect_acl_from_ref(self.dut.address)

      # Step 4: Trigger connection from DUT and REF at same time
      self.logger.info(
          "[DUT & REF] Triggering simultaneous A2DP (AVDTP) connection."
      )

      # Use asyncio.gather to run both connection attempts concurrently
      try:
        await asyncio.wait_for(
            asyncio.gather(
                self._connect_a2dp_from_dut(self.ref.address),
                self._connect_a2dp_from_ref(dut_ref_acl),
            ),
            timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
        )
      except (core.BaseBumbleError, TimeoutError):
        self.logger.warning(
            "[REF & DUT] Simultaneous A2DP connection exception.",
            stack_info=True,
        )

      # Step 5: Wait for A2DP to be connected on DUT
      self.logger.info("[DUT] Wait for A2DP connected.")
      await dut_cb.wait_for_event(
          bl4a_api.ProfileConnectionStateChanged(
              address=self.ref.address,
              state=android_constants.ConnectionState.CONNECTED,
          ),
          timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
      )
      self.logger.info("[DUT] Wait for A2DP becomes active.")
      await dut_cb.wait_for_event(
          bl4a_api.ProfileActiveDeviceChanged(address=self.ref.address),
          timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
      )

      # Step 6: Disconnect from DUT
      self.logger.info("Step 6: Disconnect from DUT.")
      self.dut.bt.disconnect(self.ref.address)

      # Step 7: Wait for A2DP to be disconnected on DUT
      self.logger.info("Step 7: Wait for A2DP disconnected.")
      await dut_cb.wait_for_event(
          bl4a_api.ProfileConnectionStateChanged(
              address=self.ref.address,
              state=android_constants.ConnectionState.DISCONNECTED,
          ),
          timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
      )

  # TODO: Remove this skip once the bug is fixed.
  @navi_test_base.TwoDevicesTestBase.require_flag(
      "com.android.bluetooth.flags.a2dp_setconfig_collision_resolution",
  )
  @navi_test_base.parameterized(
      # Disabled: AOSP cannot handle this exception.
      # ("dut", "reject", "sbc"),
      ("dut", "accept", "sbc"),
      # Disabled: AOSP cannot handle this exception.
      # ("dut", "reject", "aac"),
      ("dut", "accept", "aac"),
      ("ref", "reject", "sbc"),
      ("ref", "accept", "sbc"),
      ("ref", "reject", "aac"),
      ("ref", "accept", "aac"),
  )
  async def test_avdtp_set_configuration_collision(
      self,
      initiator: Literal["dut", "ref"],
      collision_mode: Literal["accept", "reject"],
      collision_codec_str: Literal["sbc", "aac"],
  ) -> None:
    """Tests AVDTP SetConfiguration collision robustness.

    Reference:
    https://docs.google.com/document/d/10nQBXiZVElWQFAOhuSW0D9kdxs2cW1bWalAZw3Zh93w/edit?usp=sharing&resourcekey=0-8-lywXhojjC6sC_w1faO_g

    Args:
      initiator: Who initiates connection ("dut" or "ref").
      collision_mode: Accept or reject AOSP config ("accept" or "reject").
      collision_codec_str: Targeted codec string ("sbc" or "aac").

    Test steps:
      1. Setup pairing and initial A2DP connection between DUT and REF.
      2. Disconnect A2DP from DUT.
      3. Setup a malicious AVDTP listener on REF to intercept SetConfig.
      4. Trigger A2DP connection (from either DUT or REF based on initiator).
         - If REF initiates, REF preemptively discovers capabilities and waits
           for AOSP to fallback and initiate SetConfiguration.
         - If DUT initiates, REF instantly intercepts DUT's SetConfiguration.
      5. Once REF intercepts AOSP's SetConfiguration, REF immediately triggers
         its own SetConfiguration against DUT and sends a reject/accept to
         DUT's.
      6. DUT should gracefully handle REF's SetConfiguration and the collision.
    """
    accept_aosp_config = collision_mode == "accept"
    background_tasks: set[asyncio.Task[None]] = set()
    collision_codec = (
        _A2dpCodec.AAC if collision_codec_str == "aac" else _A2dpCodec.SBC
    )

    with self.dut.bl4a.register_callback(_Module.A2DP) as dut_cb:
      # Step 1: Setup pairing and initial A2DP connection
      listener = self._setup_a2dp_sink_from_ref(
          [_A2dpCodec.SBC, _A2dpCodec.AAC]
      )
      self.logger.info("[DUT] Connect and pair REF.")
      async with self.assert_not_timeout(_DEFAULT_STEP_TIMEOUT_SECONDS):
        await self.classic_connect_and_pair(connect_profiles=True)

      self.logger.info("[DUT] Wait for A2DP connected.")
      await dut_cb.wait_for_event(
          bl4a_api.ProfileConnectionStateChanged(
              address=self.ref.address,
              state=android_constants.ConnectionState.CONNECTED,
          ),
          timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
      )

      # Step 2: Disconnect A2DP from DUT
      self.logger.info("[DUT] Disconnect A2DP.")
      self.dut.bt.disconnect(self.ref.address)

      self.logger.info("[DUT] Wait for A2DP disconnected.")
      await dut_cb.wait_for_event(
          bl4a_api.ProfileConnectionStateChanged(
              address=self.ref.address,
              state=android_constants.ConnectionState.DISCONNECTED,
          ),
          timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
      )

      # Step 3: Setup a listener for SetConfiguration collision
      collision_result: asyncio.Future[None] = (
          asyncio.get_running_loop().create_future()
      )

      def on_avdtp_connection(protocol: avdtp.Protocol) -> None:

        async def _race() -> None:
          self.logger.info(
              "[REF] Racing AVDTP SetConfiguration against DUT"
              " (initiator=%s)...",
              initiator,
          )

          # Variables needed in the hook closure
          ref_target_seid: int | None = None
          ref_config: list[avdtp.ServiceCapabilities] | None = None
          ref_local_source: avdtp.LocalStreamEndPoint | None = None

          if initiator == "ref":
            ref_target_seid, ref_config, ref_local_source = (
                await self._prepare_ref_collision_config(
                    protocol, collision_codec
                )
            )

          # Monkey-patch on_message via message_assembler.callback
          original_on_message = protocol.message_assembler.callback

          def hooked_on_message(
              transaction_label: int, message: avdtp.Message
          ) -> None:
            if not isinstance(message, avdtp.Set_Configuration_Command):
              # Default behavior for other messages
              original_on_message(transaction_label, message)
              return

            self.logger.info(
                "[REF] Intercepted AOSP's SetConfiguration via on_message!"
                " Initiating REF's SetConfiguration instantly to collide!"
            )

            # Fire the collision and link its result to `collision_result`
            t = asyncio.create_task(
                self._execute_collision_race(
                    protocol,
                    message,
                    transaction_label,
                    initiator,
                    accept_aosp_config,
                    ref_target_seid,
                    ref_config,
                    ref_local_source,
                )
            )

            def on_done(task: asyncio.Task[None]) -> None:
              protocol.message_assembler.callback = original_on_message
              background_tasks.discard(task)

              if task.exception() is not None:
                if isinstance(task.exception(), core.ProtocolError):
                  self.logger.warning(
                      "[REF] SetConfiguration rejected by DUT: %s",
                      task.exception(),
                  )
                  if not collision_result.done():
                    collision_result.set_result(None)
                else:
                  if not collision_result.done():
                    collision_result.set_exception(task.exception())  # type: ignore
              else:
                if not collision_result.done():
                  collision_result.set_result(None)

            background_tasks.add(t)
            t.add_done_callback(on_done)

          protocol.message_assembler.callback = hooked_on_message

        def _on_race_done(task: asyncio.Task[None]) -> None:
          background_tasks.discard(task)
          if task.exception() and not collision_result.done():
            collision_result.set_exception(task.exception())  # type: ignore

        t = asyncio.create_task(_race())
        background_tasks.add(t)
        t.add_done_callback(_on_race_done)

      # Step 4: Initiate Connection
      if initiator == "dut":
        async with self.assert_not_timeout(_DEFAULT_STEP_TIMEOUT_SECONDS):
          listener.on(listener.EVENT_CONNECTION, on_avdtp_connection)
          self.logger.info(
              "[DUT] Initiating A2DP connection to trigger collision."
          )
          self.dut.bt.connect(self.ref.address)
      else:
        async with self.assert_not_timeout(_DEFAULT_STEP_TIMEOUT_SECONDS):
          self.logger.info("[REF] Initiate ACL to pair.")
          dut_ref_acl = await self._find_or_connect_acl_from_ref(
              self.dut.address
          )

          self.logger.info("[REF] Connect AVDTP from REF.")
          avdtp_protocol = await avdtp.Protocol.connect(dut_ref_acl)
          avdtp_protocol.add_sink(_A2dpCodec.SBC.get_default_capabilities())
          avdtp_protocol.add_sink(_A2dpCodec.AAC.get_default_capabilities())
          on_avdtp_connection(avdtp_protocol)

      # Step 5: Wait A2DP connected on DUT
      self.logger.info("[DUT] Wait for A2DP connected.")
      await dut_cb.wait_for_event(
          bl4a_api.ProfileConnectionStateChanged(
              address=self.ref.address,
              state=android_constants.ConnectionState.CONNECTED,
          ),
          timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
      )

      # Ensure our background collision task actually ran
      async with self.assert_not_timeout(
          _DEFAULT_STEP_TIMEOUT_SECONDS * 2,
          "[REF] Collision race task did not finish in time!",
      ):
        await collision_result

  @navi_test_base.named_parameterized(
      enabled=dict(pref=OptionalCodecsPref.ENABLED),
      # TODO: because disabled mode is 100% failing on Android,
      # enable this once the bug is fixed.
      # disabled=dict(pref=OptionalCodecsPref.DISABLED),
      unknown=dict(pref=OptionalCodecsPref.UNKNOWN),
  )
  async def test_playback_with_optional_codecs(
      self, pref: OptionalCodecsPref
  ) -> None:
    """Tests A2DP playback with different optional codecs preferences.

    Args:
      pref: The optional codec preference to configure on the DUT (ENABLED,
        DISABLED, or UNKNOWN).

    Test steps:
      1. Setup A2DP Sink on REF supporting both SBC and AAC codecs.
      2. Connect and pair DUT with REF.
      3. Set the optional codecs preference on DUT for REF.
      4. Wait for A2DP connection to complete.
      5. Trigger music playback from DUT.
      6. Wait and verify that playback has successfully started on DUT.

    Test Results:
      DUT should be able to start audio playback successfully regardless of the
      optional codec preference configured.
    """
    with self.dut.bl4a.register_callback(_Module.A2DP) as dut_cb:
      # Setup A2DP Sink on REF supporting both SBC and AAC
      listener = self._setup_a2dp_sink_from_ref(
          [_A2dpCodec.SBC, _A2dpCodec.AAC]
      )

      protocol_future: asyncio.Future[avdtp.Protocol] = (
          asyncio.get_running_loop().create_future()
      )

      listener.once(listener.EVENT_CONNECTION, protocol_future.set_result)

      self.logger.info("[DUT] Connect and pair REF.")
      async with self.assert_not_timeout(_DEFAULT_STEP_TIMEOUT_SECONDS):
        await self.classic_connect_and_pair(connect_profiles=True)

      # Configure optional codecs mode on DUT
      self.logger.info("[DUT] Configuring optional codecs: %r", pref)
      self.dut.bt.setA2dpOptionalCodecsEnabled(self.ref.address, pref.value)

      self.logger.info("[DUT] Wait for A2DP connected.")
      await dut_cb.wait_for_event(
          bl4a_api.ProfileConnectionStateChanged(
              address=self.ref.address,
              state=android_constants.ConnectionState.CONNECTED,
          ),
          timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
      )

      self.logger.info("[REF] Waiting for AVDTP connection.")
      await asyncio.wait_for(
          protocol_future, timeout=_DEFAULT_STEP_TIMEOUT_SECONDS
      )

      # Trigger playback from DUT
      self.logger.info("[DUT] Triggering music playback via audioPlaySine")
      self.dut.bt.audioPlaySine()

      # Wait for playback to start
      self.logger.info("[DUT] Waiting for playback to start...")
      await dut_cb.wait_for_event(
          bl4a_api.A2dpPlayingStateChanged(
              address=self.ref.address,
              state=android_constants.A2dpState.PLAYING,
          ),
          timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
          timeout_msg="DUT reports A2DP is not playing",
      )

      await asyncio.sleep(_DEFAULT_STREAM_DURATION_SECONDS)

      self.assertTrue(
          self.dut.bt.isA2dpPlaying(self.ref.address),
          "[DUT] reports A2DP is not keeping playing",
      )

      self.logger.info("[DUT] Playback started successfully")

  async def test_reconfigure_codec_error_unsupported(self) -> None:
    """Tests DUT tolerance when REF sends invalid codec configuration.

    Test steps:
      1. Setup A2DP Sink on REF and intercept the AVDTP Protocol instance.
      2. Connect and pair DUT with REF.
      3. Wait for A2DP connection to be established.
      4. Close the existing active stream to transition endpoint to IDLE.
      5. Build an invalid SBC codec configuration (invalid sampling frequency).
      6. Discover remote endpoints and send SetConfiguration with the invalid
         codec capabilities from REF to DUT.
      7. Verify that DUT rejects the configuration with a ProtocolError.

    Test Results:
      DUT should gracefully reject the unsupported codec configuration without
      crashing or accepting the invalid state.
    """
    with self.dut.bl4a.register_callback(_Module.A2DP) as dut_cb:
      # Setup listener, connect and pair without disconnecting later
      listener = self._setup_a2dp_sink_from_ref([_A2dpCodec.SBC])
      protocol_future: asyncio.Future[avdtp.Protocol] = (
          asyncio.get_running_loop().create_future()
      )
      listener.once(listener.EVENT_CONNECTION, protocol_future.set_result)

      self.logger.info("[DUT] Connect and pair REF.")
      async with self.assert_not_timeout(_DEFAULT_STEP_TIMEOUT_SECONDS):
        await self.classic_connect_and_pair(connect_profiles=True)

      # Wait for connection
      self.logger.info("[DUT] Wait for A2DP connected.")
      await dut_cb.wait_for_event(
          bl4a_api.ProfileConnectionStateChanged(
              address=self.ref.address,
              state=android_constants.ConnectionState.CONNECTED,
          ),
          timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
      )

      self.logger.info("[REF] Waiting for AVDTP protocol to be established.")
      avdtp_protocol = await asyncio.wait_for(
          protocol_future, timeout=_DEFAULT_STEP_TIMEOUT_SECONDS
      )

      # To test SetConfiguration, the remote endpoint must be IDLE.
      # Since DUT auto-started a stream, we close it first.
      if avdtp_protocol.streams:
        self.logger.info("[REF] Closing existing stream to make endpoint IDLE.")
        stream = next(iter(avdtp_protocol.streams.values()))
        await stream.close()

      # Build an invalid configuration (e.g., invalid sampling frequency)
      invalid_sbc_info = (  # 0x00 for sampling freq/channel mode
          b"\x00\x0f\x02\x35"
      )

      invalid_codec_caps = avdtp.MediaCodecCapabilities(
          media_type=avdtp.MediaType.AUDIO,
          media_codec_type=a2dp.CodecType.SBC,
          media_codec_information=invalid_sbc_info,
      )

      # Discover endpoints
      async with self.assert_not_timeout(
          _SHORT_STEP_TIMEOUT_SECONDS,
          msg="[REF] Discover remote endpoints.",
      ):
        discover_response = await avdtp_protocol.send_command(
            avdtp.Discover_Command()
        )
      assert isinstance(discover_response, avdtp.Discover_Response)

      target_seid = next(
          (
              ep.seid
              for ep in discover_response.endpoints
              if ep.tsep == avdtp.AVDTP_TSEP_SRC
          ),
          None,
      )

      if target_seid is None:
        self.fail("[REF] No remote SRC endpoint found.")

      # Send SetConfiguration with invalid parameters and verify reject
      async with self.assert_not_timeout(
          _DEFAULT_STEP_TIMEOUT_SECONDS,
          msg="[REF] Sending invalid SetCFG and waiting for DUT to reject.",
      ):
        with self.assertRaises(core.ProtocolError) as cm:
          await avdtp_protocol.send_command(
              avdtp.Set_Configuration_Command(
                  acp_seid=target_seid,
                  int_seid=1,
                  capabilities=[invalid_codec_caps],
              )
          )

      self.logger.info(
          "[REF] DUT correctly rejected invalid SetConfiguration: %s",
          cm.exception,
      )

  async def test_avdt_handle_suspend_cfm_bad_state_error(self) -> None:
    """Test AVDTP handling of suspend confirmation BAD_STATE error.

    Test steps:
      1. Setup A2DP Sink on REF and intercept the AVDTP Protocol instance.
      2. Connect and pair DUT with REF.
      3. Start streaming from DUT to REF.
      4. Manually set endpoint's stream to None on REF to force BAD_STATE
      response
         on Suspend command.
      5. Suspend streaming from DUT.
      6. Verify that DUT receives BAD_STATE reject and falls back to
         disconnecting the A2DP profile.
    """
    with self.dut.bl4a.register_callback(_Module.A2DP) as dut_cb:
      # Setup A2DP Sink and listener
      listener = self._setup_a2dp_sink_from_ref([_A2dpCodec.SBC])
      protocol_future: asyncio.Future[avdtp.Protocol] = (
          asyncio.get_running_loop().create_future()
      )
      listener.once(listener.EVENT_CONNECTION, protocol_future.set_result)

      # Connect and pair
      self.logger.info("[DUT] Connect and pair REF.")
      async with self.assert_not_timeout(_DEFAULT_STEP_TIMEOUT_SECONDS):
        await self.classic_connect_and_pair(connect_profiles=True)

      self.logger.info("[DUT] Wait for A2DP connected.")
      await dut_cb.wait_for_event(
          bl4a_api.ProfileConnectionStateChanged(
              address=self.ref.address,
              state=android_constants.ConnectionState.CONNECTED,
          ),
          timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
      )

      self.logger.info("[REF] Waiting for AVDTP protocol to be established.")
      avdtp_protocol = await asyncio.wait_for(
          protocol_future, timeout=_DEFAULT_STEP_TIMEOUT_SECONDS
      )

      # Start streaming
      self.logger.info("[DUT] Triggering music playback via audioPlaySine")
      self.dut.bt.audioPlaySine()

      self.logger.info("[DUT] Waiting for playback to start...")
      await dut_cb.wait_for_event(
          bl4a_api.A2dpPlayingStateChanged(
              address=self.ref.address,
              state=android_constants.A2dpState.PLAYING,
          ),
          timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
          timeout_msg="DUT reports A2DP is not playing",
      )

      await asyncio.sleep(_DEFAULT_STREAM_DURATION_SECONDS)

      self.assertTrue(
          self.dut.bt.isA2dpPlaying(self.ref.address),
          "[DUT] reports A2DP is not keeping playing",
      )

      # Force REF endpoint into a bad state by removing stream
      # reference, so it will reject SUSPEND/CLOSE commands with BAD_STATE.
      self.logger.info(
          "[REF] Removing stream reference from endpoint to force BAD_STATE."
      )
      stream = next(iter(avdtp_protocol.streams.values()))
      stream.local_endpoint.stream = None

      # Suspend streaming from DUT
      self.logger.info("[DUT] Stopping music playback via audioStop")
      self.dut.bt.audioStop()

      # Verify DUT disconnects A2DP as fallback
      self.logger.info("[DUT] Wait for A2DP disconnected.")
      await dut_cb.wait_for_event(
          bl4a_api.ProfileConnectionStateChanged(
              address=self.ref.address,
              state=android_constants.ConnectionState.DISCONNECTED,
          ),
          timeout=_DEFAULT_STEP_TIMEOUT_SECONDS,
          timeout_msg="[DUT] A2DP did not disconnect in time.",
      )


if __name__ == "__main__":
  test_runner.main()
