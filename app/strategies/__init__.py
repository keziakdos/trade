"""Moteur V2 — stratégies de trading sélectionnables (spécification exacte, sans interprétation).

Règles transverses appliquées partout :
- causalité stricte (bougie i = bougies ≤ i uniquement),
- séries alignées, `None` pendant le réchauffement / fenêtre non calculable,
- jamais de données fabriquées (`no_data`),
- zones en >= / <=, alignements de moyennes en > / < stricts.
"""

from .indicators import (
    sma, ema, rsi_wilder, macd, atr,
    williams_r, williams_r_zone, ultimate, ultimate_zone,
)
from .core import validate_bars, as_of, closes, resolve_index

REGISTRY = {}


def register(entry):
    REGISTRY[entry["id"]] = entry
    return entry


def evaluate(strategy_id, bars, index=None, params=None):
    """Point d'entrée unique : choisit la stratégie par id, mêmes bars possibles pour plusieurs stratégies."""
    if strategy_id not in REGISTRY:
        raise ValueError(f"stratégie inconnue : {strategy_id}")
    validate_bars(bars)
    entry = REGISTRY[strategy_id]
    merged = dict(entry["params"])
    if params:
        merged.update(params)
    return entry["evaluate"](bars, index, merged)


# ---------------------------------------------------------------------------
# 1. WILLIAMS %R — id: williams_r (période par défaut 14)
# ---------------------------------------------------------------------------

def _eval_williams_r(bars, index, params):
    period = params["period"]
    series = williams_r(bars, period=period)  # lève ValueError si period < 1 ou high < low
    i = as_of(bars, index)["index"]
    v = series[i]
    state = williams_r_zone(v)
    return {
        "id": "williams_r",
        "state": state if v is not None else None,
        "state_label": state if v is not None else "no_data",
        "values": {"williams_r": series, "value": v},
        "as_of": as_of(bars, i),
        "params": params,
    }


register({
    "id": "williams_r",
    "label": "Williams %R",
    "kind": "indicator",
    "params": {"period": 14},
    "warmup_bars": 14,
    "evaluate": _eval_williams_r,
})


# ---------------------------------------------------------------------------
# 2. ULTIMATE OSCILLATOR — id: ultimate (7 / 14 / 28)
# ---------------------------------------------------------------------------

def _eval_ultimate(bars, index, params):
    short, medium, long_ = params["short"], params["medium"], params["long"]
    series = ultimate(bars, short=short, medium=medium, long_=long_)
    i = as_of(bars, index)["index"]
    v = series[i]
    state = ultimate_zone(v)
    return {
        "id": "ultimate",
        "state": state if v is not None else None,
        "state_label": state if v is not None else "no_data",
        "values": {"ultimate": series, "value": v},
        "as_of": as_of(bars, i),
        "params": params,
    }


register({
    "id": "ultimate",
    "label": "Ultimate Oscillator",
    "kind": "indicator",
    "params": {"short": 7, "medium": 14, "long": 28},
    "warmup_bars": 29,
    "evaluate": _eval_ultimate,
})


# Modules §§3–7 (registre unique, sélection par id).
from . import setups as _setups

for _entry in _setups.ENTRIES:
    register(_entry)


__all__ = ["REGISTRY", "register", "evaluate", "validate_bars", "as_of", "closes"]
