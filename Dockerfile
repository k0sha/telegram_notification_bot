FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY telegram_notification_bot.py /app/telegram_notification_bot.py

CMD ["python", "-u", "telegram_notification_bot.py"]