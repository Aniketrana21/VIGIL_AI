package com.vigilai.service

import android.content.Intent
import android.telecom.Call
import android.telecom.InCallService
import android.util.Log
import com.vigilai.screening.LocalBlocklistManager
import com.vigilai.screening.ThreeStageProtectionEngine
import com.vigilai.telecom.CallManager
import com.vigilai.telecom.CallNotificationManager
import com.vigilai.ui.InCallActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * Android Telecom InCallService.
 * Handles active phone calls when VIGIL-AI is selected as the Default Phone Dialer.
 * Orchestrates real-time 3-stage protection for incoming carrier calls.
 */
class VigilInCallService : InCallService() {

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val tag = "VigilInCallService"

    override fun onBind(intent: Intent?): android.os.IBinder? {
        Log.i(tag, "INCALL_SERVICE_CONNECTED: Telecom framework bound to VigilInCallService.")
        CallManager.bindService(this)
        return super.onBind(intent)
    }

    override fun onUnbind(intent: Intent?): Boolean {
        CallManager.unbindService()
        return super.onUnbind(intent)
    }

    override fun onCallAudioStateChanged(audioState: android.telecom.CallAudioState?) {
        super.onCallAudioStateChanged(audioState)
        audioState?.let {
            CallManager.notifyAudioState(it.isMuted, it.route == android.telecom.CallAudioState.ROUTE_SPEAKER)
        }
    }

    override fun onCallAdded(call: Call) {
        super.onCallAdded(call)
        val handle = call.details?.handle
        val phoneNumber = handle?.schemeSpecificPart ?: "Unknown"

        Log.i(tag, "CALL_ADDED: Incoming/outgoing call received: $phoneNumber (State: ${call.state})")

        // Register call with central CallManager
        CallManager.registerCall(call)

        // Show Heads-Up Call Notification banner ("Look Above" banner) with Answer/Decline actions
        if (call.state == Call.STATE_RINGING) {
            CallNotificationManager.showIncomingCallNotification(this, phoneNumber)
        }

        // Launch in-call UI activity (handles screen-on / locked state)
        try {
            val inCallIntent = Intent(this, InCallActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP
                putExtra("PHONE_NUMBER", phoneNumber)
            }
            startActivity(inCallIntent)
        } catch (e: Exception) {
            Log.w(tag, "Direct startActivity deferred to FullScreenIntent notification: ${e.message}")
        }

        val callback = object : Call.Callback() {
            override fun onStateChanged(call: Call, state: Int) {
                super.onStateChanged(call, state)
                Log.i(tag, "CALL_STATE_CHANGED: State transitioned to $state for $phoneNumber")
                CallManager.notifyStateChanged(state)

                if (state == Call.STATE_ACTIVE || state == Call.STATE_DIALING || state == Call.STATE_CONNECTING) {
                    Log.i(tag, "CALL_STATE_CHANGED: Active or Dialing state for $phoneNumber - cancelling notifications")
                    CallNotificationManager.cancelIncomingCallNotification(this@VigilInCallService)
                } else if (state == Call.STATE_DISCONNECTED) {
                    Log.i(tag, "CALL_DISCONNECTED: Call disconnected for $phoneNumber")
                    CallNotificationManager.cancelIncomingCallNotification(this@VigilInCallService)
                    CallManager.unregisterCall(call)
                }

                if (state == Call.STATE_RINGING) {
                    CallNotificationManager.showIncomingCallNotification(this@VigilInCallService, phoneNumber)
                    processIncomingRingingCall(call, phoneNumber)
                }
            }
        }
        call.registerCallback(callback)

        if (call.state == Call.STATE_RINGING) {
            processIncomingRingingCall(call, phoneNumber)
        } else {
            CallNotificationManager.cancelIncomingCallNotification(this)
        }
    }

    override fun onCallRemoved(call: Call) {
        super.onCallRemoved(call)
        val handle = call.details?.handle
        val phoneNumber = handle?.schemeSpecificPart ?: "Unknown"
        Log.i(tag, "CALL_DISCONNECTED: Call removed from Telecom stack: $phoneNumber")
        CallNotificationManager.cancelIncomingCallNotification(this)
        CallManager.unregisterCall(call)
    }

    private fun processIncomingRingingCall(call: Call, phoneNumber: String) {
        if (call.state != Call.STATE_RINGING) return
        // Fast-path: Check offline local blocklist
        if (LocalBlocklistManager.isBlocked(applicationContext, phoneNumber)) {
            Log.w(tag, "CALL_STATE_CHANGED: Instant hardware drop for $phoneNumber (matched in local blocklist)")
            try {
                call.reject(Call.REJECT_REASON_DECLINED)
            } catch (e: Exception) {
                call.disconnect()
            }
            CallAlertOverlayService.showWarningAlert(
                context = applicationContext,
                caller = phoneNumber,
                riskScore = 1.0f,
                reason = "BLOCKED: Known threat caller dropped before ringing"
            )
            return
        }

        // Run 3-Stage Protection
        serviceScope.launch {
            try {
                val eval = ThreeStageProtectionEngine.evaluateCall(
                    context = applicationContext,
                    phoneNumber = phoneNumber
                )

                if (eval.finalVerdict == "BLOCK") {
                    Log.w(tag, "CALL_STATE_CHANGED: 3-Stage engine mandated BLOCK for $phoneNumber (Stopped at stage ${eval.stepStoppedAt})")
                    try {
                        call.reject(Call.REJECT_REASON_DECLINED)
                    } catch (e: Exception) {
                        call.disconnect()
                    }
                    CallAlertOverlayService.showWarningAlert(
                        context = applicationContext,
                        caller = phoneNumber,
                        riskScore = eval.stage3.riskScore / 100.0f,
                        reason = "${eval.stage1.voiceType}: ${eval.stage1.explanation}"
                    )
                } else {
                    Log.i(tag, "CALL_STATE_CHANGED: Call allowed through 3-Stage protection: $phoneNumber (${eval.finalVerdict})")
                }
            } catch (e: Exception) {
                Log.e(tag, "Error during 3-stage evaluation: ${e.message}")
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        serviceScope.cancel()
    }
}
