import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from apscheduler.schedulers.background import BackgroundScheduler
from config import Config

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = "Veuillez vous connecter pour accéder à cet espace."

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)

    # --- CONFIGURATION DU SCHEDULER (CORRIGÉE) ---
    # On vérifie qu'on ne lance pas le scheduler deux fois (bug classique du reload)
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        from app.tasks import get_market_analysis
        
        # C'est ici le FIX : On crée une fonction qui "enveloppe" le scanner
        # pour lui donner le contexte de l'application (l'accès à la DB)
        def scanner_with_context():
            with app.app_context():
                get_market_analysis()

        scheduler = BackgroundScheduler()
        
        # On programme l'enveloppe (scanner_with_context) au lieu de la fonction brute
        scheduler.add_job(func=scanner_with_context, trigger="interval", minutes=15)
        
        # Lancement immédiat au démarrage (aussi avec le contexte)
        scheduler.add_job(func=scanner_with_context, trigger="date")
        
        scheduler.start()
    # ---------------------------------------------

    from app import models

    # Blueprints
    from app.routes.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from app.routes.public import public_bp
    app.register_blueprint(public_bp)

    from app.routes.dashboard import dashboard_bp
    app.register_blueprint(dashboard_bp)

    from app.routes.admin import admin_bp
    app.register_blueprint(admin_bp, url_prefix='/admin')

    return app
