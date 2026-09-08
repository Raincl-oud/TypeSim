import json, os
from dataclasses import asdict, fields

CONFIG_DIR   = os.path.join(os.path.expanduser("~"), ".typesim")
PROFILES_PATH = os.path.join(CONFIG_DIR, "profiles.json")

def _load_all():
    try:
        with open(PROFILES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def _save_all(d):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(PROFILES_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)

def save_profile(name, config):
    p = _load_all()
    p[name] = asdict(config)
    _save_all(p)

def delete_profile(name):
    p = _load_all()
    p.pop(name, None)
    _save_all(p)

def get_names():
    return sorted(_load_all().keys())

def apply_profile(name, config):
    p = _load_all()
    if name not in p:
        return config
    valid = {f.name for f in fields(config.__class__)}
    for k, v in p[name].items():
        if k in valid:
            setattr(config, k, v)
    return config
