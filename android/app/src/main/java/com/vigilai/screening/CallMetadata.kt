package com.vigilai.screening

import android.net.Uri
import android.os.Build
import android.telecom.Call
import android.telecom.Connection
import android.telecom.TelecomManager

/**
 * Encapsulates incoming call metadata strictly exposed by the Android Telecom framework.
 *
 * CRITICAL PLATFORM ARCHITECTURE CONSTRAINT:
 * Android's [android.telecom.CallScreeningService] does NOT provide raw two-way cellular
 * call audio streams. Telephony call screening and real-time audio analysis (e.g. VoIP /
 * microphone streaming Mode A) are separate components.
 */
data class CallMetadata(
    /**
     * Normalized phone number or SIP address extracted from [Call.Details.getHandle].
     */
    val rawHandle: String,

    /**
     * Normalized E.164 phone number if parseable, or raw handle.
     */
    val phoneNumber: String,

    /**
     * Caller-provided display name extracted from [Call.Details.getCallerDisplayName].
     */
    val callerDisplayName: String?,

    /**
     * Presentation requirement for caller display name (e.g. PRESENTATION_ALLOWED).
     */
    val callerDisplayNamePresentation: Int,

    /**
     * Presentation requirement for phone number handle (e.g. PRESENTATION_ALLOWED).
     */
    val handlePresentation: Int,

    /**
     * STIR/SHAKEN cryptographic caller verification status (API 30+):
     * - [STATUS_NOT_VERIFIED] (0)
     * - [STATUS_PASSED] (1)
     * - [STATUS_FAILED] (2)
     */
    val callerNumberVerificationStatus: Int,

    /**
     * Epoch timestamp when screening commenced on the device.
     */
    val timestampMillis: Long = System.currentTimeMillis(),

    /**
     * Call direction, expected to be [Call.Details.DIRECTION_INCOMING].
     */
    val callDirection: Int = Call.Details.DIRECTION_INCOMING,

    /**
     * Contact photo URI if populated by Telecom.
     */
    val contactPhotoUri: Uri? = null,

    /**
     * Indicates whether the phone number exists in local contacts / address book.
     */
    val isKnownContact: Boolean = false,

    /**
     * Network carrier code or SIM slot ID if available.
     */
    val carrierCode: String? = null
) {
    /**
     * Returns true if the caller presentation is restricted, private, or unknown.
     */
    val isRestrictedOrUnknownPresentation: Boolean
        get() = handlePresentation == TelecomManager.PRESENTATION_RESTRICTED ||
                handlePresentation == TelecomManager.PRESENTATION_UNKNOWN ||
                handlePresentation == TelecomManager.PRESENTATION_PAYPHONE

    /**
     * Returns true if STIR/SHAKEN cryptographic signature was fully validated by the carrier.
     */
    val isStirShakenVerified: Boolean
        get() = callerNumberVerificationStatus == STATUS_PASSED

    /**
     * Returns true if STIR/SHAKEN cryptographic signature failed validation (spoofing indicator).
     */
    val isStirShakenFailed: Boolean
        get() = callerNumberVerificationStatus == STATUS_FAILED

    /**
     * Returns an anonymized / masked version of the phone number for secure logging (e.g. "+1234****89").
     */
    fun toMaskedNumber(): String {
        if (rawHandle.length <= 4) return "****"
        val prefixLen = if (rawHandle.length > 7) 4 else 2
        val suffixLen = 2
        val prefix = rawHandle.take(prefixLen)
        val suffix = rawHandle.takeLast(suffixLen)
        return "$prefix****$suffix"
    }

    companion object {
        // Canonical STIR/SHAKEN caller verification status constants (Android 11+ / API 30+)
        const val STATUS_NOT_VERIFIED = 0
        const val STATUS_PASSED = 1
        const val STATUS_FAILED = 2

        /**
         * Safely extracts only the Telecom-exposed metadata from a [Call.Details] instance.
         */
        fun fromCallDetails(
            callDetails: Call.Details,
            isKnownContact: Boolean = false,
            carrierCode: String? = null
        ): CallMetadata {
            val handleUri = callDetails.handle
            val rawHandle = handleUri?.schemeSpecificPart ?: "UNKNOWN"

            val stirShakenStatus = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                callDetails.callerNumberVerificationStatus
            } else {
                STATUS_NOT_VERIFIED
            }

            val handlePres = callDetails.handlePresentation
            val namePres = callDetails.callerDisplayNamePresentation

            val contactPhoto = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                callDetails.contactPhotoUri
            } else {
                null
            }

            return CallMetadata(
                rawHandle = rawHandle,
                phoneNumber = rawHandle,
                callerDisplayName = callDetails.callerDisplayName,
                callerDisplayNamePresentation = namePres,
                handlePresentation = handlePres,
                callerNumberVerificationStatus = stirShakenStatus,
                timestampMillis = System.currentTimeMillis(),
                callDirection = Call.Details.DIRECTION_INCOMING,
                contactPhotoUri = contactPhoto,
                isKnownContact = isKnownContact,
                carrierCode = carrierCode
            )
        }
    }
}
