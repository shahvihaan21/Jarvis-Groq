web: gunicorn --chdir backend --workers 2 --threads 4 --timeout 120 ai.wsgi:application
release: python backend/manage.py collectstatic --noinput
