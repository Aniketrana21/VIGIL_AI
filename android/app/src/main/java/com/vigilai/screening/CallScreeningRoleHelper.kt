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
     * Checks if ROLE_DIALER is available on this device.
     */
    fun isDialerRoleAvailable(context: Context): Boolean {
        if (!isCallScreeningRoleSupported()) return false
        val roleManager = context.getSystemService(Context.ROLE_SERVICE) as? RoleManager ?: return false
        return roleManager.isRoleAvailable(RoleManager.ROLE_DIALER)
    }

    /**
     * Returns true if VIGIL-AI is currently the default Phone / Dialer app.
     */
    fun isDialerRoleHeld(context: Context): Boolean {
        if (!isCallScreeningRoleSupported()) {
            val telecom = context.getSystemService(Context.TELECOM_SERVICE) as? android.telecom.TelecomManager
            return telecom?.defaultDialerPackage == context.packageName
        }
        val roleManager = context.getSystemService(Context.ROLE_SERVICE) as? RoleManager ?: return false
        return roleManager.isRoleHeld(RoleManager.ROLE_DIALER)
    }

    /**
     * Generates system Intent to request setting VIGIL-AI as the Default Phone App.
     */
    fun createRequestDialerRoleIntent(context: Context): Intent? {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val roleManager = context.getSystemService(Context.ROLE_SERVICE) as? RoleManager
            if (roleManager?.isRoleAvailable(RoleManager.ROLE_DIALER) == true) {
                return roleManager.createRequestRoleIntent(RoleManager.ROLE_DIALER)
            }
        }
        return Intent(android.telecom.TelecomManager.ACTION_CHANGE_DEFAULT_DIALER).apply {
            putExtra(android.telecom.TelecomManager.EXTRA_CHANGE_DEFAULT_DIALER_PACKAGE_NAME, context.packageName)
        }
    }

    /**
     * Provides a human-readable summary of the current role status.
     */
    fun getRoleStatusDescription(context: Context): String {
        val dialer = isDialerRoleHeld(context)
        val screening = isRoleHeld(context)

        return when {
            dialer && screening -> "ACTIVE: Default Phone App & Call Screener"
            dialer -> "ACTIVE: Default Phone App (Call screening active)"
            screening -> "ACTIVE: Call Screener Armed"
            else -> "TAP TO SET AS DEFAULT PHONE APP"
        }
    }
}
