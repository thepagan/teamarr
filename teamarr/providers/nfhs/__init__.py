"""NFHS provider package."""

__all__ = ["NFHSClient", "NFHSProvider"]


def __getattr__(name: str):
    if name == "NFHSClient":
        from .client import NFHSClient

        return NFHSClient
    if name == "NFHSProvider":
        from .provider import NFHSProvider

        return NFHSProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
