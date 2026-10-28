# Gunicorn settings for Render (used automatically by the start command "gunicorn app:app")
import os

bind = f"0.0.0.0:{os.getenv('PORT', '10000')}"
workers = 1          # one process: background jobs and per-customer order stay in one place
threads = 8          # handles many webhooks at the same time
timeout = 120
graceful_timeout = 30
accesslog = '-'
errorlog = '-'
loglevel = 'info'
