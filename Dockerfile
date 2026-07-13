FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt docs/admin_panel/requirements_admin.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt -r requirements_admin.txt

COPY . .

CMD ["python", "bot.py"]
