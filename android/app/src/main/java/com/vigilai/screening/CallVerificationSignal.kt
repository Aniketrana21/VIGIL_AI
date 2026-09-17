package com.vigilai.screening

/**
 * Categorical caller identity verification status derived from STIR/SHAKEN and Telecom signals.
 */
enum class StirShakenLevel {
    VERIFIED_PASSED,      // Full cryptographic attestation by carrier (A-level)
    VERIFICATION_FAILED,  // Cryptographic signature failed or mismatch detected (Spoofing)
    NOT_VERIFIED,         // Carrier does not provide or attestation missing
    UNSUPPORTED_PLATFORM  // Android version is prior to Android 11 (API 30)
}

/**
 * Aggregate caller verification signals extracted from Telecom, carrier, and device trust lists.
 */
data class CallVerificationSignal(
    val stirShakenLevel: StirShakenLevel,
    val isKnownContact: Boolean,
    val isBlacklisted: Boolean,
    val isPresentationRestricted: Boolean,
    val flaggedKeywords: List<String> = emptyList(),
    val summarySignalScore: Float = 0.0f,
    val explanation: String = ""
) {
    companion object {
        private val HIGH_RISK_KEYWORDS = listOf(
            "BANK", "SUPPORT", "VERIFICATION", "CUSTOMS", "POLICE",
            "TAX", "URGENT", "FRAUD", "SECURITY", "PAYPAL", "AMAZON"
        )

        /**
         * Evaluates raw [CallMetadata] against verification markers to synthesize signals.
         */
        fun fromMetadata(
            metadata: CallMetadata,
            blacklistedNumbers: Set<String> = emptySet(),
            trustedContacts: Set<String> = emptySet()
        ): CallVerificationSignal {
            val stirLevel = when (metadata.callerNumberVerificationStatus) {
                CallMetadata.STATUS_PASSED -> StirShakenLevel.VERIFIED_PASSED
                CallMetadata.STATUS_FAILED -> StirShakenLevel.VERIFICATION_FAILED
                CallMetadata.STATUS_NOT_VERIFIED -> StirShakenLevel.NOT_VERIFIED
                else -> StirShakenLevel.NOT_VERIFIED
            }

            val isContact = metadata.isKnownContact || trustedContacts.contains(metadata.phoneNumber)
            val isBlacklisted = blacklistedNumbers.contains(metadata.phoneNumber)

            val nameUpper = (metadata.callerDisplayName ?: "").uppercase()
            val detectedKeywords = HIGH_RISK_KEYWORDS.filter { nameUpper.contains(it) }

            val restricted = metadata.isRestrictedOrUnknownPresentation

            // Calculate aggregate baseline signal score [0.0 = safe, 1.0 = malicious]
            var score = 0.10f
            val reasons = mutableListOf<String>()

            if (isBlacklisted) {
                score = 1.0f
                reasons.add("Phone number found on high-risk scam blacklist")
            } else if (isContact) {
                score = 0.0f
                reasons.add("Caller is a confirmed contact in device address book")
            } else {
                when (stirLevel) {
                    StirShakenLevel.VERIFIED_PASSED -> {
                        score = 0.05f
                        reasons.add("Carrier STIR/SHAKEN identity verification passed")
                    }
                    StirShakenLevel.VERIFICATION_FAILED -> {
                        score += 0.55f
                        reasons.add("Carrier STIR/SHAKEN verification FAILED: Possible spoofed caller ID")
                    }
                    StirShakenLevel.NOT_VERIFIED -> {
                        score += 0.15f
                        reasons.add("STIR/SHAKEN verification not present for caller")
                    }
                    StirShakenLevel.UNSUPPORTED_PLATFORM -> {
                        reasons.add("STIR/SHAKEN verification unsupported on this OS")
                    }
                }

                if (restricted) {
                    score += 0.25f
                    reasons.add("Caller presentation is restricted or hidden")
                }

                if (detectedKeywords.isNotEmpty()) {
                    score += 0.35f
                    reasons.add("Caller ID contains sensitive organizational keywords: ${detectedKeywords.joinToString()}")
                }
            }

            val finalScore = score.coerceIn(0.0f, 1.0f)
            val explanation = if (reasons.isEmpty()) "Standard incoming caller" else reasons.joinToString("; ")

            return CallVerificationSignal(
                stirShakenLevel = stirLevel,
                isKnownContact = isContact,
                isBlacklisted = isBlacklisted,
                isPresentationRestricted = restricted,
                flaggedKeywords = detectedKeywords,
                summarySignalScore = finalScore,
                explanation = explanation
            )
        }
    }
}
