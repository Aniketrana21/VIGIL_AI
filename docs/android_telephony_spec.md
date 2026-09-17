# VIGIL-AI: Android Platform Integration & Telephony Specification
**Architecture, Platform Limitations, and Technical Workarounds (Mode A vs. Mode B)**

---

## 1. Executive Problem Statement: Android Call Audio Isolation

A common misconception in security tool design is that an Android app can simply tap into a phone call in progress and stream the downlink caller audio into an AI pipeline.

### The Android Security Sandbox Reality:
1. **Android 9 (Pie / API 28) and earlier:**
   - Some applications exploited `MediaRecorder.AudioSource.VOICE_CALL`, `VOICE_DOWNLINK`, or `VOICE_UPLINK` to capture cellular call audio.
2. **Android 10 (API 29) to Android 15:**
   - Google completely locked down these audio sources.
   - `AudioSource.VOICE_CALL` and `VOICE_DOWNLINK` are restricted strictly to system applications signed with the platform certificate or applications holding the signature permission:
     ```xml
     android.permission.CAPTURE_AUDIO_OUTPUT
     ```
   - Normal third-party apps requesting this permission will have it rejected by the OS at install time.
3. **Accessibility API Bans (Google Play Policy 2022+):**
   - Google explicitly prohibited using the `AccessibilityService` API for audio call recording, removing non-compliant apps from the Play Store.

---

## 2. VIGIL-AI's Two-Mode Strategy

To operate realistically in enterprise, consumer, and hackathon demonstration environments without making false assumptions about the OS, VIGIL-AI partitions functionality into two cleanly decoupled modes:

```
+----------------------------------------------------------------------------------------------------+
|                                         VIGIL-AI MODES                                             |
+----------------------------------------------------------------------------------------------------+
|                                                                                                    |
|  [ MODE A: Demo / VoIP / Real-time Voice Stream ]    [ MODE B: Android Cellular Telephony System ]  |
|                                                                                                    |
|  - Real-time PCM audio streaming via WebSocket       - Pre-call screening via TelecomManager       |
|  - Ingestion from:                                   - CallScreeningService + RoleManager          |
|    * WebRTC browser client                           - STIR/SHAKEN verification level extraction   |
|    * Mobile mic / VoIP companion service             - Caller ID reputation & threat scoring       |
|    * Softphone / Customer support audio feed         - Programmatic call drop / silence / warn     |
|  - Full AI pipeline active:                          - Heads-up alert overlay HUD                  |
|    * VAD + WavLM/AASIST + ECAPA-TDNN                 - User-assisted loudspeaker mic analysis      |
|    * Continuous risk scoring (<360ms latency)                                                      |
+----------------------------------------------------------------------------------------------------+
```

---

## 3. MODE B: Android Cellular Integration Architecture

### 3.1. Core Components

```
                Incoming Call Event (GSM / VoLTE / VoNR)
                               |
                               v
               +-------------------------------+
               |    Android Telecom Framework   |
               +---------------+---------------+
                               |
                               v
               +-------------------------------+
               |  VigilCallScreeningService    | <--- RoleManager.ROLE_CALL_SCREENING
               +---------------+---------------+
                               |
               +---------------+---------------+
               | Calls VIGIL-AI Backend REST   |
               | (Phone #, STIR/SHAKEN, Carrier|
               +---------------+---------------+
                               |
       +-----------------------+-----------------------+
       |                                               |
       v                                               v
[ Risk Score < Threshold ]                 [ Risk Score >= High Alert ]
       |                                               |
       v                                               v
CallResponse.Builder()                     CallResponse.Builder()
  .setDisallowCall(false)                    .setDisallowCall(true)
  .setRejectCall(false)                      .setRejectCall(true)
  .setSkipCallLog(false)                     .setSkipNotification(true)
  .build()                                   .build()
```

### 3.2. RoleManager & CallScreeningService Registration

To intercept incoming calls prior to the user being alerted, the app must request and be granted the `ROLE_CALL_SCREENING` role.

#### Kotlin Implementation: Requesting Role
```kotlin
// In MainActivity.kt
import android.app.role.RoleManager
import android.content.Context
import android.content.Intent
import androidx.activity.result.contract.ActivityResultContracts

class MainActivity : ComponentActivity() {
    private val roleManager by lazy {
        getSystemService(Context.ROLE_SERVICE) as RoleManager
    }

    private val callScreeningRoleLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (roleManager.isRoleHeld(RoleManager.ROLE_CALL_SCREENING)) {
            // VIGIL-AI is now the active call screening handler
            Log.i("VigilAI", "ROLE_CALL_SCREENING successfully granted.")
        } else {
            Log.w("VigilAI", "ROLE_CALL_SCREENING denied by user.")
        }
    }

    fun requestCallScreeningRole() {
        if (roleManager.isRoleAvailable(RoleManager.ROLE_CALL_SCREENING)) {
            if (!roleManager.isRoleHeld(RoleManager.ROLE_CALL_SCREENING)) {
                val intent = roleManager.createRequestRoleIntent(RoleManager.ROLE_CALL_SCREENING)
                callScreeningRoleLauncher.launch(intent)
            }
        }
    }
}
```

#### Manifest Declaration
```xml
<service
    android:name=".service.VigilCallScreeningService"
    android:permission="android.permission.BIND_SCREENING_SERVICE"
    android:exported="true">
    <intent-filter>
        <action android:name="android.telecom.CallScreeningService" />
    </intent-filter>
</service>
```

### 3.3. Call Screening & Metadata Signals

The `Call.Details` object provides critical pre-call intelligence:

```kotlin
package com.vigilai.service

import android.telecom.Call
import android.telecom.CallScreeningService
import android.os.Build
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

class VigilCallScreeningService : CallScreeningService() {
    private val serviceScope = CoroutineScope(Dispatchers.IO)

    override fun onScreenCall(callDetails: Call.Details) {
        val rawHandle = callDetails.handle?.schemeSpecificPart ?: "UNKNOWN"
        val callerDisplayName = callDetails.callerDisplayName ?: ""
        
        // Extract STIR/SHAKEN Caller Verification Status (API 30+)
        val verificationStatus = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            callDetails.callerNumberVerificationStatus
        } else {
            Call.Details.CALLER_NUMBER_VERIFICATION_STATUS_NOT_VERIFIED
        }

        serviceScope.launch {
            // 1. Query VIGIL-AI Backend for reputation & known voice clone reports
            val riskResult = VigilApiClient.queryCallerRisk(
                phoneNumber = rawHandle,
                displayName = callerDisplayName,
                stirShakenStatus = verificationStatus
            )

            // 2. Formulate CallResponse based on policy
            val responseBuilder = CallResponse.Builder()
            
            when (riskResult.action) {
                Action.BLOCK -> {
                    responseBuilder.setDisallowCall(true)
                    responseBuilder.setRejectCall(true)
                    responseBuilder.setSkipCallLog(false)
                    responseBuilder.setSkipNotification(true)
                    Log.w("VigilAI", "Blocked high-risk impersonation call from: $rawHandle")
                }
                Action.WARN -> {
                    responseBuilder.setDisallowCall(false)
                    // Trigger Heads-Up Warning Overlay
                    CallAlertOverlayService.showWarningNotification(
                        context = applicationContext,
                        caller = rawHandle,
                        riskScore = riskResult.riskScore,
                        reason = riskResult.reason
                    )
                }
                Action.ALLOW -> {
                    responseBuilder.setDisallowCall(false)
                }
            }

            respondToCall(callDetails, responseBuilder.build())
        }
    }
}
```

---

## 4. In-Call Analysis Workarounds on Android

When a call is answered, how can deepfake audio analysis occur on Android? VIGIL-AI identifies three realistic pathways:

| Method | Feasibility | Privacy/Store Compliance | Description |
|---|---|---|---|
| **Loudspeaker Ambient Mic (Mode B Sub-Mode)** | **High (Supported)** | **100% Compliant** | When user activates speakerphone, ambient mic (`AudioSource.MIC`) records the caller's acoustic output from the phone's loudspeaker and runs VIGIL-AI stream analysis. |
| **VoIP / In-App Companion (Mode A)** | **High (Supported)** | **100% Compliant** | Any app using WebRTC or custom VoIP can directly feed the raw digital PCM stream into VIGIL-AI SDK. |
| **Enterprise MDM / Rooted Device** | **Limited (Demo Only)** | **Enterprise Only** | On rooted or custom OEM ROM builds, privileged daemon injects into `AudioFlinger` / ALSA mixer to pull raw downlink streams. |

### Acoustic Speakerphone Capture Implementation
When the user toggles "Speakerphone AI Guard" in the VIGIL-AI Android app:
1. `AudioManager.isSpeakerphoneOn` is monitored.
2. An `AudioRecord` session is opened using `AudioSource.MIC` (or `VOICE_RECOGNITION` to bypass some phone noise filters).
3. Audio is piped directly over a TLS-secured WebSocket to the VIGIL-AI backend for real-time inference.
4. If a clone or replay is detected, a floating system overlay HUD flashes an urgent banner: **"POTENTIAL VOICE CLONE DETECTED - VERIFY VIA CALL-BACK"**.

---

## 5. Security & Permission Matrix

| Permission | Android Level | Purpose |
|---|---|---|
| `android.permission.RECORD_AUDIO` | Runtime (Dangerous) | Mode A VoIP & Mode B speakerphone ambient analysis |
| `android.permission.READ_PHONE_STATE` | Runtime (Dangerous) | Telephony state monitoring |
| `android.permission.SYSTEM_ALERT_WINDOW` | Special App Access | Heads-Up floating security HUD over active calls |
| `android.permission.FOREGROUND_SERVICE` | Normal | Persistent background monitoring during active calls |
| `android.permission.FOREGROUND_SERVICE_MICROPHONE` | API 34+ (Android 14) | Mandatory foreground service type for mic capture |
| `android.permission.INTERNET` | Normal | WebSocket and REST API telemetry to VIGIL-AI backend |
