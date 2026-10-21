from __future__ import annotations

import json
from pathlib import Path


DEFAULTS = {
    "output_mode": "beside",
    "output_directory": "",
    "overwrite": False,
    "image_quality": 88,
    "video_quality": 76,
    "audio_bitrate": "192k",
    "default_image_format": "webp",
    "default_video_format": "mp4",
    "default_audio_format": "mp3",
    "remove_metadata": True,
    "aab_keystore": "",
    "aab_alias": "",
}


def config_path() -> Path:
    return Path.home() / ".config" / "quickconvert" / "settings.json"


def load_settings() -> dict:
    settings = DEFAULTS.copy()
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            settings.update({key: value for key, value in data.items() if key in DEFAULTS})
    except (OSError, ValueError, TypeError):
        pass
    return settings


def save_settings(settings: dict) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = DEFAULTS.copy()
    clean.update({key: value for key, value in settings.items() if key in DEFAULTS})
    path.write_text(json.dumps(clean, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
