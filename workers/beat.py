from celery.schedules import crontab

from workers.celery_app import celery_app

celery_app.conf.beat_schedule = {
    "check-payment-expiry": {
        "task": "notifications.payment_expired",
        "schedule": crontab(minute="*/15"),
        "args": []
    },
    "check-delivery-auto-accept": {
        "task": "notifications.delivery_auto_accept",
        "schedule": crontab(minute="*/30"),
        "args": []
    },
    "trial-expiry-reminders": {
        "task": "notifications.trial_expiry_reminder",
        "schedule": crontab(hour=9, minute=0),
        "args": []
    }
}