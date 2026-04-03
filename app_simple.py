from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from functools import wraps
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
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    full_name = db.Column(db.String(100))
    department = db.Column(db.String(50))
    employee_id = db.Column(db.String(20), unique=True)
    sessions = db.relationship('AttendanceSession', backref='user', lazy=True)

class AttendanceSession(db.Model):
    __tablename__ = 'attendance_sessions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    login_time = db.Column(db.DateTime, nullable=False)
    logout_time = db.Column(db.DateTime)
    login_latitude = db.Column(db.Float)
    login_longitude = db.Column(db.Float)
    logout_latitude = db.Column(db.Float)
    logout_longitude = db.Column(db.Float)
    total_hours = db.Column(db.Float, default=0.0)
    auto_logout = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default='active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class GeofenceConfig(db.Model):
    __tablename__ = 'geofence_config'
    id = db.Column(db.Integer, primary_key=True)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    radius_meters = db.Column(db.Float, default=500)
    is_active = db.Column(db.Boolean, default=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class AttendanceLog(db.Model):
    __tablename__ = 'attendance_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(db.String(20))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    is_inside_geofence = db.Column(db.Boolean)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    ip_address = db.Column(db.String(50))

# ========== HELPER FUNCTIONS ==========

def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def is_inside_geofence(latitude, longitude):
    geofence = GeofenceConfig.query.filter_by(is_active=True).first()
    if not geofence:
        return True
    distance = calculate_distance(latitude, longitude, geofence.latitude, geofence.longitude)
    return distance <= geofence.radius_meters

def get_active_session(user_id):
    return AttendanceSession.query.filter_by(user_id=user_id, status='active').first()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ========== ROUTES ==========

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.password == password:
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
    flash('You have been logged out successfully.', 'info')
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
@login_required
def employee_dashboard():
    user = User.query.get(session['user_id'])
    active_session = get_active_session(user.id)
    today = datetime.now().date()
    
    today_sessions = AttendanceSession.query.filter(
        db.func.date(AttendanceSession.login_time) == today,
        AttendanceSession.user_id == user.id
    ).all()
    
    total_hours_today = sum(s.total_hours for s in today_sessions if s.total_hours)
    
    return render_template('employee_dashboard.html',
                         user=user,
                         active_session=active_session,
                         total_hours_today=round(total_hours_today, 2),
                         today_sessions=today_sessions)

@app.route('/api/check_in', methods=['POST'])
@login_required
def check_in():
    user = User.query.get(session['user_id'])
    data = request.get_json()
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    
    if not is_inside_geofence(latitude, longitude):
        return jsonify({'success': False, 'message': 'You must be inside campus to check in!'}), 400
    
    if get_active_session(user.id):
        return jsonify({'success': False, 'message': 'You already have an active session!'}), 400
    
    session_obj = AttendanceSession(
        user_id=user.id,
        login_time=datetime.now(),
        login_latitude=latitude,
        login_longitude=longitude,
        status='active'
    )
    db.session.add(session_obj)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'Checked in successfully!'})

@app.route('/api/check_out', methods=['POST'])
@login_required
def check_out():
    user = User.query.get(session['user_id'])
    data = request.get_json()
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    
    active_session = get_active_session(user.id)
    if not active_session:
        return jsonify({'success': False, 'message': 'No active session found!'}), 400
    
    logout_time = datetime.now()
    hours = (logout_time - active_session.login_time).total_seconds() / 3600
    
    active_session.logout_time = logout_time
    active_session.logout_latitude = latitude
    active_session.logout_longitude = longitude
    active_session.total_hours = round(hours, 2)
    active_session.status = 'completed'
    db.session.commit()
    
    return jsonify({'success': True, 'message': f'Checked out! Total hours: {round(hours, 2)}'})

@app.route('/api/check_location', methods=['POST'])
@login_required
def check_location():
    user = User.query.get(session['user_id'])
    data = request.get_json()
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    
    is_inside = is_inside_geofence(latitude, longitude)
    
    active_session = get_active_session(user.id)
    if active_session and not is_inside:
        logout_time = datetime.now()
        hours = (logout_time - active_session.login_time).total_seconds() / 3600
        
        active_session.logout_time = logout_time
        active_session.logout_latitude = latitude
        active_session.logout_longitude = longitude
        active_session.total_hours = round(hours, 2)
        active_session.status = 'auto_logged_out'
        active_session.auto_logout = True
        db.session.commit()
        
        return jsonify({'inside': False, 'auto_logged_out': True, 'message': 'Auto-logged out!'})
    
    return jsonify({'inside': is_inside})

@app.route('/manager/dashboard')
@login_required
def manager_dashboard():
    user = User.query.get(session['user_id'])
    employees = User.query.filter_by(role='employee', is_active=True).all()
    
    active_employees = []
    for emp in employees:
        active_session = get_active_session(emp.id)
        if active_session:
            duration = (datetime.now() - active_session.login_time).total_seconds() / 3600
            active_employees.append({'user': emp, 'session': active_session, 'current_duration': round(duration, 2)})
    
    return render_template('manager_dashboard.html', user=user, employees=employees, active_employees=active_employees, total_employees=len(employees))

@app.route('/api/employee_sessions/<int:employee_id>')
@login_required
def get_employee_sessions(employee_id):
    sessions = AttendanceSession.query.filter_by(user_id=employee_id).order_by(AttendanceSession.login_time.desc()).limit(10).all()
    sessions_data = [{'id': s.id, 'login_time': s.login_time.strftime('%Y-%m-%d %H:%M:%S'), 'logout_time': s.logout_time.strftime('%Y-%m-%d %H:%M:%S') if s.logout_time else None, 'total_hours': s.total_hours, 'status': s.status} for s in sessions]
    return jsonify(sessions_data)

def init_database():
    db.create_all()
    
    if not GeofenceConfig.query.first():
        geofence = GeofenceConfig(latitude=28.6139, longitude=77.2090, radius_meters=500, is_active=True)
        db.session.add(geofence)
    
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', password='admin123', email='admin@company.com', role='admin', full_name='Admin', employee_id='ADMIN001')
        db.session.add(admin)
    
    if not User.query.filter_by(username='manager').first():
        manager = User(username='manager', password='manager123', email='manager@company.com', role='manager', full_name='Manager', employee_id='MGR001')
        db.session.add(manager)
    
    if not User.query.filter_by(username='john_doe').first():
        employee = User(username='john_doe', password='john123', email='john@company.com', role='employee', full_name='John Doe', department='Engineering', employee_id='EMP001')
        db.session.add(employee)
    
    db.session.commit()
    print("Database initialized!")
    print("\nDemo Credentials:")
    print("Employee: john_doe / john123")
    print("Manager: manager / manager123")
    print("Admin: admin / admin123\n")

if __name__ == '__main__':
    with app.app_context():
        init_database()
    app.run(debug=True, host='0.0.0.0', port=5000)