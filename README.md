# Sakura Blooms

A private, Sakura-themed cycle tracker built with Flask, SQLite, HTML, CSS, and JavaScript.

## Features

- Per-user accounts with Werkzeug password hashing, session login, logout, and CSRF-protected forms.
- Period start/end dates, flow, and notes; cycle and duration averages; estimated next period dates.
- Month navigation with logged and estimated days shown separately.
- Optional symptom and mood check-ins, plus editable and deletable private diary notes.
- Statistics, configurable cycle defaults, reminder timing, browser notifications, password changes, and account deletion.

Cycle dates are estimates, not medical advice. Browser notifications require notification permission and the app to remain open in a browser around the scheduled reminder time.

## Setup in VS Code on Windows

1. Open this folder in VS Code.
2. Open **Terminal > New Terminal** and create a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   If PowerShell prevents activation, use the virtual environment's Python directly in the next step instead.

3. Install the one required package:

   ```powershell
   python -m pip install -r requirements.txt
   ```

4. In VS Code, open the Command Palette, select **Python: Select Interpreter**, then choose `.venv`.
5. Set a persistent session secret in the terminal before starting the server. Replace the sample value with a long random string:

   ```powershell
   $env:SAKURA_SECRET_KEY = "replace-this-with-a-long-random-secret"
   ```

6. Run the application:

   ```powershell
   python app.py
   ```

7. Open the local URL printed by Flask (normally `http://127.0.0.1:5000`) and create an account.

## Database

SQLite initializes automatically when `app.py` starts and creates `database.db` in this folder. Use `SAKURA_DATABASE` to select another database path. Each user's periods, daily logs, and notes are linked to that account and removed when the account is deleted.

Do not use Flask's debug server or its generated development secret for a public deployment. Set a persistent, private `SAKURA_SECRET_KEY`, use HTTPS, and deploy behind a production WSGI server before exposing the app to the internet.

## Estimated Dates and Browser Reminders

- Cycle estimates advance from the most recent logged start date using the average cycle length (or your saved typical length until enough logs exist). The calendar projects estimated days into future months.
- Opt-in browser notifications are scheduled for 9 a.m. on your selected lead day, once per estimated period. The app and browser must remain open around that time; a closed-browser push reminder needs a separate push service.