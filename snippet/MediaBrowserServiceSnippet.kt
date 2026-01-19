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

import android.app.Activity
import android.content.Intent
import android.util.Log
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.session.LibraryResult
import androidx.media3.session.MediaLibraryService
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSession.ControllerInfo
import androidx.test.platform.app.InstrumentationRegistry
import com.google.android.mobly.snippet.Snippet
import com.google.android.mobly.snippet.rpc.AsyncRpc
import com.google.android.mobly.snippet.rpc.Rpc
import com.google.android.mobly.snippet.rpc.RunOnUiThread
import com.google.common.collect.ImmutableList
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture
import com.google.wireless.android.pixel.bluetooth.snippet.Utils.toList
import kotlin.time.Duration.Companion.seconds
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.json.JSONObject

/** Snippet for MediaBrowserService. */
class MediaBrowserServiceSnippet : Snippet {
  private val instrumentation = InstrumentationRegistry.getInstrumentation()
  private val context = instrumentation.targetContext
  internal var mediaLibrarySession: MediaLibraryService.MediaLibrarySession? = null

  data class MediaNode(val item: MediaItem, val children: List<MediaNode>)

  private val mediaTreeNodes = mutableMapOf<String, MediaNode>()

  /**
   * Android Bluetooth identify media player apps by querying for activies receiving
   * android.intent.action.VIEW(audio), so we need to provide a placeholder activity here.
   */
  class EmptyActivity : Activity() {}

  init {
    instance = this
  }

  /** Implementation of [MediaLibraryService] to provide media library session. */
  class MediaLibraryServiceImpl : MediaLibraryService() {

    override fun onCreate() {
      super.onCreate()
      Log.d(TAG, "onCreate")
      instance.value = this
    }

    override fun onDestroy() {
      super.onDestroy()
      Log.d(TAG, "onDestroy")
      instance.value = null
    }

    override fun onGetSession(
      controllerInfo: ControllerInfo
    ): MediaLibraryService.MediaLibrarySession? {
      Log.d(TAG, "onGetSession")
      return MediaBrowserServiceSnippet.instance?.mediaLibrarySession
    }

    companion object {
      private const val TAG = "MediaLibraryServiceImpl"
      internal val instance = MutableStateFlow<MediaLibraryServiceImpl?>(null)
    }
  }

  internal fun parseTree(json: JSONObject): MediaNode {
    val id = json.getString(SnippetConstants.FIELD_ID)
    val title = json.optString(SnippetConstants.FIELD_TITLE, "")
    val isBrowsable = json.optBoolean(SnippetConstants.FIELD_BROWSABLE, false)
    val isPlayable = json.optBoolean(SnippetConstants.FIELD_PLAYABLE, false)

    val mediaMetadata =
      MediaMetadata.Builder()
        .setTitle(title)
        .setIsBrowsable(isBrowsable)
        .setIsPlayable(isPlayable)
        .build()

    val item = MediaItem.Builder().setMediaId(id).setMediaMetadata(mediaMetadata).build()
    val children =
      json.optJSONArray(SnippetConstants.FIELD_CHILDREN)?.toList<JSONObject>()?.map {
        parseTree(it)
      } ?: listOf()

    val node = MediaNode(item, children)
    mediaTreeNodes[id] = node
    return node
  }

  @AsyncRpc(description = "Register media library session")
  fun registerMediaLibrarySession(callbackId: String, mediaTree: JSONObject) {
    context.startService(Intent(context, MediaLibraryServiceImpl::class.java))
    // Wait for MediaLibraryServiceImpl to be initiated.
    val mediaLibraryService =
      runBlocking {
        withTimeout(10.seconds) { MediaLibraryServiceImpl.instance.first { it != null } }
      } ?: throw IllegalStateException("MediaLibraryServiceImpl is not initiated")

    mediaTreeNodes.clear()

    val root = parseTree(mediaTree)

    mediaLibrarySession =
      MediaLibraryService.MediaLibrarySession.Builder(
          mediaLibraryService,
          ExoPlayer.Builder(context).build(),
          object : MediaLibraryService.MediaLibrarySession.Callback {
            override fun onGetLibraryRoot(
              session: MediaLibraryService.MediaLibrarySession,
              browser: MediaSession.ControllerInfo,
              params: MediaLibraryService.LibraryParams?,
            ): ListenableFuture<LibraryResult<MediaItem>> {
              Log.d(TAG, "onGetLibraryRoot")
              return Futures.immediateFuture(LibraryResult.ofItem(root.item, null))
            }

            override fun onGetChildren(
              session: MediaLibraryService.MediaLibrarySession,
              browser: MediaSession.ControllerInfo,
              parentId: String,
              page: Int,
              pageSize: Int,
              params: MediaLibraryService.LibraryParams?,
            ): ListenableFuture<LibraryResult<ImmutableList<MediaItem>>> {
              Log.d(TAG, "onGetChildren $parentId")
              val node = mediaTreeNodes[parentId]
              val children = node?.children ?: listOf()
              return Futures.immediateFuture(
                LibraryResult.ofItemList(children.map { it.item }, null)
              )
            }

            override fun onConnect(
              session: MediaSession,
              controller: MediaSession.ControllerInfo,
            ): MediaSession.ConnectionResult {
              Log.d(TAG, "onConnect")
              return super.onConnect(session, controller)
            }

            override fun onAddMediaItems(
              session: MediaSession,
              controller: MediaSession.ControllerInfo,
              mediaItems: List<MediaItem>,
            ): ListenableFuture<List<MediaItem>> {
              for (mediaItem in mediaItems) {
                Utils.postSnippetEvent(callbackId, SnippetConstants.MEDIA_ITEM_ADDED) {
                  putString(SnippetConstants.FIELD_ID, mediaItem.mediaId)
                }
              }
              return super.onAddMediaItems(session, controller, mediaItems)
            }
          },
        )
        .setId(callbackId)
        .build()
  }

  @RunOnUiThread
  @Rpc(description = "Release media library session")
  fun unregisterMediaLibrarySession(callbackId: String) {
    mediaLibrarySession?.run {
      player.release()
      release()
    }
    mediaLibrarySession = null
    mediaTreeNodes.clear()
  }

  private companion object {
    const val TAG = "MediaBrowserServiceSnippet"
    var instance: MediaBrowserServiceSnippet? = null
  }
}
