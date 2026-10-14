"""Setups V2 — recopie exacte des §§3, 4, 5, 6, 7, 8 imposés.

Chaque stratégie expose evaluate(bars, index=None, params=None) et figure
au REGISTRE via ENTRIES (id, label, kind, params, warmup_bars).
Libellés d'état repris à l'identique (jamais « acheter »/« vendre »).
"""

from .core import resolve_index, as_of, closes, synthesize
from .indicators import (
    sma, ema, rsi_wilder, macd, atr,
    williams_r, williams_r_zone, ultimate, ultimate_zone,
)


def _cond(name, status):
    return {"name": name, "status": status}


# ---------------------------------------------------------------------------
# 3. LECTURE COMBINÉE %R + UO — id: williams_r_ultimate_v1
# ---------------------------------------------------------------------------

def _last_valid(series):
    for v in reversed(series):
        if v is not None:
            return v
    return None


def combine_states(r_state, u_state):
    """Table de vérité imposée : condition = état %R ; confirmed = (égaux et non neutre).
    (null, *) → (no_data, None). Deux neutres ne confirment jamais."""
    if r_state is None:
        return "no_data", None
    confirmed = (r_state == u_state) and (r_state != "neutral")
    return r_state, confirmed


def evaluate_combined(bars, index=None, params=None):
    p = {"period": 14, "short": 7, "medium": 14, "long": 28}
    if params:
        p.update(params)
    i = resolve_index(bars, index)
    wr = williams_r(bars[:i + 1], period=p["period"])
    uo = ultimate(bars[:i + 1], short=p["short"], medium=p["medium"], long_=p["long"])
    r_state = williams_r_zone(_last_valid(wr))
    u_state = ultimate_zone(_last_valid(uo))
    if r_state is None:
        condition, confirmed = "no_data", None
    else:
        condition, confirmed = combine_states(r_state, u_state if u_state is not None else "neutral")
        # UO sans valeur : on rapporte l'état %R sans confirmation (rien de deviné).
        if u_state is None:
            confirmed = False
    return {
        "id": "williams_r_ultimate_v1",
        "state": condition,
        "state_label": condition,
        "direction": None,
        "conditions": [
            _cond("williams_r_state", r_state if r_state is not None else "no_data"),
            _cond("ultimate_state", u_state if u_state is not None else "no_data"),
        ],
        "confirmed": confirmed,
        "values": {"williams_r": wr[-1], "ultimate": uo[-1]},
        "as_of": as_of(bars, i),
        "params": p,
    }


# ---------------------------------------------------------------------------
# 4. RÈGLE D'ENTRÉE + SORTIES — id: williams_r_entry_v1
# ---------------------------------------------------------------------------

ENTRY_DEFAULTS = {
    "period": 14,
    "deep_oversold": -100, "long_trigger": -85,
    "deep_overbought": 0, "short_trigger": -15,
    "signal_window": 5,
    "exit_oversold": -80, "exit_overbought": -20,
    "exit_rule": "zone",
    "uo_exit_overbought": 70, "uo_fade_above": 50, "uo_fade_below": 45,
    "short": 7, "medium": 14, "long": 28,
    "stop_pct": 1.0, "target_pct": 2.0,
    "allocation": 0.95, "fee_bps": 10.0, "max_notional": 1.0,
}


def entry_direction(wr_series, i, params):
    """Décidée à la clôture de i, fenêtre = les 5 bougies PRÉCÉDENTES (courante exclue).
    LONG si ≥1 des 5 a %R ≤ −100 ET courant ≥ −85 ; SHORT miroir ; sinon None."""
    w = params["signal_window"]
    if i < w:
        return None
    prev = wr_series[i - w:i]
    cur = wr_series[i]
    if cur is None or any(v is None for v in prev):
        return None
    if any(v <= params["deep_oversold"] for v in prev) and cur >= params["long_trigger"]:
        return "long"
    if any(v >= params["deep_overbought"] for v in prev) and cur <= params["short_trigger"]:
        return "short"
    return None


def exit_hit(direction, wr_v, uo_v, fade_armed, params):
    """Sorties : zone (défaut), uo_above_70, uo_fade. Retourne (exit, fade_armed)."""
    rule = params["exit_rule"]
    if direction == "long":
        if rule == "zone":
            return (wr_v is not None and wr_v >= params["exit_overbought"]), fade_armed
        if rule == "uo_above_70":
            return (uo_v is not None and uo_v >= params["uo_exit_overbought"]), fade_armed
        if rule == "uo_fade":
            armed = fade_armed or (uo_v is not None and uo_v >= params["uo_fade_above"])
            return (armed and uo_v is not None and uo_v < params["uo_fade_below"]), armed
    else:
        if rule == "zone":
            return (wr_v is not None and wr_v <= params["exit_oversold"]), fade_armed
        # côté short : zone opposée pour les règles UO
        if rule == "uo_above_70":
            return (wr_v is not None and wr_v <= params["exit_oversold"]), fade_armed
        if rule == "uo_fade":
            return (wr_v is not None and wr_v <= params["exit_oversold"]), fade_armed
    return False, fade_armed


def backtest(bars, params=None, capital=10000.0):
    """Exécution imposée : ordre à l'OUVERTURE suivante ; gap au prix d'ouverture ;
    stop et objectif même bougie → le stop l'emporte ; stop 1 %, objectif 2 % ;
    allocation 95 %, frais 10 bps/côté, notionnel ≤ 100 %, aucun levier."""
    p = dict(ENTRY_DEFAULTS)
    if params:
        p.update(params)
    wr = williams_r(bars, period=p["period"])
    need_uo = p["exit_rule"] in ("uo_above_70", "uo_fade")
    uo = ultimate(bars, short=p["short"], medium=p["medium"], long_=p["long"]) if need_uo else [None] * len(bars)
    fee = p["fee_bps"] / 10000.0
    trades = []
    pending = None
    position = None
    eq = capital
    for i in range(len(bars)):
        # 1. exécution d'un signal en attente à l'ouverture
        if pending is not None and i == pending["bar"]:
            fill = bars[i]["open"]
            size = min(p["allocation"] * eq, p["max_notional"] * eq) / (fill * (1 + fee))
            if position is None and size > 0:
                position = {
                    "direction": pending["direction"], "fill": fill, "size": size,
                    "bar": i,
                    "stop": fill * (1 - p["stop_pct"] / 100.0) if pending["direction"] == "long" else fill * (1 + p["stop_pct"] / 100.0),
                    "target": fill * (1 + p["target_pct"] / 100.0) if pending["direction"] == "long" else fill * (1 - p["target_pct"] / 100.0),
                    "fade_armed": False,
                }
            pending = None
        # 2. gestion position ouverte (stop d'abord : il l'emporte en cas d'égalité)
        if position is not None:
            b, d = bars[i], position["direction"]
            if d == "long":
                hit_stop = b["low"] <= position["stop"]
                hit_target = b["high"] >= position["target"]
            else:
                hit_stop = b["high"] >= position["stop"]
                hit_target = b["low"] <= position["target"]
            exit_px, reason = None, None
            if hit_stop:
                exit_px, reason = position["stop"], "stop"
            elif hit_target:
                exit_px, reason = position["target"], "target"
            else:
                do_exit, armed = exit_hit(d, wr[i], uo[i], position["fade_armed"], p)
                position["fade_armed"] = armed
                if do_exit:
                    exit_px, reason = b["close"], "rule_" + p["exit_rule"]
            if exit_px is not None:
                sgn = 1 if d == "long" else -1
                gross = sgn * (exit_px - position["fill"]) * position["size"]
                fees = fee * position["fill"] * position["size"] + fee * exit_px * position["size"]
                pnl = gross - fees
                eq += pnl
                trades.append({
                    "direction": d, "entry_bar": position["bar"], "exit_bar": i,
                    "fill": position["fill"], "exit": exit_px, "size": position["size"],
                    "reason": reason, "pnl": pnl, "equity": eq,
                })
                position = None
                continue
        # 3. signal décidé à la clôture → exécution prochaine ouverture
        if position is None and pending is None and i + 1 < len(bars):
            d = entry_direction(wr, i, p)
            if d is not None:
                pending = {"direction": d, "bar": i + 1}
    return {"trades": trades, "equity": eq, "open": position is not None}


def evaluate_entry(bars, index=None, params=None):
    p = dict(ENTRY_DEFAULTS)
    if params:
        p.update(params)
    i = resolve_index(bars, index)
    wr = williams_r(bars[:i + 1], period=p["period"])
    need_uo = p["exit_rule"] in ("uo_above_70", "uo_fade")
    uo = ultimate(bars[:i + 1], short=p["short"], medium=p["medium"], long_=p["long"]) if need_uo else [None] * (i + 1)
    d = entry_direction(wr, i, p)
    conds = [
        _cond("deep_touch", "met" if d is not None else ("no_data" if wr[i] is None else "unmet")),
        _cond("trigger", "met" if d is not None else ("no_data" if wr[i] is None else "unmet")),
    ]
    state = "setup" if d is not None else ("no_data" if wr[i] is None else "no_setup")
    return {
        "id": "williams_r_entry_v1",
        "state": state,
        "state_label": state,
        "direction": d,
        "conditions": conds,
        "values": {"williams_r": wr[i], "ultimate": uo[i]},
        "as_of": as_of(bars, i),
        "params": p,
    }


# ---------------------------------------------------------------------------
# 5. DIVERGENCE WILLIAMS %R (champ `divergence`)
# ---------------------------------------------------------------------------

def _pivots(values, k, kind):
    """Extrême local des (2k+1) valeurs centrées. kind low/high."""
    piv = []
    for i in range(k, len(values) - k):
        w = values[i - k:i + k + 1]
        if any(v is None for v in w):
            continue
        c = values[i]
        if kind == "low" and c == min(w):
            piv.append(i)
        elif kind == "high" and c == max(w):
            piv.append(i)
    return piv


def divergence(bars, index=None, params=None):
    """Pivots confirmés après k=5 bougies ; paire de sens opposé, écart ≤ 60,
    validité 60 — on ne garde que la plus récente.
    bullish : prix plus bas ET %R plus haut ; bearish : l'inverse."""
    p = {"period": 14, "pivot_k": 5, "max_pair_gap": 60, "validity_bars": 60}
    if params:
        p.update(params)
    i = resolve_index(bars, index)
    k = p["pivot_k"]
    wr = williams_r(bars[:i + 1], period=p["period"])
    cl = closes(bars[:i + 1])
    out = {"direction": None, "bullish": None, "bearish": None}
    for kind in ("low", "high"):
        pp = [x for x in _pivots(cl, k, kind) if x + k <= i]
        op = [x for x in _pivots(wr, k, kind) if x + k <= i]
        best = None
        for a in range(len(pp) - 1):
            for b in range(a + 1, len(pp)):
                i1, i2 = pp[a], pp[b]
                if i2 - i1 > p["max_pair_gap"]:
                    continue
                o1 = next((x for x in op if x <= i1), None)
                o2 = next((x for x in op if i1 < x <= i2), None)
                if o1 is None or o2 is None:
                    continue
                if (i + 0) - (i2 + k) > p["validity_bars"]:
                    continue
                if kind == "low" and cl[i2] < cl[i1] and wr[o2] > wr[o1]:
                    best = {"direction": "bullish", "price": [i1, i2], "osc": [o1, o2]}
                if kind == "high" and cl[i2] > cl[i1] and wr[o2] < wr[o1]:
                    best = {"direction": "bearish", "price": [i1, i2], "osc": [o1, o2]}
        out["bullish" if kind == "low" else "bearish"] = best
    cands = [c for c in (out["bullish"], out["bearish"]) if c]
    if cands:
        newest = max(cands, key=lambda c: c["price"][1])
        out["direction"] = newest["direction"]
    out["as_of"] = as_of(bars, i)
    return out


# ---------------------------------------------------------------------------
# 6. CINQ CONFIGURATIONS + composant trend_long_ema_v1
# ---------------------------------------------------------------------------

def _ev_breakout(bars, i, p):
    w, vw, ratio = p["channel_window"], p["volume_window"], p["volume_spike_ratio"]
    if i < max(w, vw) + 1:
        return {"direction": None, "conditions": [_cond("data", "no_data")]}
    maxh = max(b["high"] for b in bars[i - w:i])
    minl = min(b["low"] for b in bars[i - w:i])
    c, v = bars[i]["close"], bars[i]["volume"]
    direction = "up" if c > maxh else ("down" if c < minl else None)
    vols = [b["volume"] for b in bars[i - vw:i]]
    avg = sum(vols) / vw
    c1 = "met" if direction is not None else "unmet"
    c2 = "met" if (avg > 0 and v >= ratio * avg) else ("no_data" if avg <= 0 else "unmet")
    if direction == "up":
        prev_max = max(b["high"] for b in bars[i - w - 1:i - 1])
        c3 = "met" if bars[i - 1]["close"] > prev_max else "unmet"
    elif direction == "down":
        prev_min = min(b["low"] for b in bars[i - w - 1:i - 1])
        c3 = "met" if bars[i - 1]["close"] < prev_min else "unmet"
    else:
        c3 = "no_data"
    return {
        "direction": direction,
        "scenario": "LONG" if direction == "up" else ("SHORT" if direction == "down" else None),
        "conditions": [_cond("franchissement", c1), _cond("volume", c2), _cond("confirmation", c3)],
    }


def _ev_pullback(bars, i, p, e20, e50):
    if e20[i] is None or e50[i] is None:
        return {"direction": None, "scenario": None, "conditions": [_cond("data", "no_data")]}
    tol = p["tolerance_pct"] / 100.0
    if e20[i] > e50[i]:
        direction = "up"
    elif e20[i] < e50[i]:
        direction = "down"
    else:
        return {"direction": None, "scenario": None,
                "conditions": [_cond("tendance", "unmet"), _cond("repli", "no_data"), _cond("structure", "no_data")]}
    w = p["pullback_window"]
    if i < w - 1:
        return {"direction": direction, "scenario": None,
                "conditions": [_cond("tendance", "met"), _cond("repli", "no_data"), _cond("structure", "no_data")]}
    if direction == "up":
        lo = min(b["low"] for b in bars[i - w + 1:i + 1])
        c_repli = "met" if lo <= e20[i] * (1 + tol) else "unmet"
        c_struct = "met" if bars[i]["close"] >= e50[i] else "unmet"
    else:
        hi = max(b["high"] for b in bars[i - w + 1:i + 1])
        c_repli = "met" if hi >= e20[i] * (1 - tol) else "unmet"
        c_struct = "met" if bars[i]["close"] <= e50[i] else "unmet"
    return {"direction": direction,
            "scenario": "LONG" if direction == "up" else "SHORT",
            "conditions": [_cond("tendance", "met"), _cond("repli", c_repli), _cond("structure", c_struct)]}


def _ev_mean_reversion(bars, i, p, s20, a14, r14):
    if s20[i] is None or a14[i] is None or r14[i] is None:
        return {"direction": None, "scenario": None, "conditions": [_cond("data", "no_data")]}
    gap = bars[i]["close"] - s20[i]
    direction = "up" if gap > 0 else ("down" if gap < 0 else None)
    if direction is None:
        return {"direction": None, "scenario": None,
                "conditions": [_cond("direction", "unmet"), _cond("extension", "no_data"),
                               _cond("rsi_extreme", "no_data"), _cond("stabilite", "no_data")]}
    if a14[i] <= 0:
        c_ext = "no_data"
    else:
        c_ext = "met" if abs(gap) >= p["extension_atr_mult"] * a14[i] else "unmet"
    if direction == "up":
        c_rsi = "met" if r14[i] >= 70 else "unmet"
    else:
        c_rsi = "met" if r14[i] <= 30 else "unmet"
    if i >= 10 and s20[i - 10] not in (None, 0):
        c_stab = "met" if abs(s20[i] / s20[i - 10] - 1) <= p["max_slope_pct"] / 100.0 else "unmet"
    else:
        c_stab = "no_data"
    return {"direction": direction,
            "scenario": "SHORT" if direction == "up" else "LONG",
            "conditions": [_cond("direction", "met"), _cond("extension", c_ext),
                           _cond("rsi_extreme", c_rsi), _cond("stabilite", c_stab)]}


def _ev_trend_following(bars, i, p, e9, e20, s50):
    if e9[i] is None or e20[i] is None or s50[i] is None:
        return {"direction": None, "scenario": None, "conditions": [_cond("data", "no_data")]}
    if e9[i] > e20[i] > s50[i]:
        direction = "up"
    elif e9[i] < e20[i] < s50[i]:
        direction = "down"
    else:
        return {"direction": None, "scenario": None,
                "conditions": [_cond("alignement", "unmet"), _cond("pente", "no_data"), _cond("prix", "no_data")]}
    w = p["slope_window"]
    if e20[i - w] is None:
        return {"direction": direction, "scenario": None,
                "conditions": [_cond("alignement", "met"), _cond("pente", "no_data"), _cond("prix", "no_data")]}
    if direction == "up":
        c_slope = "met" if e20[i] > e20[i - w] else "unmet"
        c_prix = "met" if bars[i]["close"] >= e20[i] else "unmet"
    else:
        c_slope = "met" if e20[i] < e20[i - w] else "unmet"
        c_prix = "met" if bars[i]["close"] <= e20[i] else "unmet"
    return {"direction": direction,
            "scenario": "LONG" if direction == "up" else "SHORT",
            "conditions": [_cond("alignement", "met"), _cond("pente", c_slope), _cond("prix", c_prix)]}


def _ev_momentum(bars, i, p, hist, r14):
    if i == 0 or hist[i] is None or hist[i - 1] is None or r14[i] is None:
        return {"direction": None, "scenario": None, "conditions": [_cond("data", "no_data")]}
    if hist[i] > 0 and hist[i] > hist[i - 1]:
        direction = "up"
    elif hist[i] < 0 and hist[i] < hist[i - 1]:
        direction = "down"
    else:
        return {"direction": None, "scenario": None,
                "conditions": [_cond("impulsion_macd", "unmet"), _cond("rsi", "no_data"), _cond("roc", "no_data")]}
    w = p["roc_window"]
    if i < w or bars[i - w]["close"] == 0:
        return {"direction": direction, "scenario": None,
                "conditions": [_cond("impulsion_macd", "met"), _cond("rsi", "no_data"), _cond("roc", "no_data")]}
    roc = (bars[i]["close"] / bars[i - w]["close"] - 1) * 100.0
    if direction == "up":
        c_rsi = "met" if r14[i] >= p["rsi_mid"] else "unmet"
        c_roc = "met" if roc >= p["roc_threshold_pct"] else "unmet"
    else:
        c_rsi = "met" if r14[i] <= p["rsi_mid"] else "unmet"
        c_roc = "met" if roc <= p["roc_threshold_pct"] else "unmet"
    return {"direction": direction,
            "scenario": "LONG" if direction == "up" else "SHORT",
            "conditions": [_cond("impulsion_macd", "met"), _cond("rsi", c_rsi), _cond("roc", c_roc)]}


def _ev_trend_long(bars, i, p, e50, e200):
    if e50[i] is None or e200[i] is None:
        return {"direction": None, "scenario": None, "conditions": [_cond("data", "no_data")]}
    if e50[i] > e200[i]:
        direction = "up"
    elif e50[i] < e200[i]:
        direction = "down"
    else:
        return {"direction": None, "scenario": None,
                "conditions": [_cond("alignement", "unmet"), _cond("prix", "no_data"), _cond("pente", "no_data")]}
    w = p["slope_window"]
    if e50[i - w] is None:
        return {"direction": direction, "scenario": None,
                "conditions": [_cond("alignement", "met"), _cond("prix", "no_data"), _cond("pente", "no_data")]}
    if direction == "up":
        c_prix = "met" if bars[i]["close"] >= e200[i] else "unmet"
        c_pente = "met" if e50[i] > e50[i - w] else "unmet"
    else:
        c_prix = "met" if bars[i]["close"] <= e200[i] else "unmet"
        c_pente = "met" if e50[i] < e50[i - w] else "unmet"
    return {"direction": direction,
            "scenario": "LONG" if direction == "up" else "SHORT",
            "conditions": [_cond("alignement", "met"), _cond("prix", c_prix), _cond("pente", c_pente)]}


def _setup_evaluator(sid, needs):
    def run(bars, index, params):
        i = resolve_index(bars, index)
        cl = closes(bars)
        ind = {}
        if "e20" in needs or "e50" in needs or "e9" in needs or "e200" in needs:
            for n_, key in ((20, "e20"), (50, "e50"), (9, "e9"), (200, "e200")):
                if key in needs:
                    ind[key] = ema(cl, n_)
        if "s20" in needs or "s50" in needs:
            for n_, key in ((20, "s20"), (50, "s50")):
                if key in needs:
                    ind[key] = sma(cl, n_)
        if "rsi" in needs:
            ind["rsi"] = rsi_wilder(cl, params.get("rsi", 14))
        if "atr" in needs:
            ind["atr"] = atr(bars, params.get("atr", 14))
        if "macd" in needs:
            ind["macd"] = macd(cl, params.get("macd_fast", 12), params.get("macd_slow", 26), params.get("macd_signal", 9))
        if sid == "breakout_donchian_v1":
            r = _ev_breakout(bars, i, params)
        elif sid == "pullback_trend_v1":
            r = _ev_pullback(bars, i, params, ind["e20"], ind["e50"])
        elif sid == "mean_reversion_atr_v1":
            r = _ev_mean_reversion(bars, i, params, ind["s20"], ind["atr"], ind["rsi"])
        elif sid == "trend_following_ma_v1":
            r = _ev_trend_following(bars, i, params, ind["e9"], ind["e20"], ind["s50"])
        elif sid == "momentum_macd_v1":
            r = _ev_momentum(bars, i, params, ind["macd"]["hist"], ind["rsi"])
        elif sid == "trend_long_ema_v1":
            r = _ev_trend_long(bars, i, params, ind["e50"], ind["e200"])
        else:
            raise ValueError(sid)
        state, force = synthesize(r["conditions"])
        return {
            "id": sid, "state": state, "state_label": state,
            "direction": r["direction"], "scenario": r.get("scenario"),
            "conditions": r["conditions"], "force": force,
            "as_of": as_of(bars, i), "params": params,
        }
    return run


# ---------------------------------------------------------------------------
# 7. SCORE DE PANIQUE — id: panic_reversal_v1 (total / 100)
# ---------------------------------------------------------------------------

def _clamp01(x):
    return max(0.0, min(1.0, x))


def _rsi_bullish_divergence(cl, rsi, i, window=20):
    """Nouveau plus bas de prix avec RSI plus haut, strict, sur `window` bougies."""
    if i < window or rsi[i] is None:
        return False
    seg = [(cl[j], rsi[j], j) for j in range(i - window, i + 1) if rsi[j] is not None]
    if len(seg) < 2:
        return False
    low = min(s[0] for s in seg)
    at_low = [s for s in seg if s[0] == low]
    first_low_j = at_low[0][2]
    if i == first_low_j:
        prev = [s for s in seg if s[2] < i and s[0] > low]
        if not prev:
            return False
        return rsi[i] > min(s[1] for s in prev)
    prev_low_j = max(s[2] for s in seg if s[2] < i and s[0] == low) if any(s[2] < i and s[0] == low for s in seg) else None
    if prev_low_j is None:
        return False
    return rsi[i] > rsi[prev_low_j]


def evaluate_panic(bars, index=None, params=None):
    p = {"drop_window": 5, "drop_full_pct": 5.0, "volume_window": 20, "volume_spike": 2.0,
         "rsi_period": 14, "rsi_ref": 30.0, "wr_period": 14, "wr_ref": -80.0, "wr_full": 10.0,
         "sma_window": 20, "slope_window": 10, "div_window": 20, "threshold": 60.0}
    if params:
        p.update(params)
    i = resolve_index(bars, index)
    cl = closes(bars)
    vols = [b["volume"] for b in bars]
    rsi = rsi_wilder(cl, p["rsi_period"])
    wr = williams_r(bars, period=p["wr_period"])
    sm = sma(cl, p["sma_window"])
    parts, cover = {}, 0
    total_n = 5
    # chute (fenêtre 5)
    if i >= p["drop_window"] and cl[i - p["drop_window"]] > 0:
        drop = -((cl[i] / cl[i - p["drop_window"]] - 1) * 100.0)
        parts["chute"] = 25.0 * _clamp01(drop / p["drop_full_pct"])
        cover += 1
    else:
        parts["chute"] = None
    # volume (fenêtre 20)
    if i >= p["volume_window"]:
        prev = vols[i - p["volume_window"]:i]
        avg = sum(prev) / p["volume_window"]
        if avg > 0:
            ratio = vols[i] / avg
            parts["volume"] = 15.0 if ratio >= p["volume_spike"] else 15.0 * _clamp01((ratio - 1) / (p["volume_spike"] - 1))
            cover += 1
        else:
            parts["volume"] = None
    else:
        parts["volume"] = None
    # RSI
    if rsi[i] is not None:
        parts["rsi"] = 20.0 * _clamp01((p["rsi_ref"] - rsi[i]) / p["rsi_ref"])
        cover += 1
    else:
        parts["rsi"] = None
    # %R
    if wr[i] is not None:
        parts["williams_r"] = 0.0 if wr[i] >= p["wr_ref"] else 15.0 * _clamp01((p["wr_ref"] - wr[i]) / p["wr_full"])
        cover += 1
    else:
        parts["williams_r"] = None
    # confirmation (cumulatif 0/12,5/25)
    conf_eval = rsi[i] is not None and i > 0 and rsi[i - 1] is not None
    conf = 0.0
    if conf_eval:
        if rsi[i - 1] <= 30 < rsi[i]:
            conf += 12.5
        if _rsi_bullish_divergence(cl, rsi, i, p["div_window"]):
            conf += 12.5
        cover += 1
    parts["confirmation"] = conf if conf_eval else None
    if cover == 0:
        return {"id": "panic_reversal_v1", "state": None, "state_label": "no_data",
                "direction": None, "score": 0.0, "parts": parts, "coverage": 0.0,
                "warning": None, "as_of": as_of(bars, i), "params": p}
    total = sum(v for v in parts.values() if v is not None)
    # avertissement falling_knife : aucune confirmation ET (chute pleine OU close < SMA20 en pente descendante sur 10)
    chute_full = parts["chute"] is not None and parts["chute"] >= 25.0
    sma_falling = (sm[i] is not None and sm[i - p["slope_window"]] is not None
                   and cl[i] < sm[i] and sm[i] < sm[i - p["slope_window"]]) if i >= p["slope_window"] else False
    warning = "falling_knife" if (conf == 0 and (chute_full or sma_falling)) else None
    if total >= p["threshold"] and conf > 0:
        state = "potential_reversal"
    elif total >= p["threshold"]:
        state = "panic"
    elif warning:
        state = "falling_knife"
    else:
        state = "neutral"
    return {"id": "panic_reversal_v1", "state": state, "state_label": state,
            "direction": None, "score": total, "parts": parts, "coverage": cover / total_n,
            "warning": warning, "as_of": as_of(bars, i), "params": p}


# ---------------------------------------------------------------------------
# 8. SCORE UNIQUE (agrégation optionnelle, total 100)
# ---------------------------------------------------------------------------

UNIQUE_WEIGHTS = {
    "momentum_macd_v1": 20, "trend_following_ma_v1": 15, "breakout_donchian_v1": 15,
    "pullback_trend_v1": 15, "mean_reversion_atr_v1": 15, "zone": 10, "trend_long_ema_v1": 10,
}


def unique_score(evaluated, margin=1.0):
    """contrib(config) = poids × (remplies / évaluées). Signal long/short par sens
    attribuable ; confiance = round(min(score,100) × marge) ; jamais une probabilité.
    ÉCART DOCUMENTÉ : la spec ne définit ni `marge` (défaut 1.0) ni la règle exacte
    d'attribution long/short — attribution au sens déterminable, sinon total seul."""
    total, long_pts, short_pts = 0.0, 0.0, 0.0
    for sid, weight, res in evaluated:
        conds = [c for c in res.get("conditions", []) if c["status"] in ("met", "unmet")]
        contrib = weight * (sum(1 for c in conds if c["status"] == "met") / len(conds)) if conds else 0.0
        total += contrib
        side = None
        if sid == "zone":
            if res.get("confirmed") is True and res.get("state") == "oversold":
                side = "long"
            elif res.get("confirmed") is True and res.get("state") == "overbought":
                side = "short"
        else:
            sc = res.get("scenario")
            if sc == "LONG":
                side = "long"
            elif sc == "SHORT":
                side = "short"
        if side == "long":
            long_pts += contrib
        elif side == "short":
            short_pts += contrib
    if total == 0 and long_pts == 0 and short_pts == 0:
        signal = "no_data"
    elif long_pts > short_pts:
        signal = "long"
    elif short_pts > long_pts:
        signal = "short"
    else:
        signal = "neutral"
    confidence = round(min(total, 100.0) * margin)
    label = "Élevée" if confidence >= 60 else ("Moyenne" if confidence >= 35 else "Faible")
    return {"score": total, "signal": signal, "confidence": confidence,
            "confidence_label": label, "long_pts": long_pts, "short_pts": short_pts}


# ---------------------------------------------------------------------------
# Registre (§5 : chaque stratégie = module indépendant sélectionnable par id)
# ---------------------------------------------------------------------------

ENTRIES = [
    {"id": "williams_r_ultimate_v1", "label": "Lecture combinée %R + UO", "kind": "zone",
     "params": {"period": 14, "short": 7, "medium": 14, "long": 28}, "warmup_bars": 29,
     "evaluate": evaluate_combined},
    {"id": "williams_r_entry_v1", "label": "Entrée + sorties %R", "kind": "entry_exit",
     "params": dict(ENTRY_DEFAULTS),
     "warmup_bars": 29, "evaluate": evaluate_entry},
    {"id": "breakout_donchian_v1", "label": "Breakout Donchian + volume", "kind": "setup",
     "params": {"channel_window": 20, "volume_window": 20, "volume_spike_ratio": 1.5}, "warmup_bars": 21,
     "evaluate": _setup_evaluator("breakout_donchian_v1", set())},
    {"id": "pullback_trend_v1", "label": "Pullback en tendance EMA", "kind": "setup",
     "params": {"fast": 20, "slow": 50, "pullback_window": 5, "tolerance_pct": 0.5}, "warmup_bars": 50,
     "evaluate": _setup_evaluator("pullback_trend_v1", {"e20", "e50"})},
    {"id": "mean_reversion_atr_v1", "label": "Mean reversion ATR + RSI", "kind": "setup",
     "params": {"sma": 20, "atr": 14, "extension_atr_mult": 1.0, "rsi": 14, "slope_window": 10, "max_slope_pct": 2.0},
     "warmup_bars": 30, "evaluate": _setup_evaluator("mean_reversion_atr_v1", {"s20", "atr", "rsi"})},
    {"id": "trend_following_ma_v1", "label": "Suivi de tendance MA", "kind": "setup",
     "params": {"fast": 9, "mid": 20, "slow": 50, "slope_window": 10}, "warmup_bars": 50,
     "evaluate": _setup_evaluator("trend_following_ma_v1", {"e9", "e20", "s50"})},
    {"id": "momentum_macd_v1", "label": "Momentum MACD + RSI + ROC", "kind": "setup",
     "params": {"macd_fast": 12, "macd_slow": 26, "macd_signal": 9, "rsi": 14, "rsi_mid": 50, "roc_window": 20, "roc_threshold_pct": 0},
     "warmup_bars": 34, "evaluate": _setup_evaluator("momentum_macd_v1", {"macd", "rsi"})},
    {"id": "trend_long_ema_v1", "label": "Tendance longue EMA50/200 (composant)", "kind": "setup",
     "params": {"fast": 50, "slow": 200, "slope_window": 10}, "warmup_bars": 200,
     "evaluate": _setup_evaluator("trend_long_ema_v1", {"e50", "e200"})},
    {"id": "panic_reversal_v1", "label": "Score de panique / retournement", "kind": "score",
     "params": {"drop_window": 5, "drop_full_pct": 5.0, "volume_window": 20, "volume_spike": 2.0,
                "rsi_period": 14, "rsi_ref": 30.0, "wr_period": 14, "wr_ref": -80.0, "wr_full": 10.0,
                "sma_window": 20, "slope_window": 10, "div_window": 20, "threshold": 60.0},
     "warmup_bars": 29, "evaluate": evaluate_panic},
]
