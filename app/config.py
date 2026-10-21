from pathlib import Path
import os
BASE_DIR = Path(__file__).resolve().parents[1]
UPLOAD_DIR = BASE_DIR / 'data' / 'uploads'
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = BASE_DIR / 'results' / 'verification.db'
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.bmp'}
MAX_CONTENT_LENGTH = 15 * 1024 * 1024
TESSERACT_CMD = os.getenv('TESSERACT_CMD', '').strip()
