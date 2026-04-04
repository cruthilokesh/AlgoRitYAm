from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from functools import wraps
import os
import math

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///attendance.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ========== DATABASE MODELS ==========

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    role = db.Column(db.String(20), default='employee')
    full_name = db.Column(db.String(100))
    department = db.Column(db.String(50))
    employee_id = db.Column(db.String(20), unique=True)

class AttendanceSession(db.Model):
    __tablename__ = 'attendance_sessions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    login_time = db.Column(db.DateTime, nullable=False)
    logout_time = db.Column(db.DateTime)
    total_hours = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default='active')

# ========== ROUTES ==========

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username, password=password).first()
        
        if user:
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            flash(f'Welcome back, {user.full_name or user.username}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    if user.role == 'employee':
        return redirect(url_for('employee_dashboard'))
    else:
        return redirect(url_for('manager_dashboard'))

@app.route('/employee/dashboard')
def employee_dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    today = datetime.now().date()
    
    today_sessions = AttendanceSession.query.filter(
        db.func.date(AttendanceSession.login_time) == today,
        AttendanceSession.user_id == user.id
    ).all()
    
    total_hours = sum(s.total_hours for s in today_sessions if s.total_hours)
    
    return render_template('employee_dashboard.html', 
                         user=user, 
                         today_sessions=today_sessions, 
                         total_hours_today=round(total_hours, 2))

@app.route('/manager/dashboard')
def manager_dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    employees = User.query.filter_by(role='employee').all()
    return render_template('manager_dashboard.html', employees=employees)

@app.route('/api/check_in', methods=['POST'])
def check_in():
    if 'user_id' not in session:
        return {'success': False, 'message': 'Not logged in'}, 401
    
    active = AttendanceSession.query.filter_by(
        user_id=session['user_id'], 
        status='active'
    ).first()
    
    if active:
        return {'success': False, 'message': 'Already checked in'}, 400
    
    new_session = AttendanceSession(
        user_id=session['user_id'],
        login_time=datetime.now(),
        status='active'
    )
    db.session.add(new_session)
    db.session.commit()
    
    return {'success': True, 'message': 'Checked in successfully'}

@app.route('/api/check_out', methods=['POST'])
def check_out():
    if 'user_id' not in session:
        return {'success': False, 'message': 'Not logged in'}, 401
    
    active = AttendanceSession.query.filter_by(
        user_id=session['user_id'], 
        status='active'
    ).first()
    
    if not active:
        return {'success': False, 'message': 'No active session'}, 400
    
    active.logout_time = datetime.now()
    hours = (active.logout_time - active.login_time).total_seconds() / 3600
    active.total_hours = round(hours, 2)
    active.status = 'completed'
    db.session.commit()
    
    return {'success': True, 'message': f'Checked out. Total: {round(hours, 2)} hours'}

# ========== INITIALIZE DATABASE ==========

def init_database():
    db.create_all()
    
    # Create sample users if none exist
    if User.query.count() == 0:
        users = [
            User(username='admin', password='admin123', email='admin@site.com', role='admin', full_name='Admin User'),
            User(username='manager', password='manager123', email='manager@site.com', role='manager', full_name='Manager User'),
            User(username='john_doe', password='john123', email='john@site.com', role='employee', full_name='John Doe', department='Engineering'),
            User(username='jane_smith', password='jane123', email='jane@site.com', role='employee', full_name='Jane Smith', department='Sales'),
        ]
        for user in users:
            db.session.add(user)
        db.session.commit()
        print("Database initialized with sample users!")

# Call this when the app starts
with app.app_context():
    init_database()

# For production server (gunicorn)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key')

# For local testing
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
