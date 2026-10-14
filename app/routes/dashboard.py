from flask import Blueprint, render_template, request, flash, redirect, url_for, abort
from flask_login import login_required, current_user
from app.models import MarketStatus, TradeSimulation, TradeNote, Portfolio, Strategy, db
import json
from datetime import datetime # Assurez-vous d'avoir cet import en haut du fichier
import ccxt
from flask import jsonify


dashboard_bp = Blueprint('dashboard', __name__)

def get_or_create_default_portfolio():
    """Un portefeuille 'Principal' par utilisateur (C10)."""
    pf = Portfolio.query.filter_by(user_id=current_user.id).order_by(Portfolio.id).first()
    if pf is None:
        pf = Portfolio(user_id=current_user.id, name='Principal', initial_balance=10000.0)
        db.session.add(pf)
        db.session.commit()
    return pf

def get_available_strategies():
    """Stratégies système + celles de l'utilisateur (V2). Source unique : table Strategy.
    Les 11 modules moteur sont fichés comme les stratégies manuelles (même présentation,
    même bouton Utiliser) ; les lignes existantes sont conservées (jamais supprimées)."""
    ENGINE_LIBRARY = [
        dict(engine='williams_r', name='Williams %R (zones)', level='Débutant', side='LONG', sl=2.0, tp=4.0,
             indicator='Williams %R 14', timeframe='1D',
             entry="État : %R ≥ −20 surachat · ≤ −80 survente (non strict). Fenêtre 14 incluant la courante ; 13 premières = pas de donnée ; fenêtre plate = pas de donnée.",
             exit="Lecture seule : aucune sortie propre — utilisez la lecture combinée ou la règle d'entrée.",
             desc="Oscillateur borné −100 à 0 : position de la clôture dans sa fenêtre de 14 bougies."),
        dict(engine='ultimate', name='Ultimate Oscillator (zones)', level='Intermédiaire', side='LONG', sl=2.0, tp=4.0,
             indicator='UO 7/14/28', timeframe='1D',
             entry="UO ≥ 70 surachat · ≤ 30 survente. Première valeur à la 29ᵉ bougie ; somme des amplitudes ≤ 0 = pas de donnée.",
             exit="Lecture seule : utilisez les règles UO de la stratégie d'entrée.",
             desc="Pression d'achat pondérée 4/2/1 sur 7, 14 et 28 bougies, borné 0 à 100."),
        dict(engine='williams_r_ultimate_v1', name='Lecture combinée %R + UO', level='Intermédiaire', side='LONG', sl=2.0, tp=4.0,
             indicator='%R 14 + UO', timeframe='1D',
             entry="État affiché = celui du %R (dernière valeur non nulle). Confirmé si les deux d'accord et non neutres ; deux neutres ne confirment jamais.",
             exit="Lecture seule : pas de sortie, utilisez la règle d'entrée.",
             desc="Confluence %R prioritaire + Ultimate. Vocabulaire d'état uniquement, jamais acheter/vendre."),
        dict(engine='williams_r_entry_v1', name='Entrée + sorties %R', level='Intermédiaire', side='LONG', sl=1.0, tp=2.0,
             indicator='%R 14 (+UO)', timeframe='1D',
             entry="LONG si %R a touché −100 sur les 5 dernières (courante exclue) ET courant ≥ −85. SHORT miroir : touché 0 ET courant ≤ −15. Ordre à l'ouverture suivante.",
             exit="Zone : LONG sort si %R ≥ −20, SHORT si ≤ −80. Stop 1 %, objectif 2 % ; même bougie : le stop l'emporte.",
             desc="Signaux %R + sorties zone/UO, exécution à l'ouverture suivante, sans levier, frais inclus."),
        dict(engine='breakout_donchian_v1', name='Breakout (Cassure)', level='Intermédiaire', side='LONG', sl=3.0, tp=6.0,
             indicator='Donchian 20 + Volume', timeframe='1D',
             entry="Clôture au-delà du canal des 20 précédentes (courante exclue) + volume ≥ 1,5× la moyenne + clôture précédente déjà hors canal. Haut → LONG, bas → SHORT.",
             exit="Stop/objectif du simulateur. Faux départ = on sort, on ne moyenne pas.",
             desc="Explosion après compression. Jamais après +5 % en une bougie."),
        dict(engine='pullback_trend_v1', name='Pullback en tendance', level='Intermédiaire', side='LONG', sl=2.0, tp=4.0,
             indicator='EMA20/50', timeframe='1D',
             entry="EMA20 > EMA50 (up). Plus bas des 5 dernières ≤ EMA20 × 1,005. Clôture ≥ EMA50. Miroir en down.",
             exit="Stop/objectif du simulateur.",
             desc="Achat du repli dans une tendance établie, structure conservée."),
        dict(engine='mean_reversion_atr_v1', name='Mean Reversion ATR (sens inversé)', level='Avancé', side='LONG', sl=2.0, tp=4.0,
             indicator='SMA20 + ATR14 + RSI', timeframe='1D',
             entry="Écart à la SMA20 ≥ 1× ATR + RSI extrême (≥ 70 en up, ≤ 30 en down) + SMA20 stable (±2 % sur 10). SENS INVERSÉ : up → SHORT, down → LONG.",
             exit="Stop/objectif du simulateur.",
             desc="Retour à la moyenne après extension anormale, contre le sens de l'écart."),
        dict(engine='trend_following_ma_v1', name='Suivi de Tendance (Trend Following)', level='Débutant', side='LONG', sl=2.0, tp=4.0,
             indicator='EMA9/20 + SMA50', timeframe='1D',
             entry="EMA9 > EMA20 > SMA50 strict + pente EMA20 sur 10 bougies + clôture du bon côté d'EMA20.",
             exit="Stop/objectif du simulateur. Ne jamais trader contre l'alignement.",
             desc="The Trend is your Friend : jamais contre le courant dominant."),
        dict(engine='momentum_macd_v1', name='Momentum MACD + RSI + ROC', level='Intermédiaire', side='LONG', sl=2.0, tp=4.0,
             indicator='MACD 12/26/9 + RSI + ROC20', timeframe='1D',
             entry="Histogramme > 0 et croissant + RSI ≥ 50 + ROC20 ≥ 0. Miroir en down.",
             exit="Stop/objectif du simulateur.",
             desc="Triple confirmation d'élan : impulsion, force et vitesse."),
        dict(engine='trend_long_ema_v1', name='Tendance longue EMA50/200', level='Débutant', side='LONG', sl=2.0, tp=4.0,
             indicator='EMA50/200', timeframe='1D',
             entry="EMA50 > EMA200 + prix ≥ EMA200 + pente EMA50 sur 10 bougies. Composant de fond, pas un signal seul.",
             exit="—",
             desc="Filtre de régime long terme pour valider les autres stratégies."),
        dict(engine='panic_reversal_v1', name='Score de panique / retournement', level='Avancé', side='LONG', sl=2.0, tp=4.0,
             indicator='Chute+Volume+RSI+%R', timeframe='1D',
             entry="Score /100 : chute 25, volume 15, RSI 20, %R 15, confirmation 25. ≥ 60 + confirmation : potentiel retournement ; ≥ 60 seul : panique ; avertissement falling_knife. Jamais une probabilité.",
             exit="Lecture seule : pas de sortie mécanique.",
             desc="Mesure la capitulation : chute, volume, RSI, %R et confirmation cumulée."),
    ]
    if Strategy.query.filter_by(user_id=None).count() == 0:
        db.session.add_all([
            Strategy(user_id=None, name='Suivi de Tendance (Trend Following)', level='Débutant',
                     side='LONG', sl_pct=2.0, tp_pct=4.0, indicator='MA200 + RSI', timeframe='1D',
                     entry_rules="Prix au-dessus de la MA200. Repli vers support. RSI < 70. Bougie verte engloutissante.",
                     exit_rules="Sortie au TP (+4%). Stop sous le support (−2%). Ne pas déplacer le stop.",
                     description="The Trend is your Friend : on ne trade jamais contre le courant dominant."),
            Strategy(user_id=None, name='Breakout (Cassure)', level='Intermédiaire',
                     side='LONG', sl_pct=3.0, tp_pct=6.0, indicator='Volume + Range', timeframe='4H',
                     entry_rules="Prix bloqué sous résistance. Bougies qui se compriment. Cassure franche avec VOLUME. Jamais après +5% en une bougie.",
                     exit_rules="Sortie au TP (+6%). Stop sous la résistance cassée (−3%). Faux départ = on sort, on ne moyenne pas.",
                     description="Explosion de prix après compression (range). Gain rapide, risque de faux départ."),
            Strategy(user_id=None, name='Rejet de Résistance (Range Short)', level='Intermédiaire',
                     side='SHORT', sl_pct=2.0, tp_pct=4.0, indicator='RSI + Résistance', timeframe='4H',
                     entry_rules="Prix bloqué sous une résistance en range. Mèche haute de rejet. RSI qui se retourne.",
                     exit_rules="Sortie au TP (−4%). Stop au-dessus de la résistance (+2%).",
                     description="Vente sur rejet d'une résistance en range, retour vers le bas du range."),
        ])
        db.session.commit()
    # Backfill règles sur seeds déjà existants (sans toucher aux ids)
    for st, er, xr, ind, tf in [
        ('Rejet de Résistance (Range Short)', "Prix bloqué sous une résistance en range. Mèche haute de rejet. RSI qui se retourne.", "Sortie au TP (−4%). Stop au-dessus de la résistance (+2%).", 'RSI + Résistance', '4H'),
    ]:
        row = Strategy.query.filter_by(user_id=None, name=st).first()
        if row and not row.entry_rules:
            row.entry_rules, row.exit_rules, row.indicator, row.timeframe = er, xr, ind, tf
    # Fiches moteur : mise à niveau des 2 lignes historiques (mêmes ids, mêmes noms),
    # création des 9 autres si absentes (repérées par engine_id, jamais en double).
    for seed in ENGINE_LIBRARY:
        row = Strategy.query.filter_by(user_id=None, engine_id=seed['engine']).first()
        if row is None and seed['name'] in ('Suivi de Tendance (Trend Following)', 'Breakout (Cassure)'):
            row = Strategy.query.filter_by(user_id=None, name=seed['name']).first()
            if row is not None and row.engine_id:
                row = None  # déjà liée à un autre module : ne pas écraser
        if row is not None:
            row.engine_id = seed['engine']
            row.level, row.side = seed['level'], seed['side']
            row.sl_pct, row.tp_pct = seed['sl'], seed['tp']
            row.indicator, row.timeframe = seed['indicator'], seed['timeframe']
            row.entry_rules, row.exit_rules, row.description = seed['entry'], seed['exit'], seed['desc']
        else:
            if Strategy.query.filter_by(user_id=None, engine_id=seed['engine']).first() is None:
                db.session.add(Strategy(user_id=None, name=seed['name'], level=seed['level'],
                                        side=seed['side'], sl_pct=seed['sl'], tp_pct=seed['tp'],
                                        indicator=seed['indicator'], timeframe=seed['timeframe'],
                                        entry_rules=seed['entry'], exit_rules=seed['exit'],
                                        description=seed['desc'], engine_id=seed['engine']))
    db.session.commit()
    return Strategy.query.filter((Strategy.user_id == None) | (Strategy.user_id == current_user.id)).order_by(Strategy.id).all()

@dashboard_bp.route('/dashboard')
@login_required
def index():
    # 1. On récupère les données du scanner pour le résumé en haut (cryptos d'abord, puis Yahoo)
    market_data = MarketStatus.query.order_by(MarketStatus.source, MarketStatus.symbol).all()

    # Portefeuilles (C10) : auto-crée 'Principal' si aucun
    get_or_create_default_portfolio()
    portfolios = Portfolio.query.filter_by(user_id=current_user.id).order_by(Portfolio.id).all()
    pf_stats = []
    for pf in portfolios:
        closed = [t for t in pf.trades if t.status == 'closed' and t.pnl_usd]
        open_trades = [t for t in pf.trades if t.status == 'open']
        wins = sum(1 for t in pf.trades if t.outcome == 'WIN')
        open_engaged = round(sum(t.position_size_usd or 0 for t in open_trades), 2)
        pf_stats.append({
            'pf': pf,
            'equity': pf.equity(),
            'pnl_total': round(sum(t.pnl_usd for t in closed), 2),
            'n_trades': len(pf.trades),
            'n_closed': len(closed),
            'n_open': len(open_trades),
            'open_engaged': open_engaged,
            'available': round(pf.equity() - open_engaged, 2),
            'winrate': round(wins / len(closed) * 100, 1) if closed else 0,
        })

    # 2. On récupère l'historique des simulations de l'utilisateur
    recent_trades = TradeSimulation.query.filter_by(user_id=current_user.id).order_by(TradeSimulation.entry_date.desc()).limit(5).all()

    # 3. Préparation des données pour le Graphique TradingView (Demo: BTC data simple)
    # Dans une V2, on passera l'historique complet via une API interne
    # Pour l'instant, on envoie juste le dernier prix pour initialiser
    btc_data = MarketStatus.query.filter_by(symbol='BTCUSDT').first()
    current_btc_price = btc_data.price if btc_data else 0

    # Pré-sélection stratégie via ?strategy_id= (depuis page Stratégies → Utiliser)
    try:
        selected_strategy_id = int(request.args.get('strategy_id') or 0) or None
    except (TypeError, ValueError):
        selected_strategy_id = None

    return render_template('dashboard/index.html',
                         market_data=market_data,
                         recent_trades=recent_trades,
                         btc_price=current_btc_price,
                         portfolios=portfolios,
                         pf_stats=pf_stats,
                         strategies=get_available_strategies(),
                         selected_strategy_id=selected_strategy_id)


@dashboard_bp.route('/portfolios', methods=['POST'])
@login_required
def create_portfolio():
    """Crée un portefeuille fictif (C10)."""
    name = (request.form.get('name') or '').strip()[:50] or 'Portefeuille'
    try:
        balance = float(request.form.get('initial_balance') or 10000)
        if balance <= 0:
            raise ValueError
    except (TypeError, ValueError):
        flash("Balance initiale invalide.", "error")
        return redirect(url_for('dashboard.index'))
    if Portfolio.query.filter_by(user_id=current_user.id, name=name).first():
        flash("Un portefeuille porte déjà ce nom.", "error")
        return redirect(url_for('dashboard.index'))
    db.session.add(Portfolio(user_id=current_user.id, name=name, initial_balance=balance))
    db.session.commit()
    flash(f"Portefeuille '{name}' créé ({balance}$ fictifs).", "success")
    return redirect(url_for('dashboard.index'))



YAHOO_MAP = {'GOLD': 'GC=F', 'EURUSD': 'EURUSD=X', 'SP500': '^GSPC', 'IXIC': '^IXIC', 'SPY': 'SPY', 'AAPL': 'AAPL', 'MSFT': 'MSFT'}


def _fetch_bars(symbol, limit=250):
    """Bougies OHLCV réutilisées par le graphique ET le moteur V2 (mêmes données de marché)."""
    market = MarketStatus.query.filter_by(symbol=symbol).first()
    source = (market.source if market and market.source else 'binance')
    bars = []
    if source == 'yahoo':
        import yfinance as yf
        ticker = YAHOO_MAP.get(symbol, symbol)
        df = yf.download(ticker, period='1y', interval='1d', progress=False, auto_adjust=True)
        if df is None or len(df) == 0:
            raise ValueError('Aucune donnée Yahoo')
        try:
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        except Exception:
            pass
        for idx, row in df.tail(limit).iterrows():
            try:
                ts = int(idx.timestamp())
            except Exception:
                continue
            o = float(row.get('Open', float('nan')))
            h = float(row.get('High', float('nan')))
            l = float(row.get('Low', float('nan')))
            c = float(row.get('Close', float('nan')))
            v = float(row.get('Volume', 0) or 0)
            if any(vv != vv for vv in [o, h, l, c]):  # NaN
                continue
            bars.append({'time': ts, 'open': o, 'high': h, 'low': l, 'close': c, 'volume': v})
    else:
        binance_symbol = symbol.replace('USDT', '/USDT')
        exchange = ccxt.binance()
        ohlcv = exchange.fetch_ohlcv(binance_symbol, timeframe='1d', limit=limit)
        for candle in ohlcv:
            bars.append({
                'time': int(candle[0] / 1000),
                'open': candle[1], 'high': candle[2],
                'low': candle[3], 'close': candle[4], 'volume': candle[5] or 0,
            })
    if not bars:
        raise ValueError('Aucune bougie')
    return bars


@dashboard_bp.route('/api/history/<symbol>')
@login_required
def get_history(symbol):
    """Récupère l'historique OHLCV (Binance pour crypto, Yahoo pour Gold/Forex/Indices)."""
    try:
        bars = _fetch_bars(symbol, limit=100)
        data = [{'time': b['time'], 'open': b['open'], 'high': b['high'],
                 'low': b['low'], 'close': b['close']} for b in bars]
        current_price = data[-1]['close'] if data else None
        return jsonify({'success': True, 'data': data, 'current_price': current_price})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@dashboard_bp.route('/api/strategy/evaluate/<engine_id>/<symbol>')
@login_required
def api_strategy_evaluate(engine_id, symbol):
    """Lecture marché via le moteur V2 (données réelles, PAS un résultat de simulation)."""
    try:
        from app.strategies import evaluate as engine_evaluate, REGISTRY
        if engine_id not in REGISTRY:
            return jsonify({'success': False, 'error': f"moteur inconnu : {engine_id}"})
        bars = _fetch_bars(symbol)
        res = engine_evaluate(engine_id, bars)
        # Réponse allégée : pas les séries complètes, que l'état et les scalaires.
        scalars = {k: v for k, v in res.get('values', {}).items() if isinstance(v, (int, float)) or v is None}
        out = dict(res)
        out['values'] = scalars
        out['detail'] = {k: v for k, v in res.items() if k in ('direction', 'scenario', 'force', 'confirmed', 'score', 'parts', 'coverage', 'warning', 'conditions')}
        return jsonify({'success': True, 'result': out})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})








@dashboard_bp.route('/simulate_trade', methods=['POST'])
@login_required
def simulate_trade():
    # Récupération + validation (évite crash 500 si champ vide)
    try:
        symbol = request.form.get('symbol')
        entry = float(request.form.get('entry'))
        stop_loss = float(request.form.get('sl'))
        take_profit = float(request.form.get('tp'))
        capital = float(request.form.get('capital'))
    except (TypeError, ValueError):
        flash("Valeurs invalides : vérifiez entrée / SL / TP / capital.", "error")
        return redirect(url_for('dashboard.index'))

    if not symbol or entry <= 0 or capital <= 0:
        flash("Symbole, entrée et capital doivent être positifs.", "error")
        return redirect(url_for('dashboard.index'))

    # Déduction directionnelle (C1) : refuse les combos incohérents
    direction = None
    if stop_loss < entry < take_profit:
        direction = 'LONG'   # pari vers le haut
    elif stop_loss > entry > take_profit:
        direction = 'SHORT'  # pari vers le bas
    else:
        flash("SL/TP incohérents : LONG exige SL < Entrée < TP ; SHORT exige SL > Entrée > TP.", "error")
        return redirect(url_for('dashboard.index'))

    risk = abs(entry - stop_loss)
    reward = abs(take_profit - entry)
    if risk == 0:
        flash("Stop Loss invalide (identique à l'entrée)", "error")
        return redirect(url_for('dashboard.index'))

    rr_ratio = round(reward / risk, 2)
    quantity = capital / entry
    risk_amount = round(risk / entry * capital, 2)
    reward_amount = round(reward / entry * capital, 2)

    # Portefeuille (C10) : vérifie l'appartenance, sinon défaut
    default_pf = get_or_create_default_portfolio()
    try:
        pf_id = int(request.form.get('portfolio_id') or default_pf.id)
    except (TypeError, ValueError):
        pf_id = default_pf.id
    pf = Portfolio.query.filter_by(id=pf_id, user_id=current_user.id).first() or default_pf

    # Stratégie liée (aligne simulateur ↔ page Stratégies, champ prêt pour stats V2)
    strategy_tag = None
    try:
        st_id = int(request.form.get('strategy_id') or 0) or None
    except (TypeError, ValueError):
        st_id = None
    if st_id:
        st = Strategy.query.filter(((Strategy.user_id == None) | (Strategy.user_id == current_user.id)), Strategy.id == st_id).first()
        if st:
            strategy_tag = st.name

    sim = TradeSimulation(
        user_id=current_user.id,
        portfolio_id=pf.id,
        strategy_tag=strategy_tag,
        symbol=symbol,
        direction=direction,
        entry_price=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        position_size_usd=capital,
        leverage=1.0,
        quantity=quantity,
        risk_reward=rr_ratio,
        risk_amount_usd=risk_amount,
        reward_amount_usd=reward_amount,
    )

    db.session.add(sim)
    db.session.commit()

    flash(f"Simulation {direction} [{pf.name}] enregistrée ! R/R: {rr_ratio} | Risque: -{risk_amount}$ | Gain: +{reward_amount}$", "success")
    return redirect(url_for('dashboard.index'))


@dashboard_bp.route('/journal')
@login_required
def journal():
    get_or_create_default_portfolio()
    portfolios = Portfolio.query.filter_by(user_id=current_user.id).order_by(Portfolio.id).all()
    # Filtre portefeuille via ?portfolio_id=
    try:
        filter_pf_id = int(request.args.get('portfolio_id') or 0) or None
    except (TypeError, ValueError):
        filter_pf_id = None
    q = TradeSimulation.query.filter_by(user_id=current_user.id)
    if filter_pf_id:
        q = q.filter_by(portfolio_id=filter_pf_id)
    # Les archivés ont leur section dédiée en bas (toujours visible)
    trades = q.order_by(TradeSimulation.entry_date.desc()).all()

    # Infos portefeuilles pour le sélecteur (équité + P&L à côté du nom)
    pf_info = {}
    for pf in portfolios:
        pnl = round(sum(t.pnl_usd for t in pf.trades if t.status == 'closed' and t.pnl_usd), 2)
        pf_info[pf.id] = {'equity': pf.equity(), 'pnl': pnl}

    # 2. Récupérer les prix actuels du marché pour l'affichage "En cours"
    market_status = MarketStatus.query.all()
    # On crée un dictionnaire pour accès rapide : {'BTCUSDT': 65000, 'ETHUSDT': 3500...}
    current_prices = {m.symbol: m.price for m in market_status}

    return render_template('dashboard/journal.html',
                         trades=trades,
                         current_prices=current_prices,
                         portfolios=portfolios,
                         pf_info=pf_info,
                         filter_pf_id=filter_pf_id)


@dashboard_bp.route('/trade/archive/<int:trade_id>', methods=['POST'])
@login_required
def archive_trade(trade_id):
    """Ferme définitivement : trade archivé (caché, historique + P&L conservés)."""
    trade = TradeSimulation.query.get_or_404(trade_id)
    if trade.user_id != current_user.id:
        abort(403)
    if trade.status != 'closed':
        flash("On n'archive qu'un trade déjà clôturé.", "error")
        return redirect(url_for('dashboard.journal'))
    final_note = (request.form.get('final_note') or '').strip()
    if final_note:
        db.session.add(TradeNote(trade_id=trade.id, user_id=current_user.id, content=final_note))
        trade.notes = final_note
    trade.archived = True
    db.session.commit()
    flash("Trade archivé définitivement (historique et P&L conservés).", "success")
    return redirect(url_for('dashboard.journal'))


@dashboard_bp.route('/trade/unarchive/<int:trade_id>', methods=['POST'])
@login_required
def unarchive_trade(trade_id):
    trade = TradeSimulation.query.get_or_404(trade_id)
    if trade.user_id != current_user.id:
        abort(403)
    trade.archived = False
    db.session.commit()
    flash("Trade restauré dans le journal.", "success")
    return redirect(url_for('dashboard.journal'))




NEWS_FEEDS = [
    ('CoinDesk', 'https://www.coindesk.com/arc/outboundfeeds/rss/'),
    ('Cointelegraph', 'https://cointelegraph.com/rss'),
    ('Decrypt', 'https://decrypt.co/feed'),
    ('Marchés (Investing)', 'https://www.investing.com/rss/news_25.rss'),
]
_news_cache = {'ts': None, 'items': [], 'ok': False}

def fetch_news(force=False):
    """Agrège les RSS crypto/éco (cache 20 min, chaque flux en erreur est ignoré)."""
    import time as _time
    now = _time.time()
    if not force and _news_cache['ts'] and now - _news_cache['ts'] < 1200:
        return _news_cache['items'], _news_cache['ok']
    import feedparser
    import requests as _rq
    items = []
    ok = False
    for source, url in NEWS_FEEDS:
        try:
            r = _rq.get(url, headers={'User-Agent': 'Mozilla/5.0 (RwaTrade learning)'}, timeout=12)
            feed = feedparser.parse(r.content)
            for e in feed.entries[:8]:
                img = None
                try:
                    mc = getattr(e, 'media_content', None)
                    if mc: img = mc[0].get('url')
                    if not img:
                        mt = getattr(e, 'media_thumbnail', None)
                        if mt: img = mt[0].get('url')
                    if not img:
                        for enc in getattr(e, 'enclosures', []):
                            if 'image' in (enc.get('type') or '') and enc.get('href'):
                                img = enc['href']; break
                except Exception:
                    img = None
                pub = getattr(e, 'published', '') or getattr(e, 'updated', '')
                items.append({
                    'source': source,
                    'title': getattr(e, 'title', '(sans titre)'),
                    'link': getattr(e, 'link', '#'),
                    'published': pub,
                    'summary': (getattr(e, 'summary', '') or '')[:220],
                    'image': img,
                    'sortkey': str(getattr(e, 'published_parsed', '') or pub),
                })
            ok = True
        except Exception as ex:
            print(f"News {source} ignoré : {ex}")
            continue
    items.sort(key=lambda x: x['sortkey'], reverse=True)
    _news_cache.update({'ts': now, 'items': items, 'ok': ok})
    return items, ok


@dashboard_bp.route('/news')
@login_required
def news():
    items, ok = fetch_news()
    return render_template('dashboard/news.html', items=items, feeds_ok=ok)


@dashboard_bp.route('/strategies', methods=['GET', 'POST'])
@login_required
def strategies():
    # Ajout V2 : l'utilisateur crée ses propres stratégies (système + siennes listées)
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()[:80]
        level = request.form.get('level') or 'Débutant'
        side = request.form.get('side') or 'LONG'
        try:
            sl = float(request.form.get('sl_pct') or 0)
            tp = float(request.form.get('tp_pct') or 0)
        except (TypeError, ValueError):
            sl, tp = 0, 0
        desc = (request.form.get('description') or '').strip()
        indicator = (request.form.get('indicator') or 'RSI + MA200').strip()[:60]
        timeframe = request.form.get('timeframe') or '1D'
        entry_rules = (request.form.get('entry_rules') or '').strip()
        exit_rules = (request.form.get('exit_rules') or '').strip()
        engine_id = (request.form.get('engine_id') or '').strip() or None
        from app.strategies import REGISTRY as _REG
        if engine_id is not None and engine_id not in _REG:
            engine_id = None
        if not name or sl <= 0 or tp <= 0 or side not in ('LONG', 'SHORT'):
            flash("Stratégie invalide : nom + sens + SL/TP % positifs requis.", "error")
        else:
            db.session.add(Strategy(user_id=current_user.id, name=name, level=level,
                                    side=side, sl_pct=sl, tp_pct=tp, description=desc,
                                    indicator=indicator, timeframe=timeframe,
                                    entry_rules=entry_rules, exit_rules=exit_rules,
                                    engine_id=engine_id))
            db.session.commit()
            flash(f"Stratégie '{name}' ajoutée — utilisable dans le simulateur.", "success")
        return redirect(url_for('dashboard.strategies'))
    strategies = get_available_strategies()
    from app.strategies import REGISTRY as _REGISTRY
    engines = [{'id': e['id'], 'label': e['label'], 'kind': e['kind']} for e in _REGISTRY.values()]
    return render_template('dashboard/strategies.html', strategies=strategies, engines=engines)


@dashboard_bp.route('/strategy/<int:strategy_id>/edit', methods=['POST'])
@login_required
def edit_strategy(strategy_id):
    """Modifie une stratégie perso (système = lecture seule). Le simulateur recharge à la prochaine ouverture."""
    st = Strategy.query.get_or_404(strategy_id)
    if st.user_id != current_user.id:
        abort(403)
    name = (request.form.get('name') or '').strip()[:80]
    try:
        sl = float(request.form.get('sl_pct') or 0)
        tp = float(request.form.get('tp_pct') or 0)
    except (TypeError, ValueError):
        sl, tp = 0, 0
    if not name or sl <= 0 or tp <= 0:
        flash("Modification invalide : nom + SL/TP % positifs requis.", "error")
    else:
        st.name = name
        st.level = request.form.get('level') or st.level
        if request.form.get('side') in ('LONG', 'SHORT'):
            st.side = request.form.get('side')
        st.sl_pct, st.tp_pct = sl, tp
        st.indicator = (request.form.get('indicator') or st.indicator or '').strip()[:60]
        st.timeframe = request.form.get('timeframe') or st.timeframe
        st.entry_rules = (request.form.get('entry_rules') or '').strip()
        st.exit_rules = (request.form.get('exit_rules') or '').strip()
        st.description = (request.form.get('description') or '').strip()
        engine_id = (request.form.get('engine_id') or '').strip() or None
        from app.strategies import REGISTRY as _REG2
        st.engine_id = engine_id if (engine_id is None or engine_id in _REG2) else st.engine_id
        db.session.commit()
        flash(f"Stratégie '{name}' mise à jour.", "success")
    return redirect(url_for('dashboard.strategies'))


@dashboard_bp.route('/strategy/<int:strategy_id>/delete', methods=['POST'])
@login_required
def delete_strategy(strategy_id):
    """Supprime une stratégie perso (jamais celles du système). Les trades déjà taggés gardent leur nom."""
    st = Strategy.query.get_or_404(strategy_id)
    if st.user_id != current_user.id:
        abort(403)
    db.session.delete(st)
    db.session.commit()
    flash(f"Stratégie '{st.name}' supprimée.", "success")
    return redirect(url_for('dashboard.strategies'))






@dashboard_bp.route('/trade/close/<int:trade_id>', methods=['POST'])
@login_required
def close_trade(trade_id):
    trade = TradeSimulation.query.get_or_404(trade_id)

    # Sécurité : vérifier que le trade appartient bien à l'utilisateur
    if trade.user_id != current_user.id:
        abort(403)

    # Clôture définitive : un trade déjà clôturé ne peut pas être re-clôturé
    # (ni P&L recompté, ni note dupliquée) — ses notes restent consultables/ajoutables
    if trade.status == 'closed':
        flash(f"Trade déjà clôturé le {trade.close_date.strftime('%d/%m/%Y') if trade.close_date else ''} ({trade.outcome}, {trade.pnl_usd}$). Notes conservées.", "error")
        return redirect(url_for('dashboard.journal'))

    try:
        exit_price = float(request.form.get('exit_price'))
    except (TypeError, ValueError):
        flash("Prix de sortie invalide.", "error")
        return redirect(url_for('dashboard.journal'))
    user_note = (request.form.get('note') or '').strip()

    trade.exit_price = exit_price
    if user_note:
        trade.notes = user_note  # dernière note (compat) + historique ci-dessous
    trade.status = 'closed'
    trade.close_reason = 'MANUAL'  # clôturé par l'utilisateur (vs SL/TP auto)
    trade.close_date = datetime.utcnow()

    # P&L direction-aware (C1+C4) : SHORT inversé vs LONG
    direction = trade.direction or 'LONG'
    sign = 1 if direction == 'LONG' else -1
    pnl_pct = sign * (exit_price - trade.entry_price) / trade.entry_price * 100 if trade.entry_price else 0
    pnl_usd = round(pnl_pct / 100 * (trade.position_size_usd or 0) * (trade.leverage or 1.0), 2)
    trade.pnl_usd = pnl_usd

    if pnl_usd > 0:
        trade.outcome = 'WIN'
        flash(f'Trade {direction} clôturé en GAIN : +{pnl_usd}$ ({pnl_pct:+.2f}%).', 'success')
    elif pnl_usd < 0:
        trade.outcome = 'LOSS'
        flash(f'Trade {direction} clôturé en PERTE : {pnl_usd}$ ({pnl_pct:+.2f}%).', 'warning')
    else:
        trade.outcome = 'LOSS'
        flash('Trade clôturé à l’équilibre (0$).', 'warning')

    if user_note:
        db.session.add(TradeNote(trade_id=trade.id, user_id=current_user.id, content=user_note))

    db.session.commit()
    return redirect(url_for('dashboard.journal'))


@dashboard_bp.route('/trade/note/<int:trade_id>', methods=['POST'])
@login_required
def add_note(trade_id):
    """Ajoute une note/sentiment même si le trade est encore ouvert (C5)."""
    trade = TradeSimulation.query.get_or_404(trade_id)
    if trade.user_id != current_user.id:
        abort(403)
    content = (request.form.get('content') or '').strip()
    if not content:
        flash("Note vide.", "error")
        return redirect(url_for('dashboard.journal'))
    db.session.add(TradeNote(trade_id=trade.id, user_id=current_user.id, content=content))
    trade.notes = content  # garde la dernière en accès rapide
    db.session.commit()
    flash('Note ajoutée au journal.', 'success')
    return redirect(url_for('dashboard.journal'))

@dashboard_bp.route('/trade/delete/<int:trade_id>', methods=['POST'])
@login_required
def delete_trade(trade_id):
    trade = TradeSimulation.query.get_or_404(trade_id)
    
    if trade.user_id != current_user.id:
        abort(403)
        
    db.session.delete(trade)
    db.session.commit()
    flash('Entrée supprimée du journal.', 'success')
    return redirect(url_for('dashboard.journal'))

# ... code existant ...

@dashboard_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        # Sauvegarde de l'ID Telegram
        tg_id = request.form.get('telegram_id')
        current_user.telegram_id = tg_id
        db.session.commit()
        flash('Paramètres mis à jour avec succès.', 'success')
        return redirect(url_for('dashboard.settings'))
        
    return render_template('dashboard/settings.html')

# Petite route utilitaire pour tester les notifications
@dashboard_bp.route('/test_notification')
@login_required
def test_notification():
    if not current_user.telegram_id:
        flash("Veuillez d'abord entrer votre ID Telegram.", "error")
        return redirect(url_for('dashboard.settings'))
    
    from app.tasks import send_telegram_alert
    try:
        send_telegram_alert(current_user.telegram_id, "🔔 Test RwaTrade : Le système d'alerte fonctionne !")
        flash("Message de test envoyé sur Telegram !", "success")
    except Exception as e:
        flash(f"Erreur d'envoi : {str(e)}", "error")
        
    return redirect(url_for('dashboard.settings'))





