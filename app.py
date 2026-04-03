from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from functools import wraps
import os
from dotenv import load_dotenv
import math

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key-here')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///attendance.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ========== DATABASE MODELS ==========

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    role = db.Column(db.String(20), default='employee')  # employee, manager, admin
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Employee details
    full_name = db.Column(db.String(100))
    department = db.Column(db.String(50))
    employee_id = db.Column(db.String(20), unique=True)
    
    # Relationships
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
    status = db.Column(db.String(20), default='active')  # active, completed, auto_logged_out
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
    action = db.Column(db.String(20))  # login, logout, auto_logout, location_check
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    is_inside_geofence = db.Column(db.Boolean)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    ip_address = db.Column(db.String(50))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ========== HELPER FUNCTIONS ==========

def calculate_distance(lat1, lon1, lat2, lon2):
    """Calculate distance between two coordinates in meters using Haversine formula"""
    R = 6371000  # Earth's radius in meters
    
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    
    a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c

def is_inside_geofence(latitude, longitude):
    """Check if coordinates are within active geofence"""
    geofence = GeofenceConfig.query.filter_by(is_active=True).first()
    if not geofence:
        return True  # No geofence configured, allow all
    
    distance = calculate_distance(latitude, longitude, geofence.latitude, geofence.longitude)
    return distance <= geofence.radius_meters

def get_active_session(user_id):
    """Get current active session for user"""
    return AttendanceSession.query.filter_by(
        user_id=user_id, 
        status='active'
    ).first()

# ========== DECORATORS ==========

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            if current_user.role not in roles:
                flash('Access denied. Insufficient permissions.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ========== ROUTES ==========

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.password == password:  # In production, use hashed passwords!
            login_user(user)
            
            # Log the login
            log = AttendanceLog(
                user_id=user.id,
                action='login',
                ip_address=request.remote_addr
            )
            db.session.add(log)
            db.session.commit()
            
            flash(f'Welcome back, {user.full_name or user.username}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    # Check if user has active session
    active_session = get_active_session(current_user.id)
    if active_session:
        flash('Please logout from attendance first before logging out of system.', 'warning')
        return redirect(url_for('dashboard'))
    
    logout_user()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'employee':
        return redirect(url_for('employee_dashboard'))
    elif current_user.role == 'manager':
        return redirect(url_for('manager_dashboard'))
    else:
        return redirect(url_for('admin_dashboard'))

# ========== EMPLOYEE ROUTES ==========

@app.route('/employee/dashboard')
@login_required
@role_required('employee')
def employee_dashboard():
    active_session = get_active_session(current_user.id)
    today = datetime.now().date()
    
    # Get today's sessions
    today_sessions = AttendanceSession.query.filter(
        db.func.date(AttendanceSession.login_time) == today,
        AttendanceSession.user_id == current_user.id
    ).all()
    
    total_hours_today = sum(s.total_hours for s in today_sessions if s.total_hours)
    
    # Get weekly summary
    week_start = today - timedelta(days=today.weekday())
    weekly_sessions = AttendanceSession.query.filter(
        db.func.date(AttendanceSession.login_time) >= week_start,
        db.func.date(AttendanceSession.login_time) <= today,
        AttendanceSession.user_id == current_user.id
    ).all()
    
    weekly_hours = {}
    for i in range(7):
        day = week_start + timedelta(days=i)
        daily_total = sum(s.total_hours for s in weekly_sessions 
                         if db.func.date(s.login_time) == day and s.total_hours)
        weekly_hours[day.strftime('%A')] = round(daily_total, 2)
    
    geofence = GeofenceConfig.query.filter_by(is_active=True).first()
    
    return render_template('employee_dashboard.html',
                         active_session=active_session,
                         total_hours_today=round(total_hours_today, 2),
                         weekly_hours=weekly_hours,
                         geofence=geofence,
                         today_sessions=today_sessions)

@app.route('/api/check_in', methods=['POST'])
@login_required
@role_required('employee')
def check_in():
    data = request.get_json()
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    
    # Validate geofence
    if not is_inside_geofence(latitude, longitude):
        return jsonify({'success': False, 'message': 'You must be inside campus to check in!'}), 400
    
    # Check for active session
    active_session = get_active_session(current_user.id)
    if active_session:
        return jsonify({'success': False, 'message': 'You already have an active session!'}), 400
    
    # Create new session
    session = AttendanceSession(
        user_id=current_user.id,
        login_time=datetime.now(),
        login_latitude=latitude,
        login_longitude=longitude,
        status='active'
    )
    db.session.add(session)
    
    # Log the action
    log = AttendanceLog(
        user_id=current_user.id,
        action='login',
        latitude=latitude,
        longitude=longitude,
        is_inside_geofence=True,
        ip_address=request.remote_addr
    )
    db.session.add(log)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'Checked in successfully!'})

@app.route('/api/check_out', methods=['POST'])
@login_required
@role_required('employee')
def check_out():
    data = request.get_json()
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    
    active_session = get_active_session(current_user.id)
    if not active_session:
        return jsonify({'success': False, 'message': 'No active session found!'}), 400
    
    # Calculate hours
    logout_time = datetime.now()
    hours = (logout_time - active_session.login_time).total_seconds() / 3600
    
    active_session.logout_time = logout_time
    active_session.logout_latitude = latitude
    active_session.logout_longitude = longitude
    active_session.total_hours = round(hours, 2)
    active_session.status = 'completed'
    
    # Log the action
    is_inside = is_inside_geofence(latitude, longitude) if latitude and longitude else None
    log = AttendanceLog(
        user_id=current_user.id,
        action='logout',
        latitude=latitude,
        longitude=longitude,
        is_inside_geofence=is_inside,
        ip_address=request.remote_addr
    )
    db.session.add(log)
    db.session.commit()
    
    return jsonify({'success': True, 'message': f'Checked out! Total hours: {round(hours, 2)}'})

@app.route('/api/check_location', methods=['POST'])
@login_required
def check_location():
    data = request.get_json()
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    
    is_inside = is_inside_geofence(latitude, longitude)
    
    # Log location check
    log = AttendanceLog(
        user_id=current_user.id,
        action='location_check',
        latitude=latitude,
        longitude=longitude,
        is_inside_geofence=is_inside,
        ip_address=request.remote_addr
    )
    db.session.add(log)
    db.session.commit()
    
    # If user has active session and is outside geofence, auto logout
    active_session = get_active_session(current_user.id)
    if active_session and not is_inside:
        # Auto logout
        logout_time = datetime.now()
        hours = (logout_time - active_session.login_time).total_seconds() / 3600
        
        active_session.logout_time = logout_time
        active_session.logout_latitude = latitude
        active_session.logout_longitude = longitude
        active_session.total_hours = round(hours, 2)
        active_session.status = 'auto_logged_out'
        active_session.auto_logout = True
        
        db.session.commit()
        
        return jsonify({
            'inside': False, 
            'auto_logged_out': True,
            'message': 'Auto-logged out as you left campus!'
        })
    
    return jsonify({'inside': is_inside})

# ========== MANAGER ROUTES ==========

@app.route('/manager/dashboard')
@login_required
@role_required('manager', 'admin')
def manager_dashboard():
    # Get all employees
    employees = User.query.filter_by(role='employee', is_active=True).all()
    
    # Get active sessions
    active_employees = []
    for emp in employees:
        active_session = get_active_session(emp.id)
        if active_session:
            # Calculate current session duration
            duration = (datetime.now() - active_session.login_time).total_seconds() / 3600
            active_employees.append({
                'user': emp,
                'session': active_session,
                'current_duration': round(duration, 2)
            })
    
    # Get today's summary
    today = datetime.now().date()
    today_logins = AttendanceLog.query.filter(
        db.func.date(AttendanceLog.timestamp) == today,
        AttendanceLog.action == 'login'
    ).count()
    
    total_present = len(set([log.user_id for log in AttendanceLog.query.filter(
        db.func.date(AttendanceLog.timestamp) == today,
        AttendanceLog.action == 'login'
    ).all()]))
    
    return render_template('manager_dashboard.html',
                         employees=employees,
                         active_employees=active_employees,
                         total_employees=len(employees),
                         total_present=total_present,
                         today_logins=today_logins)
@app.route('/api/update_geofence', methods=['POST'])
@login_required
@role_required('admin')
def update_geofence():
    """Update geofence configuration (Admin only)"""
    data = request.get_json()
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    radius = data.get('radius')
    
    if not latitude or not longitude:
        return jsonify({'success': False, 'message': 'Latitude and longitude required'}), 400
    
    # Deactivate current geofence
    GeofenceConfig.query.update({'is_active': False})
    
    # Create new geofence
    new_geofence = GeofenceConfig(
        latitude=latitude,
        longitude=longitude,
        radius_meters=radius or 500,
        is_active=True
    )
    db.session.add(new_geofence)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'Geofence updated successfully'})
@app.route('/api/employee_sessions/<int:employee_id>')
@login_required
@role_required('manager', 'admin')
def get_employee_sessions(employee_id):
    days = request.args.get('days', 7, type=int)
    start_date = datetime.now().date() - timedelta(days=days)
    
    sessions = AttendanceSession.query.filter(
        AttendanceSession.user_id == employee_id,
        db.func.date(AttendanceSession.login_time) >= start_date
    ).order_by(AttendanceSession.login_time.desc()).all()
    
    sessions_data = []
    for session in sessions:
        sessions_data.append({
            'id': session.id,
            'login_time': session.login_time.strftime('%Y-%m-%d %H:%M:%S'),
            'logout_time': session.logout_time.strftime('%Y-%m-%d %H:%M:%S') if session.logout_time else None,
            'total_hours': session.total_hours,
            'status': session.status,
            'auto_logout': session.auto_logout
        })
    
    return jsonify(sessions_data)

# ========== INITIALIZATION ==========

def init_database():
    """Initialize database with sample data"""
    db.create_all()
    
    # Create default geofence (example coordinates - replace with your location)
    if not GeofenceConfig.query.first():
        geofence = GeofenceConfig(
            latitude=28.6139,  # Replace with your campus latitude
            longitude=77.2090,  # Replace with your campus longitude
            radius_meters=500,
            is_active=True
        )
        db.session.add(geofence)
    
    # Create admin user
    if not User.query.filter_by(username='admin').first():
        admin = User(
            username='admin',
            password='admin123',  # Change this!
            email='admin@company.com',
            role='admin',
            full_name='System Administrator',
            employee_id='ADMIN001'
        )
        db.session.add(admin)
    
    # Create manager user
    if not User.query.filter_by(username='manager').first():
        manager = User(
            username='manager',
            password='manager123',
            email='manager@company.com',
            role='manager',
            full_name='Department Manager',
            employee_id='MGR001'
        )
        db.session.add(manager)
    
    # Create sample employees
    sample_employees = [
        ('john_doe', 'john123', 'john@company.com', 'John Doe', 'Engineering', 'EMP001'),
        ('jane_smith', 'jane123', 'jane@company.com', 'Jane Smith', 'Sales', 'EMP002'),
        ('bob_wilson', 'bob123', 'bob@company.com', 'Bob Wilson', 'Engineering', 'EMP003'),
    ]
    
    for emp in sample_employees:
        if not User.query.filter_by(username=emp[0]).first():
            employee = User(
                username=emp[0],
                password=emp[1],
                email=emp[2],
                role='employee',
                full_name=emp[3],
                department=emp[4],
                employee_id=emp[5]
            )
            db.session.add(employee)
    
    db.session.commit()
    print("Database initialized with sample data!")

if __name__ == '__main__':
    with app.app_context():
        init_database()
    app.run(debug=True, host='0.0.0.0', port=5000)