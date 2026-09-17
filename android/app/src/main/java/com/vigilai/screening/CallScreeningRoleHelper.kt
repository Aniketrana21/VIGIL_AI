package com.vigilai.screening

import android.app.role.RoleManager
import android.content.Context
import android.content.Intent
import android.os.Build

/**
 * Encapsulates Android Telecom [RoleManager.ROLE_CALL_SCREENING] verification and request workflows.
 *
 * Telecom CallScreeningService requires the app to hold the ROLE_CALL_SCREENING role on Android 10+ (API 29+).
 */
object CallScreeningRoleHelper {

    /**
     * Checks whether the device OS supports [RoleManager.ROLE_CALL_SCREENING].
     */
    fun isCallScreeningRoleSupported(): Boolean {
        return Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
    }

    /**
     * Checks if ROLE_CALL_SCREENING is available for request on this device hardware/OEM profile.
     */
    fun isRoleAvailable(context: Context): Boolean {
        if (!isCallScreeningRoleSupported()) return false
        val roleManager = context.getSystemService(Context.ROLE_SERVICE) as? RoleManager ?: return false
        return roleManager.isRoleAvailable(RoleManager.ROLE_CALL_SCREENING)
    }

    /**
     * Returns true if VIGIL-AI currently holds the active ROLE_CALL_SCREENING role.
     */
    fun isRoleHeld(context: Context): Boolean {
        if (!isCallScreeningRoleSupported()) return false
        val roleManager = context.getSystemService(Context.ROLE_SERVICE) as? RoleManager ?: return false
        return roleManager.isRoleHeld(RoleManager.ROLE_CALL_SCREENING)
    }

    /**
     * Generates the system Intent to launch the OS prompt requesting ROLE_CALL_SCREENING from the user.
     */
    fun createRequestRoleIntent(context: Context): Intent? {
        if (!isCallScreeningRoleSupported()) return null
        val roleManager = context.getSystemService(Context.ROLE_SERVICE) as? RoleManager ?: return null
        return if (roleManager.isRoleAvailable(RoleManager.ROLE_CALL_SCREENING)) {
            roleManager.createRequestRoleIntent(RoleManager.ROLE_CALL_SCREENING)
        } else {
            null
        }
    }

    /**
     * Provides a human-readable summary of the current role status.
     */
    fun getRoleStatusDescription(context: Context): String {
        return when {
            !isCallScreeningRoleSupported() -> "Requires Android 10 (API 29) or higher"
            !isRoleAvailable(context) -> "Call screening role not supported on this device"
            isRoleHeld(context) -> "ACTIVE (VIGIL-AI is default screening service)"
            else -> "NOT GRANTED (Click to enable Mode B screening)"
        }
    }
}
