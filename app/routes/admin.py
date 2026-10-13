from flask import Blueprint, render_template, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from app.models import User, db

admin_bp = Blueprint('admin', __name__)

# Sécurité : Seul un admin peut accéder à ces routes
@admin_bp.before_request
def restrict_access():
    if not current_user.is_authenticated or not current_user.is_admin:
        flash("Accès réservé aux administrateurs.", "error")
        return redirect(url_for('public.home'))

@admin_bp.route('/users')
def users_list():
    # On récupère tous les utilisateurs
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)

@admin_bp.route('/approve/<int:user_id>')
def approve_user(user_id):
    user = User.query.get_or_404(user_id)
    user.status = 'active'
    db.session.commit()
    flash(f"L'utilisateur {user.username} a été activé.", "success")
    return redirect(url_for('admin.users_list'))

@admin_bp.route('/block/<int:user_id>')
def block_user(user_id):
    user = User.query.get_or_404(user_id)
    user.status = 'blocked'
    db.session.commit()
    flash(f"L'utilisateur {user.username} a été bloqué.", "error")
    return redirect(url_for('admin.users_list'))
