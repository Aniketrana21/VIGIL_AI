"""
VIGIL-AI Phase 7: Device Manager — Hardware Acceleration Auto-Detection & Management.

Detects CUDA, MPS, and CPU capabilities. Provides unified tensor placement,
device metadata for dashboard, and inference mode context management.
"""
import threading
import time
from dataclasses import dataclass
from typing import Optional
import torch
from app.core.config import settings
from app.core.logging import logger


@dataclass
class DeviceInfo:
    """Hardware acceleration status for dashboard display and telemetry."""
    device_type: str       # "cuda" | "mps" | "cpu"
    device_name: str       # e.g. "NVIDIA GeForce RTX 4090" or "Intel Core i9 (CPU)"
    gpu_available: bool
    gpu_enabled: bool
    cuda_version: Optional[str] = None
    total_memory_mb: Optional[int] = None
    warmup_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "device_type": self.device_type,
            "device_name": self.device_name,
            "gpu_available": self.gpu_available,
            "gpu_enabled": self.gpu_enabled,
            "cuda_version": self.cuda_version,
            "total_memory_mb": self.total_memory_mb,
            "warmup_ms": round(self.warmup_ms, 2),
        }


class DeviceManager:
    """
    Thread-safe singleton that resolves the optimal inference device at startup
    and caches the result for the entire application lifecycle.
    """
    _lock = threading.Lock()
    _device: Optional[torch.device] = None
    _info: Optional[DeviceInfo] = None

    @classmethod
    def resolve(cls) -> torch.device:
        """Return the resolved torch.device (cached after first call)."""
        if cls._device is None:
            with cls._lock:
                if cls._device is None:
                    cls._device, cls._info = cls._detect()
        return cls._device

    @classmethod
    def get_info(cls) -> DeviceInfo:
        """Return hardware info (triggers resolution if needed)."""
        cls.resolve()
        return cls._info  # type: ignore

    @classmethod
    def _detect(cls) -> tuple:
        requested = getattr(settings, "INFERENCE_DEVICE", "auto").lower().strip()
        start = time.perf_counter()

        # 1. Attempt CUDA
        if requested in ("auto", "cuda"):
            if torch.cuda.is_available():
                dev = torch.device("cuda")
                name = torch.cuda.get_device_name(0)
                cuda_ver = torch.version.cuda or "unknown"
                mem_mb = int(torch.cuda.get_device_properties(0).total_mem / (1024 * 1024))
                # Warmup allocation
                try:
                    _warmup = torch.zeros(1, device=dev)
                    del _warmup
                except Exception:
                    pass
                elapsed = (time.perf_counter() - start) * 1000.0
                info = DeviceInfo(
                    device_type="cuda",
                    device_name=name,
                    gpu_available=True,
                    gpu_enabled=True,
                    cuda_version=cuda_ver,
                    total_memory_mb=mem_mb,
                    warmup_ms=elapsed,
                )
                logger.info(f"Device: CUDA — {name} ({mem_mb} MB, CUDA {cuda_ver}), warmup {elapsed:.1f}ms")
                return dev, info

        # 2. Attempt MPS (Apple Silicon)
        if requested in ("auto", "mps"):
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                dev = torch.device("mps")
                elapsed = (time.perf_counter() - start) * 1000.0
                info = DeviceInfo(
                    device_type="mps",
                    device_name="Apple Silicon (MPS)",
                    gpu_available=True,
                    gpu_enabled=True,
                    warmup_ms=elapsed,
                )
                logger.info(f"Device: MPS — Apple Silicon, warmup {elapsed:.1f}ms")
                return dev, info

        # 3. CPU fallback
        dev = torch.device("cpu")
        elapsed = (time.perf_counter() - start) * 1000.0
        import platform
        cpu_name = platform.processor() or "Unknown CPU"
        info = DeviceInfo(
            device_type="cpu",
            device_name=cpu_name,
            gpu_available=torch.cuda.is_available(),
            gpu_enabled=False,
            warmup_ms=elapsed,
        )
        logger.info(f"Device: CPU — {cpu_name}, warmup {elapsed:.1f}ms")
        return dev, info

    @classmethod
    def reset(cls) -> None:
        """Reset cached device (for testing)."""
        with cls._lock:
            cls._device = None
            cls._info = None
