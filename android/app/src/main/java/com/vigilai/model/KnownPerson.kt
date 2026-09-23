package com.vigilai.model

import org.json.JSONObject

/**
 * Represents a recognized person and their relationship to the device user.
 * Used in Stage 2 to verify if caller is known and if their voice matches.
 */
data class KnownPerson(
    val phoneNumber: String,
    val name: String,
    val relation: String, // e.g. "Father", "Mother", "Colleague", "Friend", "Doctor", "Bank"
    val isConfirmed: Boolean = true,
    val trustLevel: String = "TRUSTED", // "TRUSTED", "VERIFIED", "CAUTION", "BLOCKED"
    val voiceEnrolled: Boolean = false,
    val notes: String = "",
    val dateAdded: Long = System.currentTimeMillis()
) {
    fun toJson(): JSONObject {
        return JSONObject().apply {
            put("phoneNumber", phoneNumber)
            put("name", name)
            put("relation", relation)
            put("isConfirmed", isConfirmed)
            put("trustLevel", trustLevel)
            put("voiceEnrolled", voiceEnrolled)
            put("notes", notes)
            put("dateAdded", dateAdded)
        }
    }

    companion object {
        fun fromJson(json: JSONObject): KnownPerson {
            return KnownPerson(
                phoneNumber = json.optString("phoneNumber", ""),
                name = json.optString("name", "Unknown"),
                relation = json.optString("relation", "Contact"),
                isConfirmed = json.optBoolean("isConfirmed", true),
                trustLevel = json.optString("trustLevel", "TRUSTED"),
                voiceEnrolled = json.optBoolean("voiceEnrolled", false),
                notes = json.optString("notes", ""),
                dateAdded = json.optLong("dateAdded", System.currentTimeMillis())
            )
        }
    }
}
