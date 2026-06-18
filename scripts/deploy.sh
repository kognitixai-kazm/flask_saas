#!/bin/bash
# ============================================
# deploy.sh — سكريبت التحديث والنشر على Hetzner
# ============================================

set -e

echo "🚀 بدء عملية النشر (Deployment)..."

# 1. سحب أحدث كود (إذا كنت تستخدم Git على السيرفر)
# git pull origin main

# 2. بناء الصورة وبدء الحاويات في الخلفية
echo "📦 بناء وتشغيل الحاويات..."
docker compose -f docker-compose.production.yml up -d --build

# 3. تشغيل الـ Migrations لقاعدة البيانات
echo "🗄️ تحديث قاعدة البيانات (Migrations)..."
docker compose -f docker-compose.production.yml exec -T app flask db upgrade

# 4. تنظيف الصور القديمة غير المستخدمة (اختياري لتوفير المساحة)
echo "🧹 تنظيف الصور القديمة..."
docker image prune -f

echo "✅ تم النشر بنجاح!"
