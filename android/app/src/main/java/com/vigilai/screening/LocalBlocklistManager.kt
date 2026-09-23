package com.vigilai.screening

import android.content.Context
import android.util.Log

/**
 * Local persistent blacklist manager for VIGIL-AI Android Telephony screening.
 * 
 * Ensures that high-risk and explicitly blocked phone numbers are IMMEDIATELY
 * rejected by Android Telecom with zero lag, even if the backend is temporarily
 * unreachable or the network is degraded.
 * 
 * Dynamic: Populated dynamically via user actions and backend screening verdicts.
 * Zero hardcoded phone numbers in production.
 */
object LocalBlocklistManager {
    private const val TAG = "LocalBlocklist"
    private const val PREFS_NAME = "vigil_blocklist_prefs"
    private const val KEY_BLOCKED_NUMBERS = "blocked_numbers"

    // In-memory runtime blocked set (dynamically populated)
    private val runtimeBlocked = mutableSetOf<String>()

    /**
     * Checks whether the phone number is present in either the memory or persistent blocklist.
     */
    fun isBlocked(context: Context?, rawNumber: String?): Boolean {
        if (rawNumber.isNullOrBlank()) return false
        val clean = rawNumber.replace(Regex("[^0-9+]"), "")

        // 1. Check in-memory set
        if (runtimeBlocked.contains(clean)) {
            Log.i(TAG, "Number $clean matched in runtime blocklist!")
            return true
        }

        // 2. Check SharedPreferences if context is available
        if (context != null) {
            try {
                val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                val set = prefs.getStringSet(KEY_BLOCKED_NUMBERS, null)
                if (set != null && set.contains(clean)) {
                    Log.i(TAG, "Number $clean matched in persistent SharedPreferences blocklist!")
                    return true
                }
            } catch (e: Exception) {
                Log.w(TAG, "Error checking persistent blocklist: ${e.message}")
            }
        }

        return false
    }

    /**
     * Persists a phone number to the local blocklist.
     */
    fun addBlocked(context: Context?, rawNumber: String?) {
        if (rawNumber.isNullOrBlank()) return
        val clean = rawNumber.replace(Regex("[^0-9+]"), "")
        runtimeBlocked.add(clean)

        if (context != null) {
            try {
                val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                val existing = prefs.getStringSet(KEY_BLOCKED_NUMBERS, mutableSetOf())?.toMutableSet() ?: mutableSetOf()
                existing.add(clean)
                prefs.edit().putStringSet(KEY_BLOCKED_NUMBERS, existing).apply()
                Log.i(TAG, "Added $clean to local persistent blocklist.")
            } catch (e: Exception) {
                Log.w(TAG, "Failed to persist blocked number: ${e.message}")
            }
        }
    }

    /**
     * Removes a number from the persistent and memory blocklist.
     */
    fun removeBlocked(context: Context?, rawNumber: String?) {
        if (rawNumber.isNullOrBlank()) return
        val clean = rawNumber.replace(Regex("[^0-9+]"), "")
        runtimeBlocked.remove(clean)

        if (context != null) {
            try {
                val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                val existing = prefs.getStringSet(KEY_BLOCKED_NUMBERS, mutableSetOf())?.toMutableSet() ?: mutableSetOf()
                existing.remove(clean)
                prefs.edit().putStringSet(KEY_BLOCKED_NUMBERS, existing).apply()
                Log.i(TAG, "Removed $clean from local blocklist.")
            } catch (e: Exception) {
                Log.w(TAG, "Failed to remove blocked number: ${e.message}")
            }
        }
    }

    /**
     * Clears all blocked numbers from both memory and persistent storage.
     * Used for full reset when user requests resetting protection.
     */
    fun clearAllBlocked(context: Context?) {
        runtimeBlocked.clear()
        if (context != null) {
            try {
                val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                prefs.edit().remove(KEY_BLOCKED_NUMBERS).apply()
                Log.i(TAG, "Cleared ALL numbers from local persistent blocklist.")
            } catch (e: Exception) {
                Log.w(TAG, "Failed to clear blocklist: ${e.message}")
            }
        }
    }

    /**
     * Retrieves all active blocked numbers.
     */
    fun getBlockedNumbers(context: Context?): List<String> {
        val result = LinkedHashSet<String>()
        result.addAll(runtimeBlocked)
        if (context != null) {
            try {
                val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                val set = prefs.getStringSet(KEY_BLOCKED_NUMBERS, null)
                if (set != null) {
                    result.addAll(set)
                }
            } catch (e: Exception) {
                Log.w(TAG, "Error fetching blocked numbers: ${e.message}")
            }
        }
        return result.toList()
    }

    fun getSavedBackendUrl(context: Context): String {
        return com.vigilai.config.VigilConfig.getBaseUrl(context)
    }

    fun saveBackendUrl(context: Context, url: String) {
        com.vigilai.config.VigilConfig.setBaseUrl(context, url)
        com.vigilai.network.VigilApiClient.backendBaseUrl = url
        com.vigilai.network.CallerLookupClient.baseUrl = url
    }
}
