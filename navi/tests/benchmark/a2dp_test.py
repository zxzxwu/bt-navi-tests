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

import asyncio
import decimal
import enum
from typing import Iterable, TypeAlias

from bumble import avdtp
from bumble import avrcp
from bumble import core
from mobly import test_runner
from typing_extensions import override

from navi.bumble_ext import a2dp as a2dp_ext
from navi.bumble_ext import avrcp as avrcp_ext
from navi.tests import navi_test_base
from navi.tests.benchmark import performance_tool
from navi.tests.benchmark import test_base
from navi.utils import android_constants
from navi.utils import audio
from navi.utils import bl4a_api
from navi.utils import matcher


_A2DP_SERVICE_RECORD_HANDLE = 1
_AVRCP_CONTROLLER_RECORD_HANDLE = 2
_AVRCP_TARGET_RECORD_HANDLE = 3
_DEFAULT_REPEAT_TIMES = 30
_PROPERTY_CODEC_PRIORITY = "bluetooth.a2dp.source.%s_priority.config"
_VALUE_CODEC_DISABLED = -1
_DEFAULT_TIMEOUT_SECONDS = 10.0
_PREPARE_TIME_SECONDS = 0.5
_AVRCP_MAX_VOLUME = 127
_Callback = bl4a_api.CallbackHandler
_A2dpCodec = a2dp_ext.A2dpCodec
_A2dpState = android_constants.A2dpState
_StreamType: TypeAlias = android_constants.StreamType


@enum.unique
class _A2dpStreamState(enum.Enum):
  START = enum.auto()
  STOP = enum.auto()


class LocalSinkWrapper:
  """Wrapper for LocalSink to provide start/suspend events."""

  def __init__(self, impl: avdtp.LocalSink):
    self.impl = impl
    self.condition = asyncio.Condition()
    for command in (
        impl.EVENT_CONFIGURATION,
        impl.EVENT_OPEN,
        impl.EVENT_START,
        impl.EVENT_SUSPEND,
        impl.EVENT_CLOSE,
        impl.EVENT_ABORT,
    ):
      self.impl.on(command, self._on_command)

  async def _on_command(self) -> None:
    async with self.condition:
      self.condition.notify_all()

  @property
  def stream_state(self) -> int | None:
    return self.impl.stream.state if self.impl.stream else None


class AvrcpDelegate(avrcp.Delegate):

  def __init__(self, supported_events: Iterable[avrcp.EventId] = ()):
    super().__init__(supported_events)
    self.condition = asyncio.Condition()

  @override
  async def set_absolute_volume(self, volume: int) -> None:
    await super().set_absolute_volume(volume)
    async with self.condition:
      self.condition.notify_all()


class A2dpTest(test_base.PerformanceTestBase):
  def _setup_a2dp_device(
      self, codecs: list[_A2dpCodec]
  ) -> tuple[avdtp.Listener, avrcp.Protocol]:
    """Sets up A2DP profile on REF.

    Args:
      codecs: A2DP codecs supported by REF.

    Returns:
      A tuple of (avdtp.Listener, avrcp.Protocol).
    """
    listener = a2dp_ext.setup_sink_server(
        self.ref.device,
        [codec.get_default_capabilities() for codec in codecs],
        _A2DP_SERVICE_RECORD_HANDLE,
    )
    avrcp_delegator = AvrcpDelegate(
        supported_events=(avrcp.EventId.VOLUME_CHANGED,)  # type: ignore[wrong-arg-types]
    )
    avrcp_protocol = avrcp_ext.setup_server(
        self.ref.device,
        avrcp_controller_handle=_AVRCP_CONTROLLER_RECORD_HANDLE,
        avrcp_target_handle=_AVRCP_TARGET_RECORD_HANDLE,
        delegate=avrcp_delegator,
    )

    return listener, avrcp_protocol

  async def _setup_a2dp_connection(self, ref_codecs: list[_A2dpCodec]) -> tuple[
      avrcp.Protocol,
      avdtp.Protocol,
  ]:
    """Sets up A2DP connection between DUT and REF.

    Args:
      ref_codecs: A2DP codecs supported by REF.

    Returns:
      A tuple of (avrcp.Protocol, avdtp.Protocol).
    """
    with self.dut.bl4a.register_callback(bl4a_api.Module.A2DP) as dut_cb:
      ref_avdtp_listener, ref_avrcp_protocol = self._setup_a2dp_device(
          ref_codecs
      )
      ref_avdtp_connections = asyncio.Queue[avdtp.Protocol]()
      ref_avdtp_listener.on(
          ref_avdtp_listener.EVENT_CONNECTION, ref_avdtp_connections.put
      )

      self.logger.info("[DUT] Connect and pair REF.")
      ref_acl = await self.classic_connect_and_pair()

      self.logger.info("[DUT] Wait for A2DP connected.")
      await dut_cb.wait_for_event(
          bl4a_api.ProfileConnectionStateChanged(
              address=self.ref.address,
              state=android_constants.ConnectionState.CONNECTED,
          ),
      )
      async with self.assert_not_timeout(
          _DEFAULT_TIMEOUT_SECONDS, msg="[REF] Wait for A2DP connected."
      ):
        ref_avdtp_connection = await ref_avdtp_connections.get()
      self.logger.info("[DUT] Wait for A2DP becomes active.")
      await dut_cb.wait_for_event(
          bl4a_api.ProfileActiveDeviceChanged(address=self.ref.address),
          timeout=_DEFAULT_TIMEOUT_SECONDS,
      )

      if ref_avrcp_protocol.avctp_protocol is not None:
        self.logger.info("[REF] AVRCP already connected.")
      else:
        self.logger.info("[REF] Connect AVRCP.")
        async with self.assert_not_timeout(_DEFAULT_TIMEOUT_SECONDS):
          await ref_avrcp_protocol.connect(ref_acl)
        self.logger.info("[REF] AVRCP connected.")
    return ref_avrcp_protocol, ref_avdtp_connection

  async def pair_and_connect(self) -> None:
    with self.dut.bl4a.register_callback(bl4a_api.Module.A2DP) as dut_cb:
      a2dp_ext.setup_sink_server(
          self.ref.device,
          [_A2dpCodec.SBC.get_default_capabilities()],
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
    """Test make outgoing A2DP connections.

    Test steps:
      1. Pair and connect.
      2. Terminate the connection.
      3. Make A2DP connection from DUT to REF.
      4. Terminate the connection.
      5. Repeat step 3-4.
    """
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
        self.success_attempt_record(
            test_round=i + 1, latency=latency_seconds, latency_list=latency_list
        )
      except (core.BaseBumbleError, AssertionError):
        self.logger.exception("Failed to make A2DP connection")
      finally:
        await performance_tool.terminate_connection_from_ref(self.dut, self.ref)
    self.record_sponge_data(
        repeat_times=_DEFAULT_REPEAT_TIMES, latency_list=latency_list
    )

  @navi_test_base.named_parameterized(
      without_avrcp=(False,), with_avrcp=(True,)
  )
  async def test_connection_incoming(self, avrcp_enabled: bool) -> None:
    """Test make incoming A2DP connections.

    Test steps:
      1. Pair and connect.
      2. Terminate the connection.
      3. Make A2DP connection from REF to DUT.
      4. Terminate the connection.
      5. Repeat step 3-4.

    Args:
      avrcp_enabled: Enable AVRCP during the test.
    """
    latency_list = list[float]()
    ref_avdtp_listener = a2dp_ext.setup_sink_server(
        self.ref.device,
        [_A2dpCodec.SBC.get_default_capabilities()],
        _A2DP_SERVICE_RECORD_HANDLE,
    )
    ref_avrcp_protocol: avrcp.Protocol | None = None
    if avrcp_enabled:
      ref_avrcp_protocol = avrcp_ext.setup_server(
          self.ref.device,
          avrcp_controller_handle=_AVRCP_CONTROLLER_RECORD_HANDLE,
          avrcp_target_handle=_AVRCP_TARGET_RECORD_HANDLE,
      )
    ref_acl = await self.classic_connect_and_pair()
    await performance_tool.terminate_connection_from_ref(self.dut, self.ref)
    for i in range(_DEFAULT_REPEAT_TIMES):
      try:
        if avrcp_enabled:
          ref_avdtp_connections = asyncio.Queue[avdtp.Protocol]()
          ref_avdtp_listener.on(
              ref_avdtp_listener.EVENT_CONNECTION, ref_avdtp_connections.put
          )
        with self.dut.bl4a.register_callback(bl4a_api.Module.A2DP) as dut_cb:
          self.logger.info("[REF] Connect to DUT.")
          with performance_tool.Stopwatch() as stop_watch:
            dut_ref_acl = await self.ref.device.connect(
                self.dut.address,
                transport=core.BT_BR_EDR_TRANSPORT,
                timeout=_DEFAULT_TIMEOUT_SECONDS,
            )

            async with self.assert_not_timeout(
                _DEFAULT_TIMEOUT_SECONDS,
                msg="[REF] Authenticate and encrypt connection.",
            ):
              await dut_ref_acl.authenticate()
              await dut_ref_acl.encrypt()

            async with self.assert_not_timeout(
                _DEFAULT_TIMEOUT_SECONDS,
                msg="[REF] Connect A2DP.",
            ):
              server = await avdtp.Protocol.connect(dut_ref_acl)
            server.add_sink(_A2dpCodec.AAC.get_default_capabilities())

            self.logger.info("[DUT] Wait for A2DP connected.")
            await dut_cb.wait_for_event(
                bl4a_api.ProfileConnectionStateChanged(
                    address=self.ref.address,
                    state=android_constants.ConnectionState.CONNECTED,
                ),
            )
            self.logger.info("[DUT] Wait for A2DP becomes active.")
            await dut_cb.wait_for_event(
                bl4a_api.ProfileActiveDeviceChanged(address=self.ref.address),
                timeout=_DEFAULT_TIMEOUT_SECONDS,
            )
            if avrcp_enabled:
              if ref_avrcp_protocol is None:
                raise ValueError("[REF] AVRCP is not initialized.")
              elif ref_avrcp_protocol.avctp_protocol is not None:
                raise ValueError("[REF] AVRCP already connected.")
              else:
                self.logger.info("[REF] Connect AVRCP.")
                async with self.assert_not_timeout(_DEFAULT_TIMEOUT_SECONDS):
                  await ref_avrcp_protocol.connect(ref_acl)
                self.logger.info("[REF] AVRCP connected.")
          latency_seconds = stop_watch.elapsed_time.total_seconds()
          self.success_attempt_record(
              test_round=i + 1,
              latency=latency_seconds,
              latency_list=latency_list,
          )
      except (core.BaseBumbleError, AssertionError):
        self.logger.exception("Failed to make A2DP connection")
      finally:
        await performance_tool.terminate_connection_from_ref(self.dut, self.ref)
    self.record_sponge_data(
        repeat_times=_DEFAULT_REPEAT_TIMES, latency_list=latency_list
    )

  async def wait_for_a2dp_status(
      self, ref_sink: LocalSinkWrapper, status: _A2dpStreamState
  ) -> None:
    with self.dut.bl4a.register_callback(bl4a_api.Module.A2DP) as dut_cb:
      if status == _A2dpStreamState.STOP:
        if self.dut.bt.isA2dpPlaying(self.ref.address):
          self.logger.info("[DUT] A2DP is streaming, wait for A2DP stopped.")
          await dut_cb.wait_for_event(
              bl4a_api.A2dpPlayingStateChanged(
                  self.ref.address, _A2dpState.NOT_PLAYING
              ),
          )
      elif status == _A2dpStreamState.START:
        if not self.dut.bt.isA2dpPlaying(self.ref.address):
          self.logger.info("[DUT] wait for A2DP started.")
          await dut_cb.wait_for_event(
              bl4a_api.A2dpPlayingStateChanged(
                  self.ref.address, _A2dpState.PLAYING
              ),
          )
    async with (
        self.assert_not_timeout(
            _DEFAULT_TIMEOUT_SECONDS,
        ),
        ref_sink.condition,
    ):
      if status == _A2dpStreamState.STOP:
        self.logger.info("[REF] Wait for A2DP stopped.")
        await ref_sink.condition.wait_for(
            lambda: ref_sink.stream_state != avdtp.AVDTP_STREAMING_STATE
        )
      elif status == _A2dpStreamState.START:
        self.logger.info("[REF] Wait for A2DP started.")
        await ref_sink.condition.wait_for(
            lambda: ref_sink.stream_state == avdtp.AVDTP_STREAMING_STATE
        )

  async def test_stream_start(self) -> None:
    """Tests A2DP streaming controlled by DUT.

    Test steps:
      1. Setup pairing between DUT and REF.
      2. Start stream from DUT.
      3. Stop stream from DUT.
    """
    codec = _A2dpCodec.SBC
    self.dut.bt.audioSetRepeat(android_constants.RepeatMode.ONE)
    _, ref_avdtp_connection = await self._setup_a2dp_connection([codec])

    ref_sinks = a2dp_ext.find_local_endpoints_by_codec(
        ref_avdtp_connection,
        codec.codec_type,
        avdtp.LocalSink,
        vendor_id=codec.vendor_id,
        codec_id=codec.codec_id,
    )
    if not ref_sinks:
      self.fail("No sink found for codec %s." % codec.name)
    ref_sink = LocalSinkWrapper(ref_sinks[0])

    # If there is a playback, wait until it ends.
    await self.wait_for_a2dp_status(ref_sink, _A2dpStreamState.STOP)
    latency_list = list[float]()
    for i in range(_DEFAULT_REPEAT_TIMES):
      try:
        # Register the sink buffer to receive the packets.
        buffer = a2dp_ext.register_sink_buffer(ref_sink.impl, codec)
        with (
            performance_tool.Stopwatch() as stop_watch_for_start_stream,
        ):
          self.logger.info("[DUT] Start stream.")
          self.dut.bt.audioPlaySine()
          await self.wait_for_a2dp_status(ref_sink, _A2dpStreamState.START)
        latency_seconds = (
            stop_watch_for_start_stream.elapsed_time.total_seconds()
        )
        # Streaming for 1 second.
        await asyncio.sleep(1.0)
        self.logger.info("[DUT] Stop stream.")
        self.dut.bt.audioPause()
        await self.wait_for_a2dp_status(ref_sink, _A2dpStreamState.STOP)

        if (
            buffer is not None
            and audio.SUPPORT_AUDIO_PROCESSING
        ):
          dominant_frequency = audio.get_dominant_frequency(
              buffer, format=codec.format
          )
          self.logger.info("Dominant frequency: %.2f", dominant_frequency)
          # Dominant frequency is not accurate on emulator.
          if not self.dut.device.is_emulator:
            self.assertAlmostEqual(dominant_frequency, 1000, delta=10)
        self.success_attempt_record(
            test_round=i + 1,
            latency=latency_seconds,
            latency_list=latency_list,
        )
      except (core.BaseBumbleError, AssertionError):
        self.logger.exception("Failed to stream")
      finally:
        self.dut.bt.audioPause()
        await self.wait_for_a2dp_status(ref_sink, _A2dpStreamState.STOP)
    self.record_sponge_data(
        repeat_times=_DEFAULT_REPEAT_TIMES, latency_list=latency_list
    )

  async def test_set_absolute_volume(self) -> None:
    """Tests setting absolute volume.

    Test steps:
      1. Setup pairing between DUT and REF.
      2. Set absolute volume.
    """
    ref_avrcp_protocol, _ = await self._setup_a2dp_connection([_A2dpCodec.SBC])
    ref_avrcp_delegator = ref_avrcp_protocol.delegate
    assert isinstance(ref_avrcp_delegator, AvrcpDelegate)

    dut_max_volume = self.dut.bt.getMaxVolume(_StreamType.MUSIC)
    dut_min_volume = self.dut.bt.getMinVolume(_StreamType.MUSIC)
    if dut_max_volume == dut_min_volume:
      raise self.skipTest("DUT's max volume is the same as min volume.")

    def android_to_avrcp_volume(volume: int) -> int:
      # Android JVM uses ROUND_HALF_UP policy, while Python uses ROUND_HALF_EVEN
      # by default, so we need to specify policy here.
      return int(
          decimal.Decimal(
              volume / dut_max_volume * _AVRCP_MAX_VOLUME
          ).to_integral_exact(rounding=decimal.ROUND_HALF_UP)
      )

    async with (
        self.assert_not_timeout(
            _DEFAULT_TIMEOUT_SECONDS,
            msg="[REF] Wait for initial volume indicator.",
        ),
        ref_avrcp_delegator.condition,
    ):
      await ref_avrcp_delegator.condition.wait_for(
          lambda: (
              android_to_avrcp_volume(self.dut.bt.getVolume(_StreamType.MUSIC))
              == ref_avrcp_delegator.volume
          )
      )

    # DUT's VCS client might not be stable at the beginning. If we set volume
    # immediately, the volume might not be set correctly.
    await asyncio.sleep(_PREPARE_TIME_SECONDS)
    latency_list = list[float]()
    for i in range(_DEFAULT_REPEAT_TIMES):
      try:
        dut_expected_volume = dut_max_volume
        if self.dut.bt.getVolume(_StreamType.MUSIC) == dut_expected_volume:
          dut_expected_volume -= 1

        ref_expected_volume = android_to_avrcp_volume(dut_expected_volume)
        with performance_tool.Stopwatch() as stop_watch:
          with self.dut.bl4a.register_callback(
              bl4a_api.Module.AUDIO
          ) as dut_audio_cb:
            self.logger.info("[DUT] Set volume to %d.", dut_expected_volume)
            self.dut.bt.setVolume(_StreamType.MUSIC, dut_expected_volume)

            self.logger.info("[DUT] Wait for volume changed.")
            volume_changed_event = await dut_audio_cb.wait_for_event(
                bl4a_api.VolumeChanged(
                    stream_type=_StreamType.MUSIC, volume_value=matcher.ANY
                ),
            )
            self.assertEqual(
                volume_changed_event.volume_value, dut_expected_volume
            )
          async with (
              self.assert_not_timeout(
                  _DEFAULT_TIMEOUT_SECONDS,
                  msg="[REF] Wait for volume changed.",
              ),
              ref_avrcp_delegator.condition,
          ):
            await ref_avrcp_delegator.condition.wait_for(
                lambda: ref_avrcp_delegator.volume == ref_expected_volume  # pylint: disable=cell-var-from-loop
            )
        latency_seconds = stop_watch.elapsed_time.total_seconds()
        self.success_attempt_record(
            test_round=i + 1, latency=latency_seconds, latency_list=latency_list
        )
      except (core.BaseBumbleError, AssertionError):
        self.logger.exception("Failed to set volume")
    self.record_sponge_data(
        repeat_times=_DEFAULT_REPEAT_TIMES, latency_list=latency_list
    )


if __name__ == "__main__":
  test_runner.main()
