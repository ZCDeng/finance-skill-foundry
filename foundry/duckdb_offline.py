"""DuckDB connections that never fetch an extension.

DuckDB's default is to install and load a known extension the first time a
query names one of its functions, downloading it from the internet into
``~/.duckdb``. The SQL this kit writes uses only what is built in today, and the
packaged app must not start reaching the network the day a query grows a
function that lives in an extension. With these off, such a query fails with a
catalog error on every machine, including the developer's, instead of working
only where the download succeeded.

The settings are applied with ``SET`` after connecting rather than passed as
``config``: DuckDB refuses a second connection to the same file with a
different config, and the sandboxed SQL in ``analysis_sql`` and the tests open
their own.
"""

from __future__ import annotations

import duckdb


def connect(database: str, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(database, read_only=read_only)
    connection.execute("SET autoinstall_known_extensions = false")
    connection.execute("SET autoload_known_extensions = false")
    return connection
