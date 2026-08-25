from __future__ import annotations


class FoundryError(Exception):
    pass


class LockRefused(FoundryError):
    pass


class WindowBusy(FoundryError):
    pass


class QueryRefused(FoundryError):
    pass
