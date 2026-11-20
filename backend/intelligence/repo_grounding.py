"""
backend/intelligence/repo_grounding.py

Authorized, read-only repository grounding and indexing for HINAKU Project Intelligence.
Connects project knowledge and claims to concrete repository files, hashes, and evidence.
"""

import hashlib
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from .errors import (
    RepositoryAccessViolation,
    UnauthorizedRepositoryAccessError,
)
from .project_types import RepositoryFileIndex

# Strictly excluded directory names and path patterns to preserve security and privacy
EXCLUDED_DIR_NAMES: Set[str] = {
    ".git",
    "venv",
    ".venv",
    "env",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".idea",
    ".vscode",
    "data",
    "logs",
    "dist",
    "build",
}

# Strictly excluded file patterns and extensions (secrets, private databases, credentials)
EXCLUDED_FILE_PATTERNS: Set[str] = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "id_rsa",
    "id_ecdsa",
    "id_ed25519",
}

EXCLUDED_EXTENSIONS: Set[str] = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".pem",
    ".key",
    ".pfx",
    ".p12",
    ".pyc",
    ".pyo",
    ".log",
    ".exe",
    ".bin",
    ".dll",
    ".so",
}

MAX_INDEXABLE_FILE_SIZE = 5 * 1024 * 1024  # 5 MB safety cap per file


class RepoGrounding:
    """Read-only repository grounding engine for project repositories."""

    @staticmethod
    def validate_repository_path(repo_path: str, allowed_root: Optional[Path] = None) -> Path:
        """
        Validates that the repository path exists, is a directory, and is authorized.
        Raises UnauthorizedRepositoryAccessError or RepositoryAccessViolation if invalid.
        """
        if not repo_path or not str(repo_path).strip():
            raise UnauthorizedRepositoryAccessError("Repository path must be a non-empty string.")

        path = Path(repo_path).resolve()
        if not path.exists():
            raise UnauthorizedRepositoryAccessError(f"Repository path does not exist: {path}")
        if not path.is_dir():
            raise UnauthorizedRepositoryAccessError(f"Repository path is not a directory: {path}")

        # If an explicit root boundary is enforced, verify containment
        if allowed_root is not None:
            resolved_root = allowed_root.resolve()
            try:
                path.relative_to(resolved_root)
            except ValueError:
                raise UnauthorizedRepositoryAccessError(
                    f"Repository path '{path}' is outside the authorized root boundary '{resolved_root}'."
                )

        return path

    @staticmethod
    def is_safe_file(rel_path: Path, filename: str) -> bool:
        """Checks if a file path is safe to inspect, excluding secrets, caches, and binaries."""
        # Check directories in path
        for part in rel_path.parts:
            if part.lower() in EXCLUDED_DIR_NAMES:
                return False

        # Check filename patterns
        fn_lower = filename.lower()
        if fn_lower in EXCLUDED_FILE_PATTERNS or fn_lower.startswith(".env"):
            return False

        # Check extensions
        ext = os.path.splitext(filename)[1].lower()
        if ext in EXCLUDED_EXTENSIONS:
            return False

        return True

    @classmethod
    def index_repository(
        cls,
        project_id: str,
        repo_path: str,
        max_files: int = 500,
    ) -> List[RepositoryFileIndex]:
        """
        Performs read-only scanning of the repository, generating RepositoryFileIndex items.
        Computes SHA256 hashes and file metadata for grounding.
        """
        root = cls.validate_repository_path(repo_path)
        indexed: List[RepositoryFileIndex] = []

        for current_dir, dirs, files in os.walk(root):
            # Prune excluded directories in-place to prevent traversing them
            dirs[:] = [d for d in dirs if d.lower() not in EXCLUDED_DIR_NAMES]

            for f in files:
                full_path = Path(current_dir) / f
                try:
                    rel_path = full_path.relative_to(root)
                except ValueError:
                    continue

                if not cls.is_safe_file(rel_path, f):
                    continue

                try:
                    stat = full_path.stat()
                    if stat.st_size > MAX_INDEXABLE_FILE_SIZE:
                        continue  # Skip oversized files

                    # Calculate content hash (read-only)
                    hasher = hashlib.sha256()
                    with open(full_path, "rb") as fp:
                        while chunk := fp.read(65536):
                            hasher.update(chunk)
                    content_hash = hasher.hexdigest()

                    file_id = f"{project_id}_{rel_path.as_posix()}"
                    ext = rel_path.suffix.lower()

                    indexed.append(
                        RepositoryFileIndex(
                            file_id=file_id,
                            project_id=project_id,
                            relative_path=rel_path.as_posix(),
                            file_extension=ext,
                            size_bytes=stat.st_size,
                            content_hash=content_hash,
                            last_modified=stat.st_mtime,
                            indexed_at=time.time(),
                        )
                    )

                    if len(indexed) >= max_files:
                        break
                except (PermissionError, OSError):
                    continue

            if len(indexed) >= max_files:
                break

        return indexed

    @classmethod
    def detect_stale_files(
        cls,
        repo_path: str,
        indexed_files: List[RepositoryFileIndex],
    ) -> Dict[str, List[str]]:
        """
        Compares indexed records against the current filesystem to detect stale knowledge.
        Returns dict with "modified", "deleted", and "untracked" file lists.
        """
        root = cls.validate_repository_path(repo_path)
        indexed_map = {f.relative_path: f for f in indexed_files}

        modified: List[str] = []
        deleted: List[str] = []

        # Check existing indexed files
        for rel_str, idx in indexed_map.items():
            disk_path = root / rel_str
            if not disk_path.exists():
                deleted.append(rel_str)
            else:
                try:
                    stat = disk_path.stat()
                    # If mtime or size changed, check hash
                    if stat.st_mtime != idx.last_modified or stat.st_size != idx.size_bytes:
                        hasher = hashlib.sha256()
                        with open(disk_path, "rb") as fp:
                            while chunk := fp.read(65536):
                                hasher.update(chunk)
                        if hasher.hexdigest() != idx.content_hash:
                            modified.append(rel_str)
                except Exception:
                    modified.append(rel_str)

        return {
            "modified": modified,
            "deleted": deleted,
        }

    @classmethod
    def generate_file_evidence(cls, repo_path: str, relative_path: str) -> Dict[str, Any]:
        """
        Generates concrete, verifiable implementation evidence for a given file.
        Suitable for KnowledgeProvenance.implementation_evidence.
        """
        root = cls.validate_repository_path(repo_path)
        target = root / relative_path

        if not target.exists() or not target.is_file():
            raise RepositoryAccessViolation(f"Evidence file does not exist: {relative_path}")

        stat = target.stat()
        hasher = hashlib.sha256()
        with open(target, "rb") as fp:
            while chunk := fp.read(65536):
                hasher.update(chunk)

        return {
            "evidence_type": "repository_file",
            "relative_path": relative_path,
            "sha256": hasher.hexdigest(),
            "size_bytes": stat.st_size,
            "mtime": stat.st_mtime,
            "verified_at": time.time(),
        }
