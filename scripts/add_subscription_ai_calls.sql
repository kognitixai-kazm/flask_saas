-- عمود عدّاد طلبات الـ AI شهرياً (مرة واحدة على قواعد قديمة).
ALTER TABLE subscriptions ADD COLUMN ai_calls_this_month INTEGER NOT NULL DEFAULT 0;
