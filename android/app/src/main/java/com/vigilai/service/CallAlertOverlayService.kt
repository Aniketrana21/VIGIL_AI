package com.vigilai.service

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.PixelFormat
import android.os.Build
import android.os.IBinder
import android.view.Gravity
import android.view.LayoutInflater
import android.view.View
import android.view.WindowManager
import android.widget.TextView
import androidx.core.app.NotificationCompat
import com.vigilai.R

/**
 * System Overlay & Floating Alert Service.
 * Displays a non-intrusive Heads-Up Display (HUD) security banner over active calls
 * when the VIGIL-AI Risk Engine detects synthetic speech or suspicious caller signals.
 */
class CallAlertOverlayService : Service() {

    private var windowManager: WindowManager? = null
    private var overlayView: View? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val caller = intent?.getStringExtra("EXTRA_CALLER") ?: "UNKNOWN"
        val riskScore = intent?.getFloatExtra("EXTRA_RISK_SCORE", 0.0f) ?: 0.0f
        val reason = intent?.getStringExtra("EXTRA_REASON") ?: "Potential Voice Clone Detected"

        showHeadsUpNotification(caller, riskScore, reason)
        return START_NOT_STICKY
    }

    private fun showHeadsUpNotification(caller: String, riskScore: Float, reason: String) {
        val notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_notify_error)
            .setContentTitle("VIGIL-AI: Impersonation Warning ($caller)")
            .setContentText("Risk: ${(riskScore * 100).toInt()}% - $reason")
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setAutoCancel(true)
            .build()

        val notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        notificationManager.notify(NOTIFICATION_ID, notification)
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "VIGIL-AI Security Alerts",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "Critical real-time voice clone and impersonation warning banners"
            }
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }
    }

    companion object {
        const val CHANNEL_ID = "vigil_ai_alerts"
        const val NOTIFICATION_ID = 9001

        fun showWarningAlert(context: Context, caller: String, riskScore: Float, reason: String) {
            val intent = Intent(context, CallAlertOverlayService::class.java).apply {
                putExtra("EXTRA_CALLER", caller)
                putExtra("EXTRA_RISK_SCORE", riskScore)
                putExtra("EXTRA_REASON", reason)
            }
            context.startService(intent)
        }
    }
}
