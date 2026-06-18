import os
import cloudinary
import cloudinary.uploader
import tempfile
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')

CLOUD_NAME = os.getenv('CLOUDINARY_CLOUD_NAME') or os.getenv('CLOUD_NAME')
API_KEY = os.getenv('CLOUDINARY_API_KEY') or os.getenv('API_KEY')
API_SECRET = os.getenv('CLOUDINARY_API_SECRET') or os.getenv('API_SECRET')

# Dummy PDF content (minimal valid PDF)
PDF_CONTENT = b"%PDF-1.0\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/MediaBox[0 0 3 3]>>endobj\nxref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000052 00000 n\n0000000101 00000 n\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n149\n%EOF\n"

def test_pdf_upload():
    print("="*60)
    print("Testing PDF Upload to Cloudinary...")
    print("="*60)
    
    if not CLOUD_NAME or not API_KEY or not API_SECRET:
        print("Error: Cloudinary credentials are missing.")
        return

    cloudinary.config(
        cloud_name=CLOUD_NAME,
        api_key=API_KEY,
        api_secret=API_SECRET,
        secure=True
    )
    
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_pdf:
        temp_pdf.write(PDF_CONTENT)
        temp_pdf_path = temp_pdf.name
    
    try:
        print("Uploading PDF to Cloudinary (resource_type='image' - default)...")
        response_image = cloudinary.uploader.upload(
            temp_pdf_path,
            folder="test_folder",
            public_id="test_pdf_image",
            overwrite=True
        )
        print(f"SUCCESS: PDF uploaded as image! URL: {response_image.get('secure_url')}")
    except Exception as e:
        print(f"FAILED to upload PDF as image. Exception: {e}")

    try:
        print("\nUploading PDF to Cloudinary (resource_type='raw')...")
        response_raw = cloudinary.uploader.upload(
            temp_pdf_path,
            resource_type="raw",
            folder="test_folder",
            public_id="test_pdf_raw.pdf",
            overwrite=True
        )
        print(f"SUCCESS: PDF uploaded as raw! URL: {response_raw.get('secure_url')}")
    except Exception as e:
        print(f"FAILED to upload PDF as raw. Exception: {e}")

    if os.path.exists(temp_pdf_path):
        os.remove(temp_pdf_path)

if __name__ == "__main__":
    test_pdf_upload()
