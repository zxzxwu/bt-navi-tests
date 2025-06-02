/*
 * Copyright 2025 The Android Open Source Project
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package com.google.wireless.android.pixel.bluetooth.snippet

import android.bluetooth.BluetoothA2dp
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import androidx.test.platform.app.InstrumentationRegistry
import com.google.android.mobly.snippet.Snippet
import com.google.android.mobly.snippet.rpc.AsyncRpc
import com.google.android.mobly.snippet.rpc.Rpc
import com.google.wireless.android.pixel.bluetooth.snippet.Utils.postSnippetEvent

class BluetoothA2dpSnippet : Snippet {
  // TODO(b/312179595): Providing tests for snippets.
  private val instrumentation = InstrumentationRegistry.getInstrumentation()
  private val context = instrumentation.targetContext
  private val bluetoothAdapter = context.getSystemService(BluetoothManager::class.java).adapter
  private val proxy = Utils.getProfileProxy<BluetoothA2dp>(context, BluetoothProfile.A2DP)
  private val broadcastReceivers = mutableMapOf<String, BroadcastReceiver>()

  init {
    instrumentation.uiAutomation.adoptShellPermissionIdentity()
  }

  /** Setup an A2DP callback with ID [callbackId]. */
  @AsyncRpc(description = "Setup A2DP callbacks.")
  fun a2dpSetup(callbackId: String) {
    val intentFilter =
      IntentFilter().apply {
        addAction(BluetoothA2dp.ACTION_CONNECTION_STATE_CHANGED)
        addAction(BluetoothA2dp.ACTION_PLAYING_STATE_CHANGED)
        addAction(BluetoothA2dp.ACTION_ACTIVE_DEVICE_CHANGED)
      }
    broadcastReceivers[callbackId] =
      object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
          val device =
            intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE, BluetoothDevice::class.java)
          val state = intent.getIntExtra(BluetoothProfile.EXTRA_STATE, BluetoothDevice.ERROR)
          when (intent.action) {
            BluetoothA2dp.ACTION_CONNECTION_STATE_CHANGED -> {
              postSnippetEvent(callbackId, SnippetConstants.PROFILE_CONNECTION_STATE_CHANGE) {
                putString(SnippetConstants.FIELD_DEVICE, device?.address)
                putInt(SnippetConstants.FIELD_STATE, state)
              }
            }
            BluetoothA2dp.ACTION_PLAYING_STATE_CHANGED -> {
              postSnippetEvent(callbackId, SnippetConstants.A2DP_PLAYING_STATE_CHANGED) {
                putString(SnippetConstants.FIELD_DEVICE, device?.address)
                putInt(SnippetConstants.FIELD_STATE, state)
              }
            }
            BluetoothA2dp.ACTION_ACTIVE_DEVICE_CHANGED -> {
              postSnippetEvent(callbackId, SnippetConstants.ACTIVE_DEVICE_CHANGED) {
                putString(SnippetConstants.FIELD_DEVICE, device?.address)
              }
            }
          }
        }
      }
    context.registerReceiver(broadcastReceivers[callbackId], intentFilter)
  }

  /** Teardown an A2DP callback with ID [callbackId]. */
  @Rpc(description = "Teardown A2DP callbacks.")
  fun a2dpTeardown(callbackId: String) {
    broadcastReceivers.remove(callbackId)?.let { context.unregisterReceiver(it) }
  }

  /** Sets A2DP connection policy of device [address] to [policy]. */
  @Rpc(description = "Set A2DP connection policy.")
  fun setA2dpConnectionPolicy(address: String, policy: Int): Boolean =
    proxy.setConnectionPolicy(bluetoothAdapter.getRemoteDevice(address), policy)

  /* Get connected A2DP devices list. */
  @Rpc(description = "Get connected A2DP devices list")
  fun a2dpGetConnectedDevices(): List<String> {
    return proxy.connectedDevices.map { it.address }.toList()
  }

  /* Get A2DP playing state of device [address]. */
  @Rpc(description = "Get A2DP playing state of device [address]")
  fun isA2dpPlaying(address: String): Boolean =
    proxy.isA2dpPlaying(bluetoothAdapter.getRemoteDevice(address))

  companion object {
    const val TAG = "BluetoothA2dpSnippet"
  }
}
