package com.vigilai.audio

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.util.Log
import androidx.core.content.ContextCompat
import kotlin.math.sqrt

/**
 * Categorization of captured audio origin.
 * Enforces strict honesty: Never pretend local mic audio is the remote caller.
 */
enum class AudioSourceOrigin(val description: String) {
    LOCAL_MIC_AUDIO("Device physical microphone (captures local user or room ambient sound)"),
    REMOTE_CALL_AUDIO("Direct digital cellular baseband downlink (remote party speech)"),
    MIXED_CALL_AUDIO("Hardware-mixed uplink and downlink audio"),
    DEMO_AUDIO("Controlled test/demo audio vector for SIH 2026 presentation"),
    NO_AUDIO("No audio signal captured or available"),
    UNKNOWN_AUDIO_SOURCE("Unknown / unverified audio origin")
}

/**
 * Result status of the Audio Feasibility Test.
 */
enum class AudioFeasibilityStatus {
    AUDIO_PATH_AVAILABLE,
    AUDIO_PATH_UNAVAILABLE,
    AUDIO_PATH_UNCERTAIN
}

/**
 * Diagnostic metrics for an individual AudioSource test.
 */
data class AudioSourceProbeResult(
    val sourceName: String,
    val sourceId: Int,
    val sampleRate: Int,
    val channelConfig: String,
    val encoding: String,
    val bufferSize: Int,
    val initialized: Boolean,
    val recordingStarted: Boolean,
    val bytesRead: Int,
    val nonZeroPcmDetected: Boolean,
    val rmsLevelDb: Float,
    val peakAmplitude: Int,
    val inferredOrigin: AudioSourceOrigin,
    val status: AudioFeasibilityStatus,
    val diagnosticReason: String
)

/**
 * Full summary report of the Audio Feasibility Investigation.
 */
data class AudioFeasibilityReport(
    val overallStatus: AudioFeasibilityStatus,
    val primaryOrigin: AudioSourceOrigin,
    val canAccessRemoteCallerAudioDirectly: Boolean,
    val probeResults: List<AudioSourceProbeResult>,
    val executiveSummary: String
)

/**
 * Android Audio Feasibility Probe.
 *
 * Evaluates real-time audio capture capabilities across all platform AudioSources
 * on physical hardware during cellular calls.
 *
 * Privacy Invariant:
 * Calculates only statistical energy metrics (RMS, peak, non-zero sample count).
 * Purges raw PCM bytes immediately. Never uploads or retains private call recordings.
 */
object AudioFeasibilityProbe {
    private const val TAG = "AudioFeasibilityProbe"

    /**
     * Executes the comprehensive diagnostic probe across supported AudioSources.
     */
    fun runProbe(context: Context): AudioFeasibilityReport {
        Log.i(TAG, "Starting AudioFeasibilityProbe on device: ${android.os.Build.MANUFACTURER} ${android.os.Build.MODEL} (Android ${android.os.Build.VERSION.RELEASE}, API ${android.os.Build.VERSION.SDK_INT})")

        val hasPermission = ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.RECORD_AUDIO
        ) == PackageManager.PERMISSION_GRANTED

        if (!hasPermission) {
            val unavail = AudioSourceProbeResult(
                sourceName = "ALL_SOURCES",
                sourceId = -1,
                sampleRate = 16000,
                channelConfig = "CHANNEL_IN_MONO",
                encoding = "ENCODING_PCM_16BIT",
                bufferSize = 0,
                initialized = false,
                recordingStarted = false,
                bytesRead = 0,
                nonZeroPcmDetected = false,
                rmsLevelDb = -100f,
                peakAmplitude = 0,
                inferredOrigin = AudioSourceOrigin.UNKNOWN_AUDIO_SOURCE,
                status = AudioFeasibilityStatus.AUDIO_PATH_UNAVAILABLE,
                diagnosticReason = "RECORD_AUDIO runtime permission not granted by user."
            )
            return AudioFeasibilityReport(
                overallStatus = AudioFeasibilityStatus.AUDIO_PATH_UNAVAILABLE,
                primaryOrigin = AudioSourceOrigin.UNKNOWN_AUDIO_SOURCE,
                canAccessRemoteCallerAudioDirectly = false,
                probeResults = listOf(unavail),
                executiveSummary = "AUDIO_PATH_UNAVAILABLE: android.permission.RECORD_AUDIO is not granted."
            )
        }

        val testSources = listOf(
            "MediaRecorder.AudioSource.MIC" to MediaRecorder.AudioSource.MIC,
            "MediaRecorder.AudioSource.VOICE_COMMUNICATION" to MediaRecorder.AudioSource.VOICE_COMMUNICATION,
            "MediaRecorder.AudioSource.DEFAULT" to MediaRecorder.AudioSource.DEFAULT,
            "MediaRecorder.AudioSource.VOICE_CALL (Requires system permission)" to 4, // MediaRecorder.AudioSource.VOICE_CALL
            "MediaRecorder.AudioSource.VOICE_DOWNLINK (Requires system permission)" to 3 // MediaRecorder.AudioSource.VOICE_DOWNLINK
        )

        val probeResults = mutableListOf<AudioSourceProbeResult>()

        for ((name, sourceId) in testSources) {
            val res = testIndividualSource(sourceId, name)
            probeResults.add(res)
            Log.i(TAG, "Source Probe [$name]: Status=${res.status}, NonZeroPCM=${res.nonZeroPcmDetected}, RMS=${res.rmsLevelDb}dB, Origin=${res.inferredOrigin}")
        }

        // Evaluate overall capability
        val micWorking = probeResults.firstOrNull { it.sourceId == MediaRecorder.AudioSource.MIC }?.nonZeroPcmDetected == true
        val directDownlinkWorking = probeResults.any {
            (it.sourceId == 3 || it.sourceId == 4) && it.nonZeroPcmDetected
        }

        val overallStatus = when {
            directDownlinkWorking -> AudioFeasibilityStatus.AUDIO_PATH_AVAILABLE
            micWorking -> AudioFeasibilityStatus.AUDIO_PATH_UNCERTAIN
            else -> AudioFeasibilityStatus.AUDIO_PATH_UNAVAILABLE
        }

        val primaryOrigin = when {
            directDownlinkWorking -> AudioSourceOrigin.REMOTE_CALL_AUDIO
            micWorking -> AudioSourceOrigin.LOCAL_MIC_AUDIO
            else -> AudioSourceOrigin.UNKNOWN_AUDIO_SOURCE
        }

        val summary = buildString {
            append("Audio Feasibility Test Verdict: $overallStatus\n")
            append("• Direct Cellular Downlink Access: ${if (directDownlinkWorking) "YES (Root/System App)" else "BLOCKED by Android OS (Standard Security Policy)"}\n")
            append("• Local Microphone Capture (AudioSource.MIC): ${if (micWorking) "AVAILABLE (Captures local user & room ambient sound)" else "UNAVAILABLE"}\n")
            if (!directDownlinkWorking && micWorking) {
                append("• Platform Architecture Notice: Android restricts direct baseband downlink PCM capture from 3rd-party non-system apps (CAPTURE_AUDIO_OUTPUT requires system signature). AudioSource.MIC captures local microphone audio only. Remote party voice can only be analyzed acoustically when Speakerphone / Loudspeaker (Mode A) is active or via CallScreeningService metadata (Mode B).")
            }
        }

        return AudioFeasibilityReport(
            overallStatus = overallStatus,
            primaryOrigin = primaryOrigin,
            canAccessRemoteCallerAudioDirectly = directDownlinkWorking,
            probeResults = probeResults,
            executiveSummary = summary
        )
    }

    private fun testIndividualSource(sourceId: Int, name: String): AudioSourceProbeResult {
        val sampleRate = 16000
        val channelConfig = AudioFormat.CHANNEL_IN_MONO
        val audioFormat = AudioFormat.ENCODING_PCM_16BIT
        val minBufferSize = AudioRecord.getMinBufferSize(sampleRate, channelConfig, audioFormat)
        val bufferSize = maxOf(minBufferSize, 3200) // 100ms

        var audioRecord: AudioRecord? = null
        var initialized = false
        var recordingStarted = false
        var bytesRead = 0
        var nonZeroCount = 0
        var peak = 0
        var sumSquares = 0.0

        try {
            audioRecord = AudioRecord(sourceId, sampleRate, channelConfig, audioFormat, bufferSize)
            initialized = audioRecord.state == AudioRecord.STATE_INITIALIZED

            if (initialized) {
                audioRecord.startRecording()
                recordingStarted = audioRecord.recordingState == AudioRecord.RECORDSTATE_RECORDING

                if (recordingStarted) {
                    val pcmBuffer = ShortArray(1600) // 100ms
                    val shortsRead = audioRecord.read(pcmBuffer, 0, pcmBuffer.size)
                    bytesRead = if (shortsRead > 0) shortsRead * 2 else 0

                    for (i in 0 until maxOf(0, shortsRead)) {
                        val sample = pcmBuffer[i].toInt()
                        val absVal = kotlin.math.abs(sample)
                        if (absVal > peak) peak = absVal
                        if (absVal > 10) nonZeroCount++ // Count above noise floor
                        sumSquares += sample * sample
                    }
                }
            }
        } catch (e: SecurityException) {
            return AudioSourceProbeResult(
                sourceName = name,
                sourceId = sourceId,
                sampleRate = sampleRate,
                channelConfig = "CHANNEL_IN_MONO",
                encoding = "ENCODING_PCM_16BIT",
                bufferSize = bufferSize,
                initialized = false,
                recordingStarted = false,
                bytesRead = 0,
                nonZeroPcmDetected = false,
                rmsLevelDb = -100f,
                peakAmplitude = 0,
                inferredOrigin = AudioSourceOrigin.UNKNOWN_AUDIO_SOURCE,
                status = AudioFeasibilityStatus.AUDIO_PATH_UNAVAILABLE,
                diagnosticReason = "SecurityException: Requires android.permission.CAPTURE_AUDIO_OUTPUT (System Signature app required): ${e.message}"
            )
        } catch (e: Exception) {
            return AudioSourceProbeResult(
                sourceName = name,
                sourceId = sourceId,
                sampleRate = sampleRate,
                channelConfig = "CHANNEL_IN_MONO",
                encoding = "ENCODING_PCM_16BIT",
                bufferSize = bufferSize,
                initialized = initialized,
                recordingStarted = recordingStarted,
                bytesRead = bytesRead,
                nonZeroPcmDetected = false,
                rmsLevelDb = -100f,
                peakAmplitude = 0,
                inferredOrigin = AudioSourceOrigin.UNKNOWN_AUDIO_SOURCE,
                status = AudioFeasibilityStatus.AUDIO_PATH_UNAVAILABLE,
                diagnosticReason = "Failed to capture audio: ${e.message}"
            )
        } finally {
            try {
                audioRecord?.stop()
                audioRecord?.release()
            } catch (e: Exception) {
                // Ignore cleanup errors
            }
        }

        val nonZeroPcm = nonZeroCount > 10
        val rms = if (bytesRead > 0) sqrt(sumSquares / (bytesRead / 2)) else 0.0
        val rmsDb = if (rms > 0.0) 20.0f * kotlin.math.log10(rms.toFloat() / 32768.0f) else -100f

        val origin = when (sourceId) {
            3 -> AudioSourceOrigin.REMOTE_CALL_AUDIO
            4 -> AudioSourceOrigin.MIXED_CALL_AUDIO
            else -> AudioSourceOrigin.LOCAL_MIC_AUDIO
        }

        val status = if (nonZeroPcm) {
            if (sourceId == 3 || sourceId == 4) AudioFeasibilityStatus.AUDIO_PATH_AVAILABLE
            else AudioFeasibilityStatus.AUDIO_PATH_UNCERTAIN // MIC captures local voice or ambient room
        } else {
            AudioFeasibilityStatus.AUDIO_PATH_UNAVAILABLE
        }

        val reason = when {
            !initialized -> "AudioRecord failed to initialize (State: UNINITIALIZED)"
            !recordingStarted -> "AudioRecord failed to start recording"
            bytesRead <= 0 -> "Read returned 0 bytes or error code"
            !nonZeroPcm -> "All samples were zero (Digital silence or telephony baseband muted)"
            sourceId == MediaRecorder.AudioSource.MIC -> "Audio capture active: Capturing LOCAL MICROPHONE (user speech / ambient room). Not direct digital cellular downlink."
            sourceId == 3 || sourceId == 4 -> "Raw cellular audio successfully captured!"
            else -> "Capturing audio via $name"
        }

        return AudioSourceProbeResult(
            sourceName = name,
            sourceId = sourceId,
            sampleRate = sampleRate,
            channelConfig = "CHANNEL_IN_MONO",
            encoding = "ENCODING_PCM_16BIT",
            bufferSize = bufferSize,
            initialized = initialized,
            recordingStarted = recordingStarted,
            bytesRead = bytesRead,
            nonZeroPcmDetected = nonZeroPcm,
            rmsLevelDb = rmsDb,
            peakAmplitude = peak,
            inferredOrigin = origin,
            status = status,
            diagnosticReason = reason
        )
    }
}
