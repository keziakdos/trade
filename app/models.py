from app import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))

    telegram_id = db.Column(db.String(50), nullable=True)

    
    # Rôles et Statuts
    is_admin = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default='pending') # pending, active, blocked
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    @property
    def is_active_user(self):
        """Vérifie si l'utilisateur a été validé par l'admin"""
        return self.status == 'active'

class Portfolio(db.Model):
    """Portefeuille fictif d'apprentissage (C10)."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(50), nullable=False, default='Principal')
    initial_balance = db.Column(db.Float, nullable=False, default=10000.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('portfolios', lazy=True, cascade='all, delete-orphan'))

    def equity(self):
        """Balance initiale + P&L clôturés (fictif)."""
        total = self.initial_balance
        for t in self.trades:
            if t.status == 'closed' and t.pnl_usd:
                total += t.pnl_usd
        return round(total, 2)


class TradeSimulation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    portfolio_id = db.Column(db.Integer, db.ForeignKey('portfolio.id'), nullable=True)
    
    symbol = db.Column(db.String(20), nullable=False) # ex: BTCUSDT
    direction = db.Column(db.String(10), nullable=False, default='LONG') # LONG (vers le haut) / SHORT (vers le bas)
    entry_price = db.Column(db.Float, nullable=False)
    stop_loss = db.Column(db.Float, nullable=False)
    take_profit = db.Column(db.Float, nullable=False)
    
    position_size_usd = db.Column(db.Float, nullable=False) # capital simulé (fictif)
    leverage = db.Column(db.Float, default=1.0)
    quantity = db.Column(db.Float, nullable=True) # capital / entry
    risk_reward = db.Column(db.Float)
    risk_amount_usd = db.Column(db.Float, nullable=True) # perte si SL touché
    reward_amount_usd = db.Column(db.Float, nullable=True) # gain si TP touché
    pnl_usd = db.Column(db.Float, nullable=True) # P&L définitif stocké à la clôture
    strategy_tag = db.Column(db.String(50), nullable=True) # réservé évolution stratégies
    
    status = db.Column(db.String(20), default='open') # open, closed
    close_reason = db.Column(db.String(10), nullable=True) # MANUAL (utilisateur), SL, TP (auto)
    archived = db.Column(db.Boolean, default=False) # fermé définitivement : caché du journal, historique + P&L gardés

    exit_price = db.Column(db.Float, nullable=True) # Prix de sortie
    outcome = db.Column(db.String(10), nullable=True) # WIN ou LOSS
    notes = db.Column(db.Text, nullable=True) # Dernière note (compat) — historique dans TradeNote


    entry_date = db.Column(db.DateTime, default=datetime.utcnow)
    close_date = db.Column(db.DateTime, nullable=True)

    # Relation pour accéder au User depuis un trade
    user = db.relationship('User', backref=db.backref('trades', lazy=True))
    portfolio = db.relationship('Portfolio', backref=db.backref('trades', lazy=True))

    @property
    def direction_sign(self):
        return 1 if (self.direction or 'LONG') == 'LONG' else -1

    def calc_pnl_usd(self, price):
        """P&L fictif en $ pour un prix donné (direction-aware)."""
        if not self.entry_price or not self.position_size_usd:
            return 0.0
        return self.direction_sign * (price - self.entry_price) / self.entry_price * self.position_size_usd * (self.leverage or 1.0)


class TradeNote(db.Model):
    """Notes/sentiments multiples, ajoutables même si trade ouvert."""
    id = db.Column(db.Integer, primary_key=True)
    trade_id = db.Column(db.Integer, db.ForeignKey('trade_simulation.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    trade = db.relationship('TradeSimulation', backref=db.backref('all_notes', lazy=True, cascade='all, delete-orphan', order_by='TradeNote.created_at'))


class Strategy(db.Model):
    """Stratégie pédagogique (V2 : l'utilisateur peut ajouter les siennes). user_id NULL = système."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    name = db.Column(db.String(80), nullable=False)
    level = db.Column(db.String(20), default='Débutant') # Débutant / Intermédiaire / Avancé
    side = db.Column(db.String(10), nullable=False, default='LONG') # LONG / SHORT
    sl_pct = db.Column(db.Float, nullable=False, default=2.0) # % stop loss
    tp_pct = db.Column(db.Float, nullable=False, default=4.0) # % take profit
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('strategies', lazy=True, cascade='all, delete-orphan'))





# ... (Gardez les imports et les classes User/TradeSimulation existants) ...

class MarketStatus(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(20), unique=True, nullable=False) # BTCUSDT
    price = db.Column(db.Float, nullable=False)
    asset_type = db.Column(db.String(20), default='crypto') # crypto, forex, commodity, indice
    source = db.Column(db.String(20), default='binance') # binance, yahoo
    
    # --- DAILY (La Tendance de fond) ---
    rsi_1d = db.Column(db.Float)
    trend_1d = db.Column(db.String(20)) # UPTREND / DOWNTREND
    
    # --- 4 HEURES (Le Swing) ---
    rsi_4h = db.Column(db.Float)
    trend_4h = db.Column(db.String(20))
    
    # --- 1 HEURE (L'Entrée Sniper) ---
    rsi_1h = db.Column(db.Float)
    trend_1h = db.Column(db.String(20))
    
    # Synthèse Globale
    global_signal = db.Column(db.String(20)) # STRONG BUY, BUY, WAIT, SELL...
    color_code = db.Column(db.String(20)) # green, yellow, red
    
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
