"""
VIGIL-AI Phase 7: Optional ONNX Runtime Backend.

Provides an ONNX Runtime inference session wrapper that checks for onnxruntime availability
and gracefully falls back to native PyTorch when unavailable.
"""
import threading
import time
from typing import Any, Dict, List, Optional

import numpy as np

from app.core.config import settings
from app.core.logging import logger

_onnxruntime = None
_onnx_available = False

try:
    import onnxruntime as _ort
    _onnxruntime = _ort
    _onnx_available = True
except ImportError:
    _onnx_available = False


def is_onnx_available() -> bool:
    """Check if ONNX Runtime is installed and enabled in config."""
    return _onnx_available and getattr(settings, "ENABLE_ONNX_RUNTIME", True)


class ONNXInferenceSession:
    """
    Thin wrapper around onnxruntime.InferenceSession.
    Automatically selects CUDA or CPU execution provider.
    Thread-safe singleton per model path.
    """
    _sessions: Dict[str, Any] = {}
    _lock = threading.Lock()

    @classmethod
    def get_session(cls, model_path: str, device_type: str = "cpu") -> Optional[Any]:
        """
        Load and cache an ONNX session for the given model path.
        Returns None if ONNX Runtime is unavailable or model doesn't exist.
        """
        if not is_onnx_available() or _onnxruntime is None:
            return None

        if model_path in cls._sessions:
            return cls._sessions[model_path]

        with cls._lock:
            if model_path in cls._sessions:
                return cls._sessions[model_path]

            import os
            if not os.path.isfile(model_path):
                logger.warning(f"ONNX model not found: {model_path}")
                return None

            try:
                providers = []
                if device_type == "cuda":
                    providers.append("CUDAExecutionProvider")
                providers.append("CPUExecutionProvider")

                sess_options = _onnxruntime.SessionOptions()
                sess_options.graph_optimization_level = _onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL
                sess_options.intra_op_num_threads = 4
                sess_options.inter_op_num_threads = 2

                session = _onnxruntime.InferenceSession(
                    model_path, sess_options=sess_options, providers=providers,
                )
                cls._sessions[model_path] = session
                active_provider = session.get_providers()[0] if session.get_providers() else "unknown"
                logger.info(f"ONNX session loaded: {model_path} (provider: {active_provider})")
                return session
            except Exception as e:
                logger.warning(f"Failed to load ONNX session for {model_path}: {e}")
                return None

    @classmethod
    def run(cls, session: Any, input_name: str, input_data: np.ndarray) -> Optional[List[np.ndarray]]:
        """
        Execute inference on an ONNX session.
        Returns list of output arrays, or None on error.
        """
        if session is None:
            return None
        try:
            outputs = session.run(None, {input_name: input_data})
            return outputs
        except Exception as e:
            logger.warning(f"ONNX inference error: {e}")
            return None

    @classmethod
    def clear_sessions(cls) -> None:
        """Release all cached sessions."""
        with cls._lock:
            cls._sessions.clear()


class ONNXStatus:
    """Dashboard-friendly ONNX availability report."""

    @staticmethod
    def to_dict() -> Dict[str, Any]:
        return {
            "onnx_runtime_installed": _onnx_available,
            "onnx_enabled_in_config": getattr(settings, "ENABLE_ONNX_RUNTIME", True),
            "onnx_active": is_onnx_available(),
            "onnx_version": getattr(_onnxruntime, "__version__", None) if _onnx_available else None,
        }
