FROM python:3.11-slim AS base

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


FROM base AS development

COPY . .

CMD ["python", "-m", "app.main"]


FROM base AS production

COPY . .

RUN adduser --disabled-password --no-create-home appuser
USER appuser

EXPOSE 4000

CMD ["python", "-m", "app.main"]
