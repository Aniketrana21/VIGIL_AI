package com.vigilai.telecom

import android.telecom.Call
import android.telecom.CallAudioState
import android.telecom.InCallService
import android.telecom.VideoProfile
import android.util.Log
import java.lang.ref.WeakReference

/**
 * Central state coordinator for the active cellular call.
 * Bridges Android Telecom InCallService events to the InCallActivity UI
 * and manages real hardware controls (Mute, Speaker, Hold, DTMF, Record).
 */
object CallManager {
    private const val TAG = "CallManager"

    var currentCall: Call? = null
        private set

    private var activeServiceRef: WeakReference<InCallService>? = null

    var isMuted: Boolean = false
        private set
    var isSpeakerOn: Boolean = false
        private set
    var isOnHold: Boolean = false
        private set
    var isRecording: Boolean = false

    interface CallStateListener {
        fun onCallStateChanged(state: Int)
        fun onCallDisconnected()
        fun onAudioStateChanged(isMuted: Boolean, isSpeakerOn: Boolean) {}
    }

    private val listeners = mutableListOf<CallStateListener>()

    fun bindService(service: InCallService) {
        activeServiceRef = WeakReference(service)
        Log.i(TAG, "INCALL_SERVICE_CONNECTED: InCallService bound to CallManager")
    }

    fun unbindService() {
        activeServiceRef = null
    }

    fun registerCall(call: Call) {
        currentCall = call
        isOnHold = false
        isRecording = false
        Log.i(TAG, "INCALL_SERVICE_CONNECTED: Registered active call ${call.details?.handle?.schemeSpecificPart} (State: ${call.state})")
    }

    fun unregisterCall(call: Call) {
        if (currentCall == call) {
            currentCall = null
            isOnHold = false
            isRecording = false
            Log.i(TAG, "CALL_DISCONNECTED: Unregistered call")
            notifyDisconnected()
        }
    }

    fun addListener(listener: CallStateListener) {
        if (!listeners.contains(listener)) {
            listeners.add(listener)
        }
    }

    fun removeListener(listener: CallStateListener) {
        listeners.remove(listener)
    }

    fun notifyStateChanged(state: Int) {
        for (l in ArrayList(listeners)) {
            try { l.onCallStateChanged(state) } catch (e: Exception) { Log.e(TAG, "Listener error: ${e.message}") }
        }
    }

    fun notifyDisconnected() {
        for (l in ArrayList(listeners)) {
            try { l.onCallDisconnected() } catch (e: Exception) { Log.e(TAG, "Listener error: ${e.message}") }
        }
    }

    fun notifyAudioState(muted: Boolean, speaker: Boolean) {
        isMuted = muted
        isSpeakerOn = speaker
        for (l in ArrayList(listeners)) {
            try { l.onAudioStateChanged(muted, speaker) } catch (e: Exception) { Log.e(TAG, "Listener error: ${e.message}") }
        }
    }

    fun answerCall() {
        currentCall?.let {
            try {
                it.answer(VideoProfile.STATE_AUDIO_ONLY)
                Log.i(TAG, "CALL_ACTIVE: Call answered via CallManager")
            } catch (e: Exception) {
                Log.e(TAG, "Error answering call: ${e.message}")
            }
        }
    }

    fun rejectCall() {
        currentCall?.let {
            try {
                it.reject(Call.REJECT_REASON_DECLINED)
                Log.i(TAG, "CALL_DISCONNECTED: Call rejected via CallManager")
            } catch (e: Exception) {
                Log.e(TAG, "Error rejecting call: ${e.message}")
            }
        }
    }

    fun endCall() {
        currentCall?.let {
            try {
                it.disconnect()
                Log.i(TAG, "CALL_DISCONNECTED: Call disconnected via CallManager")
            } catch (e: Exception) {
                Log.e(TAG, "Error ending call: ${e.message}")
            }
        }
    }

    fun toggleMute(): Boolean {
        isMuted = !isMuted
        try {
            activeServiceRef?.get()?.setMuted(isMuted)
            notifyAudioState(isMuted, isSpeakerOn)
        } catch (e: Exception) {
            Log.e(TAG, "Error toggling mute: ${e.message}")
        }
        return isMuted
    }

    fun toggleSpeaker(): Boolean {
        isSpeakerOn = !isSpeakerOn
        try {
            val route = if (isSpeakerOn) CallAudioState.ROUTE_SPEAKER else CallAudioState.ROUTE_EARPIECE
            activeServiceRef?.get()?.setAudioRoute(route)
            notifyAudioState(isMuted, isSpeakerOn)
        } catch (e: Exception) {
            Log.e(TAG, "Error toggling speaker: ${e.message}")
        }
        return isSpeakerOn
    }

    fun toggleHold(): Boolean {
        currentCall?.let { call ->
            try {
                if (isOnHold) {
                    call.unhold()
                    isOnHold = false
                } else {
                    call.hold()
                    isOnHold = true
                }
            } catch (e: Exception) {
                Log.e(TAG, "Error toggling hold: ${e.message}")
            }
        }
        return isOnHold
    }

    fun playDtmf(digit: Char) {
        currentCall?.let { call ->
            try {
                call.playDtmfTone(digit)
                call.stopDtmfTone()
            } catch (e: Exception) {
                Log.e(TAG, "Error playing DTMF tone: ${e.message}")
            }
        }
    }
}
