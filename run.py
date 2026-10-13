from app import create_app, db
from app.models import User

app = create_app()

# Permet de créer la DB automatiquement au premier lancement si elle n'existe pas
with app.app_context():
    db.create_all()
    # On pourrait ici vérifier si l'admin existe, sinon le créer (on verra ça plus tard)

if __name__ == '__main__':
    app.run(debug=True)
