from __future__ import annotations


class PixivDirectError(Exception):
    """Base exception for plugin domain errors."""


class UserInputError(PixivDirectError):
    """Raised when user input cannot be processed."""


class PermissionDeniedError(PixivDirectError):
    """Raised when the caller lacks permission."""


class StorageError(PixivDirectError):
    """Raised when plugin state cannot be loaded or persisted."""


class PixivApiError(PixivDirectError):
    """Raised when the Pixiv API returns an unexpected result."""


class PixivAuthError(PixivApiError):
    """Raised when Pixiv authentication fails."""


class TransientNetworkError(PixivApiError):
    """Raised for retryable network failures."""
