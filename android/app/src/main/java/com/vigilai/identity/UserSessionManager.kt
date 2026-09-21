package com.vigilai.identity

import android.content.Context
import android.content.SharedPreferences
import android.os.Build
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.TimeUnit

/**
 * VIGIL-AI: User & Device Identity Session Manager.
 * 
 * Enforces Zero-Trust Dynamic Identity:
 * - Users are identified by UUID (never by phone number).
 * - Devices are identified by (user_id, device_uuid, installation_id).
 * - Fresh installs generate a new installation_id while preserving account user_id if restored.
 */
object UserSessionManager {
    private const val TAG = "UserSessionManager"
    private const val PREFS_NAME = "vigil_identity_prefs"
    private const val KEY_USER_ID = "vigil_user_id"
    private const val KEY_DEVICE_UUID = "vigil_device_uuid"
    private const val KEY_INSTALLATION_ID = "vigil_installation_id"
    private const val KEY_USER_NAME = "vigil_user_name"
    private const val KEY_USER_EMAIL = "vigil_user_email"
    private const val KEY_BACKEND_URL = "vigil_backend_url"
    private const val KEY_IS_REGISTERED = "vigil_device_registered"

    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.SECONDS)
        .build()

    @Volatile
    private var isInitialized = false

    private lateinit var prefs: SharedPreferences

    fun initialize(context: Context) {
        if (isInitialized) return
        synchronized(this) {
            if (isInitialized) return
            prefs = context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

            // 1. Ensure user_id exists (UUID)
            if (!prefs.contains(KEY_USER_ID)) {
                val newUserId = UUID.randomUUID().toString()
                prefs.edit().putString(KEY_USER_ID, newUserId).apply()
                Log.i(TAG, "Generated fresh user_id: $newUserId")
            }

            // 2. Ensure device_uuid exists (hardware-anchored UUID)
            if (!prefs.contains(KEY_DEVICE_UUID)) {
                val newDeviceUuid = UUID.randomUUID().toString()
                prefs.edit().putString(KEY_DEVICE_UUID, newDeviceUuid).apply()
                Log.i(TAG, "Generated persistent device_uuid: $newDeviceUuid")
            }

            // 3. Ensure installation_id exists (UUID per APK install)
            if (!prefs.contains(KEY_INSTALLATION_ID)) {
                val newInstallId = UUID.randomUUID().toString()
                prefs.edit().putString(KEY_INSTALLATION_ID, newInstallId).apply()
                Log.i(TAG, "Generated installation_id: $newInstallId")
            }

            isInitialized = true
        }
    }

    fun getUserId(context: Context): String {
        initialize(context)
        return prefs.getString(KEY_USER_ID, null) ?: UUID.randomUUID().toString()
    }

    fun getDeviceUuid(context: Context): String {
        initialize(context)
        return prefs.getString(KEY_DEVICE_UUID, null) ?: UUID.randomUUID().toString()
    }

    fun getInstallationId(context: Context): String {
        initialize(context)
        return prefs.getString(KEY_INSTALLATION_ID, null) ?: UUID.randomUUID().toString()
    }

    fun getUserName(context: Context): String {
        initialize(context)
        val uid = getUserId(context)
        return prefs.getString(KEY_USER_NAME, "User-${uid.take(8)}") ?: "User-${uid.take(8)}"
    }

    fun getUserEmail(context: Context): String {
        initialize(context)
        val uid = getUserId(context)
        return prefs.getString(KEY_USER_EMAIL, "$uid@vigil-ai.local") ?: "$uid@vigil-ai.local"
    }

    fun getBackendUrl(context: Context): String {
        return com.vigilai.screening.LocalBlocklistManager.getSavedBackendUrl(context)
    }

    fun setBackendUrl(context: Context, url: String) {
        com.vigilai.screening.LocalBlocklistManager.saveBackendUrl(context, url)
    }

    fun isDeviceRegistered(context: Context): Boolean {
        initialize(context)
        return prefs.getBoolean(KEY_IS_REGISTERED, false)
    }

    /**
     * Registers the user and device with the VIGIL-AI backend.
     * Called during first-launch onboarding.
     */
    suspend fun registerWithBackend(context: Context): Boolean = withContext(Dispatchers.IO) {
        initialize(context)
        val backendUrl = getBackendUrl(context)
        val userId = getUserId(context)
        val deviceUuid = getDeviceUuid(context)
        val installId = getInstallationId(context)

        try {
            // 1. Register User
            val userJson = JSONObject().apply {
                put("user_id", userId)
                put("name", getUserName(context))
                put("email", getUserEmail(context))
            }
            val userReq = Request.Builder()
                .url("$backendUrl/api/v1/auth/register-user")
                .post(RequestBody.create("application/json".toMediaTypeOrNull(), userJson.toString()))
                .build()

            val userResp = httpClient.newCall(userReq).execute()
            if (userResp.isSuccessful) {
                val respBody = userResp.body?.string() ?: ""
                val respJson = JSONObject(respBody)
                val returnedUserId = respJson.optString("user_id", userId)
                prefs.edit().putString(KEY_USER_ID, returnedUserId).apply()
            }

            // 2. Register Device
            val deviceJson = JSONObject().apply {
                put("user_id", getUserId(context))
                put("device_uuid", deviceUuid)
                put("installation_id", installId)
                put("platform", "android")
                put("app_version", "1.0.0 (${Build.VERSION.RELEASE})")
            }
            val deviceReq = Request.Builder()
                .url("$backendUrl/api/v1/auth/register-device")
                .post(RequestBody.create("application/json".toMediaTypeOrNull(), deviceJson.toString()))
                .build()

            val deviceResp = httpClient.newCall(deviceReq).execute()
            val success = deviceResp.isSuccessful
            if (success) {
                prefs.edit().putBoolean(KEY_IS_REGISTERED, true).apply()
                Log.i(TAG, "Device registered successfully with backend!")
            }
            return@withContext success
        } catch (e: Exception) {
            Log.w(TAG, "Error registering device with backend: ${e.message}. Operating in offline-safe mode.")
            return@withContext false
        }
    }
}
