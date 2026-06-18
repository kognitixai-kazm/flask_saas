web: gunicorn wsgi:app --workers 3 --timeout 120 --bind 0.0.0.0:$PORT --access-logfile - --error-logfile -
release: flask db upgrade && flask patch-schema
