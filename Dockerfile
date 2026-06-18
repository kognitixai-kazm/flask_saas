# ============================================
# Stage 1: Builder — تثبيت الحزم وتجميعها
# ============================================
FROM python:3.11-slim AS builder

WORKDIR /build

# تثبيت أدوات البناء اللازمة لـ psycopg2 و Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    libjpeg62-turbo-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ============================================
# Stage 2: Runtime — الصورة النهائية الخفيفة
# ============================================
FROM python:3.11-slim AS runtime

# تثبيت مكتبات وقت التشغيل فقط
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libjpeg62-turbo \
    curl \
    && rm -rf /var/lib/apt/lists/*

# نسخ الحزم المثبتة من الـ builder
COPY --from=builder /install /usr/local

# إنشاء مستخدم غير root للأمان
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

# نسخ كود التطبيق
COPY . .

# إنشاء المجلدات اللازمة
RUN mkdir -p instance/flask_session logs static/uploads \
    && chown -R appuser:appuser /app

# التبديل للمستخدم غير root
USER appuser

# منفذ التطبيق
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# تشغيل Gunicorn
CMD ["gunicorn", "wsgi:app", \
     "--workers", "3", \
     "--timeout", "120", \
     "--bind", "0.0.0.0:8000", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
