"""
VIGIL-AI PyTorch Compatibility & Fallback Layer.
Handles safe importing of PyTorch when C-extension DLL loading is restricted
by Windows Application Control policy or Python version ABI incompatibility.
"""
import sys
from typing import Any, Optional

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    HAS_TORCH = True
except Exception:
    HAS_TORCH = False
    torch = None
    nn = None
    F = None


class DummyDevice:
    def __init__(self, type_str: str = "cpu"):
        self.type = type_str

    def __str__(self):
        return self.type

    def __repr__(self):
        return f"device(type='{self.type}')"


class DummyTensor:
    def __init__(self, data=None):
        self.data = data

    def zero_(self):
        pass

    def cpu(self):
        return self

    def numpy(self):
        import numpy as np
        return np.array(self.data) if self.data is not None else np.zeros((1,))


if not HAS_TORCH:
    class DummyNN:
        class Module:
            def __init__(self, *args, **kwargs):
                pass

    class DummyF:
        @staticmethod
        def softmax(*args, **kwargs):
            return None

    class MockTorch:
        Tensor = DummyTensor
        device = DummyDevice
        float32 = "float32"
        float64 = "float64"
        int64 = "int64"

        @staticmethod
        def from_numpy(arr):
            return DummyTensor(arr)

        @staticmethod
        def zeros(*args, **kwargs):
            import numpy as np
            shape = args[0] if args and isinstance(args[0], (tuple, list)) else args
            return DummyTensor(np.zeros(shape if shape else (1,)))

        @staticmethod
        def ones(*args, **kwargs):
            import numpy as np
            shape = args[0] if args and isinstance(args[0], (tuple, list)) else args
            return DummyTensor(np.ones(shape if shape else (1,)))

        @staticmethod
        def tensor(data, *args, **kwargs):
            import numpy as np
            return DummyTensor(np.array(data))

        @staticmethod
        def no_grad():
            class NoGradContext:
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    pass
            return NoGradContext()

        class hub:
            @staticmethod
            def load(*args, **kwargs):
                raise RuntimeError("Torch hub disabled in fallback mode")

        class cuda:
            @staticmethod
            def is_available():
                return False
            @staticmethod
            def get_device_name(dev=0):
                return "CPU Fallback"
            @staticmethod
            def get_device_properties(dev=0):
                class Props:
                    total_memory = 0
                return Props()

        class backends:
            class mps:
                @staticmethod
                def is_available():
                    return False

    torch = MockTorch()
    nn = DummyNN()
    F = DummyF()
