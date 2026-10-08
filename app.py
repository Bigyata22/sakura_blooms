import calendar
import json
import os
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SAKURA_SECRET_KEY") or secrets.token_hex(32)
app.config["DATABASE"] = os.environ.get(
	"SAKURA_DATABASE", os.path.join(app.root_path, "database.db")
)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

REMINDER_OPTIONS = (1, 2, 3, 5)
SYMPTOM_OPTIONS = ("Cramps", "Headache", "Fatigue", "Bloating", "Backache", "Acne", "Nausea", "Other")
MOOD_OPTIONS = ("Happy", "Calm", "Okay", "Tired", "Sad", "Stressed", "Irritated")
DISCLAIMER = "Sakura Blooms provides estimated cycle dates for personal tracking. Predictions can vary and are not medical advice."


@app.template_filter("prettydate")
def prettydate(value):
	return date.fromisoformat(value).strftime("%b %d").replace(" 0", " ")


def get_db():
	if "db" not in g:
		g.db = sqlite3.connect(app.config["DATABASE"])
		g.db.row_factory = sqlite3.Row
		g.db.execute("PRAGMA foreign_keys = ON")
	return g.db


@app.teardown_appcontext
def close_db(_error=None):
	db = g.pop("db", None)
	if db is not None:
		db.close()


def init_db():
	db = get_db()
	db.executescript("""
		CREATE TABLE IF NOT EXISTS users (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			name TEXT NOT NULL,
			email TEXT NOT NULL UNIQUE,
			password_hash TEXT NOT NULL,
			cycle_length INTEGER NOT NULL DEFAULT 28 CHECK(cycle_length BETWEEN 15 AND 60),
			period_length INTEGER NOT NULL DEFAULT 5 CHECK(period_length BETWEEN 1 AND 15),
			reminder_days INTEGER NOT NULL DEFAULT 3 CHECK(reminder_days IN (1, 2, 3, 5)),
			notifications INTEGER NOT NULL DEFAULT 0
		);
		CREATE TABLE IF NOT EXISTS periods (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
			start_date TEXT NOT NULL,
			end_date TEXT NOT NULL,
			flow TEXT NOT NULL DEFAULT 'Medium',
			notes TEXT NOT NULL DEFAULT '',
			created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
			UNIQUE(user_id, start_date)
		);
		CREATE TABLE IF NOT EXISTS daily_logs (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
			log_date TEXT NOT NULL,
			symptoms TEXT NOT NULL DEFAULT '[]',
			mood TEXT NOT NULL DEFAULT '',
			UNIQUE(user_id, log_date)
		);
		CREATE TABLE IF NOT EXISTS notes (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
			title TEXT NOT NULL,
			body TEXT NOT NULL,
			created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
			updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
		);
	""")
	db.commit()


with app.app_context():
	init_db()


@app.before_request
def protect_posts():
	if request.method == "POST":
		submitted = request.form.get("csrf_token", "")
		expected = session.get("csrf_token", "")
		if not expected or not secrets.compare_digest(submitted, expected):
			abort(400, description="Your form expired. Please go back and try again.")


@app.context_processor
def inject_globals():
	if "csrf_token" not in session:
		session["csrf_token"] = secrets.token_urlsafe(32)
	reminder = None
	if session.get("user_id"):
		user = current_user()
		if user:
			summary = cycle_summary(user)
			if summary["estimated_next"]:
				reminder_date = summary["estimated_next"] - timedelta(days=user["reminder_days"])
				reminder = {
					"enabled": bool(user["notifications"]),
					"period_date": summary["estimated_next"].isoformat(),
					"reminder_date": reminder_date.isoformat(),
					"days_before": user["reminder_days"],
				}
	return {
		"csrf_token": session["csrf_token"],
		"disclaimer": DISCLAIMER,
		"today": date.today(),
		"cycle_reminder": reminder,
	}


def login_required(view):
	@wraps(view)
	def wrapped(*args, **kwargs):
		if "user_id" not in session:
			return redirect(url_for("login", next=request.path))
		return view(*args, **kwargs)
	return wrapped


def current_user():
	return get_db().execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()


def get_periods(user_id):
	return get_db().execute(
		"SELECT * FROM periods WHERE user_id = ? ORDER BY start_date DESC", (user_id,)
	).fetchall()


def cycle_summary(user, periods=None):
	periods = periods if periods is not None else get_periods(user["id"])
	starts = sorted(date.fromisoformat(row["start_date"]) for row in periods)
	durations = [(date.fromisoformat(row["end_date"]) - date.fromisoformat(row["start_date"])).days + 1 for row in periods]
	differences = [(right - left).days for left, right in zip(starts, starts[1:])]
	cycle_length = round(sum(differences) / len(differences)) if differences else user["cycle_length"]
	cycle_length = min(60, max(15, cycle_length))
	period_length = round(sum(durations) / len(durations)) if durations else user["period_length"]
	last_start = starts[-1] if starts else None
	estimated_next = last_start + timedelta(days=cycle_length) if last_start else None
	while estimated_next and estimated_next < date.today():
		estimated_next += timedelta(days=cycle_length)
	days_remaining = (estimated_next - date.today()).days if estimated_next else None
	return {
		"cycle_length": cycle_length,
		"period_length": period_length,
		"last_start": last_start,
		"estimated_next": estimated_next,
		"days_remaining": days_remaining,
		"cycle_day": ((date.today() - last_start).days % cycle_length + 1) if last_start else None,
		"cycle_gaps": differences,
		"durations": durations,
		"starts": starts,
	}


@app.route("/")
def index():
	if "user_id" not in session:
		return redirect(url_for("login"))
	user = current_user()
	summary = cycle_summary(user)
	reminder_due = summary["days_remaining"] == user["reminder_days"]
	return render_template("index.html", user=user, summary=summary, reminder_due=reminder_due)


@app.route("/register", methods=["GET", "POST"])
def register():
	if request.method == "POST":
		name = request.form.get("name", "").strip()
		email = request.form.get("email", "").strip().lower()
		password = request.form.get("password", "")
		if not name or len(name) > 80 or "@" not in email:
			flash("Please enter your name and a valid email address.", "error")
		elif len(password) < 8:
			flash("Choose a password with at least 8 characters.", "error")
		else:
			try:
				cursor = get_db().execute(
					"INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
					(name, email, generate_password_hash(password)),
				)
				get_db().commit()
				session.clear()
				session["user_id"] = cursor.lastrowid
				session["csrf_token"] = secrets.token_urlsafe(32)
				flash("Your little diary is ready. Welcome to Sakura Blooms!", "success")
				return redirect(url_for("index"))
			except sqlite3.IntegrityError:
				flash("An account with that email already exists.", "error")
	return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
	if request.method == "POST":
		email = request.form.get("email", "").strip().lower()
		user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
		if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
			session.clear()
			session["user_id"] = user["id"]
			session["csrf_token"] = secrets.token_urlsafe(32)
			flash("Welcome back, " + user["name"] + ".", "success")
			destination = request.args.get("next", "")
			return redirect(destination if destination.startswith("/") and not destination.startswith("//") else url_for("index"))
		flash("That email and password combination was not recognised.", "error")
	return render_template("login.html")


@app.post("/logout")
def logout():
	session.clear()
	flash("You have been logged out safely.", "success")
	return redirect(url_for("login"))


@app.route("/log-period", methods=["GET", "POST"])
@login_required
def log_period():
	if request.method == "POST":
		start_text = request.form.get("start_date", "")
		end_text = request.form.get("end_date", "")
		flow = request.form.get("flow", "Medium")
		notes = request.form.get("notes", "").strip()[:2000]
		try:
			start, end = date.fromisoformat(start_text), date.fromisoformat(end_text)
			if end < start or (end - start).days > 14 or start > date.today() or flow not in ("Light", "Medium", "Heavy"):
				raise ValueError
		except ValueError:
			flash("Please check the dates and choose a valid flow.", "error")
		else:
			db = get_db()
			try:
				db.execute(
					"INSERT INTO periods (user_id, start_date, end_date, flow, notes) VALUES (?, ?, ?, ?, ?)",
					(session["user_id"], start.isoformat(), end.isoformat(), flow, notes),
				)
				db.commit()
				flash("Period saved to your diary.", "success")
				return redirect(url_for("calendar_view"))
			except sqlite3.IntegrityError:
				flash("A period is already saved with that start date. Edit or remove the earlier entry first.", "error")
	return render_template("log_period.html", user=current_user())


@app.post("/period/<int:period_id>/delete")
@login_required
def delete_period(period_id):
	get_db().execute("DELETE FROM periods WHERE id = ? AND user_id = ?", (period_id, session["user_id"]))
	get_db().commit()
	flash("Period entry removed.", "success")
	return redirect(url_for("statistics"))


@app.route("/calendar")
@login_required
def calendar_view():
	try:
		year, month = (int(part) for part in request.args.get("month", date.today().strftime("%Y-%m")).split("-"))
		if month not in range(1, 13) or year not in range(1900, 2201):
			raise ValueError
	except (ValueError, TypeError):
		year, month = date.today().year, date.today().month
	user = current_user()
	periods = get_periods(user["id"])
	summary = cycle_summary(user, periods)
	logged_days = set()
	for period in periods:
		cursor = date.fromisoformat(period["start_date"])
		end = date.fromisoformat(period["end_date"])
		while cursor <= end:
			logged_days.add(cursor)
			cursor += timedelta(days=1)
	estimated_days = set()
	if summary["estimated_next"]:
		month_start = date(year, month, 1)
		month_end = date(year, month, calendar.monthrange(year, month)[1])
		estimated_start = summary["estimated_next"]
		while estimated_start + timedelta(days=summary["period_length"] - 1) < month_start:
			estimated_start += timedelta(days=summary["cycle_length"])
		while estimated_start <= month_end:
			for offset in range(summary["period_length"]):
				estimated_days.add(estimated_start + timedelta(days=offset))
			estimated_start += timedelta(days=summary["cycle_length"])
	weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(year, month)
	month_cells = []
	for week in weeks:
		row = []
		for day in week:
			row.append({
				"date": day,
				"in_month": day.month == month,
				"today": day == date.today(),
				"logged": day in logged_days,
				"estimated": day in estimated_days and day not in logged_days,
			})
		month_cells.append(row)
	previous_month = date(year, month, 1) - timedelta(days=1)
	next_month = date(year + (month == 12), month % 12 + 1, 1)
	return render_template(
		"calendar.html", user=user, summary=summary, month_cells=month_cells,
		month_label=date(year, month, 1).strftime("%B %Y"),
		previous_month=previous_month.strftime("%Y-%m"), next_month=next_month.strftime("%Y-%m"),
		recent_periods=periods[:5],
	)


@app.route("/symptoms", methods=["GET", "POST"])
@login_required
def symptoms():
	if request.method == "POST":
		log_date = request.form.get("log_date", "")
		selected = request.form.getlist("symptoms")
		try:
			parsed_date = date.fromisoformat(log_date)
			if parsed_date > date.today() or any(item not in SYMPTOM_OPTIONS for item in selected):
				raise ValueError
		except ValueError:
			flash("Choose a valid date and symptoms.", "error")
		else:
			db = get_db()
			db.execute("""INSERT INTO daily_logs (user_id, log_date, symptoms)
				VALUES (?, ?, ?) ON CONFLICT(user_id, log_date) DO UPDATE SET symptoms = excluded.symptoms""",
				(session["user_id"], log_date, json.dumps(selected)))
			db.commit()
			flash("Symptoms saved for " + parsed_date.strftime("%B %d").replace(" 0", " ") + ".", "success")
			return redirect(url_for("symptoms"))
	logs = get_db().execute("SELECT * FROM daily_logs WHERE user_id = ? ORDER BY log_date DESC", (session["user_id"],)).fetchall()
	history = [{**dict(row), "symptoms_list": json.loads(row["symptoms"])} for row in logs if row["symptoms"] != "[]"]
	return render_template("symptoms.html", user=current_user(), options=SYMPTOM_OPTIONS, history=history)


@app.route("/mood", methods=["GET", "POST"])
@login_required
def mood():
	if request.method == "POST":
		log_date, selected_mood = request.form.get("log_date", ""), request.form.get("mood", "")
		try:
			parsed_date = date.fromisoformat(log_date)
			if parsed_date > date.today() or selected_mood not in MOOD_OPTIONS:
				raise ValueError
		except ValueError:
			flash("Choose a valid date and mood.", "error")
		else:
			db = get_db()
			db.execute("""INSERT INTO daily_logs (user_id, log_date, mood)
				VALUES (?, ?, ?) ON CONFLICT(user_id, log_date) DO UPDATE SET mood = excluded.mood""",
				(session["user_id"], log_date, selected_mood))
			db.commit()
			flash("Mood saved for " + parsed_date.strftime("%B %d") + ".", "success")
			return redirect(url_for("mood"))
	history = get_db().execute("SELECT log_date, mood FROM daily_logs WHERE user_id = ? AND mood != '' ORDER BY log_date DESC", (session["user_id"],)).fetchall()
	return render_template("mood.html", user=current_user(), options=MOOD_OPTIONS, history=history)


@app.route("/notes", methods=["GET", "POST"])
@login_required
def notes():
	db = get_db()
	if request.method == "POST":
		title, body = request.form.get("title", "").strip(), request.form.get("body", "").strip()
		note_id = request.form.get("note_id", "")
		if not title or not body or len(title) > 120 or len(body) > 5000:
			flash("Add a title and note (up to 5,000 characters).", "error")
		elif note_id:
			db.execute("UPDATE notes SET title = ?, body = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?", (title, body, note_id, session["user_id"]))
			db.commit()
			flash("Your note has been updated.", "success")
			return redirect(url_for("notes"))
		else:
			db.execute("INSERT INTO notes (user_id, title, body) VALUES (?, ?, ?)", (session["user_id"], title, body))
			db.commit()
			flash("A little thought tucked safely away.", "success")
			return redirect(url_for("notes"))
	edit_id = request.args.get("edit", type=int)
	editing = db.execute("SELECT * FROM notes WHERE id = ? AND user_id = ?", (edit_id, session["user_id"])).fetchone() if edit_id else None
	entries = db.execute("SELECT * FROM notes WHERE user_id = ? ORDER BY updated_at DESC", (session["user_id"],)).fetchall()
	return render_template("notes.html", user=current_user(), notes=entries, editing=editing)


@app.post("/notes/<int:note_id>/delete")
@login_required
def delete_note(note_id):
	get_db().execute("DELETE FROM notes WHERE id = ? AND user_id = ?", (note_id, session["user_id"]))
	get_db().commit()
	flash("Note deleted.", "success")
	return redirect(url_for("notes"))


@app.route("/statistics")
@login_required
def statistics():
	user = current_user()
	periods = get_periods(user["id"])
	summary = cycle_summary(user, periods)
	cycle_values = summary["cycle_gaps"]
	duration_values = summary["durations"]
	logs = get_db().execute("SELECT log_date, mood, symptoms FROM daily_logs WHERE user_id = ? ORDER BY log_date DESC LIMIT 8", (user["id"],)).fetchall()
	history = [{**dict(row), "symptoms_list": json.loads(row["symptoms"])} for row in logs]
	return render_template("statistics.html", user=user, periods=periods, summary=summary,
		shortest_cycle=min(cycle_values) if cycle_values else None,
		longest_cycle=max(cycle_values) if cycle_values else None, history=history)


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
	db = get_db()
	user = current_user()
	if request.method == "POST":
		action = request.form.get("action", "preferences")
		if action == "preferences":
			try:
				cycle_length = int(request.form.get("cycle_length", "28"))
				period_length = int(request.form.get("period_length", "5"))
				reminder_days = int(request.form.get("reminder_days", "3"))
				if not 15 <= cycle_length <= 60 or not 1 <= period_length <= 15 or reminder_days not in REMINDER_OPTIONS:
					raise ValueError
			except ValueError:
				flash("Check the cycle, period, and reminder values.", "error")
			else:
				db.execute("UPDATE users SET cycle_length = ?, period_length = ?, reminder_days = ?, notifications = ? WHERE id = ?",
					(cycle_length, period_length, reminder_days, int(request.form.get("notifications") == "on"), user["id"]))
				db.commit()
				flash("Your preferences have been saved.", "success")
				return redirect(url_for("settings"))
		elif action == "password":
			current_password = request.form.get("current_password", "")
			new_password = request.form.get("new_password", "")
			if not check_password_hash(user["password_hash"], current_password):
				flash("Your current password did not match.", "error")
			elif len(new_password) < 8:
				flash("Your new password needs at least 8 characters.", "error")
			else:
				db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(new_password), user["id"]))
				db.commit()
				flash("Password updated.", "success")
				return redirect(url_for("settings"))
		elif action == "delete_account":
			if check_password_hash(user["password_hash"], request.form.get("password", "")):
				db.execute("DELETE FROM users WHERE id = ?", (user["id"],))
				db.commit()
				session.clear()
				flash("Your account and personal data have been deleted.", "success")
				return redirect(url_for("register"))
			flash("Password did not match. Your data is unchanged.", "error")
	return render_template("settings.html", user=current_user(), reminder_options=REMINDER_OPTIONS)


if __name__ == "__main__":
	app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
