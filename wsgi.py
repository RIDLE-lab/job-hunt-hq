"""Job Hunt HQ as a website (gunicorn wsgi:app). Your PC keeps using run.bat – this file is only for hosting."""
import os
import threading

os.environ.setdefault("JOBHUNT_HOSTED", "1")

import app as _app  # noqa: E402

app = _app.app


def _background():
    """Refresh everyone's jobs every few hours (one copy of this runs – see gunicorn.conf.py)."""
    try:
        threading.Thread(target=_app.auto_refresh_loop, daemon=True).start()
    except Exception:
        pass
