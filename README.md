# 🤖 منصة SaaS لإدارة خدمة العملاء — Flask

منصة سحابية متعددة المستأجرين (Multi-tenant) لإدارة خدمة العملاء بالذكاء الاصطناعي.

---

## 📋 المتطلبات

| البرنامج | الإصدار |
|----------|---------|
| Python | 3.11+ |
| PostgreSQL | 14+ |
| Redis | 7+ (اختياري للتطوير) |

---

## 🚀 خطوات التثبيت والتشغيل

### 1. استنساخ المشروع
```bash
cd ~/projects
# ضع مجلد flask_saas هنا
cd flask_saas
```

### 2. إنشاء بيئة افتراضية
```bash
python3 -m venv venv
source venv/bin/activate        # Linux/Mac
# أو: venv\Scripts\activate     # Windows
```

### 3. تثبيت الحزم
```bash
pip install -r requirements.txt
```

### 4. إنشاء قاعدة البيانات (PostgreSQL)
```sql
-- في psql:
CREATE USER saas_user WITH PASSWORD 'saas_password';
CREATE DATABASE saas_db OWNER saas_user;
GRANT ALL PRIVILEGES ON DATABASE saas_db TO saas_user;
```

### 5. إعداد ملف البيئة
```bash
cp .env.example .env
# عدّل القيم في .env حسب بيئتك
```

### 6. تهيئة قاعدة البيانات + إنشاء Super Admin
```bash
flask init-db
```
هذا الأمر:
- ✅ ينشئ كل الجداول
- ✅ ينشئ Super Admin من `.env`
- ✅ يضيف الأنشطة الافتراضية (فندق + مطعم)
- ✅ يضيف الباقات الافتراضية (تجريبي + أساسي + احترافي + مؤسسي)

### 7. تشغيل الخادم
```bash
python run.py
# أو: flask run
```
يعمل على: http://localhost:5000

---

## 🗺️ خريطة الروابط (URL Map)

| العالم | المسار | الوصف |
|--------|--------|-------|
| 🌐 عام | `/` | الصفحة الرئيسية (Landing) |
| 🌐 عام | `/features`, `/pricing`, `/faq` | صفحات تعريفية |
| 📝 تسجيل | `/register` → `/register/activity` → `/register/plan` | تسجيل 3 خطوات |
| 🏢 عميل | `/app/setup?token=XYZ` | إعداد الحساب (username/password) |
| 🏢 عميل | `/app/login` | تسجيل دخول العميل |
| 🏢 عميل | `/app/dashboard` | لوحة التحكم |
| 🏢 عميل | `/app/profile`, `/app/settings`, `/app/billing` | إعدادات |
| 👑 أدمن | `/sa/login` | دخول السوبر أدمن (مخفي) |
| 👑 أدمن | `/sa/` | لوحة الإدارة |
| 👑 أدمن | `/sa/tenants`, `/sa/plans`, `/sa/activities` | إدارة |
| 💬 شات | `/c/<slug>` | واجهة الشات للزوار |
| 🔌 API | `/api/v1/health` | Health check |
| 🔌 API | `/api/v1/webhooks/whatsapp` | WhatsApp webhook |

---

## 🏗️ هيكل المشروع

```
flask_saas/
├── run.py                          # نقطة التشغيل
├── requirements.txt
├── .env.example
├── .gitignore
│
├── app/
│   ├── __init__.py                 # Factory pattern (create_app)
│   ├── config.py                   # إعدادات + 3 جلسات منفصلة
│   ├── extensions.py               # db, csrf, limiter, session
│   │
│   ├── models/                     # 8 جداول
│   │   ├── super_admin.py
│   │   ├── activity.py
│   │   ├── plan.py
│   │   ├── tenant.py
│   │   ├── tenant_user.py
│   │   ├── subscription.py
│   │   ├── conversation.py + Message
│   │   └── audit_log.py
│   │
│   ├── blueprints/                 # 6 blueprints
│   │   ├── public.py               # / (Landing)
│   │   ├── registration.py         # /register (3 خطوات)
│   │   ├── super_admin.py          # /sa/* (أدمن)
│   │   ├── tenant.py               # /app/* (عميل)
│   │   ├── chat.py                 # /c/* (شات)
│   │   └── api.py                  # /api/v1/*
│   │
│   ├── services/                   # طبقة الأعمال
│   │   ├── auth_service.py
│   │   ├── tenant_service.py
│   │   ├── plan_service.py
│   │   ├── activity_service.py
│   │   ├── chat_service.py         # AI (OpenAI + Anthropic)
│   │   └── audit_service.py
│   │
│   ├── decorators/                 # فصل العوالم
│   │   ├── super_admin_required.py # /sa فقط
│   │   ├── tenant_required.py      # /app فقط
│   │   ├── plan_feature_required.py
│   │   └── chat_visitor_session.py # /c فقط
│   │
│   ├── utils/
│   │   ├── passwords.py            # argon2
│   │   ├── slug.py                 # nanoid
│   │   └── tokens.py               # Setup token (24h)
│   │
│   └── activities/                 # Plugin لكل نشاط
│       ├── hotel/
│       │   ├── manifest.json
│       │   └── handler.py
│       └── restaurant/
│           ├── manifest.json
│           └── handler.py
│
├── templates/
│   ├── base.html
│   ├── public/home.html + stubs
│   ├── registration/step1-3 + success
│   ├── tenant/setup, login, dashboard + stubs
│   ├── super_admin/login, dashboard + stubs
│   ├── chat/interface.html
│   └── errors/404, 403, 500, 429
│
├── static/                         # CSS, JS, images
├── migrations/                     # Alembic
├── instance/                       # Flask instance
└── logs/                           # Application logs
```

---

## 🔐 نظام الجلسات (3 عوالم منفصلة)

| العالم | Cookie | Path Scope | المدة |
|--------|--------|------------|-------|
| Super Admin | `sa_session` | `/sa/*` | ساعتان |
| Tenant User | `tenant_session` | `/app/*` | 7 أيام |
| Chat Visitor | `chat_visitor` | `/c/*` | 30 يوم |

**القاعدة الذهبية**: لا يوجد cookie واحد يعمل في عالمين.

---

## 🧪 الاختبار السريع

```bash
# 1. شغّل الخادم
python run.py

# 2. ادخل الصفحة الرئيسية
open http://localhost:5000

# 3. سجّل كعميل جديد
# اتبع الخطوات الـ 3 → ستحصل على رابط setup

# 4. أكمل الإعداد (username/password)
# → ستدخل لوحة التحكم

# 5. شارك رابط الشات
# http://localhost:5000/c/<your-slug>

# 6. ادخل لوحة الأدمن
open http://localhost:5000/sa/login
# username: superadmin (من .env)
```

---

## 📅 المراحل القادمة

- [ ] **المرحلة 1**: تفاصيل Super Admin dashboard
- [ ] **المرحلة 2**: تفاصيل Tenant dashboard (profile, settings, billing)
- [ ] **المرحلة 3**: نظام Activities متقدم (hotel rooms, restaurant menu)
- [ ] **المرحلة 4**: WhatsApp Integration
- [ ] **المرحلة 5**: Email verification + 2FA
- [ ] **المرحلة 6**: Payment gateway (Moyasar)
- [ ] **المرحلة 7**: i18n (عربي + إنجليزي)
