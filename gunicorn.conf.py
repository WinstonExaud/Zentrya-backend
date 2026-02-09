import multiprocessing
import os

# Fly uses 8080 by default
bind = f"0.0.0.0:{os.getenv('PORT', '8080')}"
backlog = 2048

workers = int(os.getenv("WORKERS", max(2, multiprocessing.cpu_count() * 2 + 1)))
worker_class = "uvicorn.workers.UvicornWorker"
worker_connections = 1000
timeout = 120
keepalive = 5

# ✅ LOGS TO STDOUT (Fly-friendly)
accesslog = "-"          # stdout
errorlog = "-"           # stderr
loglevel = os.getenv("LOG_LEVEL", "info")

access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

proc_name = "zentrya-api"

# Performance tuning
max_requests = 1000
max_requests_jitter = 50
graceful_timeout = 30

# Security
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

# ✅ Minimal logging config (no file handlers!)
logconfig_dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "generic": {
            "format": "%(asctime)s [%(process)d] [%(levelname)s] %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "generic",
            "stream": "ext://sys.stdout",
        },
    },
    "root": {"level": "INFO", "handlers": ["console"]},
    # ✅ explicitly define gunicorn loggers
    "loggers": {
        "gunicorn.error": {"level": "INFO", "handlers": ["console"], "propagate": False},
        "gunicorn.access": {"level": "INFO", "handlers": ["console"], "propagate": False},
    },
}
