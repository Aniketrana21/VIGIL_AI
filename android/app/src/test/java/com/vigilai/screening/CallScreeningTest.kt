package com.vigilai.screening

import android.telecom.TelecomManager
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * Android Incoming-Call Screening Tests (Phase 8).
 *
 * Verifies real-time decisioning, Telecom SLA timeout guarantees,
 * STIR/SHAKEN verification handling, and fallback mechanics.
 */
class CallScreeningTest {

    private lateinit var riskEngine: DefaultCallRiskEngine
    private val blacklistedNumbers = setOf("+919876543210", "+18005550199")
    private val trustedContacts = setOf("+15551112233", "+447911123456")

    @Before
    fun setUp() {
        riskEngine = DefaultCallRiskEngine(
            remoteClient = null,
            blacklistedNumbers = blacklistedNumbers,
            trustedContacts = trustedContacts,
            deadlineTimeoutMs = 1500L
        )
    }

    /**
     * 1. Test Unknown Caller:
     * Standard incoming call with unverified carrier status and no blacklist hit.
     * Expectation: Safe ALLOW decision with low/moderate baseline score.
     */
    @Test
    fun testUnknownCaller_ReturnsAllow() = runBlocking {
        val metadata = CallMetadata(
            rawHandle = "+15559876543",
            phoneNumber = "+15559876543",
            callerDisplayName = "John Smith",
            callerDisplayNamePresentation = TelecomManager.PRESENTATION_ALLOWED,
            handlePresentation = TelecomManager.PRESENTATION_ALLOWED,
            callerNumberVerificationStatus = CallMetadata.STATUS_NOT_VERIFIED,
            isKnownContact = false
        )

        val decision = riskEngine.evaluate(metadata)

        assertEquals("Unknown caller without negative markers must be allowed", ScreeningAction.ALLOW, decision.action)
        assertTrue("Risk score should be below warning threshold (0.5)", decision.riskScore < 0.5f)
        assertFalse("Decision must not be marked preliminary", decision.isPreliminary)
        assertTrue("Latency must be positive", decision.latencyMs >= 0L)
    }

    /**
     * 2. Test Verified Caller:
     * Carrier STIR/SHAKEN attestation passed (status = PASSED / 1).
     * Expectation: High trust, minimal risk score, ALLOW action.
     */
    @Test
    fun testVerifiedCaller_ReturnsAllowWithHighTrust() = runBlocking {
        val metadata = CallMetadata(
            rawHandle = "+12025550143",
            phoneNumber = "+12025550143",
            callerDisplayName = "Verified Delivery Service",
            callerDisplayNamePresentation = TelecomManager.PRESENTATION_ALLOWED,
            handlePresentation = TelecomManager.PRESENTATION_ALLOWED,
            callerNumberVerificationStatus = CallMetadata.STATUS_PASSED,
            isKnownContact = false
        )

        val decision = riskEngine.evaluate(metadata)

        assertEquals("Verified caller must be allowed", ScreeningAction.ALLOW, decision.action)
        assertTrue("Verified caller risk score must be very low (<= 0.10)", decision.riskScore <= 0.10f)
        assertTrue("Explanation should mention STIR/SHAKEN verification", decision.explanation.contains("STIR/SHAKEN", ignoreCase = true))
    }

    /**
     * 3. Test Failed Caller Verification:
     * Carrier STIR/SHAKEN cryptographic check failed (status = FAILED / 2).
     * Indicates caller ID spoofing / impersonation attack.
     * Expectation: SILENCE or BLOCK action to shield user, high risk score.
     */
    @Test
    fun testFailedCallerVerification_ReturnsSilenceOrBlock() = runBlocking {
        val metadata = CallMetadata(
            rawHandle = "+18002752273", // Spoofed Apple Support number
            phoneNumber = "+18002752273",
            callerDisplayName = "Apple Support",
            callerDisplayNamePresentation = TelecomManager.PRESENTATION_ALLOWED,
            handlePresentation = TelecomManager.PRESENTATION_ALLOWED,
            callerNumberVerificationStatus = CallMetadata.STATUS_FAILED,
            isKnownContact = false
        )

        val decision = riskEngine.evaluate(metadata)

        assertTrue(
            "Failed STIR/SHAKEN verification must trigger SILENCE or BLOCK",
            decision.action == ScreeningAction.SILENCE || decision.action == ScreeningAction.BLOCK
        )
        assertTrue("Risk score must be >= 0.70 on failed cryptographic verification", decision.riskScore >= 0.70f)
        assertTrue("Explanation must detail verification failure", decision.explanation.contains("failed", ignoreCase = true))
    }

    /**
     * 4. Test Known Contact:
     * Number matches user's local contact address book.
     * Expectation: Fast-path ALLOW with 0.0 risk score, regardless of carrier STIR/SHAKEN status.
     */
    @Test
    fun testKnownContact_ReturnsImmediateAllow() = runBlocking {
        val metadata = CallMetadata(
            rawHandle = "+15551112233",
            phoneNumber = "+15551112233",
            callerDisplayName = "Alice Family",
            callerDisplayNamePresentation = TelecomManager.PRESENTATION_ALLOWED,
            handlePresentation = TelecomManager.PRESENTATION_ALLOWED,
            callerNumberVerificationStatus = CallMetadata.STATUS_NOT_VERIFIED,
            isKnownContact = true
        )

        val decision = riskEngine.evaluate(metadata)

        assertEquals("Known contact must be instantly allowed", ScreeningAction.ALLOW, decision.action)
        assertEquals("Risk score must be 0.0 for known contact", 0.0f, decision.riskScore, 0.001f)
        assertTrue("Explanation must indicate trusted contact", decision.explanation.contains("contact", ignoreCase = true))
    }

    /**
     * 5. Test Blocked Number:
     * Number present on scam / voice clone blacklist.
     * Expectation: Instant BLOCK decision, risk score 1.0.
     */
    @Test
    fun testBlockedNumber_ReturnsImmediateBlock() = runBlocking {
        val metadata = CallMetadata(
            rawHandle = "+919876543210", // On blacklist
            phoneNumber = "+919876543210",
            callerDisplayName = "Scam Tax Agent",
            callerDisplayNamePresentation = TelecomManager.PRESENTATION_ALLOWED,
            handlePresentation = TelecomManager.PRESENTATION_ALLOWED,
            callerNumberVerificationStatus = CallMetadata.STATUS_NOT_VERIFIED,
            isKnownContact = false
        )

        val decision = riskEngine.evaluate(metadata)

        assertEquals("Blacklisted caller must be blocked immediately", ScreeningAction.BLOCK, decision.action)
        assertEquals("Blacklisted caller risk score must be 1.0", 1.0f, decision.riskScore, 0.001f)
        assertTrue("Explanation must cite blacklist", decision.explanation.contains("blacklist", ignoreCase = true))
    }

    /**
     * 6. Test Timeout Deadline Enforcement:
     * Simulates a slow remote backend or complex check that exceeds the deadline SLA.
     * Expectation: Safe preliminary ALLOW returned before Android Telecom 5s ceiling expires.
     * Secondary analysis task is queued.
     */
    @Test
    fun testTimeout_ReturnsSafePreliminaryDecision() = runBlocking {
        var secondaryAnalysisTriggered = false
        var capturedSecondaryTaskId: String? = null

        // Slow remote client that simulates an 8000ms delay (exceeding deadline)
        val slowClient = object : ScreeningRemoteClient {
            override suspend fun queryRisk(
                phoneNumber: String,
                displayName: String?,
                stirShakenStatus: Int,
                carrierCode: String?
            ): RemoteRiskResponse {
                delay(8000L) // Exceeds deadlineTimeoutMs
                return RemoteRiskResponse(ScreeningAction.BLOCK, 0.95f, "Slow detection")
            }
        }

        val engineWithTimeout = DefaultCallRiskEngine(
            remoteClient = slowClient,
            blacklistedNumbers = emptySet(),
            trustedContacts = emptySet(),
            deadlineTimeoutMs = 300L, // Strict 300ms SLA for fast test
            onSecondaryAnalysisNeeded = { _, decision ->
                secondaryAnalysisTriggered = true
                capturedSecondaryTaskId = decision.secondaryTaskId
            }
        )

        val metadata = CallMetadata(
            rawHandle = "+19998887777",
            phoneNumber = "+19998887777",
            callerDisplayName = "Unknown Enterprise",
            callerDisplayNamePresentation = TelecomManager.PRESENTATION_ALLOWED,
            handlePresentation = TelecomManager.PRESENTATION_ALLOWED,
            callerNumberVerificationStatus = CallMetadata.STATUS_NOT_VERIFIED
        )

        val startTime = System.currentTimeMillis()
        val decision = engineWithTimeout.evaluate(metadata)
        val elapsed = System.currentTimeMillis() - startTime

        // Verify SLA deadline compliance: must return well before 1000ms
        assertTrue("Decision must return within the deadline threshold", elapsed < 1000L)
        assertEquals("Timeout must yield safe preliminary ALLOW", ScreeningAction.ALLOW, decision.action)
        assertTrue("Decision must be marked as preliminary", decision.isPreliminary)
        assertTrue("Explanation must state timeout fallback", decision.explanation.contains("timeout", ignoreCase = true))
        assertTrue("Secondary analysis must be dispatched", secondaryAnalysisTriggered)
        assertNotNull("Secondary task ID must be generated", capturedSecondaryTaskId)
    }

    /**
     * 7. Test Phone Number Privacy Masking:
     * Sensitive caller IDs must be masked in audit logs.
     */
    @Test
    fun testPhoneNumberMasking() {
        val meta1 = CallMetadata(
            rawHandle = "+18005550199",
            phoneNumber = "+18005550199",
            callerDisplayName = null,
            callerDisplayNamePresentation = 1,
            handlePresentation = 1,
            callerNumberVerificationStatus = 0
        )
        val masked1 = meta1.toMaskedNumber()
        assertEquals("+180****99", masked1)
        assertFalse("Masked string must not contain full middle digits", masked1.contains("55501"))

        val auditLog = CallScreeningDecision(
            action = ScreeningAction.BLOCK,
            riskScore = 0.9f,
            explanation = "Test block"
        ).toSecureAuditLog(masked1)

        assertTrue("Audit log must contain masked number", auditLog.contains("+180****99"))
        assertFalse("Audit log must not contain raw number", auditLog.contains("+18005550199"))
    }
}
