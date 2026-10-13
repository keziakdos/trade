from flask import Blueprint, render_template
from app.models import MarketStatus

public_bp = Blueprint('public', __name__)

@public_bp.route('/')
def home():
    # Récupération des données du scanner
    market_data = MarketStatus.query.all()
    
    # Si la base est vide (premier lancement), on met une liste vide
    if not market_data:
        market_data = []
    
    return render_template('public/home.html', market_data=market_data)
