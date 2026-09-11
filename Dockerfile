FROM python:3.12-slim

WORKDIR /app

# fonts-dejavu-core -- real TTF files (regular/bold/oblique/bold-oblique) needed to render
# custom labels (label-printer feature: arbitrary font size/bold/italic, rasterized to ZPL).
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV DJANGO_DEBUG=false
RUN python manage.py collectstatic --noinput

EXPOSE 3200

CMD ["sh", "-c", "python manage.py migrate && gunicorn config.wsgi:application --bind 0.0.0.0:3200"]
