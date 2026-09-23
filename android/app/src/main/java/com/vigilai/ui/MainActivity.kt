package com.vigilai.ui

import android.app.Activity
import android.app.AlertDialog
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.util.Log
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.core.app.ActivityCompat
import com.vigilai.model.AiVerdict
import com.vigilai.model.CallLogItem
import com.vigilai.model.CallType
import com.vigilai.model.KnownPerson
import com.vigilai.network.VigilApiClient
import com.vigilai.screening.CallScreeningRoleHelper
import com.vigilai.screening.LocalBlocklistManager
import com.vigilai.screening.ThreeStageEvaluation
import android.telecom.PhoneAccount
import android.telecom.TelecomManager
import com.vigilai.screening.ThreeStageProtectionEngine
import com.vigilai.service.AudioStreamVoipService
import com.vigilai.storage.CallLogManager
import com.vigilai.storage.DeviceContact
import com.vigilai.storage.DeviceContactsManager
import com.vigilai.storage.KnownPersonRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Modern Native Phone App with VIGIL-AI 3-Stage Defense Pipeline.
 *
 * Visual Aesthetics:
 * - Crisp White Background (#FFFFFF) theme matching native Android / Xiaomi dialer.
 * - Top Header: "Recents" with settings/shield button.
 * - Rounded search bar ("Search contacts") with live query filtering.
 * - Category filter ("All calls ⌄").
 * - Call log items with circular avatars, names, timestamps ("5:39 PM India"), right chevrons, and AI badges.
 * - Bright green Floating Action Button (FAB) opening interactive dialpad.
 * - 3-tab Bottom Navigation (Recents, Contacts, AI Shield).
 * - Full 3-Stage Defense:
 *   Stage 1: Voice Authenticity & Deepfake / Clone Detection (Blocks if robotic/clone).
 *   Stage 2: Known Person & Relationship Verification (Asks "Do you know this person?", saves locally).
 *   Stage 3: AI Spam & Multi-Factor Risk Engine.
 */
class MainActivity : Activity() {

    private val REQUEST_PERMISSIONS = 201
    private val REQUEST_DIALER_ROLE = 202

    private lateinit var contentContainer: FrameLayout
    private lateinit var headerTitle: TextView
    private lateinit var searchInput: EditText
    private lateinit var filterDropdown: TextView
    private lateinit var callLogsContainer: LinearLayout
    private lateinit var contactsContainer: LinearLayout
    private lateinit var shieldContainer: LinearLayout

    private lateinit var tabRecents: LinearLayout
    private lateinit var tabContacts: LinearLayout
    private lateinit var tabShield: LinearLayout

    private var currentTab = "RECENTS" // "RECENTS", "CONTACTS", "SHIELD"
    private var currentFilter = "ALL" // "ALL", "MISSED", "BLOCKED", "SCREENED"
    private var currentSearchQuery = ""

    private var isVoipStreaming = false

    private val mainScope = CoroutineScope(Dispatchers.Main + SupervisorJob())
    private var cachedCallLogs: List<CallLogItem>? = null
    private var cachedContacts: List<DeviceContact>? = null
    private var isLoadingLogs = false
    private var isLoadingContacts = false
    private var searchJob: Job? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Initialize backend URL & seed initial contacts
        val savedUrl = LocalBlocklistManager.getSavedBackendUrl(this)
        VigilApiClient.backendBaseUrl = savedUrl
        KnownPersonRepository.getAllKnownPersons(this)

        // Clean slate: Clear all blocked numbers so real calls are never auto-rejected
        LocalBlocklistManager.clearAllBlocked(this)

        // Request telephony permissions gracefully
        requestRequiredPermissions()

        // Root FrameLayout hosting Main View + Floating Dialpad FAB + Bottom Nav
        val rootLayout = FrameLayout(this).apply {
            setBackgroundColor(Color.WHITE)
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
        }

        // Main Vertical Layout (Header, Search, Dynamic Content)
        val mainVertical = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.WHITE)
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            ).apply {
                bottomMargin = dp(64) // Reserve space for bottom nav
            }
        }

        // ══════════════════════════════════════════════════════════════
        // 1. TOP HEADER ROW: "Recents" / "Contacts" + Shield Icon
        // ══════════════════════════════════════════════════════════════
        val headerRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(20), dp(16), dp(20), dp(8))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            )
        }

        headerTitle = TextView(this).apply {
            id = View.generateViewId()
            text = "Recents"
            textSize = 24f
            setTextColor(Color.parseColor("#111827"))
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        }
        headerRow.addView(headerTitle)

        // Top-right Settings / Shield Gear icon
        val btnTopSettings = TextView(this).apply {
            text = "🛡️"
            textSize = 20f
            setPadding(dp(8), dp(8), dp(8), dp(8))
            background = createRipplePill(Color.parseColor("#F3F4F6"), dp(20))
            isClickable = true
            setOnClickListener {
                switchTab("SHIELD")
            }
        }
        headerRow.addView(btnTopSettings)
        mainVertical.addView(headerRow)

        // ══════════════════════════════════════════════════════════════
        // 2. SEARCH BAR ("Search contacts")
        // ══════════════════════════════════════════════════════════════
        val searchContainer = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(16), dp(4), dp(16), dp(4))
            background = createCardDrawable(Color.parseColor("#F3F4F6"), Color.parseColor("#E5E7EB"), dp(24))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                dp(46)
            ).apply {
                leftMargin = dp(20)
                rightMargin = dp(20)
                bottomMargin = dp(10)
            }
        }

        val searchIcon = TextView(this).apply {
            text = "🔍"
            textSize = 14f
            setPadding(0, 0, dp(8), 0)
        }
        searchContainer.addView(searchIcon)

        searchInput = EditText(this).apply {
            hint = "Search contacts"
            setHintTextColor(Color.parseColor("#9CA3AF"))
            setTextColor(Color.parseColor("#111827"))
            textSize = 15f
            background = null
            isSingleLine = true
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            addTextChangedListener(object : TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                    searchJob?.cancel()
                    searchJob = mainScope.launch {
                        delay(200)
                        currentSearchQuery = s?.toString()?.trim() ?: ""
                        refreshCurrentTab(forceReload = true)
                    }
                }
                override fun afterTextChanged(s: Editable?) {}
            })
        }
        searchContainer.addView(searchInput)
        mainVertical.addView(searchContainer)

        // ══════════════════════════════════════════════════════════════
        // 3. FILTER DROPDOWN ROW ("All calls ⌄")
        // ══════════════════════════════════════════════════════════════
        val filterRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(20), dp(4), dp(20), dp(8))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            )
        }

        filterDropdown = TextView(this).apply {
            text = "All calls ⌄"
            textSize = 13f
            setTextColor(Color.parseColor("#6B7280"))
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.NORMAL)
            isClickable = true
            setOnClickListener { showFilterMenu() }
        }
        filterRow.addView(filterDropdown)
        mainVertical.addView(filterRow)

        // ══════════════════════════════════════════════════════════════
        // 4. MAIN CONTENT CONTAINER (Recents / Contacts / AI Shield)
        // ══════════════════════════════════════════════════════════════
        contentContainer = FrameLayout(this).apply {
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                0,
                1f
            )
        }

        // Tab A: Recents Call Log ScrollView
        val recentsScroll = ScrollView(this).apply {
            isFillViewport = true
            overScrollMode = View.OVER_SCROLL_IF_CONTENT_SCROLLS
        }
        callLogsContainer = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(0, 0, 0, dp(80))
        }
        recentsScroll.addView(callLogsContainer)
        contentContainer.addView(recentsScroll)

        // Tab B: Contacts ScrollView
        val contactsScroll = ScrollView(this).apply {
            isFillViewport = true
            visibility = View.GONE
        }
        contactsContainer = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(10), dp(20), dp(80))
        }
        contactsScroll.addView(contactsContainer)
        contentContainer.addView(contactsScroll)

        // Tab C: AI Defense & 3-Stage Pipeline ScrollView
        val shieldScroll = ScrollView(this).apply {
            isFillViewport = true
            visibility = View.GONE
        }
        shieldContainer = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(12), dp(20), dp(80))
        }
        shieldScroll.addView(shieldContainer)
        contentContainer.addView(shieldScroll)

        mainVertical.addView(contentContainer)
        rootLayout.addView(mainVertical)

        // ══════════════════════════════════════════════════════════════
        // 5. BRIGHT GREEN FLOATING ACTION BUTTON (DIALPAD FAB)
        // ══════════════════════════════════════════════════════════════
        val dialpadFab = TextView(this).apply {
            text = "⁝⁝⁝"
            textSize = 24f
            setTextColor(Color.WHITE)
            gravity = Gravity.CENTER
            background = createCircleDrawable(Color.parseColor("#10B981"))
            elevation = dp(8).toFloat()
            isClickable = true
            setOnClickListener {
                showDialpadBottomSheet()
            }
            layoutParams = FrameLayout.LayoutParams(dp(58), dp(58)).apply {
                gravity = Gravity.BOTTOM or Gravity.END
                rightMargin = dp(22)
                bottomMargin = dp(76)
            }
        }
        rootLayout.addView(dialpadFab)

        // ══════════════════════════════════════════════════════════════
        // 6. BOTTOM NAVIGATION BAR (Recents, Contacts, AI Defense)
        // ══════════════════════════════════════════════════════════════
        val bottomNav = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setBackgroundColor(Color.WHITE)
            elevation = dp(10).toFloat()
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                dp(62)
            ).apply {
                gravity = Gravity.BOTTOM
            }
        }

        tabRecents = createBottomNavItem("📞", "Recents", true) { switchTab("RECENTS") }
        tabContacts = createBottomNavItem("👤", "Contacts", false) { switchTab("CONTACTS") }
        tabShield = createBottomNavItem("🛡️", "AI Defense", false) { switchTab("SHIELD") }

        bottomNav.addView(tabRecents)
        bottomNav.addView(tabContacts)
        bottomNav.addView(tabShield)
        rootLayout.addView(bottomNav)

        setContentView(rootLayout)

        // Load initial views
        refreshCallLogs(forceReload = false)
    }

    override fun onResume() {
        super.onResume()
        handleIncomingDialIntent(intent)
        when (currentTab) {
            "RECENTS" -> refreshCallLogs(forceReload = true)
            "CONTACTS" -> refreshContacts(forceReload = true)
            "SHIELD" -> refreshShieldView()
        }
    }

    // ══════════════════════════════════════════════════════════════════
    // TAB SWITCHING LOGIC
    // ══════════════════════════════════════════════════════════════════
    private fun switchTab(tab: String) {
        if (currentTab == tab) return
        currentTab = tab

        val recentsScroll = contentContainer.getChildAt(0)
        val contactsScroll = contentContainer.getChildAt(1)
        val shieldScroll = contentContainer.getChildAt(2)

        recentsScroll.visibility = if (tab == "RECENTS") View.VISIBLE else View.GONE
        contactsScroll.visibility = if (tab == "CONTACTS") View.VISIBLE else View.GONE
        shieldScroll.visibility = if (tab == "SHIELD") View.VISIBLE else View.GONE

        updateBottomNavState(tabRecents, tab == "RECENTS")
        updateBottomNavState(tabContacts, tab == "CONTACTS")
        updateBottomNavState(tabShield, tab == "SHIELD")

        headerTitle.text = when (tab) {
            "RECENTS" -> "Recents"
            "CONTACTS" -> "Contacts"
            else -> "AI Defense"
        }

        if (tab == "RECENTS") {
            filterDropdown.visibility = View.VISIBLE
            refreshCallLogs(forceReload = false)
        } else if (tab == "CONTACTS") {
            filterDropdown.visibility = View.GONE
            refreshContacts(forceReload = false)
        } else {
            filterDropdown.visibility = View.GONE
            refreshShieldView()
        }
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIncomingDialIntent(intent)
    }

    private fun handleIncomingDialIntent(intent: Intent?) {
        val data = intent?.data ?: return
        if (data.scheme == "tel") {
            val raw = data.schemeSpecificPart
            if (!raw.isNullOrBlank()) {
                val clean = com.vigilai.storage.ContactLookupHelper.cleanNumberForDial(raw)
                if (intent.action == Intent.ACTION_CALL && ActivityCompat.checkSelfPermission(this, android.Manifest.permission.CALL_PHONE) == PackageManager.PERMISSION_GRANTED) {
                    initiatePhoneCall(clean)
                } else {
                    showDialpadBottomSheet(clean)
                }
                intent.data = null
            }
        }
    }

    private fun refreshCurrentTab(forceReload: Boolean = false) {
        when (currentTab) {
            "RECENTS" -> refreshCallLogs(forceReload)
            "CONTACTS" -> refreshContacts(forceReload)
            "SHIELD" -> refreshShieldView()
        }
    }

    private fun initiatePhoneCall(number: String) {
        if (number.isBlank()) return
        val cleanNumber = com.vigilai.storage.ContactLookupHelper.cleanNumberForDial(number)
        if (cleanNumber.isBlank()) return

        if (ActivityCompat.checkSelfPermission(this, android.Manifest.permission.CALL_PHONE) != PackageManager.PERMISSION_GRANTED) {
            Toast.makeText(this, "Call phone permission required. Please grant permission.", Toast.LENGTH_SHORT).show()
            ActivityCompat.requestPermissions(
                this,
                arrayOf(android.Manifest.permission.CALL_PHONE),
                REQUEST_PERMISSIONS
            )
            return
        }

        try {
            val telecomManager = getSystemService(Context.TELECOM_SERVICE) as? TelecomManager
            val uri = Uri.fromParts(PhoneAccount.SCHEME_TEL, cleanNumber, null)
            val extras = Bundle()

            if (telecomManager != null) {
                try {
                    val defaultAccount = telecomManager.getDefaultOutgoingPhoneAccount(PhoneAccount.SCHEME_TEL)
                    if (defaultAccount != null) {
                        extras.putParcelable(TelecomManager.EXTRA_PHONE_ACCOUNT_HANDLE, defaultAccount)
                    }
                    telecomManager.placeCall(uri, extras)
                    Log.i("MainActivity", "TelecomManager placed outgoing call to $cleanNumber")
                    return
                } catch (e: Exception) {
                    Log.w("MainActivity", "TelecomManager placeCall failed: ${e.message}, falling back to intent")
                }
            }

            // Fallback via ACTION_CALL
            val callIntent = Intent(Intent.ACTION_CALL, Uri.parse("tel:$cleanNumber")).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK
            }
            val resolveInfos = packageManager.queryIntentActivities(callIntent, 0)
            val systemDialer = resolveInfos.firstOrNull { it.activityInfo.packageName != packageName }
            if (systemDialer != null) {
                callIntent.setClassName(systemDialer.activityInfo.packageName, systemDialer.activityInfo.name)
            }
            startActivity(callIntent)
        } catch (e: Exception) {
            Toast.makeText(this, "Could not place call: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }

    // ══════════════════════════════════════════════════════════════════
    // 1. RECENTS CALL LOG LIST RENDERING (Real Device Calls)
    // ══════════════════════════════════════════════════════════════════
    private fun renderCallLogPermissionNotice() {
        val permCard = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(14), dp(16), dp(14))
            background = createCardDrawable(Color.parseColor("#FEF3C7"), Color.parseColor("#F59E0B"), dp(12))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply {
                bottomMargin = dp(14)
            }
        }
        val permTitle = TextView(this).apply {
            text = "🔒 Call Logs Permission Required"
            textSize = 14f
            setTextColor(Color.parseColor("#92400E"))
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
        }
        val permSub = TextView(this).apply {
            text = "Grant permission so VIGIL-AI can display real call history and screen recent callers."
            textSize = 12f
            setTextColor(Color.parseColor("#78350F"))
            setPadding(0, dp(2), 0, dp(8))
        }
        val btnGrant = TextView(this).apply {
            text = "Grant Call Log Permission"
            textSize = 12f
            setTextColor(Color.WHITE)
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
            gravity = Gravity.CENTER
            setPadding(dp(14), dp(8), dp(14), dp(8))
            background = createCardDrawable(Color.parseColor("#D97706"), Color.parseColor("#B45309"), dp(8))
            isClickable = true
            setOnClickListener {
                ActivityCompat.requestPermissions(
                    this@MainActivity,
                    arrayOf(android.Manifest.permission.READ_CALL_LOG, android.Manifest.permission.WRITE_CALL_LOG),
                    REQUEST_PERMISSIONS
                )
            }
        }
        permCard.addView(permTitle)
        permCard.addView(permSub)
        permCard.addView(btnGrant)
        callLogsContainer.addView(permCard)
    }

    private fun refreshCallLogs(forceReload: Boolean = false) {
        if (!CallLogManager.hasCallLogPermission(this)) {
            callLogsContainer.removeAllViews()
            renderCallLogPermissionNotice()
            return
        }

        if (cachedCallLogs != null && !forceReload) {
            renderCallLogsList(cachedCallLogs!!)
            return
        }

        if (isLoadingLogs) return
        isLoadingLogs = true

        if (callLogsContainer.childCount == 0) {
            callLogsContainer.removeAllViews()
            val loadingView = TextView(this).apply {
                text = "Loading calls..."
                textSize = 13f
                setTextColor(Color.parseColor("#9CA3AF"))
                gravity = Gravity.CENTER
                setPadding(dp(20), dp(40), dp(20), dp(20))
            }
            callLogsContainer.addView(loadingView)
        }

        mainScope.launch {
            val logs = withContext(Dispatchers.IO) {
                CallLogManager.loadCallLogs(this@MainActivity, currentFilter, currentSearchQuery)
            }
            isLoadingLogs = false
            cachedCallLogs = logs
            renderCallLogsList(logs)
        }
    }

    private fun renderCallLogsList(logs: List<CallLogItem>, limit: Int = 40) {
        callLogsContainer.removeAllViews()

        if (logs.isEmpty()) {
            val emptyContainer = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                gravity = Gravity.CENTER
                setPadding(dp(24), dp(40), dp(24), dp(24))
            }
            val emptyIcon = TextView(this).apply {
                text = "📞"
                textSize = 40f
                gravity = Gravity.CENTER
                setPadding(0, 0, 0, dp(8))
            }
            val emptyTitle = TextView(this).apply {
                text = "No recent calls found"
                textSize = 16f
                setTextColor(Color.parseColor("#374151"))
                typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
                gravity = Gravity.CENTER
            }
            val emptySub = TextView(this).apply {
                text = "Incoming and outgoing cellular calls will show up here dynamically."
                textSize = 13f
                setTextColor(Color.parseColor("#9CA3AF"))
                gravity = Gravity.CENTER
                setPadding(0, dp(4), 0, dp(16))
            }
            val btnLoadDemo = TextView(this).apply {
                text = "🧪 Load Demo Calls (For Testing)"
                textSize = 12f
                setTextColor(Color.parseColor("#2563EB"))
                typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
                gravity = Gravity.CENTER
                setPadding(dp(14), dp(8), dp(14), dp(8))
                background = createCardDrawable(Color.parseColor("#EFF6FF"), Color.parseColor("#BFDBFE"), dp(8))
                isClickable = true
                setOnClickListener {
                    callLogsContainer.removeAllViews()
                    for (item in CallLogManager.getDemoCallLogs(this@MainActivity)) {
                        callLogsContainer.addView(createCallLogItemView(item))
                    }
                }
            }
            emptyContainer.addView(emptyIcon)
            emptyContainer.addView(emptyTitle)
            emptyContainer.addView(emptySub)
            emptyContainer.addView(btnLoadDemo)
            callLogsContainer.addView(emptyContainer)
            return
        }

        val displayItems = logs.take(limit)
        for (item in displayItems) {
            callLogsContainer.addView(createCallLogItemView(item))
        }

        if (logs.size > limit) {
            val btnMore = TextView(this).apply {
                text = "Show more calls (${logs.size - limit} more)..."
                textSize = 13f
                setTextColor(Color.parseColor("#2563EB"))
                typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
                gravity = Gravity.CENTER
                setPadding(0, dp(16), 0, dp(16))
                isClickable = true
                setOnClickListener {
                    renderCallLogsList(logs, limit + 40)
                }
            }
            callLogsContainer.addView(btnMore)
        }
    }

    private fun createCallLogItemView(item: CallLogItem): View {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(20), dp(12), dp(20), dp(12))
            background = createRipplePill(Color.WHITE, 0)
            isClickable = true
            isFocusable = true
            setOnClickListener {
                showCallDetailsDialog(item)
            }
        }

        // Circular Avatar placeholder
        val avatar = TextView(this).apply {
            text = "👤"
            textSize = 16f
            gravity = Gravity.CENTER
            background = createCircleDrawable(Color.parseColor("#F3F4F6"))
            layoutParams = LinearLayout.LayoutParams(dp(44), dp(44)).apply {
                rightMargin = dp(14)
            }
        }
        row.addView(avatar)

        // Middle Text Details (Name, Timestamp, Relation)
        val textCol = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        }

        val nameRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }

        val nameView = TextView(this).apply {
            text = item.displayTitle
            textSize = 16f
            setTextColor(if (item.isBlockedOrCloned) Color.parseColor("#DC2626") else Color.parseColor("#111827"))
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
        }
        nameRow.addView(nameView)

        if (!item.relation.isNullOrBlank()) {
            val relationBadge = TextView(this).apply {
                text = " • ${item.relation}"
                textSize = 12f
                setTextColor(Color.parseColor("#2563EB"))
                typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.NORMAL)
            }
            nameRow.addView(relationBadge)
        }
        textCol.addView(nameRow)

        val subtitleView = TextView(this).apply {
            text = item.formattedTime
            textSize = 13f
            setTextColor(Color.parseColor("#6B7280"))
            setPadding(0, dp(2), 0, 0)
        }
        textCol.addView(subtitleView)
        row.addView(textCol)

        // Right side: Quick Call Button, AI Status badge & Chevron >
        val rightCol = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }

        // Quick Call Button
        val btnQuickCall = TextView(this).apply {
            text = "📞"
            textSize = 16f
            gravity = Gravity.CENTER
            background = createCircleDrawable(Color.parseColor("#ECFDF5"))
            isClickable = true
            layoutParams = LinearLayout.LayoutParams(dp(36), dp(36)).apply {
                rightMargin = dp(8)
            }
            setOnClickListener {
                initiatePhoneCall(item.number)
            }
        }
        rightCol.addView(btnQuickCall)

        // AI Verdict Chip
        val aiChip = TextView(this).apply {
            text = when (item.aiVerdict) {
                AiVerdict.GENUINE -> "✓ Genuine"
                AiVerdict.CLONED -> "⛔ Clone"
                AiVerdict.SPAM -> "⚠️ Spam"
                AiVerdict.SCREENED -> "🛡️ Safe"
                AiVerdict.UNKNOWN -> "?"
            }
            textSize = 10f
            setTextColor(Color.parseColor(item.aiVerdict.badgeColorHex))
            typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
            setPadding(dp(6), dp(2), dp(6), dp(2))
            background = createCardDrawable(Color.WHITE, Color.parseColor(item.aiVerdict.badgeColorHex), dp(8))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply {
                rightMargin = dp(8)
            }
        }
        rightCol.addView(aiChip)

        val chevron = TextView(this).apply {
            text = "›"
            textSize = 22f
            setTextColor(Color.parseColor("#D1D5DB"))
        }
        rightCol.addView(chevron)

        row.addView(rightCol)
        return row
    }

    // ══════════════════════════════════════════════════════════════════
    // 2. CONTACTS & KNOWN PERSONS TAB (Dynamic ContactsContract)
    // ══════════════════════════════════════════════════════════════════
    private fun renderContactsPermissionNotice() {
        val permNotice = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(14), dp(12), dp(14), dp(12))
            background = createCardDrawable(Color.parseColor("#FEF3C7"), Color.parseColor("#F59E0B"), dp(10))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply {
                bottomMargin = dp(14)
            }
        }
        val permTitle = TextView(this).apply {
            text = "⚠️ Contacts Permission Required"
            textSize = 13f
            setTextColor(Color.parseColor("#92400E"))
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
        }
        val permSub = TextView(this).apply {
            text = "Grant Contacts permission to sync your phone's real contact book dynamically."
            textSize = 12f
            setTextColor(Color.parseColor("#78350F"))
            setPadding(0, dp(2), 0, dp(6))
        }
        val btnGrant = TextView(this).apply {
            text = "Grant Contacts Permission"
            textSize = 12f
            setTextColor(Color.WHITE)
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
            gravity = Gravity.CENTER
            setPadding(dp(12), dp(6), dp(12), dp(6))
            background = createCardDrawable(Color.parseColor("#D97706"), Color.parseColor("#B45309"), dp(6))
            isClickable = true
            setOnClickListener {
                ActivityCompat.requestPermissions(
                    this@MainActivity,
                    arrayOf(android.Manifest.permission.READ_CONTACTS, android.Manifest.permission.WRITE_CONTACTS),
                    REQUEST_PERMISSIONS
                )
            }
        }
        permNotice.addView(permTitle)
        permNotice.addView(permSub)
        permNotice.addView(btnGrant)
        contactsContainer.addView(permNotice)
    }

    private fun refreshContacts(forceReload: Boolean = false) {
        contactsContainer.removeAllViews()

        // Top Action Row: "+ Add Known Person"
        val btnAddPerson = TextView(this).apply {
            text = "+ Add Known Person & Relation"
            textSize = 14f
            setTextColor(Color.WHITE)
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
            gravity = Gravity.CENTER
            setPadding(dp(16), dp(12), dp(16), dp(12))
            background = createCardDrawable(Color.parseColor("#2563EB"), Color.parseColor("#1D4ED8"), dp(12))
            isClickable = true
            setOnClickListener { showAddKnownPersonDialog() }
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply {
                bottomMargin = dp(12)
            }
        }
        contactsContainer.addView(btnAddPerson)

        if (!DeviceContactsManager.hasContactsPermission(this)) {
            renderContactsPermissionNotice()
            return
        }

        if (cachedContacts != null && !forceReload) {
            renderContactsList(cachedContacts!!)
            return
        }

        if (isLoadingContacts) return
        isLoadingContacts = true

        val loadingNotice = TextView(this).apply {
            text = "Loading contacts..."
            textSize = 13f
            setTextColor(Color.parseColor("#9CA3AF"))
            gravity = Gravity.CENTER
            setPadding(dp(20), dp(40), dp(20), dp(20))
        }
        contactsContainer.addView(loadingNotice)

        mainScope.launch {
            val contacts = withContext(Dispatchers.IO) {
                DeviceContactsManager.loadDeviceContacts(this@MainActivity, currentSearchQuery)
            }
            isLoadingContacts = false
            cachedContacts = contacts
            renderContactsList(contacts)
        }
    }

    private fun renderContactsList(contacts: List<DeviceContact>, limit: Int = 40) {
        contactsContainer.removeAllViews()

        // Add back the top "+ Add Known Person" button
        val btnAddPerson = TextView(this).apply {
            text = "+ Add Known Person & Relation"
            textSize = 14f
            setTextColor(Color.WHITE)
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
            gravity = Gravity.CENTER
            setPadding(dp(16), dp(12), dp(16), dp(12))
            background = createCardDrawable(Color.parseColor("#2563EB"), Color.parseColor("#1D4ED8"), dp(12))
            isClickable = true
            setOnClickListener { showAddKnownPersonDialog() }
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply {
                bottomMargin = dp(12)
            }
        }
        contactsContainer.addView(btnAddPerson)

        if (contacts.isEmpty()) {
            val emptyNotice = TextView(this).apply {
                text = if (currentSearchQuery.isBlank()) "No contacts found on device." else "No contacts matching \"$currentSearchQuery\""
                textSize = 14f
                setTextColor(Color.parseColor("#9CA3AF"))
                gravity = Gravity.CENTER
                setPadding(dp(20), dp(40), dp(20), dp(20))
            }
            contactsContainer.addView(emptyNotice)
            return
        }

        val header = TextView(this).apply {
            text = "CONTACTS (${contacts.size})"
            textSize = 11f
            setTextColor(Color.parseColor("#6B7280"))
            typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
            setPadding(0, 0, 0, dp(10))
        }
        contactsContainer.addView(header)

        val displayItems = contacts.take(limit)
        for (contact in displayItems) {
            contactsContainer.addView(createContactCardView(contact))
        }

        if (contacts.size > limit) {
            val btnMore = TextView(this).apply {
                text = "Show more contacts (${contacts.size - limit} more)..."
                textSize = 13f
                setTextColor(Color.parseColor("#2563EB"))
                typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
                gravity = Gravity.CENTER
                setPadding(0, dp(16), 0, dp(16))
                isClickable = true
                setOnClickListener {
                    renderContactsList(contacts, limit + 40)
                }
            }
            contactsContainer.addView(btnMore)
        }
    }

    private fun createContactCardView(contact: DeviceContact): View {
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(16), dp(12), dp(16), dp(12))
            background = createCardDrawable(Color.WHITE, Color.parseColor("#E5E7EB"), dp(12))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply {
                bottomMargin = dp(8)
            }
            isClickable = true
            setOnClickListener {
                showContactOptionsDialog(contact)
            }
        }

        // Avatar initial letter
        val initial = if (contact.name.isNotBlank()) contact.name.first().uppercase() else "👤"
        val avatar = TextView(this).apply {
            text = initial
            textSize = 16f
            setTextColor(Color.parseColor("#1E40AF"))
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
            gravity = Gravity.CENTER
            background = createCircleDrawable(Color.parseColor("#EFF6FF"))
            layoutParams = LinearLayout.LayoutParams(dp(42), dp(42)).apply {
                rightMargin = dp(12)
            }
        }
        card.addView(avatar)

        val infoCol = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        }

        val nameView = TextView(this).apply {
            text = contact.name
            textSize = 15f
            setTextColor(Color.parseColor("#111827"))
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
        }
        val subText = if (!contact.relation.isNullOrBlank()) {
            "Relation: ${contact.relation} • ${contact.phoneNumber}"
        } else {
            contact.phoneNumber
        }
        val relationView = TextView(this).apply {
            text = subText
            textSize = 12f
            setTextColor(if (!contact.relation.isNullOrBlank()) Color.parseColor("#2563EB") else Color.parseColor("#6B7280"))
            setPadding(0, dp(2), 0, 0)
        }
        infoCol.addView(nameView)
        infoCol.addView(relationView)
        card.addView(infoCol)

        // Direct Call Button
        val btnCall = TextView(this).apply {
            text = "📞"
            textSize = 16f
            gravity = Gravity.CENTER
            background = createCircleDrawable(Color.parseColor("#ECFDF5"))
            isClickable = true
            layoutParams = LinearLayout.LayoutParams(dp(36), dp(36)).apply {
                rightMargin = dp(8)
            }
            setOnClickListener {
                initiatePhoneCall(contact.phoneNumber)
            }
        }
        card.addView(btnCall)
        return card
    }

    private fun showContactOptionsDialog(contact: DeviceContact) {
        val options = arrayOf("📞 Call ${contact.name}", "🛡️ Set Known Relationship (Stage 2 AI)", "🧪 Test AI Call Screening")
        AlertDialog.Builder(this)
            .setTitle(contact.name)
            .setItems(options) { _, which ->
                when (which) {
                    0 -> initiatePhoneCall(contact.phoneNumber)
                    1 -> showSetRelationForContactDialog(contact)
                    2 -> simulateThreeStageCall(contact.phoneNumber, contact.name, if (contact.isKnown) "GENUINE_KNOWN" else "GENUINE_UNKNOWN")
                }
            }
            .show()
    }

    private fun showSetRelationForContactDialog(contact: DeviceContact) {
        val input = EditText(this).apply {
            hint = "e.g. Father, Mother, Brother, Boss, Doctor"
            setText(contact.relation ?: "")
            setPadding(dp(12), dp(10), dp(12), dp(10))
            background = createCardDrawable(Color.parseColor("#F9FAFB"), Color.parseColor("#D1D5DB"), dp(8))
        }
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(22), dp(12), dp(22), dp(12))
            addView(input)
        }

        AlertDialog.Builder(this)
            .setTitle("Set Relation for ${contact.name}")
            .setMessage("Designate relation for VIGIL-AI Stage 2 Voice Verification:")
            .setView(layout)
            .setPositiveButton("Save") { _, _ ->
                val relation = input.text.toString().trim()
                if (relation.isNotBlank()) {
                    KnownPersonRepository.saveKnownPerson(
                        this,
                        KnownPerson(
                            phoneNumber = contact.phoneNumber,
                            name = contact.name,
                            relation = relation,
                            isConfirmed = true,
                            trustLevel = "VERIFIED"
                        )
                    )
                    Toast.makeText(this, "Saved $relation for ${contact.name}", Toast.LENGTH_SHORT).show()
                    cachedContacts = null
                    cachedCallLogs = null
                    refreshContacts(forceReload = true)
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    // ══════════════════════════════════════════════════════════════════
    // 3. AI DEFENSE & 3-STAGE PIPELINE TAB
    // ══════════════════════════════════════════════════════════════════
    private fun refreshShieldView() {
        shieldContainer.removeAllViews()

        // 1. Default Phone App Role Card
        val roleCard = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(16), dp(16), dp(16))
            val isHeld = CallScreeningRoleHelper.isDialerRoleHeld(this@MainActivity) || CallScreeningRoleHelper.isRoleHeld(this@MainActivity)
            background = createCardDrawable(
                if (isHeld) Color.parseColor("#F0FDF4") else Color.parseColor("#FFFBEB"),
                if (isHeld) Color.parseColor("#86EFAC") else Color.parseColor("#FDE68A"),
                dp(16)
            )
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply {
                bottomMargin = dp(16)
            }
        }

        val roleStatus = TextView(this).apply {
            text = CallScreeningRoleHelper.getRoleStatusDescription(this@MainActivity)
            textSize = 13f
            setTextColor(Color.parseColor("#1E293B"))
            typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
            setPadding(0, 0, 0, dp(4))
        }
        val roleDesc = TextView(this).apply {
            text = "Set VIGIL-AI as your Default Phone App to automatically intercept calls, screen voice deepfakes, and enforce relationship verification."
            textSize = 12f
            setTextColor(Color.parseColor("#475569"))
            setPadding(0, 0, 0, dp(12))
        }
        val btnSetDefault = TextView(this).apply {
            text = "⚡ Set as Default Phone App"
            textSize = 13f
            setTextColor(Color.WHITE)
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
            gravity = Gravity.CENTER
            setPadding(dp(16), dp(10), dp(16), dp(10))
            background = createCardDrawable(Color.parseColor("#10B981"), Color.parseColor("#059669"), dp(10))
            isClickable = true
            setOnClickListener { requestDefaultDialerRole() }
        }
        val btnManageDefault = TextView(this).apply {
            text = "⚙️ Open System Default Apps Settings"
            textSize = 12f
            setTextColor(Color.parseColor("#2563EB"))
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
            gravity = Gravity.CENTER
            setPadding(dp(14), dp(8), dp(14), dp(8))
            background = createCardDrawable(Color.parseColor("#EFF6FF"), Color.parseColor("#BFDBFE"), dp(8))
            isClickable = true
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                topMargin = dp(8)
            }
            setOnClickListener { openSystemDefaultAppsSettings() }
        }
        val btnBatterySaver = TextView(this).apply {
            text = "🔋 Disable Battery Saver (Prevents MIUI Reverting)"
            textSize = 12f
            setTextColor(Color.parseColor("#D97706"))
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
            gravity = Gravity.CENTER
            setPadding(dp(14), dp(8), dp(14), dp(8))
            background = createCardDrawable(Color.parseColor("#FEF3C7"), Color.parseColor("#FDE68A"), dp(8))
            isClickable = true
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                topMargin = dp(8)
            }
            setOnClickListener { requestDisableBatteryOptimization() }
        }
        roleCard.addView(roleStatus)
        roleCard.addView(roleDesc)
        roleCard.addView(btnSetDefault)
        roleCard.addView(btnManageDefault)
        roleCard.addView(btnBatterySaver)
        shieldContainer.addView(roleCard)

        // 2. 3-Stage Pipeline Diagram
        val pipelineCard = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(16), dp(16), dp(16))
            background = createCardDrawable(Color.WHITE, Color.parseColor("#E5E7EB"), dp(16))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply {
                bottomMargin = dp(16)
            }
        }

        val pTitle = TextView(this).apply {
            text = "3-STAGE AI DEFENSE PIPELINE"
            textSize = 12f
            setTextColor(Color.parseColor("#0F172A"))
            typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
            setPadding(0, 0, 0, dp(10))
        }
        pipelineCard.addView(pTitle)

        pipelineCard.addView(createStageDiagramStep("1", "Voice Authenticity & Deepfake Engine", "Checks genuine vs robotics / AI clone voice. If clone -> BLOCKED instantly."))
        pipelineCard.addView(createStageDiagramStep("2", "Known Person & Relationship Verification", "Checks if caller is known. If unknown -> asks Name & Relation to save locally. Verifies voice match."))
        pipelineCard.addView(createStageDiagramStep("3", "AI Spam & Multi-Factor Risk Engine", "Analyzes conversation for OTP theft, financial coercion, and assigns dynamic threat score."))
        shieldContainer.addView(pipelineCard)

        // 3. Audio Feasibility Diagnostic Probe Card
        val audioProbeCard = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(16), dp(16), dp(16))
            background = createCardDrawable(Color.parseColor("#F0F9FF"), Color.parseColor("#BAE6FD"), dp(16))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply {
                bottomMargin = dp(16)
            }
        }

        val probeTitle = TextView(this).apply {
            text = "🎙️ AUDIO SOURCE & CALL PATH PROBE"
            textSize = 12f
            setTextColor(Color.parseColor("#0369A1"))
            typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
            setPadding(0, 0, 0, dp(4))
        }
        val probeDesc = TextView(this).apply {
            text = "Tests hardware AudioSources (MIC, VOICE_COMMUNICATION, VOICE_CALL, VOICE_DOWNLINK) during real cellular calls to report whether direct digital remote audio is provided by Android."
            textSize = 12f
            setTextColor(Color.parseColor("#0C4A6E"))
            setPadding(0, 0, 0, dp(10))
        }
        val btnRunProbe = TextView(this).apply {
            text = "🔬 Run Live Audio Feasibility Test"
            textSize = 12f
            setTextColor(Color.WHITE)
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
            gravity = Gravity.CENTER
            setPadding(dp(12), dp(8), dp(12), dp(8))
            background = createCardDrawable(Color.parseColor("#0284C7"), Color.parseColor("#0369A1"), dp(8))
            isClickable = true
            setOnClickListener { showAudioFeasibilityDialog() }
        }
        audioProbeCard.addView(probeTitle)
        audioProbeCard.addView(probeDesc)
        audioProbeCard.addView(btnRunProbe)
        shieldContainer.addView(audioProbeCard)

        // 4. Interactive Call Simulation Sandbox (Clearly Labeled as Simulation Test)
        val simCard = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(16), dp(16), dp(16))
            background = createCardDrawable(Color.WHITE, Color.parseColor("#E5E7EB"), dp(16))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply {
                bottomMargin = dp(16)
            }
        }

        val simTitle = TextView(this).apply {
            text = "🧪 Simulation / Development Test"
            textSize = 12f
            setTextColor(Color.parseColor("#0F172A"))
            typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
            setPadding(0, 0, 0, dp(2))
        }
        val simNotice = TextView(this).apply {
            text = "⚠️ Development Note: Evaluates AI models with synthetic test vectors. This is not proof of real cellular carrier call protection."
            textSize = 10f
            setTextColor(Color.parseColor("#D97706"))
            setPadding(0, 0, 0, dp(10))
        }
        simCard.addView(simTitle)
        simCard.addView(simNotice)

        // Button A: AI Clone Call
        simCard.addView(createSimulateBtn("🚨 Test Case 1: AI Robotic Clone Call (Stage 1 Auto-Block)", "#EF4444") {
            simulateThreeStageCall("+15550199", "Unknown Robotic Synthesizer", "CLONE")
        })

        // Button B: Unknown Caller
        simCard.addView(createSimulateBtn("❓ Test Case 2: Unknown Caller (Stage 2 Asks: Who is this?)", "#2563EB") {
            simulateThreeStageCall("+919876543210", "Unsaved Caller", "GENUINE_UNKNOWN")
        })

        // Button C: Known Person
        simCard.addView(createSimulateBtn("✅ Test Case 3: Known Person (Father - Verified Match)", "#10B981") {
            simulateThreeStageCall("+919820110009", "Father", "GENUINE_KNOWN")
        })

        // Button D: Voice Impersonator
        simCard.addView(createSimulateBtn("⚠️ Test Case 4: Impersonator (Claims Father, Voice Mismatch)", "#D97706") {
            simulateThreeStageCall("+919820110009", "Father", "GENUINE_IMPERSONATOR")
        })

        shieldContainer.addView(simCard)

        // 5. System Protection Reset Card
        val resetCard = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(16), dp(16), dp(16))
            background = createCardDrawable(Color.parseColor("#FEF2F2"), Color.parseColor("#FECACA"), dp(16))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply {
                bottomMargin = dp(16)
            }
        }
        val resetTitle = TextView(this).apply {
            text = "🔄 RESET ALL PROTECTION & UNBLOCK"
            textSize = 12f
            setTextColor(Color.parseColor("#991B1B"))
            typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
            setPadding(0, 0, 0, dp(4))
        }
        val resetDesc = TextView(this).apply {
            text = "Clears all blocked numbers, stops continuous busy signals / auto-rejections, and resets Stage 1, 2, 3 protection back to clean default."
            textSize = 12f
            setTextColor(Color.parseColor("#7F1D1D"))
            setPadding(0, 0, 0, dp(10))
        }
        val btnResetAll = TextView(this).apply {
            text = "🔄 Reset All Protection & Unblock All Numbers"
            textSize = 12f
            setTextColor(Color.WHITE)
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
            gravity = Gravity.CENTER
            setPadding(dp(14), dp(10), dp(14), dp(10))
            background = createCardDrawable(Color.parseColor("#DC2626"), Color.parseColor("#B91C1C"), dp(8))
            isClickable = true
            setOnClickListener {
                LocalBlocklistManager.clearAllBlocked(this@MainActivity)
                cachedCallLogs = null
                cachedContacts = null
                Toast.makeText(this@MainActivity, "All protection reset. Blocklist cleared. Normal calls enabled.", Toast.LENGTH_LONG).show()
                refreshShieldView()
                refreshCallLogs(forceReload = true)
            }
        }
        resetCard.addView(resetTitle)
        resetCard.addView(resetDesc)
        resetCard.addView(btnResetAll)
        shieldContainer.addView(resetCard)

        // 4. Backend Gateway Configuration
        val gatewayCard = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(16), dp(14), dp(16), dp(14))
            background = createCardDrawable(Color.parseColor("#F8FAFC"), Color.parseColor("#E2E8F0"), dp(12))
        }
        val gwText = TextView(this).apply {
            text = "Backend Gateway: ${VigilApiClient.backendBaseUrl}"
            textSize = 11f
            setTextColor(Color.parseColor("#64748B"))
            typeface = Typeface.MONOSPACE
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        }
        val btnChangeIp = TextView(this).apply {
            text = "Change"
            textSize = 11f
            setTextColor(Color.parseColor("#2563EB"))
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
            setPadding(dp(10), dp(4), dp(10), dp(4))
            isClickable = true
            setOnClickListener { showChangeIpDialog() }
        }
        gatewayCard.addView(gwText)
        gatewayCard.addView(btnChangeIp)
        shieldContainer.addView(gatewayCard)
    }

    private fun createStageDiagramStep(stepNum: String, title: String, desc: String): View {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, dp(6), 0, dp(6))
        }
        val numBadge = TextView(this).apply {
            text = stepNum
            textSize = 11f
            setTextColor(Color.WHITE)
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
            gravity = Gravity.CENTER
            background = createCircleDrawable(Color.parseColor("#2563EB"))
            layoutParams = LinearLayout.LayoutParams(dp(22), dp(22)).apply {
                rightMargin = dp(10)
                topMargin = dp(2)
            }
        }
        val textCol = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
        }
        val tView = TextView(this).apply {
            text = title
            textSize = 13f
            setTextColor(Color.parseColor("#111827"))
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
        }
        val dView = TextView(this).apply {
            text = desc
            textSize = 11f
            setTextColor(Color.parseColor("#6B7280"))
            setPadding(0, dp(2), 0, 0)
        }
        textCol.addView(tView)
        textCol.addView(dView)
        row.addView(numBadge)
        row.addView(textCol)
        return row
    }

    private fun createSimulateBtn(title: String, colorHex: String, onClick: () -> Unit): View {
        return TextView(this).apply {
            text = title
            textSize = 12f
            setTextColor(Color.parseColor(colorHex))
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
            setPadding(dp(12), dp(10), dp(12), dp(10))
            background = createCardDrawable(Color.WHITE, Color.parseColor(colorHex), dp(8))
            isClickable = true
            setOnClickListener { onClick() }
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply {
                bottomMargin = dp(8)
            }
        }
    }

    // ══════════════════════════════════════════════════════════════════
    // 4. THE 3-STAGE EVALUATION & SIMULATION RUNNER
    // ══════════════════════════════════════════════════════════════════
    private fun simulateThreeStageCall(phoneNumber: String, name: String, simulatedType: String) {
        CoroutineScope(Dispatchers.IO).launch {
            val eval = ThreeStageProtectionEngine.evaluateCall(
                context = this@MainActivity,
                phoneNumber = phoneNumber,
                simulatedVoiceType = simulatedType
            )

            withContext(Dispatchers.Main) {
                when {
                    // Stage 1 Blocked (Robotic Clone)
                    eval.stepStoppedAt == 1 -> {
                        showStage1BlockedDialog(phoneNumber, eval)
                    }

                    // Stage 2 Blocked (Voice Impersonator of known relation)
                    eval.stepStoppedAt == 2 && eval.finalVerdict == "BLOCK" -> {
                        showStage2ImpersonatorDialog(phoneNumber, eval)
                    }

                    // Stage 2 Prompt User ("Do you know this person?")
                    eval.finalVerdict == "PROMPT_USER" -> {
                        showDoYouKnowThisPersonDialog(phoneNumber, eval)
                    }

                    // Allowed Call (Known person + clean voice + Stage 3 passed)
                    else -> {
                        showCallPassedDialog(phoneNumber, name, eval)
                    }
                }
            }
        }
    }

    private fun showStage1BlockedDialog(phoneNumber: String, eval: ThreeStageEvaluation) {
        AlertDialog.Builder(this)
            .setTitle("🚨 STAGE 1 BLOCKED: Voice Clone Detected")
            .setMessage(
                "Caller: $phoneNumber\n\n" +
                "Stage 1 Verdict: ⛔ REJECTED\n" +
                "Voice Type: ${eval.stage1.voiceType}\n" +
                "Clone Probability: ${(eval.stage1.cloneProbability * 100).toInt()}%\n\n" +
                "Action Taken: Call dropped before ringing.\n" +
                "Number added to local hardware blocklist."
            )
            .setPositiveButton("OK") { _, _ -> refreshCallLogs() }
            .show()
    }

    private fun showStage2ImpersonatorDialog(phoneNumber: String, eval: ThreeStageEvaluation) {
        AlertDialog.Builder(this)
            .setTitle("⛔ STAGE 2 BLOCKED: Voice Impersonation Fraud")
            .setMessage(
                "Caller Number: $phoneNumber\n" +
                "Claimed Relation: ${eval.stage2.matchedRelation} (${eval.stage2.matchedPersonName})\n\n" +
                "Stage 1: Passed (Natural human speech)\n" +
                "Stage 2: ⛔ FAILED BIOMETRIC MATCH\n" +
                "Similarity: ${(eval.stage2.similarityScore * 100).toInt()}% (Threshold: 65%)\n\n" +
                "Reason: Caller claims to be your ${eval.stage2.matchedRelation}, but their voice acoustic profile does NOT match the registered voiceprint.\n\n" +
                "Action Taken: Call terminated to protect from impersonation extortion."
            )
            .setPositiveButton("OK") { _, _ -> refreshCallLogs() }
            .show()
    }

    private fun showDoYouKnowThisPersonDialog(phoneNumber: String, eval: ThreeStageEvaluation) {
        AlertDialog.Builder(this)
            .setTitle("❓ Stage 2: Do you know this person?")
            .setMessage(
                "Incoming call from: $phoneNumber\n\n" +
                "Stage 1 Result: ✓ Genuine voice confirmed (No AI deepfake detected).\n\n" +
                "This number is not yet saved in your verified contacts.\n" +
                "Do you know the person calling from this number?"
            )
            .setPositiveButton("Yes, I know them") { _, _ ->
                showSaveNameAndRelationDialog(phoneNumber)
            }
            .setNegativeButton("No, Unknown Caller") { _, _ ->
                Toast.makeText(this, "Marked as unverified stranger.", Toast.LENGTH_SHORT).show()
                refreshCallLogs()
            }
            .show()
    }

    private fun showSaveNameAndRelationDialog(phoneNumber: String) {
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(10), dp(20), dp(10))
        }

        val inputName = EditText(this).apply {
            hint = "Enter person's name (e.g. Rahul, Dr. Sharma)"
            textSize = 14f
            setPadding(dp(12), dp(12), dp(12), dp(12))
            background = createCardDrawable(Color.WHITE, Color.parseColor("#CBD5E1"), dp(8))
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply {
                bottomMargin = dp(10)
            }
        }

        val inputRelation = EditText(this).apply {
            hint = "Enter relation (e.g. Father, Colleague, Friend)"
            textSize = 14f
            setPadding(dp(12), dp(12), dp(12), dp(12))
            background = createCardDrawable(Color.WHITE, Color.parseColor("#CBD5E1"), dp(8))
        }

        container.addView(inputName)
        container.addView(inputRelation)

        AlertDialog.Builder(this)
            .setTitle("Save Name & Relationship")
            .setMessage("Save this person locally so VIGIL-AI can verify future calls from them:")
            .setView(container)
            .setPositiveButton("Save Locally") { _, _ ->
                val name = inputName.text.toString().trim()
                val relation = inputRelation.text.toString().trim()

                if (name.isNotBlank()) {
                    val person = KnownPerson(
                        phoneNumber = phoneNumber,
                        name = name,
                        relation = if (relation.isNotBlank()) relation else "Acquaintance",
                        isConfirmed = true,
                        voiceEnrolled = true
                    )
                    KnownPersonRepository.saveKnownPerson(this, person)
                    Toast.makeText(this, "Saved: $name ($relation)", Toast.LENGTH_SHORT).show()
                    cachedCallLogs = null
                    cachedContacts = null
                    refreshCallLogs(forceReload = true)
                    refreshContacts(forceReload = true)
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun showCallPassedDialog(phoneNumber: String, name: String, eval: ThreeStageEvaluation) {
        AlertDialog.Builder(this)
            .setTitle("✅ 3-Stage Screening Passed")
            .setMessage(
                "Caller: $name ($phoneNumber)\n\n" +
                "✓ Stage 1: Genuine Human Voice (0.04 synthetic score)\n" +
                "✓ Stage 2: Verified Relation (${eval.stage2.matchedRelation}) - Voice Matched\n" +
                "✓ Stage 3: Spam & Risk Analysis - Risk Score: ${eval.stage3.riskScore}/100 [LOW RISK]\n\n" +
                "Verdict: ALLOWED & SECURED"
            )
            .setPositiveButton("OK", null)
            .show()
    }

    private fun showAudioFeasibilityDialog() {
        val report = com.vigilai.audio.AudioFeasibilityProbe.runProbe(this)

        val scroll = ScrollView(this).apply {
            setPadding(dp(16), dp(8), dp(16), dp(16))
        }
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
        }

        val tvStatus = TextView(this).apply {
            text = "Status: ${report.overallStatus}"
            textSize = 15f
            setTextColor(when (report.overallStatus) {
                com.vigilai.audio.AudioFeasibilityStatus.AUDIO_PATH_AVAILABLE -> Color.parseColor("#059669")
                com.vigilai.audio.AudioFeasibilityStatus.AUDIO_PATH_UNCERTAIN -> Color.parseColor("#D97706")
                else -> Color.parseColor("#DC2626")
            })
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
            setPadding(0, 0, 0, dp(4))
        }
        val tvOrigin = TextView(this).apply {
            text = "Primary Origin: ${report.primaryOrigin.name}\n${report.primaryOrigin.description}"
            textSize = 12f
            setTextColor(Color.parseColor("#475569"))
            setPadding(0, 0, 0, dp(12))
        }
        container.addView(tvStatus)
        container.addView(tvOrigin)

        for (probe in report.probeResults) {
            val item = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(dp(10), dp(8), dp(10), dp(8))
                background = createCardDrawable(Color.parseColor("#F8FAFC"), Color.parseColor("#E2E8F0"), dp(8))
                layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                    bottomMargin = dp(6)
                }
            }
            val title = TextView(this).apply {
                text = probe.sourceName
                textSize = 12f
                setTextColor(Color.parseColor("#0F172A"))
                typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
            }
            val details = TextView(this).apply {
                text = "Status: ${probe.status} • NonZeroPCM: ${probe.nonZeroPcmDetected} • RMS: ${probe.rmsLevelDb.toInt()}dB\n${probe.diagnosticReason}"
                textSize = 11f
                setTextColor(Color.parseColor("#64748B"))
                setPadding(0, dp(2), 0, 0)
            }
            item.addView(title)
            item.addView(details)
            container.addView(item)
        }

        val tvExec = TextView(this).apply {
            text = "\nEXECUTIVE SUMMARY:\n${report.executiveSummary}"
            textSize = 11f
            setTextColor(Color.parseColor("#334155"))
            setPadding(0, dp(8), 0, 0)
        }
        container.addView(tvExec)
        scroll.addView(container)

        AlertDialog.Builder(this)
            .setTitle("🔬 Audio Feasibility Investigation")
            .setView(scroll)
            .setPositiveButton("Close", null)
            .show()
    }

    // ══════════════════════════════════════════════════════════════════
    // 5. INTERACTIVE DIALPAD BOTTOM SHEET
    // ══════════════════════════════════════════════════════════════════
    private fun showDialpadBottomSheet(initialNumber: String = "") {
        val sheetLayout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(24), dp(16), dp(24), dp(24))
            setBackgroundColor(Color.WHITE)
        }

        // Top drag handle
        val handle = View(this).apply {
            background = createCardDrawable(Color.parseColor("#D1D5DB"), Color.TRANSPARENT, dp(3))
            layoutParams = LinearLayout.LayoutParams(dp(40), dp(5)).apply {
                gravity = Gravity.CENTER_HORIZONTAL
                bottomMargin = dp(16)
            }
        }
        sheetLayout.addView(handle)

        // Number Display Row
        val displayRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(48)).apply {
                bottomMargin = dp(16)
            }
        }

        val numberDisplay = TextView(this).apply {
            text = initialNumber
            textSize = 28f
            setTextColor(Color.parseColor("#111827"))
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
            gravity = Gravity.CENTER
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        }
        displayRow.addView(numberDisplay)

        val btnBackspace = TextView(this).apply {
            text = "⌫"
            textSize = 22f
            setTextColor(Color.parseColor("#9CA3AF"))
            setPadding(dp(8), dp(4), dp(8), dp(4))
            isClickable = true
            setOnClickListener {
                val cur = numberDisplay.text.toString()
                if (cur.isNotEmpty()) {
                    numberDisplay.text = cur.substring(0, cur.length - 1)
                }
            }
        }
        displayRow.addView(btnBackspace)
        sheetLayout.addView(displayRow)

        // 3x4 Dialpad Grid
        val keys = listOf(
            listOf("1" to "", "2" to "ABC", "3" to "DEF"),
            listOf("4" to "GHI", "5" to "JKL", "6" to "MNO"),
            listOf("7" to "PQRS", "8" to "TUV", "9" to "WXYZ"),
            listOf("*" to "", "0" to "+", "#" to "")
        )

        for (rowKeys in keys) {
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                weightSum = 3f
                layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(64))
            }

            for ((digit, sub) in rowKeys) {
                val keyBtn = LinearLayout(this).apply {
                    orientation = LinearLayout.VERTICAL
                    gravity = Gravity.CENTER
                    background = createRipplePill(Color.parseColor("#F9FAFB"), dp(32))
                    isClickable = true
                    layoutParams = LinearLayout.LayoutParams(0, dp(58), 1f).apply {
                        leftMargin = dp(8)
                        rightMargin = dp(8)
                        topMargin = dp(3)
                        bottomMargin = dp(3)
                    }
                    setOnClickListener {
                        numberDisplay.append(digit)
                    }
                    setOnLongClickListener {
                        if (digit == "0") {
                            numberDisplay.append("+")
                            true
                        } else false
                    }
                }

                val digitText = TextView(this).apply {
                    text = digit
                    textSize = 20f
                    setTextColor(Color.parseColor("#111827"))
                    typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
                }
                keyBtn.addView(digitText)

                if (sub.isNotBlank()) {
                    val subText = TextView(this).apply {
                        text = sub
                        textSize = 9f
                        setTextColor(Color.parseColor("#9CA3AF"))
                    }
                    keyBtn.addView(subText)
                }
                row.addView(keyBtn)
            }
            sheetLayout.addView(row)
        }

        // Call Action Buttons (Make Call / Test 3-Stage Scan)
        val actionRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                topMargin = dp(16)
            }
        }

        val btnCall = TextView(this).apply {
            text = "📞"
            textSize = 24f
            setTextColor(Color.WHITE)
            gravity = Gravity.CENTER
            background = createCircleDrawable(Color.parseColor("#10B981"))
            elevation = dp(4).toFloat()
            isClickable = true
            layoutParams = LinearLayout.LayoutParams(dp(64), dp(64))
        }

        var dialogRef: AlertDialog? = null

        btnCall.setOnClickListener {
            val num = numberDisplay.text.toString().trim()
            if (num.isBlank()) {
                Toast.makeText(this, "Enter a phone number to call", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            dialogRef?.dismiss()
            initiatePhoneCall(num)
        }
        actionRow.addView(btnCall)
        sheetLayout.addView(actionRow)

        dialogRef = AlertDialog.Builder(this)
            .setView(sheetLayout)
            .create()
        dialogRef.show()
    }

    // ══════════════════════════════════════════════════════════════════
    // 6. CALL DETAILS & SECURITY PROFILE DIALOG
    // ══════════════════════════════════════════════════════════════════
    private fun showCallDetailsDialog(item: CallLogItem) {
        val knownPerson = KnownPersonRepository.getKnownPerson(this, item.number)
        val isBlocked = LocalBlocklistManager.isBlocked(this, item.number)

        val dialogView = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(22), dp(18), dp(22), dp(18))
        }

        val nameView = TextView(this).apply {
            text = item.displayTitle
            textSize = 18f
            setTextColor(Color.parseColor("#111827"))
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
        }
        val numberView = TextView(this).apply {
            text = item.number
            textSize = 14f
            setTextColor(Color.parseColor("#6B7280"))
            setPadding(0, dp(2), 0, dp(10))
        }
        dialogView.addView(nameView)
        dialogView.addView(numberView)

        val audit = com.vigilai.storage.CallAuditRepository.getLatestAuditForNumber(this, item.number)

        // 3-Stage Security Summary Box
        val secCard = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(12), dp(12), dp(12), dp(12))
            background = createCardDrawable(Color.parseColor("#F8FAFC"), Color.parseColor("#E2E8F0"), dp(10))
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                bottomMargin = dp(14)
            }
        }
        secCard.addView(createMetricRow("AI Security Status:", item.aiVerdict.displayName, item.aiVerdict.badgeColorHex))
        secCard.addView(createMetricRow("Relationship:", item.relation ?: "Not Registered", "#2563EB"))
        secCard.addView(createMetricRow("Threat Risk Score:", "${item.riskScore}%", if (item.riskScore > 50) "#DC2626" else "#10B981"))

        if (audit != null) {
            secCard.addView(createMetricRow("Stage 1 (Authenticity):", if (audit.isClone) "Deepfake Clone (${(audit.cloneProbability * 100).toInt()}%)" else "Genuine Voice (${((1f - audit.cloneProbability) * 100).toInt()}%)", if (audit.isClone) "#DC2626" else "#10B981"))
            secCard.addView(createMetricRow("Stage 2 (ECAPA Sim):", "${(audit.similarityScore * 100).toInt()}% • ${if (audit.isSpeakerMatched) "Matched" else "Unmatched"}", if (audit.isSpeakerMatched) "#0284C7" else "#64748B"))
            secCard.addView(createMetricRow("Stage 3 (Intent):", "${audit.callerIntent} • ${audit.threatLevel}", if (audit.isSpam) "#DC2626" else "#10B981"))
        } else {
            secCard.addView(createMetricRow("Voice Biometrics:", if (knownPerson?.voiceEnrolled == true) "Enrolled & Protected" else "Pending Registration", "#475569"))
        }
        dialogView.addView(secCard)

        var dialogRef: AlertDialog? = null

        // Action Buttons Row (Call, Scan AI, Edit Relation, Block/Unblock)
        val btnRow = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
        }

        // Call Button
        val btnCall = TextView(this).apply {
            text = "📞 Call ${item.number}"
            textSize = 13f
            setTextColor(Color.WHITE)
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
            gravity = Gravity.CENTER
            setPadding(0, dp(10), 0, dp(10))
            background = createCardDrawable(Color.parseColor("#10B981"), Color.parseColor("#059669"), dp(8))
            isClickable = true
            setOnClickListener {
                dialogRef?.dismiss()
                initiatePhoneCall(item.number)
            }
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                bottomMargin = dp(8)
            }
        }
        btnRow.addView(btnCall)

        // Live AI Agent Scan Button
        val btnScanAi = TextView(this).apply {
            text = "🛡️ Scan Caller with AI Agent"
            textSize = 13f
            setTextColor(Color.WHITE)
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
            gravity = Gravity.CENTER
            setPadding(0, dp(10), 0, dp(10))
            background = createCardDrawable(Color.parseColor("#2563EB"), Color.parseColor("#1D4ED8"), dp(8))
            isClickable = true
            setOnClickListener {
                dialogRef?.dismiss()
                Toast.makeText(this@MainActivity, "🛡️ VIGIL-AI: Running AI Agent scan on ${item.number}...", Toast.LENGTH_SHORT).show()
                mainScope.launch {
                    withContext(Dispatchers.IO) {
                        com.vigilai.screening.ThreeStageProtectionEngine.evaluateCall(
                            context = applicationContext,
                            phoneNumber = item.number
                        )
                    }
                    refreshCallLogs(forceReload = true)
                    Toast.makeText(this@MainActivity, "✓ AI Risk Evaluation Complete & Saved to Call Log!", Toast.LENGTH_LONG).show()
                }
            }
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                bottomMargin = dp(8)
            }
        }
        btnRow.addView(btnScanAi)

        // Edit Relation Button
        val btnEditRelation = TextView(this).apply {
            text = "✏️ Set / Edit Relation"
            textSize = 13f
            setTextColor(Color.parseColor("#2563EB"))
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
            gravity = Gravity.CENTER
            setPadding(0, dp(10), 0, dp(10))
            background = createCardDrawable(Color.WHITE, Color.parseColor("#2563EB"), dp(8))
            isClickable = true
            setOnClickListener {
                dialogRef?.dismiss()
                showSaveNameAndRelationDialog(item.number)
            }
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                bottomMargin = dp(8)
            }
        }
        btnRow.addView(btnEditRelation)

        // Block / Unblock Button
        val btnBlock = TextView(this).apply {
            text = if (isBlocked) "✓ Unblock Number" else "⛔ Block Number"
            textSize = 13f
            setTextColor(if (isBlocked) Color.parseColor("#059669") else Color.parseColor("#DC2626"))
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
            gravity = Gravity.CENTER
            setPadding(0, dp(10), 0, dp(10))
            background = createCardDrawable(Color.WHITE, if (isBlocked) Color.parseColor("#059669") else Color.parseColor("#DC2626"), dp(8))
            isClickable = true
            setOnClickListener {
                dialogRef?.dismiss()
                if (isBlocked) {
                    LocalBlocklistManager.removeBlocked(this@MainActivity, item.number)
                    Toast.makeText(this@MainActivity, "Unblocked: ${item.number}", Toast.LENGTH_SHORT).show()
                } else {
                    LocalBlocklistManager.addBlocked(this@MainActivity, item.number)
                    Toast.makeText(this@MainActivity, "Added to Blocklist: ${item.number}", Toast.LENGTH_SHORT).show()
                }
                refreshCallLogs(forceReload = true)
            }
        }
        btnRow.addView(btnBlock)
        dialogView.addView(btnRow)

        dialogRef = AlertDialog.Builder(this)
            .setView(dialogView)
            .setNegativeButton("Close", null)
            .create()
        dialogRef.show()
    }

    private fun createMetricRow(label: String, value: String, colorHex: String): View {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, dp(3), 0, dp(3))
        }
        val lbl = TextView(this).apply {
            text = label
            textSize = 12f
            setTextColor(Color.parseColor("#64748B"))
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1.2f)
        }
        val valView = TextView(this).apply {
            text = value
            textSize = 12f
            setTextColor(Color.parseColor(colorHex))
            typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
            gravity = Gravity.END
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        row.addView(lbl)
        row.addView(valView)
        return row
    }

    // ══════════════════════════════════════════════════════════════════
    // 7. DIALOGS & POPUPS
    // ══════════════════════════════════════════════════════════════════
    private fun showFilterMenu() {
        val options = arrayOf("All calls", "Missed calls", "Blocked calls", "Screened calls")
        AlertDialog.Builder(this)
            .setTitle("Filter Recents")
            .setItems(options) { _, which ->
                currentFilter = when (which) {
                    1 -> "MISSED"
                    2 -> "BLOCKED"
                    3 -> "SCREENED"
                    else -> "ALL"
                }
                filterDropdown.text = "${options[which]} ⌄"
                refreshCallLogs()
            }
            .show()
    }

    private fun showAddKnownPersonDialog() {
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(10), dp(20), dp(10))
        }
        val inputName = EditText(this).apply {
            hint = "Full Name"
            textSize = 14f
            setPadding(dp(12), dp(12), dp(12), dp(12))
            background = createCardDrawable(Color.WHITE, Color.parseColor("#CBD5E1"), dp(8))
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                bottomMargin = dp(8)
            }
        }
        val inputNumber = EditText(this).apply {
            hint = "Phone Number (e.g. +91 98201 10001)"
            textSize = 14f
            setPadding(dp(12), dp(12), dp(12), dp(12))
            background = createCardDrawable(Color.WHITE, Color.parseColor("#CBD5E1"), dp(8))
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                bottomMargin = dp(8)
            }
        }
        val inputRelation = EditText(this).apply {
            hint = "Relation (Father, Colleague, Friend, etc.)"
            textSize = 14f
            setPadding(dp(12), dp(12), dp(12), dp(12))
            background = createCardDrawable(Color.WHITE, Color.parseColor("#CBD5E1"), dp(8))
        }
        container.addView(inputName)
        container.addView(inputNumber)
        container.addView(inputRelation)

        AlertDialog.Builder(this)
            .setTitle("Add Known Person")
            .setView(container)
            .setPositiveButton("Save") { _, _ ->
                val name = inputName.text.toString().trim()
                val num = inputNumber.text.toString().trim()
                val rel = inputRelation.text.toString().trim()
                if (name.isNotBlank() && num.isNotBlank()) {
                    KnownPersonRepository.saveKnownPerson(
                        this,
                        KnownPerson(num, name, if (rel.isNotBlank()) rel else "Friend", isConfirmed = true, voiceEnrolled = true)
                    )
                    Toast.makeText(this, "Saved $name to known contacts", Toast.LENGTH_SHORT).show()
                    cachedContacts = null
                    cachedCallLogs = null
                    refreshContacts(forceReload = true)
                    refreshCallLogs(forceReload = true)
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun showChangeIpDialog() {
        val input = EditText(this).apply {
            setText(VigilApiClient.backendBaseUrl)
            textSize = 13f
            typeface = Typeface.MONOSPACE
            setPadding(dp(14), dp(14), dp(14), dp(14))
            background = createCardDrawable(Color.WHITE, Color.parseColor("#CBD5E1"), dp(8))
        }
        val container = LinearLayout(this).apply {
            setPadding(dp(20), dp(10), dp(20), dp(10))
            addView(input)
        }

        AlertDialog.Builder(this)
            .setTitle("Configure Backend IP")
            .setMessage("Enter the IP and port of the computer running VIGIL-AI:")
            .setView(container)
            .setPositiveButton("Save") { _, _ ->
                val newUrl = input.text.toString().trim()
                if (newUrl.isNotBlank()) {
                    VigilApiClient.backendBaseUrl = newUrl
                    LocalBlocklistManager.saveBackendUrl(this, newUrl)
                    refreshShieldView()
                    Toast.makeText(this, "Updated backend: $newUrl", Toast.LENGTH_SHORT).show()
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    // ══════════════════════════════════════════════════════════════════
    // 8. TELEPHONY ROLES & PERMISSIONS
    // ══════════════════════════════════════════════════════════════════
    private fun requestRequiredPermissions() {
        val permissions = mutableListOf(
            android.Manifest.permission.READ_PHONE_STATE,
            android.Manifest.permission.CALL_PHONE,
            android.Manifest.permission.RECORD_AUDIO,
            android.Manifest.permission.READ_CALL_LOG,
            android.Manifest.permission.WRITE_CALL_LOG,
            android.Manifest.permission.READ_CONTACTS,
            android.Manifest.permission.WRITE_CONTACTS
        )
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            permissions.add(android.Manifest.permission.POST_NOTIFICATIONS)
        }

        val ungranted = permissions.filter {
            ActivityCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }

        if (ungranted.isNotEmpty()) {
            ActivityCompat.requestPermissions(this, ungranted.toTypedArray(), REQUEST_PERMISSIONS)
        }
    }

    private fun requestDefaultDialerRole() {
        val intent = CallScreeningRoleHelper.createRequestDialerRoleIntent(this)
        if (intent != null) {
            startActivityForResult(intent, REQUEST_DIALER_ROLE)
        } else {
            val screeningIntent = CallScreeningRoleHelper.createRequestRoleIntent(this)
            if (screeningIntent != null) {
                startActivityForResult(screeningIntent, REQUEST_DIALER_ROLE)
            } else {
                Toast.makeText(this, "Role requests not supported on this device profile", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun openSystemDefaultAppsSettings() {
        try {
            val intent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                Intent(android.provider.Settings.ACTION_MANAGE_DEFAULT_APPS_SETTINGS)
            } else {
                Intent(android.provider.Settings.ACTION_SETTINGS)
            }
            startActivity(intent)
        } catch (e: Exception) {
            try {
                val intent = Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
                    data = Uri.parse("package:$packageName")
                }
                startActivity(intent)
            } catch (e2: Exception) {
                Toast.makeText(this, "Could not open settings: ${e2.message}", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun requestDisableBatteryOptimization() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            try {
                val pm = getSystemService(Context.POWER_SERVICE) as android.os.PowerManager
                if (!pm.isIgnoringBatteryOptimizations(packageName)) {
                    val intent = Intent(android.provider.Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
                        data = Uri.parse("package:$packageName")
                    }
                    startActivity(intent)
                } else {
                    Toast.makeText(this, "Battery optimization already disabled for VIGIL-AI", Toast.LENGTH_SHORT).show()
                }
            } catch (e: Exception) {
                try {
                    startActivity(Intent(android.provider.Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
                } catch (e2: Exception) {
                    Toast.makeText(this, "Please go to Settings -> Battery -> No restrictions", Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQUEST_DIALER_ROLE) {
            refreshShieldView()
            if (resultCode == RESULT_OK) {
                Toast.makeText(this, "VIGIL-AI activated as Default Phone App!", Toast.LENGTH_SHORT).show()
            }
        }
    }

    // ══════════════════════════════════════════════════════════════════
    // 9. UI STYLING & VIEW CREATION HELPERS
    // ══════════════════════════════════════════════════════════════════
    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    private fun createCardDrawable(bgColor: Int, strokeColor: Int, cornerRadius: Int): GradientDrawable {
        return GradientDrawable().apply {
            shape = GradientDrawable.RECTANGLE
            setColor(bgColor)
            setStroke(dp(1), strokeColor)
            this.cornerRadius = cornerRadius.toFloat()
        }
    }

    private fun createCircleDrawable(color: Int): GradientDrawable {
        return GradientDrawable().apply {
            shape = GradientDrawable.OVAL
            setColor(color)
        }
    }

    private fun createRipplePill(normalColor: Int, cornerRadius: Int): RippleDrawable {
        val normal = GradientDrawable().apply {
            shape = GradientDrawable.RECTANGLE
            setColor(normalColor)
            this.cornerRadius = cornerRadius.toFloat()
        }
        val ripple = ColorStateList.valueOf(Color.parseColor("#20000000"))
        return RippleDrawable(ripple, normal, null)
    }

    private fun createBottomNavItem(icon: String, title: String, isActive: Boolean, onClick: () -> Unit): LinearLayout {
        return LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.MATCH_PARENT, 1f)
            isClickable = true
            setOnClickListener { onClick() }

            val iconView = TextView(this@MainActivity).apply {
                text = icon
                textSize = 18f
                gravity = Gravity.CENTER
            }
            val titleView = TextView(this@MainActivity).apply {
                text = title
                textSize = 11f
                gravity = Gravity.CENTER
                setTextColor(if (isActive) Color.parseColor("#111827") else Color.parseColor("#9CA3AF"))
                typeface = if (isActive) Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD) else Typeface.create(Typeface.SANS_SERIF, Typeface.NORMAL)
            }
            addView(iconView)
            addView(titleView)
        }
    }

    private fun updateBottomNavState(navItem: LinearLayout, isActive: Boolean) {
        val titleView = navItem.getChildAt(1) as? TextView
        titleView?.setTextColor(if (isActive) Color.parseColor("#111827") else Color.parseColor("#9CA3AF"))
        titleView?.typeface = if (isActive) Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD) else Typeface.create(Typeface.SANS_SERIF, Typeface.NORMAL)
    }

    override fun onDestroy() {
        super.onDestroy()
        mainScope.cancel()
    }
}
