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

from __future__ import annotations

import asyncio
from collections.abc import Callable
import contextlib
import enum
import itertools
from typing import Any
import uuid

from bumble import core
from bumble import device
from bumble import hci
from bumble import pairing
from bumble import smp
from mobly import test_runner

from navi.tests import navi_test_base
from navi.tests.smoke import pairing_utils
from navi.utils import android_constants
from navi.utils import bl4a_api
from navi.utils import constants
from navi.utils import pyee_extensions
from navi.utils import retry

# Somehow this rule has some issues.
# pylint: disable=redundant-match

_TERMINATED_BOND_STATES = (
    android_constants.BondState.BONDED,
    android_constants.BondState.NONE,
)
_DEFAULT_STEP_TIMEOUT_SECONDS = 15.0


class TestVariant(enum.Enum):
  ACCEPT = 'accept'
  REJECT = 'reject'
  REJECTED = 'rejected'
  DISCONNECTED = 'disconnected'


_AddressType = hci.OwnAddressType
_BondState = android_constants.BondState
_Direction = constants.Direction
_KeyDistribution = pairing.PairingDelegate.KeyDistribution
_AndroidPairingVariant = android_constants.PairingVariant
_BumblePairingVariant = pairing_utils.PairingVariant
_DEFAULT_SETUP_TIMEOUT_SECONDS = 15.0


class LePairingTest(navi_test_base.TwoDevicesTestBase):

  @retry.retry_on_exception()
  async def _make_outgoing_connection(
      self, ref_connection_address_type: _AddressType, create_bond: bool
  ) -> device.Connection:
    ref_addr = str(
        self.ref.random_address
        if ref_connection_address_type == _AddressType.RANDOM
        else self.ref.address
    )
    self.logger.info('[REF] Start advertising.')
    await self.ref.device.start_advertising(
        own_address_type=ref_connection_address_type
    )

    with pyee_extensions.EventWatcher() as watcher:
      ref_dut_connection_future = asyncio.get_running_loop().create_future()

      @watcher.on(self.ref.device, 'connection')
      def _(connection: device.Connection) -> None:
        if connection.transport == core.BT_LE_TRANSPORT:
          ref_dut_connection_future.set_result(connection)

      self.logger.info('[DUT] Connect to REF.')
      if create_bond:
        self.assertTrue(
            self.dut.bt.createBond(
                ref_addr,
                android_constants.Transport.LE,
                ref_connection_address_type,
            )
        )
      else:
        gatt_client = await self.dut.bl4a.connect_gatt_client(
            address=ref_addr,
            address_type=ref_connection_address_type,
            transport=android_constants.Transport.LE,
        )
        self.test_case_context.push(gatt_client)

      async with self.assert_not_timeout(_DEFAULT_STEP_TIMEOUT_SECONDS):
        ref_dut_connection = await ref_dut_connection_future

      await self.ref.device.stop_advertising()
      return ref_dut_connection

  @retry.retry_on_exception()
  async def _make_incoming_connection(
      self, ref_connection_address_type: _AddressType
  ) -> device.Connection:
    # Generate a random UUID for testing.
    service_uuid = str(uuid.uuid4())

    self.logger.info(
        '[DUT] Start advertising with service UUID %s.', service_uuid
    )
    advertise = await self.dut.bl4a.start_legacy_advertiser(
        settings=bl4a_api.LegacyAdvertiseSettings(
            own_address_type=_AddressType.RANDOM
        ),
        advertising_data=bl4a_api.AdvertisingData(service_uuids=[service_uuid]),
    )

    self.logger.info('[REF] Scan for DUT.')
    scan_result = asyncio.get_running_loop().create_future()
    with advertise, pyee_extensions.EventWatcher() as watcher:

      def on_advertising_report(adv: device.Advertisement) -> None:
        if service_uuids := adv.data.get(
            core.AdvertisingData.Type.COMPLETE_LIST_OF_128_BIT_SERVICE_CLASS_UUIDS
        ):
          if service_uuid in service_uuids and not scan_result.done():
            scan_result.set_result(adv.address)

      watcher.on(self.ref.device, 'advertisement', on_advertising_report)
      await self.ref.device.start_scanning()
      self.logger.info(
          '[REF] Wait for advertising report(scan result) from DUT.'
      )
      async with self.assert_not_timeout(_DEFAULT_STEP_TIMEOUT_SECONDS):
        dut_addr = await scan_result
      await self.ref.device.stop_scanning()

      self.logger.info('[REF] Connect to DUT.')
      ref_dut_connection = await self.ref.device.connect(
          dut_addr,
          transport=core.BT_LE_TRANSPORT,
          own_address_type=ref_connection_address_type,
      )
      # Remote may not receive CONNECT_IND, so we need to send something to make
      # sure connection is established correctly.
      await ref_dut_connection.get_remote_le_features()

    return ref_dut_connection

  @navi_test_base.parameterized(*(
      (
          variant,
          connection_direction,
          pairing_direction,
          ref_io_capability,
          ref_connection_address_type,
          smp_key_distribution,
      )
      for (
          variant,
          connection_direction,
          pairing_direction,
          ref_io_capability,
          ref_connection_address_type,
          smp_key_distribution,
      ) in itertools.product(
          list(TestVariant),
          list(_Direction),
          list(_Direction),
          (
              pairing.PairingDelegate.NO_OUTPUT_NO_INPUT,
              pairing.PairingDelegate.DISPLAY_OUTPUT_AND_YES_NO_INPUT,
          ),
          (_AddressType.RANDOM, _AddressType.PUBLIC),
          (
              # IRK + LTK
              _KeyDistribution.DISTRIBUTE_ENCRYPTION_KEY
              | _KeyDistribution.DISTRIBUTE_IDENTITY_KEY,
              # IRK + LTK + LK (CTKD)
              _KeyDistribution.DISTRIBUTE_ENCRYPTION_KEY
              | _KeyDistribution.DISTRIBUTE_IDENTITY_KEY
              | _KeyDistribution.DISTRIBUTE_LINK_KEY,
          ),
      )
      # Android cannot send SMP_Security_Request.
      if not (
          connection_direction == _Direction.INCOMING
          and pairing_direction == _Direction.OUTGOING
      )
  ))
  @navi_test_base.retry(max_count=2)
  async def test_secure_pairing(
      self,
      variant: TestVariant,
      connection_direction: _Direction,
      pairing_direction: _Direction,
      ref_io_capability: pairing.PairingDelegate.IoCapability,
      ref_connection_address_type: _AddressType,
      smp_key_distribution: _KeyDistribution,
  ) -> None:
    """Tests LE Secure pairing.

    Test steps:
    1. Setup configurations.
    2. Make ACL connections.
    3. Start pairing.
    4. Wait for pairing requests and verify pins.
    5. Make actions corresponding to variants.
    6. Verify final states.

    Args:
      variant: Action to perform in the pairing procedure.
      connection_direction: Direction of connection. DUT->REF is outgoing, and
        vice versa.
      pairing_direction: Direction of pairing. DUT->REF is outgoing, and vice
        versa.
      ref_io_capability: IO Capability on the REF device.
      ref_connection_address_type: OwnAddressType of REF used in LE-ACL.
      smp_key_distribution: Key distribution to be specified by the REF device.
    """

    # #######################
    # Setup stage
    # #######################

    pairing_delegate = pairing_utils.PairingDelegate(
        auto_accept=True,
        io_capability=ref_io_capability,
        local_initiator_key_distribution=smp_key_distribution,
        local_responder_key_distribution=smp_key_distribution,
    )

    def pairing_config_factory(
        _: device.Connection,
    ) -> pairing.PairingConfig:
      return pairing.PairingConfig(
          sc=True,
          mitm=True,
          bonding=True,
          identity_address_type=pairing.PairingConfig.AddressType.PUBLIC,
          delegate=pairing_delegate,
      )

    self.ref.device.pairing_config_factory = pairing_config_factory

    dut_cb = self.dut.bl4a.register_callback(bl4a_api.Module.ADAPTER)
    self.test_case_context.push(dut_cb)
    ref_addr = str(
        self.ref.random_address
        if ref_connection_address_type == _AddressType.RANDOM
        else self.ref.address
    ).upper()

    need_double_confirmation = (
        connection_direction == _Direction.OUTGOING
        and pairing_direction == _Direction.INCOMING
    )

    # ##############################################
    # Connecting & pairing initiating stage
    # ##############################################

    ref_dut: device.Connection
    pair_task: asyncio.Task | None = None
    if connection_direction == _Direction.OUTGOING:
      if pairing_direction == _Direction.INCOMING:
        ref_dut = await self._make_outgoing_connection(
            ref_connection_address_type, create_bond=False
        )
        self.logger.info('[REF] Request pairing.')
        ref_dut.request_pairing()
      else:
        self.logger.info('[DUT] Start pairing.')
        ref_dut = await self._make_outgoing_connection(
            ref_connection_address_type, create_bond=True
        )
        # Clean all bond state events since there might be some events produced
        # by retries.
        dut_cb.get_all_events(bl4a_api.BondStateChanged)
    else:
      ref_dut = await self._make_incoming_connection(
          ref_connection_address_type
      )
      if pairing_direction == _Direction.INCOMING:
        self.logger.info('[REF] Start pairing.')
        pair_task = asyncio.create_task(ref_dut.pair())
      else:
        self.logger.info('[DUT] Start pairing.')
        self.dut.bt.createBond(
            ref_addr,
            android_constants.Transport.LE,
            ref_connection_address_type,
        )

    # #######################
    # Pairing stage
    # #######################

    self.logger.info('[DUT] Wait for pairing request.')
    dut_pairing_event = await dut_cb.wait_for_event(
        bl4a_api.PairingRequest,
        lambda e: (e.address == ref_addr),
        timeout=_DEFAULT_SETUP_TIMEOUT_SECONDS,
    )

    if need_double_confirmation:
      self.logger.info('[DUT] Provide initial pairing confirmation.')
      self.dut.bt.setPairingConfirmation(ref_addr, True)
      self.logger.info('[DUT] Wait for 2nd pairing request.')
      dut_pairing_event = await dut_cb.wait_for_event(
          bl4a_api.PairingRequest,
          lambda e: (e.address == ref_addr),
          timeout=_DEFAULT_SETUP_TIMEOUT_SECONDS,
      )

    self.logger.info('[REF] Wait for pairing request.')
    ref_pairing_event = await asyncio.wait_for(
        pairing_delegate.pairing_events.get(),
        timeout=_DEFAULT_SETUP_TIMEOUT_SECONDS,
    )
    ref_answer = variant != TestVariant.REJECTED

    self.logger.info('[DUT] Check reported pairing method.')
    match ref_io_capability:
      case pairing.PairingDelegate.IoCapability.NO_OUTPUT_NO_INPUT:
        expected_dut_pairing_variant = _AndroidPairingVariant.CONSENT
        expected_ref_pairing_variant = _BumblePairingVariant.JUST_WORK
      case pairing.PairingDelegate.IoCapability.DISPLAY_OUTPUT_AND_YES_NO_INPUT:
        expected_dut_pairing_variant = (
            _AndroidPairingVariant.PASSKEY_CONFIRMATION
        )
        expected_ref_pairing_variant = _BumblePairingVariant.NUMERIC_COMPARISON
        self.assertEqual(ref_pairing_event.arg, dut_pairing_event.pin)
      case _:
        raise ValueError(f'Unsupported IO capability: {ref_io_capability}')

    self.assertEqual(dut_pairing_event.variant, expected_dut_pairing_variant)

    self.logger.info('[REF] Check reported pairing method.')
    self.assertEqual(ref_pairing_event.variant, expected_ref_pairing_variant)

    self.logger.info('[DUT] Handle pairing confirmation.')
    match variant:
      case TestVariant.ACCEPT | TestVariant.REJECTED:
        self.dut.bt.setPairingConfirmation(ref_addr, True)
      case TestVariant.REJECT:
        self.dut.bt.cancelBond(ref_addr)
      case _:
        # [DUT] Do nothing.
        ...

    self.logger.info('[REF] Handle pairing confirmation.')
    if variant == TestVariant.DISCONNECTED:
      await ref_dut.disconnect()

    pairing_delegate.pairing_answers.put_nowait(ref_answer)

    self.logger.info('[DUT] Check final state.')
    expect_state = (
        android_constants.BondState.BONDED
        if variant == TestVariant.ACCEPT
        else android_constants.BondState.NONE
    )
    actual_state = (
        await dut_cb.wait_for_event(
            bl4a_api.BondStateChanged,
            lambda e: (e.state in _TERMINATED_BOND_STATES),
            timeout=_DEFAULT_SETUP_TIMEOUT_SECONDS,
        )
    ).state
    self.assertEqual(actual_state, expect_state)

    if pair_task:
      self.logger.info('[REF] Wait pairing complete.')
      expected_errors: list[type[BaseException]]
      match variant:
        case TestVariant.REJECT | TestVariant.REJECTED:
          expected_errors = [core.ProtocolError]
        case TestVariant.DISCONNECTED:
          expected_errors = [asyncio.exceptions.CancelledError]
        case _:
          expected_errors = []
      with contextlib.suppress(*expected_errors):
        await pair_task

  @navi_test_base.parameterized(*(
      (
          variant,
          connection_direction,
          pairing_direction,
          ref_io_capability,
      )
      for (
          variant,
          connection_direction,
          pairing_direction,
          ref_io_capability,
      ) in itertools.product(
          list(TestVariant),
          list(_Direction),
          list(_Direction),
          (
              pairing.PairingDelegate.NO_OUTPUT_NO_INPUT,
              pairing.PairingDelegate.DISPLAY_OUTPUT_AND_YES_NO_INPUT,
              pairing.PairingDelegate.DISPLAY_OUTPUT_AND_KEYBOARD_INPUT,
              pairing.PairingDelegate.DISPLAY_OUTPUT_ONLY,
              pairing.PairingDelegate.KEYBOARD_INPUT_ONLY,
          ),
      )
      # Android cannot send SMP_Security_Request.
      if not (
          connection_direction == _Direction.INCOMING
          and pairing_direction == _Direction.OUTGOING
      )
  ))
  @navi_test_base.retry(max_count=2)
  async def test_legacy_pairing(
      self,
      variant: TestVariant,
      connection_direction: _Direction,
      pairing_direction: _Direction,
      ref_io_capability: pairing.PairingDelegate.IoCapability,
  ) -> None:
    """Tests LE Secure pairing.

    Test steps:
    1. Setup configurations.
    2. Make ACL connections.
    3. Start pairing.
    4. Wait for pairing requests and verify pins.
    5. Make actions corresponding to variants.
    6. Verify final states.

    Args:
      variant: Action to perform in the pairing procedure.
      connection_direction: Direction of connection. DUT->REF is outgoing, and
        vice versa.
      pairing_direction: Direction of pairing. DUT->REF is outgoing, and vice
        versa.
      ref_io_capability: IO Capability on the REF device.
    """

    # ####################### Setup ##########################
    pairing_delegate = pairing_utils.PairingDelegate(
        auto_accept=True,
        io_capability=ref_io_capability,
        local_initiator_key_distribution=pairing.PairingDelegate.DEFAULT_KEY_DISTRIBUTION,
        local_responder_key_distribution=pairing.PairingDelegate.DEFAULT_KEY_DISTRIBUTION,
    )

    def pairing_config_factory(_: device.Connection) -> pairing.PairingConfig:
      return pairing.PairingConfig(
          sc=False,
          mitm=True,
          bonding=True,
          identity_address_type=pairing.PairingConfig.AddressType.PUBLIC,
          delegate=pairing_delegate,
      )

    self.ref.device.pairing_config_factory = pairing_config_factory

    dut_cb = self.dut.bl4a.register_callback(bl4a_api.Module.ADAPTER)
    self.test_case_context.push(dut_cb)
    ref_addr = self.ref.random_address

    need_double_confirmation = (
        connection_direction == _Direction.OUTGOING
        and pairing_direction == _Direction.INCOMING
    )

    # ####################### Connecting ##########################
    ref_dut: device.Connection
    pair_task: asyncio.Task | None = None
    if connection_direction == _Direction.OUTGOING:
      if pairing_direction == _Direction.INCOMING:
        ref_dut = await self._make_outgoing_connection(
            _AddressType.RANDOM, create_bond=False
        )
        self.logger.info('[REF] Request pairing.')
        ref_dut.request_pairing()
      else:
        self.logger.info('[DUT] Start pairing.')
        ref_dut = await self._make_outgoing_connection(
            _AddressType.RANDOM, create_bond=True
        )
        # Clean all bond state events since there might be some events produced
        # by retries.
        dut_cb.get_all_events(bl4a_api.BondStateChanged)
    else:
      ref_dut = await self._make_incoming_connection(_AddressType.RANDOM)
      if pairing_direction == _Direction.INCOMING:
        self.logger.info('[REF] Start pairing.')
        pair_task = asyncio.create_task(ref_dut.pair())
      else:
        self.logger.info('[DUT] Start pairing.')
        self.dut.bt.createBond(
            ref_addr,
            android_constants.Transport.LE,
            _AddressType.RANDOM,
        )

    # ####################### Pairing ##########################
    self.logger.info('[DUT] Wait for pairing request.')
    dut_pairing_event = await dut_cb.wait_for_event(
        bl4a_api.PairingRequest,
        lambda e: (e.address == ref_addr),
        timeout=_DEFAULT_SETUP_TIMEOUT_SECONDS,
    )

    if need_double_confirmation:
      self.logger.info('[DUT] Provide initial pairing confirmation.')
      self.dut.bt.setPairingConfirmation(ref_addr, True)
      self.logger.info('[DUT] Wait for 2nd pairing request.')
      dut_pairing_event = await dut_cb.wait_for_event(
          bl4a_api.PairingRequest,
          lambda e: (e.address == ref_addr),
          timeout=_DEFAULT_SETUP_TIMEOUT_SECONDS,
      )

    if (
        ref_io_capability
        != pairing.PairingDelegate.IoCapability.NO_OUTPUT_NO_INPUT
    ):
      self.logger.info('[REF] Wait for pairing request.')
      async with self.assert_not_timeout(_DEFAULT_SETUP_TIMEOUT_SECONDS):
        ref_pairing_event = await pairing_delegate.pairing_events.get()
    else:
      ref_pairing_event = pairing_utils.PairingEvent(
          _BumblePairingVariant.JUST_WORK, None
      )

    dut_accept = variant != TestVariant.REJECT
    ref_accept = variant != TestVariant.REJECTED
    ref_answer: pairing_utils.PairingAnswer
    dut_answer: Callable[[], Any]

    self.logger.info('[DUT] Check reported pairing method.')
    match ref_io_capability, connection_direction:
      case (pairing.PairingDelegate.IoCapability.NO_OUTPUT_NO_INPUT, _):
        expected_dut_pairing_variant = _AndroidPairingVariant.CONSENT
        expected_ref_pairing_variant = _BumblePairingVariant.JUST_WORK
        ref_answer = ref_accept
        dut_answer = lambda: self.dut.bt.setPairingConfirmation(ref_addr, True)
      case (
          pairing.PairingDelegate.IoCapability.KEYBOARD_INPUT_ONLY,
          _,
      ) | (
          pairing.PairingDelegate.IoCapability.DISPLAY_OUTPUT_AND_KEYBOARD_INPUT,
          _Direction.OUTGOING,
      ):
        expected_dut_pairing_variant = _AndroidPairingVariant.DISPLAY_PASSKEY
        expected_ref_pairing_variant = (
            _BumblePairingVariant.PASSKEY_ENTRY_REQUEST
        )
        ref_answer = dut_pairing_event.pin if ref_accept else None
        dut_answer = lambda: None
      case (
          pairing.PairingDelegate.IoCapability.DISPLAY_OUTPUT_ONLY
          | pairing.PairingDelegate.IoCapability.DISPLAY_OUTPUT_AND_YES_NO_INPUT,
          _,
      ) | (
          pairing.PairingDelegate.IoCapability.DISPLAY_OUTPUT_AND_KEYBOARD_INPUT,
          _Direction.INCOMING,
      ):
        expected_dut_pairing_variant = _AndroidPairingVariant.PIN
        expected_ref_pairing_variant = (
            _BumblePairingVariant.PASSKEY_ENTRY_NOTIFICATION
        )
        ref_answer = dut_pairing_event.pin if ref_accept else None
        dut_answer = lambda: self.dut.bt.setPin(
            ref_addr, f'{ref_pairing_event.arg:06}'
        )
      case _:
        raise ValueError(f'Unsupported IO capability: {ref_io_capability}')

    self.assertEqual(dut_pairing_event.variant, expected_dut_pairing_variant)
    self.assertEqual(ref_pairing_event.variant, expected_ref_pairing_variant)

    self.logger.info('[DUT] Handle pairing confirmation.')
    if dut_accept:
      dut_answer()
    else:
      self.dut.bt.cancelBond(ref_addr)

    self.logger.info('[REF] Handle pairing confirmation.')
    match variant:
      case TestVariant.ACCEPT | TestVariant.REJECT:
        pairing_delegate.pairing_answers.put_nowait(ref_answer)
      case TestVariant.DISCONNECTED:
        await ref_dut.disconnect()
      case TestVariant.REJECTED:
        smp_session = self.ref.device.smp_manager.sessions[ref_dut.handle]
        smp_session.send_pairing_failed(smp.SMP_UNSPECIFIED_REASON_ERROR)

    self.logger.info('[DUT] Check final state.')
    expect_state = (
        android_constants.BondState.BONDED
        if variant == TestVariant.ACCEPT
        else android_constants.BondState.NONE
    )
    bond_state_changed_event = await dut_cb.wait_for_event(
        bl4a_api.BondStateChanged,
        lambda e: (e.state in _TERMINATED_BOND_STATES),
        timeout=_DEFAULT_SETUP_TIMEOUT_SECONDS,
    )
    self.assertEqual(bond_state_changed_event.state, expect_state)

    if pair_task:
      self.logger.info('[REF] Wait pairing complete.')
      expected_errors: list[type[BaseException]]
      match variant:
        case TestVariant.REJECT | TestVariant.REJECTED:
          expected_errors = [core.ProtocolError]
        case TestVariant.DISCONNECTED:
          expected_errors = [
              asyncio.exceptions.CancelledError,
              core.ProtocolError,
          ]
        case _:
          expected_errors = []
      with contextlib.suppress(*expected_errors):
        await pair_task


if __name__ == '__main__':
  test_runner.main()
