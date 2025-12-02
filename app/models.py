from app import db
from datetime import datetime
from flask_login import UserMixin



# ==========================================================
# USERS + OWNER GROUP STRUCTURE
# ==========================================================

class User(UserMixin, db.Model):

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(100), nullable=False)

    notifications = db.relationship("Notification", backref="user", lazy=True)

    def __repr__(self):
        return f"<User {self.email}>"


class OwnerGroup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    users = db.relationship("OwnerGroupUser", backref="group", lazy=True)
    vehicles = db.relationship("Vehicle", backref="group", lazy=True)

    def __repr__(self):
        return f"<OwnerGroup {self.group_name}>"


class OwnerGroupUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("owner_group.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    role_in_group = db.Column(db.String(20), default="member")
    added_at = db.Column(db.DateTime, default=datetime.utcnow)


# ==========================================================
# VEHICLE
# ==========================================================

class Vehicle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("owner_group.id"), nullable=False)

    brand = db.Column(db.String(50))
    model = db.Column(db.String(50))
    year = db.Column(db.Integer)
    vin = db.Column(db.String(100))
    registration_no = db.Column(db.String(50))
    purchase_date = db.Column(db.Date)

    current_odometer = db.Column(db.Integer, default=0)

    # Relationships
    service_events = db.relationship("ServiceEvent", backref="vehicle", lazy=True)
    fuel_entries = db.relationship("FuelEntry", backref="vehicle", lazy=True)
    expenses = db.relationship("Expense", backref="vehicle", lazy=True)
    issues = db.relationship("IssueLog", backref="vehicle", lazy=True)
    odometer_logs = db.relationship("OdometerLog", backref="vehicle", lazy=True)
    forecasts = db.relationship("MaintenanceForecast", backref="vehicle", lazy=True)
    health_scores = db.relationship("HealthScore", backref="vehicle", lazy=True)
    reminders = db.relationship("Reminder", backref="vehicle", lazy=True)

    def __repr__(self):
        return f"<Vehicle {self.brand} {self.model}>"


# ==========================================================
# SERVICE EVENTS + PARTS
# ==========================================================

class ServiceEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicle.id"), nullable=False)

    service_date = db.Column(db.Date, nullable=False)
    odometer_at_service = db.Column(db.Integer, nullable=False)

    service_type = db.Column(db.String(100))
    description = db.Column(db.Text)

    labor_cost = db.Column(db.Float, default=0)
    total_cost = db.Column(db.Float, default=0)

    parts_used = db.relationship("ServicePartUsage", backref="service", lazy=True)


class Part(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    category = db.Column(db.String(50))
    brand = db.Column(db.String(50))

    used_in = db.relationship("ServicePartUsage", backref="part", lazy=True)


class ServicePartUsage(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    service_id = db.Column(db.Integer, db.ForeignKey("service_event.id"), nullable=False)
    part_id = db.Column(db.Integer, db.ForeignKey("part.id"), nullable=False)

    quantity = db.Column(db.Integer, default=1)
    unit_cost = db.Column(db.Float)
    line_cost = db.Column(db.Float)
    warranty_months = db.Column(db.Integer, default=0)


# ==========================================================
# FUEL
# ==========================================================

class FuelEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicle.id"), nullable=False)

    date = db.Column(db.Date, nullable=False)
    odometer = db.Column(db.Integer, nullable=False)

    liters = db.Column(db.Float, nullable=False)

    price_per_liter = db.Column(db.Float)
    total_cost = db.Column(db.Float)

    fuel_type = db.Column(db.String(50))
    station_name = db.Column(db.String(100))


# ==========================================================
# EXPENSES
# ==========================================================

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicle.id"), nullable=False)

    date = db.Column(db.Date, nullable=False)
    category = db.Column(db.String(50))
    amount = db.Column(db.Float)
    description = db.Column(db.Text)


# ==========================================================
# ISSUE LOGS
# ==========================================================

class IssueLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicle.id"), nullable=False)

    date_reported = db.Column(db.Date, default=datetime.utcnow)
    description = db.Column(db.Text)
    severity = db.Column(db.String(20))
    category = db.Column(db.String(50))
    status = db.Column(db.String(20), default="open")


# ==========================================================
# ODOMETER LOGS
# ==========================================================

class OdometerLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicle.id"), nullable=False)

    reading = db.Column(db.Integer, nullable=False)
    log_date = db.Column(db.DateTime, default=datetime.utcnow)
    source = db.Column(db.String(50))  # manual / fuel / service


# ==========================================================
# PREDICTIVE MAINTENANCE
# ==========================================================

class MaintenanceForecast(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicle.id"), nullable=False)

    item_type = db.Column(db.String(100))
    predicted_due_date = db.Column(db.Date)
    predicted_due_odometer = db.Column(db.Integer)
    last_calculated = db.Column(db.DateTime, default=datetime.utcnow)


# ==========================================================
# HEALTH SCORE
# ==========================================================

class HealthScore(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicle.id"), nullable=False)

    score_value = db.Column(db.Integer)
    calculated_at = db.Column(db.DateTime, default=datetime.utcnow)
    explanation_text = db.Column(db.Text)


# ==========================================================
# REMINDERS + NOTIFICATIONS
# ==========================================================

class Reminder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicle.id"), nullable=False)

    title = db.Column(db.String(100))
    reminder_type = db.Column(db.String(20))  # date or mileage
    due_date = db.Column(db.Date)
    due_odometer = db.Column(db.Integer)
    is_completed = db.Column(db.Boolean, default=False)


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))

    message = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)
