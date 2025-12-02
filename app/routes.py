from flask import Blueprint, render_template, request, redirect, url_for
from flask_login import (
    login_user,
    logout_user,
    login_required,
    current_user,
)
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import text

from app import db
from app.models import (
    User,
    OwnerGroup,
    OwnerGroupUser,
    Vehicle,
    ServiceEvent,
    FuelEntry,
    Expense,
    IssueLog,
    OdometerLog,
)
from datetime import datetime, timedelta
import random
main_bp = Blueprint("main", __name__)


def vehicle_query_for_current_user():
    # Admin can see all vehicles
    if current_user.is_authenticated and current_user.email == "admin@garuda360.com":
        return Vehicle.query

    # Normal owner: only vehicles in their groups
    return (
        Vehicle.query
        .join(OwnerGroup, Vehicle.group_id == OwnerGroup.id)
        .join(OwnerGroupUser, OwnerGroup.id == OwnerGroupUser.group_id)
        .filter(OwnerGroupUser.user_id == current_user.id)
    )


def get_vehicle_for_current_user(vehicle_id: int) -> Vehicle:
    return (
        vehicle_query_for_current_user()
        .filter(Vehicle.id == vehicle_id)
        .first_or_404()
    )

def predict_next_service(vehicle, service_type: str, km_interval: int, months_interval: int):
    """
    Predict the next service for a given vehicle and service type
    using simple rules:
      - look at last service_event of this type
      - if found, next date = last_date + months_interval
                    next odo = last_odo + km_interval
      - if not found, base it on today + current odometer
    """
    from datetime import date

    # Find last service for this type
    last_event = (
        ServiceEvent.query
        .filter_by(vehicle_id=vehicle.id, service_type=service_type)
        .order_by(ServiceEvent.service_date.desc())
        .first()
    )

    if last_event:
        last_date = last_event.service_date or date.today()
        last_odo = last_event.odometer_at_service or vehicle.current_odometer
    else:
        # No history → start from current state
        last_date = date.today()
        last_odo = vehicle.current_odometer

    # Approximate months as 30 days each (simple but fine for project)
    from datetime import timedelta

    next_date = last_date + timedelta(days=months_interval * 30)
    next_odo = last_odo + km_interval

    return {
        "service_type": service_type,
        "last_date": last_date,
        "last_odo": last_odo,
        "next_date": next_date,
        "next_odo": next_odo,
    }


main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main.list_vehicles"))
    return render_template("home.html")
@main_bp.route("/create-admin-user")
def create_admin_user():
    email = "admin@garuda360.com"
    if User.query.filter_by(email=email).first():
        return "<p>Admin already exists.</p>"

    admin = User(
        email=email,
        name="Admin",
        password_hash=generate_password_hash("Admin123!"),
    )
    db.session.add(admin)
    db.session.commit()
    return "<p>Admin user created. Email: admin@garuda360.com, Password: Admin123!</p>"



@main_bp.route("/garuda-test")
def garuda_test():
    return """
    <h1>GARUDA360 TEST ROUTE</h1>
    <p>This is the GARUDA TEST route from the new Flask app.</p>
    """


@main_bp.route("/init-db")
def init_db():
    db.create_all()
    return "<p>Database tables created successfully for Garuda360.</p>"
@main_bp.route("/create-sample")
def create_sample():
    # Check if a group already exists
    group = OwnerGroup.query.first()
    if not group:
        group = OwnerGroup(group_name="My Family Garage")
        db.session.add(group)
        db.session.commit()

    # Check if any vehicle exists; if not, create one
    if not Vehicle.query.first():
        car = Vehicle(
            group_id=group.id,
            brand="Toyota",
            model="Camry",
            year=2018,
            registration_no="TEST-1234",
            current_odometer=45000
        )
        db.session.add(car)
        db.session.commit()
        return "<p>Sample group and vehicle created successfully.</p>"

    return "<p>Sample data already exists. No new vehicle created.</p>"
@main_bp.route("/vehicles")
@login_required
def list_vehicles():
    vehicles = vehicle_query_for_current_user().all()
    return render_template("vehicles.html", vehicles=vehicles)
@main_bp.route("/vehicles/<int:vehicle_id>/edit", methods=["GET", "POST"])
@login_required
def edit_vehicle(vehicle_id):
    vehicle = get_vehicle_for_current_user(vehicle_id)

    if request.method == "POST":
        vehicle.brand = request.form["brand"]
        vehicle.model = request.form["model"]
        vehicle.year = request.form["year"]
        vehicle.registration_no = request.form["registration_no"]
        vehicle.current_odometer = request.form["current_odometer"]

        db.session.commit()
        return redirect(url_for("main.list_vehicles"))

    # GET request → show form
    return render_template("edit_vehicle.html", vehicle=vehicle)
@main_bp.route("/vehicles/<int:vehicle_id>")
@login_required
def vehicle_detail(vehicle_id):
    vehicle = get_vehicle_for_current_user(vehicle_id)

    # 1) Service summary: count + total expense
    sql_service_summary = text("""
        SELECT
            COUNT(*) AS service_count,
            COALESCE(SUM(total_cost), 0) AS total_expense
        FROM service_event
        WHERE vehicle_id = :vid
    """)
    svc = db.session.execute(sql_service_summary, {"vid": vehicle.id}).first()
    service_count = svc.service_count or 0
    total_service_expense = float(svc.total_expense or 0)

    # 2) Fuel summary: total fuel cost + total liters + approx mileage
    sql_fuel_summary = text("""
        SELECT
            COALESCE(SUM(total_cost), 0) AS total_fuel_cost,
            COALESCE(SUM(liters), 0) AS total_liters,
            CASE
                WHEN SUM(liters) > 0 THEN
                    (MAX(odometer) - MIN(odometer)) * 1.0 / SUM(liters)
                ELSE NULL
            END AS km_per_liter
        FROM fuel_entry
        WHERE vehicle_id = :vid
    """)
    fuel = db.session.execute(sql_fuel_summary, {"vid": vehicle.id}).first()
    total_fuel_cost = float(fuel.total_fuel_cost or 0)
    total_liters = float(fuel.total_liters or 0)
    km_per_liter = fuel.km_per_liter  # can be None if no fuel data
    # 3) Predict next service for key items (rule-based)
    # You can adjust these intervals as needed:
    #   Oil Change  -> every 5000 km or 6 months
    #   Brake Pads  -> every 30000 km or 24 months
    #   Wipers      -> every 20000 km or 18 months

    predictions = []

    rules = [
        ("Oil Change", 5000, 6),
        ("Brake Pads", 30000, 24),
        ("Wipers", 20000, 18),
    ]

    for service_type, km_int, months_int in rules:
        pred = predict_next_service(vehicle, service_type, km_int, months_int)
        predictions.append(pred)

    return render_template(
        "vehicle_detail.html",
        vehicle=vehicle,
        service_count=service_count,
        total_service_expense=total_service_expense,
        total_fuel_cost=total_fuel_cost,
        total_liters=total_liters,
        km_per_liter=km_per_liter,
        service_predictions=predictions,
    )

@main_bp.route("/seed-sample-data")
def seed_sample_data():
    """
    Create a reasonably large demo dataset:
    - 2 owner groups
    - 5 vehicles total
    - ~10 service events per vehicle
    - ~20 fuel entries per vehicle
    - ~5 expenses per vehicle
    - ~5 issues per vehicle
    - ~15 odometer logs per vehicle
    """

    # Check if we already seeded
    if Vehicle.query.count() >= 5:
        return "<p>Database already has enough vehicles. Skipping seeding.</p>"

    # --- 1. Create owner groups ---
    group1 = OwnerGroup(group_name="Family Garage A")
    group2 = OwnerGroup(group_name="Family Garage B")

    db.session.add_all([group1, group2])
    db.session.commit()

    # --- 2. Create vehicles ---
    vehicles_data = [
        (group1.id, "Toyota", "Camry", 2018, "AAA-1111", 45000),
        (group1.id, "Honda", "Civic", 2020, "BBB-2222", 32000),
        (group1.id, "Hyundai", "Elantra", 2017, "CCC-3333", 78000),
        (group2.id, "Ford", "Focus", 2016, "DDD-4444", 91000),
        (group2.id, "Tesla", "Model 3", 2021, "EEE-5555", 15000),
    ]

    vehicles = []
    for g_id, brand, model, year, reg, odo in vehicles_data:
        v = Vehicle(
            group_id=g_id,
            brand=brand,
            model=model,
            year=year,
            registration_no=reg,
            current_odometer=odo,
        )
        db.session.add(v)
        vehicles.append(v)

    db.session.commit()

    # --- 3. Helper to generate random dates ---
    def random_past_date(days_back=365):
        return datetime.utcnow().date() - timedelta(days=random.randint(0, days_back))

    # --- 4. For each vehicle, create service, fuel, expense, issues, odometer logs ---
    for v in vehicles:
        base_odometer = v.current_odometer - 20000  # assume 20k km history

        # 4a. Service events (e.g., oil change, brakes)
        service_types = ["Oil Change", "Brake Pads", "Tire Rotation", "General Service"]
        for i in range(10):  # 10 service events
            odo_at_service = base_odometer + i * 2000
            s = ServiceEvent(
                vehicle_id=v.id,
                service_date=random_past_date(730),
                odometer_at_service=odo_at_service,
                service_type=random.choice(service_types),
                description="Routine maintenance performed.",
                labor_cost=round(random.uniform(50, 150), 2),
                total_cost=round(random.uniform(100, 400), 2),
            )
            db.session.add(s)

        # 4b. Fuel entries
        for i in range(20):  # 20 fuel fills
            odo_at_fuel = base_odometer + i * 800
            liters = round(random.uniform(30, 50), 1)
            price_per_liter = round(random.uniform(1.0, 1.5), 2)
            f = FuelEntry(
                vehicle_id=v.id,
                date=random_past_date(365),
                odometer=odo_at_fuel,
                liters=liters,
                price_per_liter=price_per_liter,
                total_cost=round(liters * price_per_liter, 2),
                fuel_type=random.choice(["Petrol", "Diesel"]),
                station_name=random.choice(["Shell", "BP", "Costco", "RandomGas"]),
            )
            db.session.add(f)

        # 4c. Expenses (insurance, tax, etc.)
        expense_categories = ["Insurance", "Tax", "Parking", "Toll", "Car Wash"]
        for i in range(5):
            e = Expense(
                vehicle_id=v.id,
                date=random_past_date(365),
                category=random.choice(expense_categories),
                amount=round(random.uniform(20, 300), 2),
                description="Recurring vehicle expense.",
            )
            db.session.add(e)

        # 4d. Issues
        issue_severity = ["Low", "Medium", "High"]
        issue_categories = ["Engine", "Brakes", "Electrical", "Body", "Suspension"]
        for i in range(5):
            issue = IssueLog(
                vehicle_id=v.id,
                date_reported=random_past_date(365),
                description="Reported issue for diagnostics.",
                severity=random.choice(issue_severity),
                category=random.choice(issue_categories),
                status=random.choice(["open", "resolved", "in-progress"]),
            )
            db.session.add(issue)

        # 4e. Odometer logs
        for i in range(15):
            odo_val = base_odometer + i * 1200
            odolog = OdometerLog(
                vehicle_id=v.id,
                reading=odo_val,
                log_date=datetime.utcnow() - timedelta(days=i * 15),
                source=random.choice(["manual", "fuel", "service"]),
            )
            db.session.add(odolog)

    db.session.commit()

    return "<p>Sample data seeded successfully: multiple vehicles, service events, fuel logs, expenses, issues, and odometer logs.</p>"
@main_bp.route("/vehicles/new", methods=["GET", "POST"])
@login_required
def add_vehicle():
    # Get or create group for this user
    link = OwnerGroupUser.query.filter_by(user_id=current_user.id).first()
    if not link:
        group = OwnerGroup(group_name=f"{current_user.name}'s Garage")
        db.session.add(group)
        db.session.commit()
        link = OwnerGroupUser(group_id=group.id, user_id=current_user.id)
        db.session.add(link)
        db.session.commit()

    group_id = link.group_id

    if request.method == "POST":
        year_val = request.form.get("year")
        odo_val = request.form.get("current_odometer")

        vehicle = Vehicle(
            group_id=group_id,
            brand=request.form["brand"],
            model=request.form["model"],
            year=int(year_val) if year_val else None,
            registration_no=request.form.get("registration_no"),
            current_odometer=int(odo_val) if odo_val else 0,
        )
        db.session.add(vehicle)
        db.session.commit()
        return redirect(url_for("main.list_vehicles"))

    return render_template("add_vehicle.html")


@main_bp.route("/vehicles/<int:vehicle_id>/services")
@login_required
def list_services(vehicle_id):
    vehicle = get_vehicle_for_current_user(vehicle_id)

    services = (
        ServiceEvent.query
        .filter_by(vehicle_id=vehicle.id)
        .order_by(ServiceEvent.service_date.desc())
        .all()
    )
    return render_template("services.html", vehicle=vehicle, services=services)


@main_bp.route("/vehicles/<int:vehicle_id>/services/new", methods=["GET", "POST"])
@login_required
def add_service(vehicle_id):
    vehicle = get_vehicle_for_current_user(vehicle_id)

    if request.method == "POST":
        service_date = datetime.strptime(request.form["service_date"], "%Y-%m-%d").date()
        odo = int(request.form["odometer_at_service"] or 0)

        s = ServiceEvent(
            vehicle_id=vehicle.id,
            service_date=service_date,
            odometer_at_service=odo,
            service_type=request.form.get("service_type"),
            description=request.form.get("description"),
            labor_cost=float(request.form.get("labor_cost") or 0),
            total_cost=float(request.form.get("total_cost") or 0),
        )
        db.session.add(s)
        db.session.commit()
        return redirect(url_for("main.list_services", vehicle_id=vehicle.id))

    return render_template("add_service.html", vehicle=vehicle)
@main_bp.route("/vehicles/<int:vehicle_id>/fuel")
@login_required
def list_fuel(vehicle_id):
    vehicle = get_vehicle_for_current_user(vehicle_id)

    entries = (
        FuelEntry.query
        .filter_by(vehicle_id=vehicle.id)
        .order_by(FuelEntry.date.desc())
        .all()
    )
    return render_template("fuel.html", vehicle=vehicle, entries=entries)


@main_bp.route("/vehicles/<int:vehicle_id>/fuel/new", methods=["GET", "POST"])
@login_required
def add_fuel(vehicle_id):
    vehicle = get_vehicle_for_current_user(vehicle_id)


    if request.method == "POST":
        date = datetime.strptime(request.form["date"], "%Y-%m-%d").date()
        odometer = int(request.form["odometer"] or 0)
        liters = float(request.form["liters"] or 0)
        price = float(request.form["price_per_liter"] or 0)
        total_cost_val = request.form.get("total_cost")

        if total_cost_val:
            total_cost = float(total_cost_val)
        else:
            total_cost = round(liters * price, 2)

        entry = FuelEntry(
            vehicle_id=vehicle.id,
            date=date,
            odometer=odometer,
            liters=liters,
            price_per_liter=price,
            total_cost=total_cost,
            fuel_type=request.form.get("fuel_type"),
            station_name=request.form.get("station_name"),
        )
        db.session.add(entry)
        db.session.commit()
        return redirect(url_for("main.list_fuel", vehicle_id=vehicle.id))

    return render_template("add_fuel.html", vehicle=vehicle)
@main_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.list_vehicles"))

    error = None

    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        if User.query.filter_by(email=email).first():
            error = "Email is already registered."
            return render_template("register.html", error=error)

        user = User(
            email=email,
            name=name,
            password_hash=generate_password_hash(password),
        )
        db.session.add(user)
        db.session.commit()

        # Create an owner group for this user
        group = OwnerGroup(group_name=f"{name}'s Garage")
        db.session.add(group)
        db.session.commit()

        link = OwnerGroupUser(group_id=group.id, user_id=user.id)
        db.session.add(link)
        db.session.commit()

        login_user(user)
        return redirect(url_for("main.list_vehicles"))

    return render_template("register.html", error=error)
@main_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.list_vehicles"))

    error = None

    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for("main.list_vehicles"))
        else:
            error = "Invalid email or password."

    return render_template("login.html", error=error)
@main_bp.route("/sql-demo")
@login_required
def sql_demo():
    """
    Demo page that runs raw SQL queries and shows results.
    """

    # 1) List all vehicles (raw SQL SELECT)
    sql_vehicles = text("""
        SELECT id, brand, model, year, current_odometer
        FROM vehicle
        ORDER BY brand, model
    """)
    result_vehicles = db.session.execute(sql_vehicles).fetchall()

    # 2) Service count per vehicle (raw SQL GROUP BY)
    sql_service_counts = text("""
        SELECT vehicle_id, COUNT(*) AS service_count
        FROM service_event
        GROUP BY vehicle_id
        ORDER BY service_count DESC
    """)
    result_services = db.session.execute(sql_service_counts).fetchall()
    # 3) Total service expenses per vehicle (SUM)
    sql_total_expenses = text("""
        SELECT vehicle_id, SUM(total_cost) AS total_expense
        FROM service_event
        GROUP BY vehicle_id
        ORDER BY total_expense DESC
    """)
    result_expenses = db.session.execute(sql_total_expenses).fetchall()
    # 4) Total fuel cost per vehicle (SUM)
    sql_total_fuel_cost = text("""
        SELECT vehicle_id, SUM(total_cost) AS total_fuel_cost
        FROM fuel_entry
        GROUP BY vehicle_id
        ORDER BY total_fuel_cost DESC
    """)
    result_fuel_cost = db.session.execute(sql_total_fuel_cost).fetchall()
    # 5) Approximate average mileage per vehicle (km per liter)
    sql_mileage = text("""
        SELECT
            vehicle_id,
            (MAX(odometer) - MIN(odometer)) * 1.0 / NULLIF(SUM(liters), 0) AS km_per_liter
        FROM fuel_entry
        GROUP BY vehicle_id
        HAVING COUNT(*) > 1
        ORDER BY km_per_liter DESC
    """)
    result_mileage = db.session.execute(sql_mileage).fetchall()

    return render_template(
        "sql_demo.html",
        vehicles=result_vehicles,
        service_counts=result_services,
        expenses=result_expenses,
        fuel_costs=result_fuel_cost,
        mileage=result_mileage
    )


@main_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.index"))
