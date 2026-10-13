import os

class Config:
    # Clé de sécurité pour les sessions (à changer en prod)
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-key-rwatrade-secret'
    
    # Configuration Base de données SQLite
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'rwatrade.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN') or "8217215079:AAFPZVYh7y14toe9voO-4mLWoBDtwdtvGGo"  # TODO: mettre en .env prod, valeur ici = fallback dev
