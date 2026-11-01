# One worker process with threads: the app keeps per-person background jobs (Gmail import, refreshes) in memory.
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
workers = 1
threads = 8
timeout = 120
accesslog = "-"


def post_worker_init(worker):
    import wsgi
    wsgi._background()
