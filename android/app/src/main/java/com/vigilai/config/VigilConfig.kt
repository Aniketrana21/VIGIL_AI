package com.vigilai.config

import android.content.Context
import android.util.Log

/**
 * Centralized Configuration System for VIGIL-AI.
 * Eliminates hardcoded local network IPs and manages operational modes cleanly.
 *
 * Modes:
 * - REAL_MODE: Live audio capture + real backend model inference.
 * - DEMO_MODE: Controlled prerecorded test vectors for SIH 2026 jury demonstration.
 * - TEST_MODE: Automated headless testing harness.
 */
object VigilConfig {
    private const val TAG = "VigilConfig"
    private const val PREFS_NAME = "vigil_ai_config_prefs"
    private const val KEY_BASE_URL = "vigil_api_base_url"
    private const val KEY_MODE = "vigil_execution_mode"

    // Default development gateway (Android emulator loopback host, or user Wi-Fi IP)
    const val DEFAULT_BASE_URL = "http://10.0.2.2:8000"

    // Demo authentication key strictly reserved for SIH hackathon demonstration.
    // Production deployments utilize ephemeral JWT session tokens issued during device registration.
    const val DEMO_ONLY_API_KEY = "vigil-ai-hackathon-demo-key-2026"

    const val MODE_REAL = "REAL_MODE"
    const val MODE_DEMO = "DEMO_MODE"
    const val MODE_TEST = "TEST_MODE"

    fun getBaseUrl(context: Context): String {
        return try {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val saved = prefs.getString(KEY_BASE_URL, null)
            if (!saved.isNullOrBlank()) saved else DEFAULT_BASE_URL
        } catch (e: Exception) {
            Log.w(TAG, "Could not load base URL from prefs: ${e.message}")
            DEFAULT_BASE_URL
        }
    }

    fun setBaseUrl(context: Context, url: String) {
        try {
            val clean = url.trim().removeSuffix("/")
            context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .edit()
                .putString(KEY_BASE_URL, clean)
                .apply()
            Log.i(TAG, "Backend base URL updated: $clean")
        } catch (e: Exception) {
            Log.w(TAG, "Failed to save base URL: ${e.message}")
        }
    }

    fun getWsUrl(context: Context): String {
        val httpUrl = getBaseUrl(context)
        return if (httpUrl.startsWith("https://")) {
            httpUrl.replaceFirst("https://", "wss://") + "/api/v1/stream/ingest"
        } else {
            httpUrl.replaceFirst("http://", "ws://") + "/api/v1/stream/ingest"
        }
    }

    fun getApiKey(context: Context): String {
        return DEMO_ONLY_API_KEY
    }

    fun getExecutionMode(context: Context): String {
        return try {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            prefs.getString(KEY_MODE, MODE_REAL) ?: MODE_REAL
        } catch (e: Exception) {
            MODE_REAL
        }
    }

    fun setExecutionMode(context: Context, mode: String) {
        try {
            context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .edit()
                .putString(KEY_MODE, mode)
                .apply()
        } catch (e: Exception) {
            Log.w(TAG, "Failed to save execution mode: ${e.message}")
        }
    }
}
