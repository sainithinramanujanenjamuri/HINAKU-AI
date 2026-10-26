"""
backend/attachments/validator.py

Security and validation rules for attachments:
- Supported: text-like (txt, md, csv, json, code), PDF (text layer), DOCX, images (png, jpg, jpeg, webp)
- Reject: executables (PE, ELF, Mach-O, scripts), archives (.zip, .tar, .gz, .7z), macros (.docm, xlsm, vbaProject)
- Content inspection by magic bytes and binary analysis, not just file extensions
- Limits:
  * Max 20 MB per file
  * Max 5 files per message
  * Disk space safety: reject if free disk space < file size + 2 GB
- Filename sanitization to prevent directory traversal
"""

import os
import re
import shutil
from pathlib import Path
from typing import BinaryIO, Optional, Set, Tuple

MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_FILES_PER_MESSAGE = 5
MAX_DECOMPRESSED_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_ZIP_ENTRIES = 500
MAX_EXPANSION_RATIO = 100
MIN_FREE_DISK_HEADROOM_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB

# Supported extensions
TEXT_EXTENSIONS: Set[str] = {
    ".txt", ".md", ".csv", ".json", ".xml", ".yaml", ".yml",
    ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css",
    ".c", ".cpp", ".h", ".hpp", ".rs", ".go", ".java", ".sh",
    ".sql", ".ini", ".cfg", ".toml", ".log"
}
PDF_EXTENSIONS: Set[str] = {".pdf"}
DOCX_EXTENSIONS: Set[str] = {".docx"}
IMAGE_EXTENSIONS: Set[str] = {".png", ".jpg", ".jpeg", ".webp"}

ALL_ALLOWED_EXTENSIONS = TEXT_EXTENSIONS | PDF_EXTENSIONS | DOCX_EXTENSIONS | IMAGE_EXTENSIONS

# Dangerous signatures
EXECUTABLE_SIGNATURES = [
    b"MZ",               # DOS / Windows PE executable
    b"\x7fELF",          # Linux ELF executable
    b"\xca\xfe\xba\xbe",  # Mach-O universal binary / Java class
    b"\xfe\xed\xfa\xce",  # Mach-O 32-bit
    b"\xfe\xed\xfa\xcf",  # Mach-O 64-bit
]

class AttachmentValidationError(ValueError):
    """Raised when an attachment fails validation."""
    pass

def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename against path traversal and forbidden characters.
    Strips directory components and replaces unsafe characters.
    """
    # Extract only the base name
    clean = Path(filename).name
    # Replace dangerous characters with underscore
    clean = re.sub(r'[^a-zA-Z0-9_\-\. ]', '_', clean)
    clean = clean.strip(". ")
    if not clean:
        clean = "attachment_unnamed"
    return clean

def check_disk_space(target_dir: Path, incoming_size_bytes: int) -> None:
    """
    Refuses upload if available disk space is less than incoming size + 2 GB.
    """
    try:
        usage = shutil.disk_usage(str(target_dir))
        required = incoming_size_bytes + MIN_FREE_DISK_HEADROOM_BYTES
        if usage.free < required:
            free_gb = usage.free / (1024 ** 3)
            req_gb = required / (1024 ** 3)
            raise AttachmentValidationError(
                f"Insufficient disk space. Free: {free_gb:.2f} GB, Required: {req_gb:.2f} GB (includes 2 GB safety headroom)."
            )
    except FileNotFoundError:
        # If directory doesn't exist yet, check parent
        if target_dir.parent != target_dir:
            check_disk_space(target_dir.parent, incoming_size_bytes)

def detect_and_validate_content(filename: str, content: bytes) -> str:
    """
    Inspects content bytes and validates allowed types:
    Returns category: 'text', 'pdf', 'docx', or 'image'.
    Raises AttachmentValidationError if rejected.
    """
    size = len(content)
    if size == 0:
        raise AttachmentValidationError("File is empty (0 bytes).")
    if size > MAX_FILE_SIZE_BYTES:
        raise AttachmentValidationError(
            f"File exceeds 20 MB limit ({size / (1024*1024):.1f} MB)."
        )

    # 1. Check for executable signatures
    for sig in EXECUTABLE_SIGNATURES:
        if content.startswith(sig):
            raise AttachmentValidationError("Executables and binary programs are not permitted.")

    ext = Path(filename).suffix.lower()

    # 2. PDF check
    if content.startswith(b"%PDF-"):
        return "pdf"

    # 3. Image checks
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image"
    if content.startswith(b"\xff\xd8\xff"):
        return "image"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image"

    # 4. DOCX check (ZIP archive containing [Content_Types].xml and word/)
    if content.startswith(b"PK\x03\x04"):
        # Check if it's a valid DOCX and NOT a macro or generic zip
        try:
            import io
            import zipfile
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                entries = zf.infolist()
                if len(entries) > MAX_ZIP_ENTRIES:
                    raise AttachmentValidationError(f"Archive exceeds maximum allowed entries ({len(entries)} > {MAX_ZIP_ENTRIES}).")

                total_uncompressed = sum(e.file_size for e in entries)
                if total_uncompressed > MAX_DECOMPRESSED_BYTES:
                    raise AttachmentValidationError(f"Decompressed size exceeds 50 MB limit ({total_uncompressed / (1024*1024):.1f} MB).")

                compressed_size = len(content)
                ratio = total_uncompressed / max(1, compressed_size)
                if ratio > MAX_EXPANSION_RATIO:
                    raise AttachmentValidationError(f"Zip bomb detected: compression ratio {ratio:.1f}:1 exceeds safety limit of {MAX_EXPANSION_RATIO}:1.")

                names = zf.namelist()
                is_word = any(n.startswith("word/") for n in names) and "[Content_Types].xml" in names
                if not is_word:
                    raise AttachmentValidationError("Generic ZIP archives are not permitted. Only DOCX documents are allowed.")

                for name in names:
                    if "vbaproject.bin" in name.lower() or name.lower().endswith((".vba", ".bas", ".cls")):
                        raise AttachmentValidationError("Macro-enabled documents (.docm / VBA) are strictly rejected for security.")
                return "docx"
        except zipfile.BadZipFile:
            raise AttachmentValidationError("Corrupted DOCX archive.")

    # 5. Reject other archive types
    if content.startswith((b"Rar!", b"7z\xbc\xaf\x27\x1c", b"\x1f\x8b\x08")):
        raise AttachmentValidationError("Compressed archives (RAR, 7Z, GZ) are not permitted.")

    # 6. Text files (txt, md, csv, json, code)
    # Validate that content can be decoded as UTF-8 or ASCII without null bytes
    if b"\x00" in content[:4096]:
        raise AttachmentValidationError("Binary content detected in non-supported format.")

    try:
        content.decode("utf-8")
        return "text"
    except UnicodeDecodeError:
        try:
            content.decode("latin-1")
            return "text"
        except Exception:
            raise AttachmentValidationError("Unable to decode text file. Ensure valid UTF-8/ASCII encoding.")
