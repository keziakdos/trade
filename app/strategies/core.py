"""Noyau V2 — validation et repères (importé par le registre et les setups, sans cycle)."""


def validate_bars(bars):
    """bars = liste ordonnée (ancien → récent) de {time, open, high, low, close, volume}."""
    if not bars:
        raise ValueError("bars vide")
    for i, b in enumerate(bars):
        for k in ("time", "open", "high", "low", "close", "volume"):
            if k not in b:
                raise ValueError(f"bougie {i} : champ manquant '{k}'")
        if b["high"] < b["low"]:
            raise ValueError(f"bougie {i} : high < low")
        if not (b["close"] > 0):
            raise ValueError(f"bougie {i} : close doit être > 0")
    return bars


def resolve_index(bars, index):
    i = len(bars) - 1 if index is None else index
    if i < 0 or i >= len(bars):
        raise ValueError("index hors bornes")
    return i


def as_of(bars, index):
    i = resolve_index(bars, index)
    return {"index": i, "time": bars[i]["time"], "bars_used": i + 1}


def closes(bars):
    return [b["close"] for b in bars]


def synthesize(conditions):
    """Synthèse commune : setup si TOUTES les évaluées sont met ;
    no_setup si ≥1 non remplie ; no_data si aucune évaluable.
    force : élevée (100 %), moyenne (≥60 %), faible (<60 %), non évaluable."""
    evaluated = [c for c in conditions if c["status"] in ("met", "unmet")]
    if not evaluated:
        return "no_data", "non évaluable"
    met = sum(1 for c in evaluated if c["status"] == "met")
    ratio = met / len(evaluated)
    if ratio == 1:
        return "setup", "élevée"
    if ratio >= 0.6:
        return "no_setup", "moyenne"
    return "no_setup", "faible"
