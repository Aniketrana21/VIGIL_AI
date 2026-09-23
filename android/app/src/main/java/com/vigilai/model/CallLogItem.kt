package com.vigilai.model

/**
 * Call type classification for phone recents log.
 */
enum class CallType {
    INCOMING,
    OUTGOING,
    MISSED,
    REJECTED,
    BLOCKED
}

/**
 * AI Security & Screening verdict for calls.
 */
enum class AiVerdict(val displayName: String, val badgeColorHex: String) {
    GENUINE("Verified Genuine", "#10B981"),
    CLONED("AI Clone Blocked", "#EF4444"),
    SPAM("Spam Suspected", "#F59E0B"),
    SCREENED("Screened Clean", "#0284C7"),
    UNKNOWN("Unverified Caller", "#6B7280")
}

/**
 * Representation of an individual call item in the Recents log list.
 */
data class CallLogItem(
    val id: Long,
    val name: String?,
    val number: String,
    val formattedTime: String,
    val type: CallType,
    val durationSeconds: Long = 0,
    val relation: String? = null,
    val aiVerdict: AiVerdict = AiVerdict.GENUINE,
    val riskScore: Int = 0,
    val rawTimestamp: Long = System.currentTimeMillis()
) {
    val displayTitle: String
        get() = if (!name.isNullOrBlank()) name else number

    val isBlockedOrCloned: Boolean
        get() = type == CallType.BLOCKED || aiVerdict == AiVerdict.CLONED
}
