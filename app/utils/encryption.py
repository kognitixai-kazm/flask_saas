import os
from cryptography.fernet import Fernet
from flask import current_app

def get_cipher() -> Fernet:
    key = current_app.config.get('ENCRYPTION_KEY')
    if not key:
        # Fallback to SECRET_KEY, but it must be valid url-safe base64.
        # So we create a valid fernet key from SECRET_KEY hash.
        import base64
        import hashlib
        secret = current_app.config.get('SECRET_KEY', 'default-secret-fallback')
        # Fernet requires 32 url-safe base64-encoded bytes
        digest = hashlib.sha256(secret.encode('utf-8')).digest()
        key = base64.urlsafe_b64encode(digest)
    elif isinstance(key, str):
        key = key.encode('utf-8')
        
    return Fernet(key)

def encrypt_value(value: str) -> str:
    if not value:
        return value
    try:
        cipher = get_cipher()
        return cipher.encrypt(value.encode('utf-8')).decode('utf-8')
    except Exception as e:
        current_app.logger.error(f"Encryption error: {e}")
        return value

def decrypt_value(encrypted_value: str) -> str:
    if not encrypted_value:
        return encrypted_value
    try:
        cipher = get_cipher()
        return cipher.decrypt(encrypted_value.encode('utf-8')).decode('utf-8')
    except Exception as e:
        # If it's not encrypted or decryption fails (e.g. old plain text data)
        # we return it as is.
        return encrypted_value
