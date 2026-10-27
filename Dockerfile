FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home bot
COPY --chown=bot:bot . .
USER bot
CMD ["sh", "-c", "alembic upgrade head && python -m quizbot.seed && exec python main.py"]
