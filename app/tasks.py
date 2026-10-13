import ccxt
import pandas as pd
import datetime
from app import db
from app.models import MarketStatus
import requests
from app.models import User



def calculate_indicators(df):
    """Calcule RSI et MA200 sur un DataFrame donné"""
    # Moyenne Mobile 200
    df['ma200'] = df['close'].rolling(window=200).mean()
    
    # RSI 14
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    return df

def get_trend(price, ma200):
    if ma200 is None or pd.isna(ma200): return "NEUTRAL"
    return "UPTREND" if price > ma200 else "DOWNTREND"


def send_telegram_alert(chat_id, message):
    """Envoie un message via l'API Telegram (token lu depuis config/env)."""
    try:
        from flask import current_app
        try:
            token = current_app.config.get('TELEGRAM_BOT_TOKEN')
        except RuntimeError:
            token = None
        if not token:
            import os
            token = os.environ.get('TELEGRAM_BOT_TOKEN')
        if not token:
            print("Telegram: token manquant, alerte ignorée.")
            return
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        print(f"Erreur Telegram: {e}")


# Actifs Yahoo réduits (C9) : Gold, Forex EURUSD, Indice SP500
YAHOO_ASSETS = {
    'GOLD': {'ticker': 'GC=F', 'asset_type': 'commodity'},
    'EURUSD': {'ticker': 'EURUSD=X', 'asset_type': 'forex'},
    'SP500': {'ticker': '^GSPC', 'asset_type': 'indice'},
    'IXIC': {'ticker': '^IXIC', 'asset_type': 'indice'},
    'SPY': {'ticker': 'SPY', 'asset_type': 'indice'},
    'AAPL': {'ticker': 'AAPL', 'asset_type': 'action'},
    'MSFT': {'ticker': 'MSFT', 'asset_type': 'action'},
}

def fetch_yahoo_df(ticker, interval='1d', period='2y'):
    """Récupère un DataFrame OHLC normalisé depuis Yahoo Finance."""
    import yfinance as yf
    df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
    if df is None or len(df) == 0:
        raise ValueError(f"Yahoo: aucune donnée pour {ticker}")
    try:
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    except Exception:
        pass
    df = df.rename(columns={'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'})
    cols = [c for c in ['open', 'high', 'low', 'close', 'volume'] if c in df.columns]
    df = df[cols].dropna()
    # s'assurer colonne close lowercase
    if 'close' not in df.columns and 'Close' in df.columns:
        df['close'] = df['Close']
    return df




def compute_signal(tf_data, db_symbol):
    """Algorithme RwaTrade V2 factorise (reutilise crypto + yahoo)."""
    is_full_uptrend = (tf_data['1d']['trend'] == 'UPTREND' and
                       tf_data['4h']['trend'] == 'UPTREND' and
                       tf_data['1h']['trend'] == 'UPTREND')
    is_dip_buy = (tf_data['1d']['trend'] == 'UPTREND' and tf_data['1h']['rsi'] < 35)
    signal, color, alert_message = "WAIT", "yellow", None
    if is_full_uptrend:
        if tf_data['1h']['rsi'] > 70:
            signal, color = "TOP (Risky)", "orange"
        else:
            signal, color = "STRONG BUY", "green"
            alert_message = f"🚀 **SIGNAL STRONG BUY**\n\nAsset: #{db_symbol}\nPrix: ${tf_data['1d']['price']}\n\n Tendance 1D/4H/1H alignee"
    elif is_dip_buy:
        signal, color = "SNIPER ENTRY", "green"
        alert_message = f"🎯 **SIGNAL SNIPER**\n\nAsset: #{db_symbol}\nPrix: ${tf_data['1d']['price']}"
    elif tf_data['1d']['trend'] == 'DOWNTREND':
        signal, color = "BEARISH", "red"
    return signal, color, alert_message


def save_market_entry(db_symbol, tf_data, signal, color, asset_type='crypto', source='binance'):
    market_entry = MarketStatus.query.filter_by(symbol=db_symbol).first()
    if not market_entry:
        market_entry = MarketStatus(symbol=db_symbol)
    market_entry.price = float(tf_data['1d']['price'])
    market_entry.asset_type = asset_type
    market_entry.source = source
    market_entry.rsi_1d = round(float(tf_data['1d']['rsi']), 1)
    market_entry.trend_1d = tf_data['1d']['trend']
    market_entry.rsi_4h = round(float(tf_data['4h']['rsi']), 1)
    market_entry.trend_4h = tf_data['4h']['trend']
    market_entry.rsi_1h = round(float(tf_data['1h']['rsi']), 1)
    market_entry.trend_1h = tf_data['1h']['trend']
    market_entry.global_signal = signal
    market_entry.color_code = color
    market_entry.last_updated = datetime.datetime.utcnow()
    db.session.add(market_entry)


def get_market_analysis():
    print(f"[{datetime.datetime.now()}] Lancement du Scan Multi-Timeframe...")
    exchange = ccxt.binance()
    symbols = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT', 'DOGE/USDT']
    try:
        for symbol in symbols:
            db_symbol = symbol.replace('/', '')
            print(f"Analyse de {db_symbol}...")
            tf_data = {}
            for tf in ['1d', '4h', '1h']:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe=tf, limit=250)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df = calculate_indicators(df)
                tf_data[tf] = {
                    'rsi': df['rsi'].iloc[-1],
                    'trend': get_trend(df['close'].iloc[-1], df['ma200'].iloc[-1]),
                    'price': df['close'].iloc[-1]
                }
            signal, color, alert_message = compute_signal(tf_data, db_symbol)
            if alert_message:
                print(f"ALERTE DETECTEE SUR {db_symbol} !")
                admins = User.query.filter(User.is_admin==True, User.telegram_id!=None).all()
                for admin in admins:
                    send_telegram_alert(admin.telegram_id, alert_message)
            save_market_entry(db_symbol, tf_data, signal, color, asset_type='crypto', source='binance')
        for db_symbol, meta in YAHOO_ASSETS.items():
            try:
                print(f"Analyse Yahoo de {db_symbol} ({meta['ticker']})...")
                df_d = calculate_indicators(fetch_yahoo_df(meta['ticker'], interval='1d', period='2y'))
                df_h = calculate_indicators(fetch_yahoo_df(meta['ticker'], interval='1h', period='1mo'))
                price_d = float(df_d['close'].iloc[-1])
                ma200_d = df_d['ma200'].iloc[-1] if 'ma200' in df_d.columns else float('nan')
                price_h = float(df_h['close'].iloc[-1])
                ma200_h = float(df_h['close'].rolling(window=200).mean().iloc[-1])
                tf_data = {
                    '1d': {'rsi': float(df_d['rsi'].iloc[-1]), 'trend': get_trend(price_d, ma200_d), 'price': price_d},
                    '4h': {'rsi': float(df_d['rsi'].iloc[-1]), 'trend': get_trend(price_d, ma200_d), 'price': price_d},
                    '1h': {'rsi': float(df_h['rsi'].iloc[-1]), 'trend': get_trend(price_h, ma200_h), 'price': price_h},
                }
                signal, color, alert_message = compute_signal(tf_data, db_symbol)
                if alert_message:
                    admins = User.query.filter(User.is_admin==True, User.telegram_id!=None).all()
                    for admin in admins:
                        send_telegram_alert(admin.telegram_id, alert_message)
                save_market_entry(db_symbol, tf_data, signal, color, asset_type=meta['asset_type'], source='yahoo')
            except Exception as ye:
                print(f"Yahoo {db_symbol} ignore : {ye}")
                continue
        db.session.commit()
        print("Scan V2 termine.")
    except Exception as e:
        print(f"Erreur Scanner V2 : {e}")
