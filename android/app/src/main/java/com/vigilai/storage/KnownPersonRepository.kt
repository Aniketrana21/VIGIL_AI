package com.vigilai.storage

import android.content.Context
import android.util.Log
import com.vigilai.model.KnownPerson
import org.json.JSONArray
import org.json.JSONObject

/**
 * Local persistent repository for storing verified contacts, their names,
 * and user-confirmed relationships (e.g., "Father", "Colleague", "Friend").
 *
 * Powers Stage 2 of VIGIL-AI:
 * If an incoming call is genuine, the system checks if the person is known.
 * If yes, it checks their voice against their registered relation/profile.
 * If not known, the app asks the user "Do you know this person?" and saves
 * their Name & Relation locally.
 */
object KnownPersonRepository {
    private const val TAG = "KnownPersonRepo"
    private const val PREFS_NAME = "vigil_known_persons_prefs"
    private const val KEY_KNOWN_PERSONS = "known_persons_data"
    private const val KEY_SEEDED = "initial_data_seeded"

    private val memoryCache = mutableMapOf<String, KnownPerson>()
    private var isInitialized = false

    private fun normalize(number: String?): String {
        if (number.isNullOrBlank()) return ""
        return number.replace(Regex("[^0-9+]"), "")
    }

    private fun ensureLoaded(context: Context) {
        if (isInitialized && memoryCache.isNotEmpty()) return

        try {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val jsonStr = prefs.getString(KEY_KNOWN_PERSONS, null)

            if (!jsonStr.isNullOrBlank()) {
                val array = JSONArray(jsonStr)
                memoryCache.clear()
                for (i in 0 until array.length()) {
                    val obj = array.getJSONObject(i)
                    val person = KnownPerson.fromJson(obj)
                    memoryCache[normalize(person.phoneNumber)] = person
                }
            } else if (!prefs.getBoolean(KEY_SEEDED, false)) {
                // Seed default contacts matching the phone app screenshot
                seedDefaultContacts(context)
            }
            isInitialized = true
        } catch (e: Exception) {
            Log.e(TAG, "Error loading known persons: ${e.message}")
        }
    }

    private fun persist(context: Context) {
        try {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val array = JSONArray()
            for (person in memoryCache.values) {
                array.put(person.toJson())
            }
            prefs.edit().putString(KEY_KNOWN_PERSONS, array.toString()).apply()
        } catch (e: Exception) {
            Log.e(TAG, "Error persisting known persons: ${e.message}")
        }
    }

    /**
     * Seeds default contacts from the user's provided dialer screenshot.
     */
    fun seedDefaultContacts(context: Context) {
        val seeds = listOf(
            KnownPerson("+919820110001", "Aniket Tut 1", "Student / Mentee", isConfirmed = true, trustLevel = "TRUSTED", voiceEnrolled = true),
            KnownPerson("+919820110002", "Mahek Home", "Family / Sister", isConfirmed = true, trustLevel = "TRUSTED", voiceEnrolled = true),
            KnownPerson("+919820110003", "Mehul Collage", "College Friend", isConfirmed = true, trustLevel = "TRUSTED", voiceEnrolled = false),
            KnownPerson("+919820110004", "Mehul J. P. Davar Father", "Friend's Father", isConfirmed = true, trustLevel = "TRUSTED", voiceEnrolled = false),
            KnownPerson("+919820110005", "Pratik 1 Rana", "Brother / Family", isConfirmed = true, trustLevel = "TRUSTED", voiceEnrolled = true),
            KnownPerson("+919820110006", "Pranay Bajuma", "Neighbor", isConfirmed = true, trustLevel = "TRUSTED", voiceEnrolled = false),
            KnownPerson("+919820110007", "Bhavin", "Colleague", isConfirmed = true, trustLevel = "TRUSTED", voiceEnrolled = false),
            KnownPerson("+919820110008", "Dishant 1", "Friend", isConfirmed = true, trustLevel = "TRUSTED", voiceEnrolled = false),
            KnownPerson("+919820110009", "Father", "Father / Family", isConfirmed = true, trustLevel = "TRUSTED", voiceEnrolled = true)
        )

        memoryCache.clear()
        for (person in seeds) {
            memoryCache[normalize(person.phoneNumber)] = person
        }
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit().putBoolean(KEY_SEEDED, true).apply()
        persist(context)
        isInitialized = true
        Log.i(TAG, "Seeded ${seeds.size} known persons from phone log.")
    }

    fun getAllKnownPersons(context: Context): List<KnownPerson> {
        ensureLoaded(context)
        return memoryCache.values.toList().sortedBy { it.name }
    }

    fun getKnownPerson(context: Context, phoneNumber: String): KnownPerson? {
        ensureLoaded(context)
        val clean = normalize(phoneNumber)
        return memoryCache[clean] ?: memoryCache.values.firstOrNull { normalize(it.phoneNumber) == clean }
    }

    fun isKnown(context: Context, phoneNumber: String): Boolean {
        ensureLoaded(context)
        val clean = normalize(phoneNumber)
        return memoryCache.containsKey(clean) || memoryCache.values.any { normalize(it.phoneNumber) == clean }
    }

    fun saveKnownPerson(context: Context, person: KnownPerson) {
        ensureLoaded(context)
        val clean = normalize(person.phoneNumber)
        memoryCache[clean] = person
        persist(context)
        Log.i(TAG, "Saved known person: ${person.name} (${person.relation}) for number $clean")
    }

    fun removeKnownPerson(context: Context, phoneNumber: String) {
        ensureLoaded(context)
        val clean = normalize(phoneNumber)
        memoryCache.remove(clean)
        persist(context)
        Log.i(TAG, "Removed known person for number $clean")
    }
}
