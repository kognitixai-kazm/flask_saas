"""
app/services/cloudinary_service.py — خدمة التخزين السحابي.

يستخدم Cloudinary لرفع:
- صور الوحدات الفندقية
- صور أصناف المنيو
- صور الهويات (للعقود)
- صور الشعارات
- المستندات (PDF عقود)

المفاتيح من /sa/system/ (تبويب Cloudinary):
- CLOUDINARY_CLOUD_NAME
- CLOUDINARY_API_KEY
- CLOUDINARY_API_SECRET
"""
import io
import time
import hashlib
import requests
from typing import Optional, Dict, BinaryIO
from flask import current_app

from app.models.system_settings import SystemSetting


class CloudinaryService:
    """خدمة Cloudinary للتخزين السحابي."""

    UPLOAD_URL = 'https://api.cloudinary.com/v1_1/{cloud_name}/{resource_type}/upload'
    DELETE_URL = 'https://api.cloudinary.com/v1_1/{cloud_name}/{resource_type}/destroy'

    # ====== حدود رفع الصور (الأمان) ======
    MAX_IMAGE_BYTES = 8 * 1024 * 1024   # 8 ميجا
    MAX_FILE_BYTES = 16 * 1024 * 1024   # 16 ميجا
    ALLOWED_IMAGE_MIMES = {
        'image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'image/gif',
    }
    ALLOWED_IMAGE_MAGIC = (
        b'\xff\xd8\xff',           # JPEG
        b'\x89PNG\r\n\x1a\n',      # PNG
        b'GIF87a', b'GIF89a',      # GIF
        b'RIFF',                   # WebP (RIFF....WEBP)
    )

    @staticmethod
    def _validate_image_file(file: BinaryIO) -> Optional[str]:
        """يفحص نوع الصورة (magic bytes) وحجمها. يرجع رسالة خطأ أو None."""
        try:
            content_type = (getattr(file, 'mimetype', '') or '').lower()
            if content_type and content_type not in CloudinaryService.ALLOWED_IMAGE_MIMES:
                return f'نوع الملف غير مسموح: {content_type}'

            pos = file.tell() if hasattr(file, 'tell') else None
            head = file.read(16) or b''
            if hasattr(file, 'seek') and pos is not None:
                file.seek(pos)

            if not any(head.startswith(sig) for sig in CloudinaryService.ALLOWED_IMAGE_MAGIC):
                return 'الملف ليس صورة صالحة'

            # حجم الملف
            if hasattr(file, 'seek') and hasattr(file, 'tell'):
                file.seek(0, 2)
                size = file.tell()
                file.seek(pos or 0)
                if size > CloudinaryService.MAX_IMAGE_BYTES:
                    return f'حجم الصورة يتجاوز {CloudinaryService.MAX_IMAGE_BYTES // (1024*1024)} ميجا'
        except Exception:
            return None
        return None

    @staticmethod
    def _get_credentials() -> Dict:
        """جلب المفاتيح من system_settings."""
        return {
            'cloud_name': SystemSetting.get('CLOUDINARY_CLOUD_NAME', '').strip(),
            'api_key': SystemSetting.get('CLOUDINARY_API_KEY', '').strip(),
            'api_secret': SystemSetting.get('CLOUDINARY_API_SECRET', '').strip(),
        }

    @staticmethod
    def is_configured() -> bool:
        creds = CloudinaryService._get_credentials()
        return bool(creds['cloud_name'] and creds['api_key'] and creds['api_secret'])

    @staticmethod
    def _sign_params(params: dict, api_secret: str) -> str:
        """توقيع المعاملات للرفع الآمن (signed upload)."""
        sorted_params = sorted(
            (k, v) for k, v in params.items()
            if k not in ('file', 'cloud_name', 'resource_type', 'api_key') and v != ''
        )
        to_sign = '&'.join(f'{k}={v}' for k, v in sorted_params) + api_secret
        return hashlib.sha1(to_sign.encode('utf-8')).hexdigest()

    @staticmethod
    def upload_image(
        file: BinaryIO,
        folder: str = '',
        public_id: Optional[str] = None,
        tags: Optional[list] = None,
    ) -> Dict:
        """
        رفع صورة لـ Cloudinary.

        Args:
            file: ملف (BytesIO أو FileStorage)
            folder: مجلد داخل Cloudinary (مثل: hotel_units/tenant_5)
            public_id: معرّف اختياري
            tags: tags للبحث لاحقاً

        Returns:
            {
                'success': bool,
                'url': 'https://res.cloudinary.com/.../image.jpg',
                'public_id': 'hotel_units/tenant_5/abc123',
                'error': str (لو فشل)
            }
        """
        creds = CloudinaryService._get_credentials()
        if not creds['cloud_name'] or not creds['api_key'] or not creds['api_secret']:
            return {'success': False, 'error': 'Cloudinary غير مضبوط في إعدادات النظام'}

        # ✅ فحص نوع/حجم الصورة قبل الرفع
        err = CloudinaryService._validate_image_file(file)
        if err:
            return {'success': False, 'error': err}

        timestamp = int(time.time())
        params = {
            'timestamp': str(timestamp),
        }
        if folder:
            params['folder'] = folder
        if public_id:
            params['public_id'] = public_id
        if tags:
            params['tags'] = ','.join(tags)

        signature = CloudinaryService._sign_params(params, creds['api_secret'])

        url = CloudinaryService.UPLOAD_URL.format(
            cloud_name=creds['cloud_name'],
            resource_type='image',
        )

        try:
            data = dict(params)
            data['api_key'] = creds['api_key']
            data['signature'] = signature

            files = {'file': file}
            resp = requests.post(url, data=data, files=files, timeout=30)

            if resp.status_code != 200:
                current_app.logger.error(f'[Cloudinary] upload failed: {resp.status_code} {resp.text[:200]}')
                return {'success': False, 'error': f'فشل الرفع: HTTP {resp.status_code}'}

            result = resp.json()
            return {
                'success': True,
                'url': result.get('secure_url') or result.get('url'),
                'public_id': result.get('public_id'),
                'format': result.get('format'),
                'width': result.get('width'),
                'height': result.get('height'),
                'bytes': result.get('bytes'),
            }

        except requests.exceptions.Timeout:
            return {'success': False, 'error': 'انتهت مهلة الرفع'}
        except Exception as e:
            current_app.logger.exception(f'[Cloudinary] upload error: {e}')
            return {'success': False, 'error': f'خطأ: {str(e)[:100]}'}

    @staticmethod
    def upload_file(
        file: BinaryIO,
        folder: str = '',
        public_id: Optional[str] = None,
        resource_type: str = 'auto',
    ) -> Dict:
        """رفع ملف عام (PDF، فيديو، صوت)."""
        creds = CloudinaryService._get_credentials()
        if not creds['cloud_name'] or not creds['api_key'] or not creds['api_secret']:
            return {'success': False, 'error': 'Cloudinary غير مضبوط'}

        timestamp = int(time.time())
        params = {'timestamp': str(timestamp)}
        if folder:
            params['folder'] = folder
        if public_id:
            params['public_id'] = public_id

        signature = CloudinaryService._sign_params(params, creds['api_secret'])

        url = CloudinaryService.UPLOAD_URL.format(
            cloud_name=creds['cloud_name'],
            resource_type=resource_type,
        )

        try:
            data = dict(params)
            data['api_key'] = creds['api_key']
            data['signature'] = signature

            files = {'file': file}
            resp = requests.post(url, data=data, files=files, timeout=60)

            if resp.status_code != 200:
                err_msg = resp.text[:200]
                try:
                    err_msg = resp.json().get('error', {}).get('message', err_msg)
                except Exception:
                    pass
                current_app.logger.error(f'[Cloudinary] upload_file failed: {resp.status_code} {resp.text[:200]}')
                return {'success': False, 'error': f'فشل سحابة التخزين (HTTP {resp.status_code}): {err_msg}'}

            result = resp.json()
            return {
                'success': True,
                'url': result.get('secure_url') or result.get('url'),
                'public_id': result.get('public_id'),
                'resource_type': result.get('resource_type'),
                'bytes': result.get('bytes'),
            }
        except Exception as e:
            current_app.logger.exception(f'[Cloudinary] upload_file error: {e}')
            return {'success': False, 'error': str(e)[:100]}

    @staticmethod
    def delete_resource(public_id: str, resource_type: str = 'image') -> bool:
        """حذف ملف من Cloudinary."""
        creds = CloudinaryService._get_credentials()
        if not creds['cloud_name'] or not creds['api_key'] or not creds['api_secret']:
            return False

        timestamp = int(time.time())
        params = {
            'public_id': public_id,
            'timestamp': str(timestamp),
        }
        signature = CloudinaryService._sign_params(params, creds['api_secret'])

        url = CloudinaryService.DELETE_URL.format(
            cloud_name=creds['cloud_name'],
            resource_type=resource_type,
        )

        try:
            data = dict(params)
            data['api_key'] = creds['api_key']
            data['signature'] = signature
            resp = requests.post(url, data=data, timeout=15)
            return resp.status_code == 200
        except Exception as e:
            current_app.logger.warning(f'[Cloudinary] delete error: {e}')
            return False

    @staticmethod
    def get_optimized_url(url: str, width: int = None, quality: str = 'auto') -> str:
        """
        تعديل رابط Cloudinary لتحسين الحجم/الجودة.
        مثال: تصغير صورة الـ 4K لعرض في Thumbnail.
        """
        if not url or 'cloudinary.com' not in url:
            return url

        # نضيف transformations في URL
        transformations = []
        if width:
            transformations.append(f'w_{width}')
        transformations.append(f'q_{quality}')
        transformations.append('f_auto')  # تنسيق تلقائي (WebP, AVIF)

        transform_str = ','.join(transformations)

        # إضافة قبل /upload/
        if '/upload/' in url:
            return url.replace('/upload/', f'/upload/{transform_str}/')
        return url
