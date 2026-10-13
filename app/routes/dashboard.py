from flask import Blueprint, render_template, request, flash, redirect, url_for, abort
from flask_login import login_required, current_user
from app.models import MarketStatus, TradeSimulation, TradeNote, Portfolio, db
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
        wins = sum(1 for t in pf.trades if t.outcome == 'WIN')
        pf_stats.append({
            'pf': pf,
            'equity': pf.equity(),
            'pnl_total': round(sum(t.pnl_usd for t in closed), 2),
            'n_trades': len(pf.trades),
            'n_closed': len(closed),
            'winrate': round(wins / len(closed) * 100, 1) if closed else 0,
        })

    # 2. On récupère l'historique des simulations de l'utilisateur
    recent_trades = TradeSimulation.query.filter_by(user_id=current_user.id).order_by(TradeSimulation.entry_date.desc()).limit(5).all()

    # 3. Préparation des données pour le Graphique TradingView (Demo: BTC data simple)
    # Dans une V2, on passera l'historique complet via une API interne
    # Pour l'instant, on envoie juste le dernier prix pour initialiser
    btc_data = MarketStatus.query.filter_by(symbol='BTCUSDT').first()
    current_btc_price = btc_data.price if btc_data else 0

    return render_template('dashboard/index.html',
                         market_data=market_data,
                         recent_trades=recent_trades,
                         btc_price=current_btc_price,
                         portfolios=portfolios,
                         pf_stats=pf_stats)


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



@dashboard_bp.route('/api/history/<symbol>')
@login_required
def get_history(symbol):
    """Récupère l'historique OHLCV (Binance pour crypto, Yahoo pour Gold/Forex/Indices)."""
    try:
        market = MarketStatus.query.filter_by(symbol=symbol).first()
        source = (market.source if market and market.source else 'binance')

        data = []
        current_price = None
        if source == 'yahoo':
            import yfinance as yf
            yahoo_map = {'GOLD': 'GC=F', 'EURUSD': 'EURUSD=X', 'SP500': '^GSPC'}
            ticker = yahoo_map.get(symbol, symbol)
            df = yf.download(ticker, period='6mo', interval='1d', progress=False, auto_adjust=True)
            if df is None or len(df) == 0:
                return jsonify({'success': False, 'error': 'Aucune donnée Yahoo'})
            # aplatir colonnes multi-index éventuelles
            try:
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            except Exception:
                pass
            for idx, row in df.iterrows():
                try:
                    ts = int(idx.timestamp())
                except Exception:
                    continue
                o = float(row.get('Open', float('nan')))
                h = float(row.get('High', float('nan')))
                l = float(row.get('Low', float('nan')))
                c = float(row.get('Close', float('nan')))
                if any(v != v for v in [o, h, l, c]):  # NaN
                    continue
                data.append({'time': ts, 'open': o, 'high': h, 'low': l, 'close': c})
            current_price = data[-1]['close'] if data else None
        else:
            binance_symbol = symbol.replace('USDT', '/USDT')
            exchange = ccxt.binance()
            ohlcv = exchange.fetch_ohlcv(binance_symbol, timeframe='1d', limit=100)
            for candle in ohlcv:
                data.append({
                    'time': int(candle[0] / 1000),
                    'open': candle[1], 'high': candle[2],
                    'low': candle[3], 'close': candle[4]
                })
            current_price = data[-1]['close'] if data else None

        return jsonify({'success': True, 'data': data, 'current_price': current_price})

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

    sim = TradeSimulation(
        user_id=current_user.id,
        portfolio_id=pf.id,
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
    trades = q.order_by(TradeSimulation.entry_date.desc()).all()

    # 2. Récupérer les prix actuels du marché pour l'affichage "En cours"
    market_status = MarketStatus.query.all()
    # On crée un dictionnaire pour accès rapide : {'BTCUSDT': 65000, 'ETHUSDT': 3500...}
    current_prices = {m.symbol: m.price for m in market_status}

    return render_template('dashboard/journal.html',
                         trades=trades,
                         current_prices=current_prices,
                         portfolios=portfolios,
                         filter_pf_id=filter_pf_id)




@dashboard_bp.route('/strategies')
@login_required
def strategies():
    # Affiche la page statique
    return render_template('dashboard/strategies.html')






@dashboard_bp.route('/trade/close/<int:trade_id>', methods=['POST'])
@login_required
def close_trade(trade_id):
    trade = TradeSimulation.query.get_or_404(trade_id)

    # Sécurité : vérifier que le trade appartient bien à l'utilisateur
    if trade.user_id != current_user.id:
        abort(403)

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





