package com.vigilai.storage

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.database.Cursor
import android.net.Uri
import android.provider.ContactsContract
import android.telecom.Call
import android.util.Log
import androidx.core.content.ContextCompat

/**
 * Universal contact resolver for incoming and outgoing phone calls.
 * Ensures the real contact name (e.g., "Aniket Tut 1") is always shown on:
 * - The Heads-up Notification Banner ("Look Above")
 * - The In-Call Screen (InCallActivity)
 * - The Call Screening Service
 */
object ContactLookupHelper {
    private const val TAG = "ContactLookupHelper"

    /**
     * Resolves the real contact name for a phone number or Telecom Call instance.
     * Order of resolution:
     * 1. Telecom Call.Details.contactDisplayName
     * 2. Android System Contacts Provider (ContactsContract.PhoneLookup)
     * 3. Local VIGIL-AI KnownPersonRepository
     * 4. Formatted phone number fallback
     */
    fun resolveCallerName(context: Context, call: Call?, rawNumber: String?): String {
        // 1. Telecom caller display name
        val telecomName = call?.details?.callerDisplayName ?: call?.details?.contactDisplayName
        if (!telecomName.isNullOrBlank()) {
            return telecomName
        }

        val number = rawNumber ?: call?.details?.handle?.schemeSpecificPart ?: return "Unknown"

        // 2. Android ContactsContract.PhoneLookup
        val systemName = lookupInPhonebook(context, number)
        if (!systemName.isNullOrBlank()) {
            return systemName
        }

        // 3. KnownPersonRepository
        val kp = KnownPersonRepository.getKnownPerson(context, number)
        if (kp != null && kp.name.isNotBlank() && kp.name != "Unknown") {
            return kp.name
        }

        return formatPhoneNumber(number)
    }

    /**
     * Queries the device's system contact book using PhoneLookup.
     */
    fun lookupInPhonebook(context: Context, rawNumber: String?): String? {
        if (rawNumber.isNullOrBlank()) return null
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.READ_CONTACTS) != PackageManager.PERMISSION_GRANTED) {
            return null
        }

        return try {
            val uri = Uri.withAppendedPath(
                ContactsContract.PhoneLookup.CONTENT_FILTER_URI,
                Uri.encode(rawNumber)
            )
            val projection = arrayOf(
                ContactsContract.PhoneLookup.DISPLAY_NAME,
                ContactsContract.PhoneLookup.NUMBER
            )
            context.contentResolver.query(uri, projection, null, null, null)?.use { cursor ->
                if (cursor.moveToFirst()) {
                    val nameIdx = cursor.getColumnIndex(ContactsContract.PhoneLookup.DISPLAY_NAME)
                    if (nameIdx >= 0) {
                        val name = cursor.getString(nameIdx)
                        if (!name.isNullOrBlank()) return name
                    }
                }
                null
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error looking up contact in phonebook: ${e.message}")
            null
        }
    }

    /**
     * Formats phone numbers nicely (e.g. "+91 88499 34960 | India HD").
     */
    fun formatPhoneNumberWithRegion(number: String?): String {
        if (number.isNullOrBlank()) return "Unknown"
        val clean = number.replace(" ", "").replace("-", "")
        return if (clean.startsWith("+91") && clean.length == 13) {
            "+91 " + clean.substring(3, 8) + " " + clean.substring(8) + "  |  India"
        } else if (clean.length == 10) {
            clean.substring(0, 5) + " " + clean.substring(5) + "  |  India"
        } else {
            "$number  |  Cellular"
        }
    }

    fun formatPhoneNumber(number: String?): String {
        if (number.isNullOrBlank()) return "Unknown"
        val clean = number.replace(" ", "").replace("-", "")
        return if (clean.startsWith("+91") && clean.length == 13) {
            "+91 " + clean.substring(3, 8) + " " + clean.substring(8)
        } else clean
    }

    fun cleanNumberForDial(number: String): String {
        // Preserves '+' for international dialing, strips spaces, hyphens, parentheses
        return number.replace(Regex("[^0-9+]"), "")
    }
}
