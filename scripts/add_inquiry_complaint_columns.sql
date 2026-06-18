-- تشغيل مرة واحدة على قواعد بيانات قديمة قبل إضافة أعمدة الشكوى في نموذج Inquiry.
-- SQLite / PostgreSQL (عدّل حسب محركك إن لزم).

ALTER TABLE inquiries ADD COLUMN inquiry_kind VARCHAR(20) NOT NULL DEFAULT 'general';
ALTER TABLE inquiries ADD COLUMN complaint_category VARCHAR(40) NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS ix_inquiries_inquiry_kind ON inquiries (inquiry_kind);
CREATE INDEX IF NOT EXISTS ix_inquiries_complaint_category ON inquiries (complaint_category);
