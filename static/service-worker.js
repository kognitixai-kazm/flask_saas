/**
 * Service Worker — KOGNITIX Push Notifications
 * يستقبل الإشعارات في الخلفية (حتى لو المتصفح مغلق) ويشغّل صوت التنبيه.
 */

// عند تثبيت الـ Service Worker
self.addEventListener('install', (event) => {
    self.skipWaiting();
});

// عند التفعيل
self.addEventListener('activate', (event) => {
    event.waitUntil(self.clients.claim());
});

// استقبال الإشعار من السيرفر (Push Event)
self.addEventListener('push', (event) => {
    let data = {
        title: 'إشعار جديد',
        body: '',
        icon: '🔔',
        url: '/',
        category: 'system',
    };

    if (event.data) {
        try {
            data = { ...data, ...event.data.json() };
        } catch (e) {
            data.body = event.data.text();
        }
    }

    // أيقونات حسب النوع
    const categoryIcons = {
        booking: '/static/img/logo.png',
        inquiry: '/static/img/logo.png',
        complaint: '/static/img/logo.png',
        new_tenant: '/static/img/logo.png',
        contract: '/static/img/logo.png',
        system: '/static/img/logo.png',
    };

    const options = {
        body: data.body,
        icon: categoryIcons[data.category] || '/static/img/logo.png',
        badge: '/static/img/logo.png',
        vibrate: [200, 100, 200],
        dir: 'rtl',
        lang: 'ar',
        tag: `kognitix-${data.category}-${data.notif_id || Date.now()}`,
        renotify: true,
        requireInteraction: true,
        data: {
            url: data.url,
            notif_id: data.notif_id,
        },
    };

    event.waitUntil(
        self.registration.showNotification(data.title, options)
    );
});

// عند النقر على الإشعار
self.addEventListener('notificationclick', (event) => {
    event.notification.close();

    const urlToOpen = event.notification.data?.url || '/';

    event.waitUntil(
        self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
            // إذا كان هناك تبويب مفتوح للموقع، نستخدمه
            for (const client of clientList) {
                if (client.url.includes(self.location.origin) && 'focus' in client) {
                    client.focus();
                    client.navigate(urlToOpen);
                    return;
                }
            }
            // إذا لا يوجد تبويب مفتوح، نفتح واحداً جديداً
            return self.clients.openWindow(urlToOpen);
        })
    );
});
