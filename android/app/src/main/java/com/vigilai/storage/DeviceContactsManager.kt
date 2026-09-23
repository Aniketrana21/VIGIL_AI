package com.vigilai.storage

import android.content.Context
import android.content.pm.PackageManager
import android.database.Cursor
import android.provider.ContactsContract
import android.util.Log
import androidx.core.content.ContextCompat
import com.vigilai.model.KnownPerson

data class DeviceContact(
    val id: Long,
    val name: String,
    val phoneNumber: String,
    val photoUri: String? = null,
    val relation: String? = null,
    val isKnown: Boolean = false,
    val trustLevel: String = "STANDARD"
)

/**
 * Fetches real user contacts dynamically from the Android system Contacts Provider
 * (ContactsContract) and merges them with VIGIL-AI Known Persons repository.
 */
object DeviceContactsManager {
    private const val TAG = "DeviceContactsManager"

    fun hasContactsPermission(context: Context): Boolean {
        return ContextCompat.checkSelfPermission(
            context,
            android.Manifest.permission.READ_CONTACTS
        ) == PackageManager.PERMISSION_GRANTED
    }

    /**
     * Loads all device contacts sorted alphabetically.
     * Enriches each contact with any user-confirmed VIGIL-AI relation or voiceprint profile.
     */
    fun loadDeviceContacts(context: Context, searchQuery: String = ""): List<DeviceContact> {
        val contacts = mutableListOf<DeviceContact>()
        if (!hasContactsPermission(context)) {
            Log.w(TAG, "READ_CONTACTS permission not granted. Falling back to saved known contacts.")
            return getFallbackSavedContacts(context, searchQuery)
        }

        try {
            val projection = arrayOf(
                ContactsContract.CommonDataKinds.Phone.CONTACT_ID,
                ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME,
                ContactsContract.CommonDataKinds.Phone.NUMBER,
                ContactsContract.CommonDataKinds.Phone.PHOTO_THUMBNAIL_URI
            )

            val selection = if (searchQuery.isNotBlank()) {
                "${ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME} LIKE ? OR ${ContactsContract.CommonDataKinds.Phone.NUMBER} LIKE ?"
            } else null

            val selectionArgs = if (searchQuery.isNotBlank()) {
                val q = "%$searchQuery%"
                arrayOf(q, q)
            } else null

            val cursor: Cursor? = context.contentResolver.query(
                ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
                projection,
                selection,
                selectionArgs,
                "${ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME} ASC"
            )

            val seenNumbers = mutableSetOf<String>()

            cursor?.use { c ->
                val idIdx = c.getColumnIndex(ContactsContract.CommonDataKinds.Phone.CONTACT_ID)
                val nameIdx = c.getColumnIndex(ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME)
                val numIdx = c.getColumnIndex(ContactsContract.CommonDataKinds.Phone.NUMBER)
                val photoIdx = c.getColumnIndex(ContactsContract.CommonDataKinds.Phone.PHOTO_THUMBNAIL_URI)

                while (c.moveToNext()) {
                    val id = if (idIdx >= 0) c.getLong(idIdx) else 0L
                    val name = if (nameIdx >= 0) c.getString(nameIdx) ?: "Unknown" else "Unknown"
                    val rawNum = if (numIdx >= 0) c.getString(numIdx) ?: "" else ""
                    val photoUri = if (photoIdx >= 0) c.getString(photoIdx) else null

                    val normalizedNum = rawNum.replace(Regex("[^0-9+]"), "")
                    if (normalizedNum.isBlank() || seenNumbers.contains(normalizedNum)) {
                        continue
                    }
                    seenNumbers.add(normalizedNum)

                    val knownPerson = KnownPersonRepository.getKnownPerson(context, normalizedNum)
                    val relation = knownPerson?.relation
                    val isKnown = knownPerson != null
                    val trustLevel = knownPerson?.trustLevel ?: "STANDARD"

                    contacts.add(
                        DeviceContact(
                            id = id,
                            name = name,
                            phoneNumber = rawNum,
                            photoUri = photoUri,
                            relation = relation,
                            isKnown = isKnown,
                            trustLevel = trustLevel
                        )
                    )
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error querying ContactsContract: ${e.message}", e)
        }

        // If no device contacts were found, merge with saved known persons
        if (contacts.isEmpty()) {
            return getFallbackSavedContacts(context, searchQuery)
        }

        return contacts
    }

    private fun getFallbackSavedContacts(context: Context, searchQuery: String): List<DeviceContact> {
        val knownPersons = KnownPersonRepository.getAllKnownPersons(context)
        return knownPersons.filter {
            if (searchQuery.isBlank()) true
            else it.name.contains(searchQuery, ignoreCase = true) ||
                 it.phoneNumber.contains(searchQuery) ||
                 it.relation.contains(searchQuery, ignoreCase = true)
        }.mapIndexed { index, person ->
            DeviceContact(
                id = index.toLong() + 1000L,
                name = person.name,
                phoneNumber = person.phoneNumber,
                relation = person.relation,
                isKnown = true,
                trustLevel = person.trustLevel
            )
        }
    }
}
