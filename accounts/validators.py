from pathlib import Path

from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError


IMAGE_FORMATS = {
    ".jpg": {"JPEG"},
    ".jpeg": {"JPEG"},
    ".png": {"PNG"},
    ".webp": {"WEBP"},
}


def validate_private_document(upload):
    """Reject files whose bytes do not match the allowed extension."""
    if not upload:
        return

    extension = Path(upload.name).suffix.lower()
    position = upload.tell() if hasattr(upload, "tell") else 0
    try:
        upload.seek(0)
        if extension == ".pdf":
            if upload.read(5) != b"%PDF-":
                raise ValidationError("ไฟล์ PDF ไม่ถูกต้อง")
            return
        if extension not in IMAGE_FORMATS:
            raise ValidationError("รองรับเฉพาะ PDF, JPG, PNG และ WEBP")
        upload.seek(0)
        image = Image.open(upload)
        detected_format = image.format
        image.verify()
        if detected_format not in IMAGE_FORMATS[extension]:
            raise ValidationError("ชนิดของรูปภาพไม่ตรงกับนามสกุลไฟล์")
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValidationError("ไฟล์รูปภาพไม่ถูกต้องหรือเสียหาย") from exc
    finally:
        if hasattr(upload, "seek"):
            upload.seek(position)