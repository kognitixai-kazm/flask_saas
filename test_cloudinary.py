import os
import cloudinary
import cloudinary.uploader
import tempfile
from pathlib import Path
from dotenv import load_dotenv

# تحميل المتغيرات البيئية من ملف .env في المجلد الرئيسي
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')

# محاولة جلب بيانات الاعتماد بالأسماء الشائعة (سواء كانت ببادئة CLOUDINARY_ أو بدونها)
CLOUD_NAME = os.getenv('CLOUDINARY_CLOUD_NAME') or os.getenv('CLOUD_NAME')
API_KEY = os.getenv('CLOUDINARY_API_KEY') or os.getenv('API_KEY')
API_SECRET = os.getenv('CLOUDINARY_API_SECRET') or os.getenv('API_SECRET')

# بايتس لصورة GIF شفافة بحجم 1x1 بكسل لرفعها كاختبار
GIF_1X1 = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'

def upload_test_image():
    print("="*60)
    print("🚀 Starting Cloudinary Connection Test...")
    print("="*60)
    
    if not CLOUD_NAME or not API_KEY or not API_SECRET:
        print("❌ Error: Cloudinary credentials are missing.")
        print("Please ensure you have CLOUD_NAME, API_KEY, and API_SECRET defined in your .env file or environment variables.")
        print("="*60)
        return

    print(f"✅ Credentials found! (Cloud Name: {CLOUD_NAME})")

    try:
        # تهيئة مكتبة Cloudinary بالإعدادات
        print("⏳ Configuring Cloudinary library...")
        cloudinary.config(
            cloud_name=CLOUD_NAME,
            api_key=API_KEY,
            api_secret=API_SECRET,
            secure=True
        )
        
        # إنشاء ملف صورة تجريبي مؤقت
        print("⏳ Creating a temporary 1x1 test image...")
        with tempfile.NamedTemporaryFile(suffix=".gif", delete=False) as temp_img:
            temp_img.write(GIF_1X1)
            temp_img_path = temp_img.name
        
        print("⏳ Uploading image to Cloudinary...")
        
        # رفع الصورة إلى Cloudinary
        response = cloudinary.uploader.upload(
            temp_img_path,
            folder="test_folder",
            public_id="test_cloudinary_connection",
            overwrite=True
        )
        
        # حذف الملف المؤقت بعد الرفع
        if os.path.exists(temp_img_path):
            os.remove(temp_img_path)
            
        print("\n✅ SUCCESS: Image uploaded successfully!")
        print(f"🔗 Image URL: {response.get('secure_url')}")
        print("="*60)

    except Exception as e:
        print("\n❌ FAILED: Could not upload image to Cloudinary.")
        print(f"Exception Type: {type(e).__name__}")
        print(f"Exception Message: {str(e)}")
        print("="*60)
        
        # تنظيف الملف المؤقت في حال الفشل
        if 'temp_img_path' in locals() and os.path.exists(temp_img_path):
            os.remove(temp_img_path)

if __name__ == "__main__":
    upload_test_image()
