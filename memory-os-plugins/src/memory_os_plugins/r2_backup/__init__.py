"""R2 backup plugin — sync memory Markdown files to Cloudflare R2 via S3 API."""

from .plugin import register

__all__ = ["register"]
