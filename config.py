import json, os
from dataclasses import dataclass, asdict, fields

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".typesim", "config.json")

@dataclass
class Config:
    wpm: int = 60
    variation: float = 0.20
    error_rate: float = 0.03
    error_correction_delay: float = 0.15
    thinking_pause_chance: float = 0.02
    thinking_pause_min: float = 0.5
    thinking_pause_max: float = 2.0
    burst_mode: bool = False
    burst_chars: int = 8
    burst_pause: float = 0.50
    unicode_method: str = "pynput"
    countdown: int = 3
    hotkey_start: str = "f9"
    hotkey_pause: str = "f10"
    hotkey_stop: str = "f11"

    def save(self):
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def load(cls):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            valid = {field.name for field in fields(cls)}
            return cls(**{k: v for k, v in raw.items() if k in valid})
        except:
            return cls()
