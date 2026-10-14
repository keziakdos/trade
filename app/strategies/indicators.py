"""Indicateurs de base V2 — recopie exacte des formules imposées.

Conventions : listes alignées sur l'entrée, `None` pendant le réchauffage
ou quand la fenêtre est non calculable. Aucune extrapolation.
"""

# ---------------------------------------------------------------------------
# Indicateurs réutilisés (§6)
# ---------------------------------------------------------------------------

def sma(values, n):
    """Moyenne glissante simple ; None tant que la fenêtre est incomplète."""
    out = [None] * len(values)
    if n < 1:
        raise ValueError("n < 1")
    acc = 0.0
    for i, x in enumerate(values):
        acc += x
        if i >= n:
            acc -= values[i - n]
        if i >= n - 1:
            out[i] = acc / n
    return out


def ema(values, n):
    """Amorcée par la SMA des n premières valeurs, puis
    EMA[i] = (x[i] − EMA[i−1]) × k + EMA[i−1], k = 2/(n+1)."""
    out = [None] * len(values)
    if n < 1:
        raise ValueError("n < 1")
    if len(values) < n:
        return out
    k = 2.0 / (n + 1)
    prev = sum(values[:n]) / n
    out[n - 1] = prev
    for i in range(n, len(values)):
        prev = (values[i] - prev) * k + prev
        out[i] = prev
    return out


def rsi_wilder(closes, period=14):
    """RSI(14) Wilder : variation nulle → ni gain ni perte ;
    init = moyenne des 14 premières variations ; avg = (avg×13 + var)/14 ;
    RS = avg_gain/avg_loss ; RSI = 100 − 100/(1+RS) ;
    avg_loss = 0 → 100 ; avg_gain = 0 → 0 ; les deux = 0 → 50."""
    out = [None] * len(closes)
    if period < 1:
        raise ValueError("period < 1")
    if len(closes) < period + 1:
        return out
    gains, losses = [], []
    for i in range(1, period + 1):
        var = closes[i] - closes[i - 1]
        gains.append(var if var > 0 else 0.0)
        losses.append(-var if var < 0 else 0.0)
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    def _rsi(g, l):
        if g == 0 and l == 0:
            return 50.0
        if l == 0:
            return 100.0
        if g == 0:
            return 0.0
        rs = g / l
        return 100.0 - 100.0 / (1.0 + rs)

    out[period] = _rsi(avg_gain, avg_loss)
    for i in range(period + 1, len(closes)):
        var = closes[i] - closes[i - 1]
        gain = var if var > 0 else 0.0
        loss = -var if var < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = _rsi(avg_gain, avg_loss)
    return out


def macd(closes, fast=12, slow=26, signal_n=9):
    """MACD = EMA12 − EMA26 ; signal = EMA9 des MACD valides ; hist = MACD − signal."""
    ef, es = ema(closes, fast), ema(closes, slow)
    macd_line = [None] * len(closes)
    for i in range(len(closes)):
        if ef[i] is not None and es[i] is not None:
            macd_line[i] = ef[i] - es[i]
    valid_idx = [i for i, v in enumerate(macd_line) if v is not None]
    valid_vals = [macd_line[i] for i in valid_idx]
    sig_vals = ema(valid_vals, signal_n)
    signal = [None] * len(closes)
    for j, i in enumerate(valid_idx):
        signal[i] = sig_vals[j]
    hist = [None] * len(closes)
    for i in range(len(closes)):
        if macd_line[i] is not None and signal[i] is not None:
            hist[i] = macd_line[i] - signal[i]
    return {"macd": macd_line, "signal": signal, "hist": hist}


def atr(bars, period=14):
    """TR = max(high−low, |high−close_prev|, |low−close_prev|) ;
    1ʳᵉ bougie = high−low ; ATR = moyenne exponentielle type Wilder (prev×13 + TR)/14,
    amorcée par la moyenne des 14 premiers TR (convention Wilder standard)."""
    out = [None] * len(bars)
    if period < 1:
        raise ValueError("period < 1")
    if not bars:
        return out
    trs = []
    for i, b in enumerate(bars):
        if i == 0:
            trs.append(b["high"] - b["low"])
        else:
            prev = bars[i - 1]["close"]
            trs.append(max(b["high"] - b["low"], abs(b["high"] - prev), abs(b["low"] - prev)))
    if len(trs) < period:
        return out
    prev = sum(trs[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(trs)):
        prev = (prev * (period - 1) + trs[i]) / period
        out[i] = prev
    return out


# ---------------------------------------------------------------------------
# 1. WILLIAMS %R
# ---------------------------------------------------------------------------

def williams_r(bars, period=14):
    """%R[i] = (max(highs 14) − close[i]) / (max(highs 14) − min(lows 14)) × (−100).
    Fenêtre glissante incluant la bougie courante. 13 premières = None.
    Fenêtre plate (max == min) → None. period < 1 → erreur ; high < low → erreur."""
    if period < 1:
        raise ValueError("period < 1")
    out = [None] * len(bars)
    for i in range(len(bars)):
        if i < period - 1:
            continue
        window = bars[i - period + 1:i + 1]
        for b in window:
            if b["high"] < b["low"]:
                raise ValueError("high < low")
        highest = max(b["high"] for b in window)
        lowest = min(b["low"] for b in window)
        if highest == lowest:
            out[i] = None
        else:
            out[i] = (highest - bars[i]["close"]) / (highest - lowest) * -100.0
    return out


def williams_r_zone(v):
    """%R >= −20 → overbought ; <= −80 → oversold ; sinon neutral ; null → null."""
    if v is None:
        return None
    if v >= -20:
        return "overbought"
    if v <= -80:
        return "oversold"
    return "neutral"


# ---------------------------------------------------------------------------
# 2. ULTIMATE OSCILLATOR
# ---------------------------------------------------------------------------

def ultimate(bars, short=7, medium=14, long_=28):
    """bp[i] = close[i] − min(low[i], close[i−1]) ; tr[i] = max(high[i], close[i−1]) − min(...).
    ratio_p = Σbp/Σtr sur p ; UO = 100 × (4×r7 + 2×r14 + r28) / 7.
    Première valeur à l'index 28. Σtr ≤ 0 → None. short < medium < long sinon erreur."""
    if not (short < medium < long_):
        raise ValueError("contrainte short < medium < long")
    n = len(bars)
    out = [None] * n
    bp = [None] * n
    tr = [None] * n
    for i in range(1, n):
        prev = bars[i - 1]["close"]
        tlow = min(bars[i]["low"], prev)
        bp[i] = bars[i]["close"] - tlow
        tr[i] = max(bars[i]["high"], prev) - tlow
    for i in range(n):
        if i < long_:
            continue
        ratios = []
        ok = True
        for p in (short, medium, long_):
            seg_bp = bp[i - p + 1:i + 1]
            seg_tr = tr[i - p + 1:i + 1]
            s_tr = sum(seg_tr)
            if s_tr <= 0:
                ok = False
                break
            ratios.append(sum(seg_bp) / s_tr)
        if ok:
            out[i] = 100.0 * (4 * ratios[0] + 2 * ratios[1] + ratios[2]) / 7.0
    return out


def ultimate_zone(v):
    """UO >= 70 → overbought ; <= 30 → oversold ; sinon neutral ; null → null."""
    if v is None:
        return None
    if v >= 70:
        return "overbought"
    if v <= 30:
        return "oversold"
    return "neutral"
