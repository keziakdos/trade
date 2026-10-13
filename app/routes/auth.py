from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models import User

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('public.home'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('public.home'))
        else:
            flash('Email ou mot de passe incorrect.', 'error')
            
    return render_template('auth/login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('public.home'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Vérification existence
        if User.query.filter_by(email=email).first():
            flash('Cet email est déjà utilisé.', 'error')
            return redirect(url_for('auth.register'))
            
        new_user = User(username=username, email=email)
        new_user.set_password(password)
        # Par défaut status = 'pending' (défini dans models.py)
        
        db.session.add(new_user)
        db.session.commit()
        
        flash('Compte créé ! En attente de validation par un administrateur.', 'success')
        return redirect(url_for('auth.login'))
        
    return render_template('auth/register.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('public.home'))
