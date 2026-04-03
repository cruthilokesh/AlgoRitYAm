from datetime import datetime, timedelta
from database import db, AttendanceSession

def calculate_working_hours(login_time, logout_time):
    """Calculate working hours between two timestamps"""
    if not logout_time:
        return 0
    seconds = (logout_time - login_time).total_seconds()
    return round(seconds / 3600, 2)

def get_daily_total(user_id, date=None):
    """Get total working hours for a user on a specific date"""
    if date is None:
        date = datetime.now().date()
    
    sessions = AttendanceSession.query.filter(
        db.func.date(AttendanceSession.login_time) == date,
        AttendanceSession.user_id == user_id,
        AttendanceSession.status != 'active'
    ).all()
    
    total = sum(session.total_hours for session in sessions if session.total_hours)
    return round(total, 2)

def get_weekly_summary(user_id):
    """Get weekly working hours summary"""
    today = datetime.now().date()
    week_start = today - timedelta(days=today.weekday())
    
    weekly_hours = {}
    for i in range(7):
        day = week_start + timedelta(days=i)
        daily_total = get_daily_total(user_id, day)
        weekly_hours[day.strftime('%A')] = daily_total
    
    return weekly_hours