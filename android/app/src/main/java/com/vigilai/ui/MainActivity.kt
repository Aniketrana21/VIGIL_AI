package com.vigilai.ui

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import com.vigilai.network.VigilApiClient
import com.vigilai.screening.CallScreeningRoleHelper
import com.vigilai.service.AudioStreamVoipService

class MainActivity : Activity() {

    private val REQUEST_ID_CALL_SCREENING = 101
    private lateinit var statusView: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(50, 80, 50, 50)
            setBackgroundColor(Color.parseColor("#0F172A"))
        }

        val titleView = TextView(this).apply {
            text = "VIGIL-AI Voice Security"
            textSize = 24f
            setTextColor(Color.parseColor("#F8FAFC"))
            setTypeface(null, Typeface.BOLD)
        }
        layout.addView(titleView)

        val subtitleView = TextView(this).apply {
            text = "Autonomous Deepfake & Impersonation Defense"
            textSize = 14f
            setTextColor(Color.parseColor("#94A3B8"))
            setPadding(0, 10, 0, 30)
        }
        layout.addView(subtitleView)

        statusView = TextView(this).apply {
            textSize = 15f
            setTextColor(Color.parseColor("#E2E8F0"))
            setPadding(0, 20, 0, 30)
        }
        layout.addView(statusView)

        val btnRole = Button(this).apply {
            text = "Enable Call Screening (Mode B)"
            setBackgroundColor(Color.parseColor("#3B82F6"))
            setTextColor(Color.WHITE)
            setOnClickListener {
                requestCallScreeningRole()
            }
        }
        layout.addView(btnRole)

        val btnVoip = Button(this).apply {
            text = "Start Microphone Stream (Mode A)"
            setBackgroundColor(Color.parseColor("#10B981"))
            setTextColor(Color.WHITE)
            setPadding(0, 20, 0, 20)
            setOnClickListener {
                val streamIntent = Intent(this@MainActivity, AudioStreamVoipService::class.java)
                startService(streamIntent)
                Toast.makeText(this@MainActivity, "Streaming mic audio to VIGIL-AI pipeline...", Toast.LENGTH_SHORT).show()
            }
        }
        layout.addView(btnVoip)

        setContentView(layout)
        updateStatus()
    }

    override fun onResume() {
        super.onResume()
        updateStatus()
    }

    private fun updateStatus() {
        val roleDesc = CallScreeningRoleHelper.getRoleStatusDescription(this)
        statusView.text = buildString {
            append("• Mode B (CallScreening): $roleDesc\n")
            append("• Backend: ${VigilApiClient.backendBaseUrl}\n")
            append("• STIR/SHAKEN: Hardware Attestation Active\n")
            append("• Latency Budget: 3500ms max (OS limit: 5000ms)")
        }
    }

    private fun requestCallScreeningRole() {
        if (!CallScreeningRoleHelper.isCallScreeningRoleSupported()) {
            Toast.makeText(this, "Call screening requires Android 10 (API 29) or higher", Toast.LENGTH_LONG).show()
            return
        }

        if (CallScreeningRoleHelper.isRoleHeld(this)) {
            Toast.makeText(this, "VIGIL-AI is already the active Call Screening service!", Toast.LENGTH_SHORT).show()
            return
        }

        val requestIntent = CallScreeningRoleHelper.createRequestRoleIntent(this)
        if (requestIntent != null) {
            startActivityForResult(requestIntent, REQUEST_ID_CALL_SCREENING)
        } else {
            Toast.makeText(this, "ROLE_CALL_SCREENING is not available on this device", Toast.LENGTH_LONG).show()
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQUEST_ID_CALL_SCREENING) {
            if (resultCode == RESULT_OK) {
                Toast.makeText(this, "ROLE_CALL_SCREENING granted to VIGIL-AI!", Toast.LENGTH_SHORT).show()
            } else {
                Toast.makeText(this, "Call screening role request was declined", Toast.LENGTH_SHORT).show()
            }
            updateStatus()
        }
    }
}
