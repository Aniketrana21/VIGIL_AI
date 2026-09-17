from dataclasses import dataclass
import math
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
from app.core.config import settings
from app.core.logging import logger
from app.db.embedding_store import EmbeddingStore, SpeakerProfile, get_embedding_store
from app.pipeline.speaker_encoder import SpeakerEncoder, SpeakerModelRegistry


@dataclass
class SpeakerEnrollmentResult:
    """Result of speaker enrollment operation."""
    success: bool
    speaker_id: str
    name: str
    num_utterances: int
    intra_speaker_consistency: float
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "speaker_id": self.speaker_id,
            "name": self.name,
            "num_utterances": self.num_utterances,
            "intra_speaker_consistency": round(self.intra_speaker_consistency, 3),
            "message": self.message,
        }


@dataclass
class SpeakerVerificationResult:
    """
    Standardized Phase 5 Speaker Verification Output.
    Conforms strictly to specification:
    {
        "speaker_id": "...",
        "similarity": 0.91,
        "match": true,
        "confidence": 0.88
    }
    """
    speaker_id: str
    similarity: float
    match: bool
    confidence: float
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "speaker_id": self.speaker_id,
            "similarity": round(self.similarity, 3),
            "match": self.match,
            "confidence": round(self.confidence, 3),
        }

    def to_extended_dict(self) -> Dict[str, Any]:
        d = self.to_dict()
        d["latency_ms"] = round(self.latency_ms, 2)
        return d


class SpeakerEnrollmentService:
    """
    Manages secure enrollment of speaker identities:
    - Never stores raw voice recordings (privacy preservation)
    - Enforces multiple enrollment utterances (minimum 3)
    - Validates intra-speaker acoustic consistency
    - Computes L2-normalized centroid reference embedding vector
    """
    def __init__(
        self,
        encoder: Optional[SpeakerEncoder] = None,
        store: Optional[EmbeddingStore] = None,
        min_utterances: int = 3,
        min_consistency: float = 0.65,
    ):
        self.encoder = encoder or SpeakerModelRegistry.get_encoder()
        self.store = store or get_embedding_store()
        self.min_utterances = min_utterances or getattr(settings, "SPEAKER_MIN_ENROLLMENT_UTTERANCES", 3)
        self.min_consistency = min_consistency

    async def enroll_speaker(
        self,
        speaker_id: str,
        name: str,
        utterances: List[Union[np.ndarray, Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SpeakerEnrollmentResult:
        """
        Enrolls a speaker profile using multiple candidate utterances.
        Requirements:
        1. Never store raw voice recordings by default.
        2. Store embeddings securely.
        3. Require multiple enrollment utterances (>= 3).
        4. Create a reference embedding using multiple utterances.
        5. Normalize embeddings.
        """
        if not speaker_id or not speaker_id.strip():
            raise ValueError("speaker_id must be a non-empty identifier.")

        clean_speaker_id = speaker_id.strip().lower()

        # Requirement 4: Require multiple enrollment utterances
        if len(utterances) < self.min_utterances:
            raise ValueError(
                f"Speaker enrollment requires at least {self.min_utterances} utterances, but received {len(utterances)}."
            )

        logger.info(f"Enrolling speaker '{clean_speaker_id}' with {len(utterances)} utterances...")

        # Extract unit-normalized embeddings for each utterance
        embeddings = []
        for i, u in enumerate(utterances):
            emb = self.encoder.encode(u)
            embeddings.append(emb)

        # Requirement 9 & Consistency: Check pairwise consistency across enrollment utterances
        n = len(embeddings)
        pairwise_sims = []
        for i in range(n):
            for j in range(i + 1, n):
                sim = float(np.dot(embeddings[i], embeddings[j]))
                pairwise_sims.append(sim)

        avg_consistency = float(np.mean(pairwise_sims)) if pairwise_sims else 1.0

        if avg_consistency < self.min_consistency:
            logger.warning(
                f"Enrollment rejected for '{clean_speaker_id}': intra-speaker consistency {avg_consistency:.3f} "
                f"is below required threshold {self.min_consistency:.3f}."
            )
            return SpeakerEnrollmentResult(
                success=False,
                speaker_id=clean_speaker_id,
                name=name,
                num_utterances=len(utterances),
                intra_speaker_consistency=avg_consistency,
                message=f"Intra-speaker consistency too low ({avg_consistency:.2f} < {self.min_consistency:.2f}). Ensure all recordings are from the same person.",
            )

        # Requirement 5: Create a reference embedding using multiple utterances (L2-normalized centroid)
        centroid = np.mean(embeddings, axis=0)
        centroid_norm = np.linalg.norm(centroid)
        if centroid_norm > 1e-12:
            reference_embedding = (centroid / centroid_norm).astype(np.float32)
        else:
            reference_embedding = centroid.astype(np.float32)

        # Requirement 1 & 2: Store ONLY the normalized embedding and metadata (zero raw audio)
        profile = SpeakerProfile(
            speaker_id=clean_speaker_id,
            name=name or clean_speaker_id,
            embedding=reference_embedding.tolist(),
            num_utterances=len(utterances),
            metadata={
                **(metadata or {}),
                "intra_speaker_consistency": round(avg_consistency, 3),
                "enrolled_at_sample_rate": settings.SAMPLE_RATE,
            }
        )

        await self.store.store_speaker_profile(profile)
        logger.info(f"Speaker '{clean_speaker_id}' successfully enrolled (consistency: {avg_consistency:.3f}).")

        return SpeakerEnrollmentResult(
            success=True,
            speaker_id=clean_speaker_id,
            name=name or clean_speaker_id,
            num_utterances=len(utterances),
            intra_speaker_consistency=avg_consistency,
            message="Speaker successfully enrolled.",
        )


class SpeakerVerificationService:
    """
    Performs 1:1 Speaker Verification and 1:N Open-Set Speaker Identification.
    - Compares unit-normalized embeddings via Cosine Similarity
    - Configurable, calibrated decision thresholds
    - Full support for unknown/unenrolled speakers
    - Strictly decoupled from deepfake detection
    """
    def __init__(
        self,
        encoder: Optional[SpeakerEncoder] = None,
        store: Optional[EmbeddingStore] = None,
        match_threshold: Optional[float] = None,
        unknown_threshold: Optional[float] = None,
    ):
        self.encoder = encoder or SpeakerModelRegistry.get_encoder()
        self.store = store or get_embedding_store()
        self.match_threshold = match_threshold if match_threshold is not None else getattr(settings, "SPEAKER_MATCH_THRESHOLD", 0.75)
        self.unknown_threshold = unknown_threshold if unknown_threshold is not None else getattr(settings, "SPEAKER_UNKNOWN_THRESHOLD", 0.60)

    def get_model_info(self) -> Dict[str, Any]:
        """Returns speaker model version, status, and dimensions."""
        if hasattr(self.encoder, "get_model_info"):
            return self.encoder.get_model_info()
        return {
            "name": "ECAPA-TDNN Speaker Verifier",
            "version": "Vigil-ECAPA-TDNN-v1.0",
            "status": "READY",
            "embedding_dim": getattr(self.encoder, "embedding_dim", 192),
        }

    def _calibrate_confidence(self, similarity: float, threshold: float) -> float:
        """
        Calibrates margin-based verification confidence using a sigmoid transfer function:
        - Confidence ~ 0.50 exactly at the decision boundary.
        - Confidence scales asymptotically towards 0.98 for high similarity.
        - Confidence drops towards 0.05 for distant impostors.
        """
        margin = similarity - threshold
        k = 10.0  # steepness of calibration sigmoid
        conf = 1.0 / (1.0 + math.exp(-k * margin))
        return float(np.clip(conf, 0.05, 0.98))

    async def verify(
        self,
        audio: Union[np.ndarray, Any],
        claimed_speaker_id: Optional[str] = None,
    ) -> SpeakerVerificationResult:
        """
        Evaluates candidate speech against an enrolled speaker or the open gallery.
        Returns:
            SpeakerVerificationResult:
            {
                "speaker_id": "...",
                "similarity": 0.91,
                "match": True,
                "confidence": 0.88
            }
        """
        t0 = time.perf_counter()

        # Extract unit-normalized candidate embedding
        candidate_emb = self.encoder.encode(audio)

        # -------------------------------------------------------------
        # Mode 1: 1:1 Verification against a claimed identity
        # -------------------------------------------------------------
        if claimed_speaker_id and claimed_speaker_id.strip():
            clean_claimed = claimed_speaker_id.strip().lower()
            profile = await self.store.get_speaker_profile(clean_claimed)

            if not profile:
                # Claimed identity is not enrolled
                latency_ms = (time.perf_counter() - t0) * 1000.0
                return SpeakerVerificationResult(
                    speaker_id="UNKNOWN",
                    similarity=0.0,
                    match=False,
                    confidence=0.10,
                    latency_ms=latency_ms,
                )

            # Cosine similarity between candidate and reference centroid
            ref_emb = profile.get_embedding_numpy()
            similarity = float(np.dot(candidate_emb, ref_emb))

            # Calibrated match decision
            is_match = bool(similarity >= self.match_threshold)
            confidence = self._calibrate_confidence(similarity, self.match_threshold)

            latency_ms = (time.perf_counter() - t0) * 1000.0
            return SpeakerVerificationResult(
                speaker_id=profile.speaker_id if is_match else "UNKNOWN",
                similarity=round(similarity, 3),
                match=is_match,
                confidence=round(confidence, 3),
                latency_ms=latency_ms,
            )

        # -------------------------------------------------------------
        # Mode 2: 1:N Open-Set Identification
        # -------------------------------------------------------------
        nearest = await self.store.search_nearest_speakers(candidate_emb, top_k=1)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        if not nearest:
            # Store is completely empty
            return SpeakerVerificationResult(
                speaker_id="UNKNOWN",
                similarity=0.0,
                match=False,
                confidence=0.10,
                latency_ms=latency_ms,
            )

        top_profile, top_similarity = nearest[0]

        # Requirement 10: Support unknown speaker
        if top_similarity < self.unknown_threshold:
            confidence = self._calibrate_confidence(top_similarity, self.match_threshold)
            return SpeakerVerificationResult(
                speaker_id="UNKNOWN",
                similarity=round(top_similarity, 3),
                match=False,
                confidence=round(confidence, 3),
                latency_ms=latency_ms,
            )

        # Above unknown threshold -> check match threshold
        is_match = bool(top_similarity >= self.match_threshold)
        confidence = self._calibrate_confidence(top_similarity, self.match_threshold)

        return SpeakerVerificationResult(
            speaker_id=top_profile.speaker_id if is_match else "UNKNOWN",
            similarity=round(top_similarity, 3),
            match=is_match,
            confidence=round(confidence, 3),
            latency_ms=latency_ms,
        )

    def verify_sync(
        self,
        audio: Union[np.ndarray, Any],
        claimed_speaker_id: Optional[str] = None,
    ) -> SpeakerVerificationResult:
        """Synchronous version of verify() for real-time audio pipelines."""
        t0 = time.perf_counter()
        candidate_emb = self.encoder.encode(audio)

        # 1:1 Verification
        if claimed_speaker_id and claimed_speaker_id.strip():
            clean_claimed = claimed_speaker_id.strip().lower()
            if hasattr(self.store, "get_speaker_profile_sync"):
                profile = self.store.get_speaker_profile_sync(clean_claimed)
            else:
                profile = None

            if not profile:
                latency_ms = (time.perf_counter() - t0) * 1000.0
                return SpeakerVerificationResult(
                    speaker_id="UNKNOWN",
                    similarity=0.0,
                    match=False,
                    confidence=0.10,
                    latency_ms=latency_ms,
                )

            ref_emb = profile.get_embedding_numpy()
            similarity = float(np.dot(candidate_emb, ref_emb))
            is_match = bool(similarity >= self.match_threshold)
            confidence = self._calibrate_confidence(similarity, self.match_threshold)
            latency_ms = (time.perf_counter() - t0) * 1000.0

            return SpeakerVerificationResult(
                speaker_id=profile.speaker_id if is_match else "UNKNOWN",
                similarity=round(similarity, 3),
                match=is_match,
                confidence=round(confidence, 3),
                latency_ms=latency_ms,
            )

        # 1:N Identification
        if hasattr(self.store, "search_nearest_speakers_sync"):
            nearest = self.store.search_nearest_speakers_sync(candidate_emb, top_k=1)
        else:
            nearest = []

        latency_ms = (time.perf_counter() - t0) * 1000.0
        if not nearest:
            return SpeakerVerificationResult(
                speaker_id="UNKNOWN",
                similarity=0.0,
                match=False,
                confidence=0.10,
                latency_ms=latency_ms,
            )

        top_profile, top_similarity = nearest[0]
        if top_similarity < self.unknown_threshold:
            confidence = self._calibrate_confidence(top_similarity, self.match_threshold)
            return SpeakerVerificationResult(
                speaker_id="UNKNOWN",
                similarity=round(top_similarity, 3),
                match=False,
                confidence=round(confidence, 3),
                latency_ms=latency_ms,
            )

        is_match = bool(top_similarity >= self.match_threshold)
        confidence = self._calibrate_confidence(top_similarity, self.match_threshold)

        return SpeakerVerificationResult(
            speaker_id=top_profile.speaker_id if is_match else "UNKNOWN",
            similarity=round(top_similarity, 3),
            match=is_match,
            confidence=round(confidence, 3),
            latency_ms=latency_ms,
        )


class SpeakerThresholdCalibrator:
    """
    Requirement 9: Calibrate thresholds using validation data.
    Computes False Acceptance Rate (FAR), False Rejection Rate (FRR),
    and finds Equal Error Rate (EER) threshold.
    """
    @staticmethod
    def compute_eer(
        genuine_scores: List[float],
        impostor_scores: List[float],
        num_thresholds: int = 1000,
    ) -> Dict[str, float]:
        """
        Calculates EER threshold from validation genuine and impostor similarity scores.
        """
        if not genuine_scores or not impostor_scores:
            return {"eer": 0.0, "eer_threshold": 0.75}

        thresholds = np.linspace(0.0, 1.0, num_thresholds)
        far_list = []
        frr_list = []

        n_gen = len(genuine_scores)
        n_imp = len(impostor_scores)

        gen_arr = np.array(genuine_scores)
        imp_arr = np.array(impostor_scores)

        min_diff = 1.0
        best_threshold = 0.75
        best_eer = 0.0

        for th in thresholds:
            # FAR: impostor score >= threshold
            far = np.sum(imp_arr >= th) / n_imp
            # FRR: genuine score < threshold
            frr = np.sum(gen_arr < th) / n_gen

            far_list.append(far)
            frr_list.append(frr)

            diff = abs(far - frr)
            if diff < min_diff:
                min_diff = diff
                best_eer = float((far + frr) / 2.0)
                best_threshold = float(th)

        return {
            "eer": round(best_eer, 4),
            "eer_threshold": round(best_threshold, 3),
            "recommended_match_threshold": round(best_threshold, 3),
            "recommended_unknown_threshold": round(max(0.40, best_threshold - 0.15), 3),
        }
