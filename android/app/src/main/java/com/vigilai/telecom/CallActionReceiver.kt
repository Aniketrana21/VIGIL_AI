package com.vigilai.telecom

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import com.vigilai.ui.InCallActivity

/**
 * BroadcastReceiver for handling Answer and Decline button clicks from the
 * high-priority heads-up call banner ("Look Above" incoming call notification).
 */
class CallActionReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent?) {
        val action = intent?.action ?: return
        Log.i("CallActionReceiver", "Received call banner action: $action")

        when (action) {
            CallNotificationManager.ACTION_ANSWER_CALL -> {
                CallNotificationManager.cancelIncomingCallNotification(context)
                CallManager.answerCall()

                // Bring InCallActivity to foreground for active conversation
                val inCallIntent = Intent(context, InCallActivity::class.java).apply {
                    flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
                    putExtra("PHONE_NUMBER", intent.getStringExtra("PHONE_NUMBER"))
                    putExtra("CALLER_NAME", intent.getStringExtra("CALLER_NAME"))
                }
                context.startActivity(inCallIntent)
            }

            CallNotificationManager.ACTION_DECLINE_CALL -> {
                CallNotificationManager.cancelIncomingCallNotification(context)
                CallManager.rejectCall()
            }
        }
    }
}
