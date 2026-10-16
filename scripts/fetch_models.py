"""Download the MediaPipe gesture model and WASM runtime into web/vendor/ to serve locally."""

import shutil
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import IO, Any

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "web" / "vendor" / "mediapipe"
VISION_VERSION = "0.10.14"
VISION_BASE = f"https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@{VISION_VERSION}"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task"
)
FILES = {
    "vision_bundle.mjs": f"{VISION_BASE}/vision_bundle.mjs",
    "wasm/vision_wasm_internal.js": f"{VISION_BASE}/wasm/vision_wasm_internal.js",
    "wasm/vision_wasm_internal.wasm": f"{VISION_BASE}/wasm/vision_wasm_internal.wasm",
    "wasm/vision_wasm_nosimd_internal.js": f"{VISION_BASE}/wasm/vision_wasm_nosimd_internal.js",
    "wasm/vision_wasm_nosimd_internal.wasm": f"{VISION_BASE}/wasm/vision_wasm_nosimd_internal.wasm",
    "gesture_recognizer.task": MODEL_URL,
}


Opener = Callable[[str], IO[bytes]]


def _download(url: str) -> Any:
    return urllib.request.urlopen(url, timeout=60)


def fetch_models(
    vendor: Path = VENDOR, files: Mapping[str, str] = FILES, open_url: Opener = _download
) -> list[str]:
    """Download whatever is missing; returns the names fetched. Partial downloads never
    count as present, because each file is written to `.part` and renamed when complete."""
    fetched = []
    for name, url in files.items():
        target = vendor / name
        if target.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".part")
        with open_url(url) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out)
        partial.rename(target)
        print(f"Fetched {name} ({target.stat().st_size // 1024} KiB)")
        fetched.append(name)
    return fetched


if __name__ == "__main__":
    fetch_models()
