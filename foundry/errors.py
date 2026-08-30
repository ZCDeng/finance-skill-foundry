from __future__ import annotations

REFUSED = 3
"""Process exit code for a domain refusal. argparse keeps 2 for usage errors.

Every entry point that turns a ``FoundryError`` into an exit code uses this one
constant, so ``python -m foundry.probe`` and ``foundry ... probe`` cannot drift
apart on what "the foundry said no" looks like to a caller.
"""


class FoundryError(Exception):
    pass


class LockRefused(FoundryError):
    pass


class WindowBusy(FoundryError):
    pass


class QueryRefused(FoundryError):
    pass
