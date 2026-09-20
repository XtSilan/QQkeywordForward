"""Data-access layer. Pure SQL grouped by aggregate; no HTTP/business logic.

Functions take an open ``sqlite3.Connection`` so callers own the transaction
boundary — multi-statement writes must stay atomic.
"""
