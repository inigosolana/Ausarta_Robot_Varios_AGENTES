import logging
import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("crypto-service")

# La ENCRYPTION_KEY debe ser una cadena de 32 bytes codificada en base64.
# Se puede generar con Fernet.generate_key().decode()
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

if not ENCRYPTION_KEY:
    logger.warning("ENCRYPTION_KEY not found in environment variables. Crypto features will fail.")
    cipher_suite = None
else:
    try:
        cipher_suite = Fernet(ENCRYPTION_KEY.encode())
    except Exception as e:
        logger.error("Invalid ENCRYPTION_KEY: %s", e)
        cipher_suite = None

def encrypt_data(data: str) -> str:
    """Cifra una cadena de texto usando Fernet."""
    if not cipher_suite:
        raise ValueError("Encryption suite not initialized. Check ENCRYPTION_KEY.")
    if not data:
        return ""
    encrypted_text = cipher_suite.encrypt(data.encode())
    return encrypted_text.decode()

def decrypt_data(encrypted_data: str) -> str:
    """Descifra una cadena de texto usando Fernet."""
    if not cipher_suite:
        raise ValueError("Encryption suite not initialized. Check ENCRYPTION_KEY.")
    if not encrypted_data:
        return ""
    try:
        decrypted_text = cipher_suite.decrypt(encrypted_data.encode())
        return decrypted_text.decode()
    except Exception as e:
        logger.error("Decryption error: %s", e)
        return "" # O lanzar excepción según política
