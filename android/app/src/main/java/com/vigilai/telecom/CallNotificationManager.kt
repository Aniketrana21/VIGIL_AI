package com.vigilai.telecom

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.RingtoneManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.vigilai.storage.DeviceContactsManager
import com.vigilai.storage.KnownPersonRepository
import com.vigilai.ui.InCallActivity

/**
 * Manages the High-Priority Heads-Up Incoming Call Notification ("Look Above" banner).
 * When an incoming cellular call rings while the user is inside any other application,
 * this posts a top floating banner with caller identification and one-tap Answer / Decline actions.
 * If the device is locked, it fires a full-screen intent waking the display to InCallActivity.
 */
object CallNotificationManager {

    const val CHANNEL_ID_INCOMING = "vigil_incoming_calls"
    const val NOTIFICATION_ID_INCOMING = 1001

    const val ACTION_ANSWER_CALL = "com.vigilai.ACTION_ANSWER_CALL"
    const val ACTION_DECLINE_CALL = "com.vigilai.ACTION_DECLINE_CALL"

    fun createNotificationChannel(context: Context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val name = "Incoming Calls"
            val descriptionText = "High-priority heads-up notifications for incoming phone calls"
            val importance = NotificationManager.IMPORTANCE_HIGH
            val channel = NotificationChannel(CHANNEL_ID_INCOMING, name, importance).apply {
                description = descriptionText
                lockscreenVisibility = NotificationCompat.VISIBILITY_PUBLIC
                enableVibration(true)
                val defaultRingtoneUri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
                setSound(
                    defaultRingtoneUri,
                    AudioAttributes.Builder()
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                        .setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE)
                        .build()
                )
            }
            val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            notificationManager.createNotificationChannel(channel)
        }
    }

    fun showIncomingCallNotification(context: Context, phoneNumber: String) {
        createNotificationChannel(context)

        // Resolve display name & relation using ContactLookupHelper (checks phonebook + known repo)
        val callerName = com.vigilai.storage.ContactLookupHelper.resolveCallerName(context, null, phoneNumber)
        val knownPerson = KnownPersonRepository.getKnownPerson(context, phoneNumber)
        val displayName = if (callerName != phoneNumber) callerName else com.vigilai.storage.ContactLookupHelper.formatPhoneNumber(phoneNumber)
        val subtitle = if (knownPerson != null) {
            "Relation: ${knownPerson.relation} • VIGIL-AI Verified"
        } else if (callerName != phoneNumber) {
            "${com.vigilai.storage.ContactLookupHelper.formatPhoneNumber(phoneNumber)} • VIGIL-AI Active"
        } else {
            "Incoming call • VIGIL-AI Active"
        }

        // Full Screen Intent to launch InCallActivity when locked or tapped
        val fullScreenIntent = Intent(context, InCallActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra("PHONE_NUMBER", phoneNumber)
            putExtra("CALLER_NAME", displayName)
        }
        val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        } else {
            PendingIntent.FLAG_UPDATE_CURRENT
        }
        val fullScreenPendingIntent = PendingIntent.getActivity(
            context,
            0,
            fullScreenIntent,
            flags
        )

        // Decline Action PendingIntent
        val declineIntent = Intent(context, CallActionReceiver::class.java).apply {
            action = ACTION_DECLINE_CALL
        }
        val declinePendingIntent = PendingIntent.getBroadcast(
            context,
            1,
            declineIntent,
            flags
        )

        // Answer Action PendingIntent
        val answerIntent = Intent(context, CallActionReceiver::class.java).apply {
            action = ACTION_ANSWER_CALL
            putExtra("PHONE_NUMBER", phoneNumber)
            putExtra("CALLER_NAME", displayName)
        }
        val answerPendingIntent = PendingIntent.getBroadcast(
            context,
            2,
            answerIntent,
            flags
        )

        val notification = NotificationCompat.Builder(context, CHANNEL_ID_INCOMING)
            .setSmallIcon(android.R.drawable.sym_call_incoming)
            .setContentTitle(displayName)
            .setContentText(subtitle)
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setCategory(NotificationCompat.CATEGORY_CALL)
            .setOngoing(true)
            .setAutoCancel(false)
            .setContentIntent(fullScreenPendingIntent)
            .setFullScreenIntent(fullScreenPendingIntent, true)
            .addAction(android.R.drawable.ic_menu_close_clear_cancel, "Decline", declinePendingIntent)
            .addAction(android.R.drawable.ic_menu_call, "Answer", answerPendingIntent)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .build()

        try {
            NotificationManagerCompat.from(context).notify(NOTIFICATION_ID_INCOMING, notification)
        } catch (e: SecurityException) {
            // Android 13+ POST_NOTIFICATIONS missing
        }
    }

    fun cancelIncomingCallNotification(context: Context) {
        NotificationManagerCompat.from(context).cancel(NOTIFICATION_ID_INCOMING)
    }
}
