"""Modal deployment of the Daily News Brief.

Schedules the brief to run at 23:00 UTC daily (= 09:00 AEST, no DST in Brisbane).
Modal Cron fires within seconds of the scheduled minute — unlike GitHub Actions'
schedule cron which can be delayed 6-10 hours on low-traffic public repos.

Self-fix layers in this file:
  1. retries=3 with exponential backoff — Modal will auto-retry a crashed run
     up to 3 times before giving up. Handles transient platform / SMTP errors.
  2. Persistent Volume mounted at /app/archive — the script's "fall back to
     yesterday's content" path needs a place to read prior archives from.
  3. timeout=900 (15 min) — well above the observed ~4 min runtime, but stops
     a runaway from burning compute forever.

Deploy:
    pip install modal
    modal token new        # one-time browser auth
    modal secret create daily-brief --from-dotenv .env   # one-time secrets
    modal deploy modal_app.py

After deploy, the schedule is live and runs forever on Modal's infrastructure.
Trigger a one-off test run with:
    modal run modal_app.py::daily_brief
"""
from __future__ import annotations

import modal

app = modal.App("daily-news-brief")

# Image: Python 3.11 + the same deps the script needs.
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "google-genai>=1.0.0",
        "requests>=2.31.0",
        "pytz>=2024.1",
    )
    # Bundle the project source into the image at /app so it's importable.
    .add_local_dir(".", remote_path="/app", ignore=[
        ".git/*",
        ".github/*",
        ".claude/*",
        "archive/*",
        "logs/*",
        "*.html",
        "__pycache__/*",
    ])
)

# Persistent storage for the archive directory — survives between runs so the
# "fall back to most recent archive" self-fix path in daily_brief.py works.
archive_volume = modal.Volume.from_name(
    "daily-brief-archive", create_if_missing=True
)


@app.function(
    image=image,
    schedule=modal.Cron("0 23 * * *"),  # 23:00 UTC = 09:00 AEST
    retries=modal.Retries(
        max_retries=3,
        backoff_coefficient=2.0,
        initial_delay=60.0,
    ),
    timeout=900,
    secrets=[modal.Secret.from_name("daily-brief")],
    volumes={"/app/archive": archive_volume},
)
def daily_brief() -> int:
    import os
    import sys

    os.chdir("/app")
    sys.path.insert(0, "/app")

    # Import the script's main() and run it. Any exception bubbles up to
    # Modal, which will retry per the @app.function decorator config above.
    from daily_brief import main as run_brief
    rc = run_brief()

    # Persist any new files written to /app/archive back to the Volume.
    archive_volume.commit()
    return rc


@app.local_entrypoint()
def main() -> None:
    """Allow `modal run modal_app.py` to trigger a one-off test execution."""
    rc = daily_brief.remote()
    print(f"daily_brief returned {rc}")
