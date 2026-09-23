package com.vigilai.storage

import android.content.Context
import android.content.pm.PackageManager
import android.database.Cursor
import android.provider.CallLog
import android.text.format.DateFormat
import android.util.Log
import androidx.core.content.ContextCompat
import com.vigilai.model.AiVerdict
import com.vigilai.model.CallLogItem
import com.vigilai.model.CallType
import com.vigilai.screening.LocalBlocklistManager
import java.util.Calendar
import java.util.Date

/**
 * Manages fetching real device call logs from Android Telecom provider
 * and enriches them with VIGIL-AI 3-Stage protection intelligence
 * and locally saved known relationships.
 */
object CallLogManager {
    private const val TAG = "CallLogManager"

    fun hasCallLogPermission(context: Context): Boolean {
        return ContextCompat.checkSelfPermission(
            context,
            android.Manifest.permission.READ_CALL_LOG
        ) == PackageManager.PERMISSION_GRANTED
    }

    /**
     * Loads the phone call history.
     * If permission is granted and device has logs, fetches real calls.
     * Otherwise, returns the realistic demonstration dataset matching the phone screenshot.
     */
    fun loadCallLogs(context: Context, filter: String = "ALL", searchQuery: String = ""): List<CallLogItem> {
        val rawLogs = if (hasCallLogPermission(context)) {
            fetchDeviceCallLogs(context)
        } else {
            emptyList()
        }

        val allLogs = if (hasCallLogPermission(context)) {
            rawLogs
        } else {
            emptyList()
        }

        return allLogs.filter { item ->
            // Category filter
            val matchesFilter = when (filter.uppercase()) {
                "MISSED" -> item.type == CallType.MISSED
                "BLOCKED" -> item.isBlockedOrCloned || LocalBlocklistManager.isBlocked(context, item.number)
                "SCREENED" -> item.aiVerdict != AiVerdict.UNKNOWN
                else -> true
            }

            // Search query filter
            val matchesSearch = if (searchQuery.isBlank()) {
                true
            } else {
                val q = searchQuery.trim().lowercase()
                item.displayTitle.lowercase().contains(q) ||
                item.number.contains(q) ||
                (item.relation?.lowercase()?.contains(q) == true)
            }

            matchesFilter && matchesSearch
        }
    }

    private fun fetchDeviceCallLogs(context: Context): List<CallLogItem> {
        val result = mutableListOf<CallLogItem>()
        try {
            val projection = arrayOf(
                CallLog.Calls._ID,
                CallLog.Calls.CACHED_NAME,
                CallLog.Calls.NUMBER,
                CallLog.Calls.DATE,
                CallLog.Calls.TYPE,
                CallLog.Calls.DURATION
            )

            val cursor: Cursor? = context.contentResolver.query(
                CallLog.Calls.CONTENT_URI,
                projection,
                null,
                null,
                "${CallLog.Calls.DATE} DESC LIMIT 100"
            )

            cursor?.use { c ->
                val idIdx = c.getColumnIndex(CallLog.Calls._ID)
                val nameIdx = c.getColumnIndex(CallLog.Calls.CACHED_NAME)
                val numberIdx = c.getColumnIndex(CallLog.Calls.NUMBER)
                val dateIdx = c.getColumnIndex(CallLog.Calls.DATE)
                val typeIdx = c.getColumnIndex(CallLog.Calls.TYPE)
                val durIdx = c.getColumnIndex(CallLog.Calls.DURATION)

                while (c.moveToNext()) {
                    val id = if (idIdx >= 0) c.getLong(idIdx) else 0L
                    var name = if (nameIdx >= 0) c.getString(nameIdx) else null
                    val number = if (numberIdx >= 0) c.getString(numberIdx) ?: "Unknown" else "Unknown"
                    val dateMs = if (dateIdx >= 0) c.getLong(dateIdx) else System.currentTimeMillis()
                    val rawType = if (typeIdx >= 0) c.getInt(typeIdx) else CallLog.Calls.INCOMING_TYPE
                    val duration = if (durIdx >= 0) c.getLong(durIdx) else 0L

                    // Check known relationship
                    val knownPerson = KnownPersonRepository.getKnownPerson(context, number)
                    if (name.isNullOrBlank() && knownPerson != null) {
                        name = knownPerson.name
                    }

                    val callType = when (rawType) {
                        CallLog.Calls.OUTGOING_TYPE -> CallType.OUTGOING
                        CallLog.Calls.MISSED_TYPE -> CallType.MISSED
                        CallLog.Calls.REJECTED_TYPE -> CallType.REJECTED
                        CallLog.Calls.BLOCKED_TYPE -> CallType.BLOCKED
                        else -> CallType.INCOMING
                    }

                    val isBlockedLocally = LocalBlocklistManager.isBlocked(context, number)
                    val audit = CallAuditRepository.getLatestAuditForNumber(context, number)

                    val effectiveType = if (isBlockedLocally || audit?.verdict == "BLOCK") CallType.BLOCKED else callType

                    val aiVerdict = when {
                        isBlockedLocally || audit?.isClone == true || audit?.verdict == "BLOCK" -> AiVerdict.CLONED
                        audit?.isSpam == true || audit?.callerIntent in listOf("OTP_REQUEST", "FINANCIAL_FRAUD", "URGENT_SCAM") -> AiVerdict.SPAM
                        audit?.verdict == "ALLOW" -> AiVerdict.GENUINE
                        knownPerson != null && knownPerson.isConfirmed -> AiVerdict.GENUINE
                        else -> AiVerdict.SCREENED
                    }

                    val effectiveRiskScore = audit?.riskScore ?: (if (isBlockedLocally) 98 else if (knownPerson != null) 4 else 22)
                    val effectiveRelation = audit?.matchedRelation ?: knownPerson?.relation

                    val formattedTime = formatCallTime(dateMs)

                    result.add(
                        CallLogItem(
                            id = id,
                            name = name,
                            number = number,
                            formattedTime = "$formattedTime India",
                            type = effectiveType,
                            durationSeconds = duration,
                            relation = effectiveRelation,
                            aiVerdict = aiVerdict,
                            riskScore = effectiveRiskScore,
                            rawTimestamp = dateMs
                        )
                    )
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error fetching device call logs: ${e.message}")
        }
        return result
    }

    private fun formatCallTime(timestamp: Long): String {
        val now = Calendar.getInstance()
        val callCal = Calendar.getInstance().apply { timeInMillis = timestamp }

        return if (now.get(Calendar.YEAR) == callCal.get(Calendar.YEAR) &&
            now.get(Calendar.DAY_OF_YEAR) == callCal.get(Calendar.DAY_OF_YEAR)
        ) {
            DateFormat.format("h:mm a", Date(timestamp)).toString()
        } else {
            DateFormat.format("MMM d", Date(timestamp)).toString()
        }
    }

    /**
     * Seeds the clean phone log entries exactly as displayed in the user's provided screenshot.
     */
    fun getDemoCallLogs(context: Context): List<CallLogItem> {
        val now = System.currentTimeMillis()
        val oneHourAgo = now - 3600_000L
        val yesterday = now - 86400_000L
        val twoDaysAgo = now - (86400_000L * 2)

        return listOf(
            CallLogItem(
                id = 1L,
                name = "Aniket Tut 1",
                number = "+91 98201 10001",
                formattedTime = "5:39 PM India",
                type = CallType.INCOMING,
                durationSeconds = 142,
                relation = "Student / Mentee",
                aiVerdict = AiVerdict.GENUINE,
                riskScore = 2,
                rawTimestamp = oneHourAgo
            ),
            CallLogItem(
                id = 2L,
                name = "Mahek Home",
                number = "+91 98201 10002",
                formattedTime = "Sep 21 India",
                type = CallType.INCOMING,
                durationSeconds = 310,
                relation = "Family / Sister",
                aiVerdict = AiVerdict.GENUINE,
                riskScore = 1,
                rawTimestamp = yesterday
            ),
            CallLogItem(
                id = 3L,
                name = "Mehul Collage",
                number = "+91 98201 10003",
                formattedTime = "Sep 21 India",
                type = CallType.INCOMING,
                durationSeconds = 64,
                relation = "College Friend",
                aiVerdict = AiVerdict.SCREENED,
                riskScore = 15,
                rawTimestamp = yesterday
            ),
            CallLogItem(
                id = 4L,
                name = "Mehul J. P. Davar Father",
                number = "+91 98201 10004",
                formattedTime = "Sep 21 India",
                type = CallType.INCOMING,
                durationSeconds = 45,
                relation = "Friend's Father",
                aiVerdict = AiVerdict.SCREENED,
                riskScore = 12,
                rawTimestamp = yesterday
            ),
            CallLogItem(
                id = 5L,
                name = "Pratik 1 Rana",
                number = "+91 98201 10005",
                formattedTime = "Sep 21 India",
                type = CallType.INCOMING,
                durationSeconds = 210,
                relation = "Brother / Family",
                aiVerdict = AiVerdict.GENUINE,
                riskScore = 3,
                rawTimestamp = yesterday
            ),
            CallLogItem(
                id = 6L,
                name = "Pranay Bajuma",
                number = "+91 98201 10006",
                formattedTime = "Sep 21 India",
                type = CallType.INCOMING,
                durationSeconds = 90,
                relation = "Neighbor",
                aiVerdict = AiVerdict.SCREENED,
                riskScore = 18,
                rawTimestamp = yesterday
            ),
            CallLogItem(
                id = 7L,
                name = "Bhavin",
                number = "+91 98201 10007",
                formattedTime = "Sep 21 India",
                type = CallType.OUTGOING,
                durationSeconds = 180,
                relation = "Colleague",
                aiVerdict = AiVerdict.GENUINE,
                riskScore = 5,
                rawTimestamp = yesterday
            ),
            CallLogItem(
                id = 8L,
                name = "Dishant 1",
                number = "+91 98201 10008",
                formattedTime = "Sep 21 India",
                type = CallType.INCOMING,
                durationSeconds = 50,
                relation = "Friend",
                aiVerdict = AiVerdict.SCREENED,
                riskScore = 14,
                rawTimestamp = yesterday
            ),
            CallLogItem(
                id = 9L,
                name = "Father",
                number = "+91 98201 10009",
                formattedTime = "Sep 21 India",
                type = CallType.INCOMING,
                durationSeconds = 420,
                relation = "Father / Family",
                aiVerdict = AiVerdict.GENUINE,
                riskScore = 1,
                rawTimestamp = yesterday
            ),
            CallLogItem(
                id = 10L,
                name = "Robotic Voice Clone (+1 555-0199)",
                number = "+15550199",
                formattedTime = "Sep 20 India",
                type = CallType.BLOCKED,
                durationSeconds = 0,
                relation = null,
                aiVerdict = AiVerdict.CLONED,
                riskScore = 98,
                rawTimestamp = twoDaysAgo
            ),
            CallLogItem(
                id = 11L,
                name = "Urgent KYC Verification (+91 98000 12345)",
                number = "+919800012345",
                formattedTime = "Sep 20 India",
                type = CallType.BLOCKED,
                durationSeconds = 0,
                relation = null,
                aiVerdict = AiVerdict.SPAM,
                riskScore = 91,
                rawTimestamp = twoDaysAgo
            )
        )
    }
}
