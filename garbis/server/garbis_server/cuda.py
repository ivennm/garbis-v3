"""
Make the pip-installed CUDA libraries (nvidia-cublas-cu12, nvidia-cudnn-cu12) loadable.

ctranslate2 (whisper) opens libcublas/libcudnn by name, and nothing puts the venv's
nvidia/*/lib folders on the library path. Loading them here with RTLD_GLOBAL first means
ctranslate2 finds them already loaded. Must run before the first GPU model load.
"""
import ctypes
import glob
import logging
import os
import sysconfig

log = logging.getLogger(__name__)

_PATTERNS = (
    "nvidia/cublas/lib/libcublasLt.so.*",   # libcublas needs this one first
    "nvidia/cublas/lib/libcublas.so.*",
    "nvidia/cudnn/lib/libcudnn*.so.*",
)
_loaded = False


def preload() -> bool:
    """Returns True if the CUDA libraries were found and loaded (safe to call more than once)."""
    global _loaded
    if _loaded:
        return True
    site = sysconfig.get_paths()["purelib"]
    found = 0
    for pattern in _PATTERNS:
        for path in sorted(glob.glob(os.path.join(site, pattern))):
            try:
                ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
                found += 1
            except OSError as e:
                log.warning("could not load %s: %s", os.path.basename(path), e)
    _loaded = found > 0
    if not _loaded:
        log.warning("no pip CUDA libraries found in %s; whisper will fall back to the CPU", site)
    return _loaded
