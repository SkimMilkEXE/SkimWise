"""Back up the database to a file and restore it. The app is local-only, so this is the user's only
copy outside this PC."""

import os
import sqlite3
from pathlib import Path

from skimwise.db.connection import MIGRATIONS, connect, migrate


class BackupError(ValueError):
    """A user-facing error; the message is safe to show in the UI."""


class BackupService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def backup_to(self, path: Path | str) -> None:
        """Write a complete copy of the database. SQLite's backup API gives a consistent snapshot
        even while the app has the database open."""
        path = Path(path)
        self._refuse_live_file(path)
        # Write beside the target first and swap it in only when complete, so a failed backup
        # never destroys an older backup with the same name.
        temp = path.with_name(path.name + ".partial")
        try:
            temp.unlink(missing_ok=True)
            dest = sqlite3.connect(temp)
            try:
                self.conn.backup(dest)
            finally:
                dest.close()
            os.replace(temp, path)
        except (sqlite3.Error, OSError) as e:
            temp.unlink(missing_ok=True)
            raise BackupError(f"Couldn't save the backup there ({e}). Try another folder.") from None

    def restore_from(self, path: Path | str) -> None:
        """Replace ALL current data with the backup's. Older backups are upgraded to the current schema."""
        self._refuse_live_file(Path(path))  # restoring a database onto itself waits on its own lock forever
        source = _open_backup(Path(path))
        try:
            source.backup(self.conn)  # overwrites this connection's database in place
        finally:
            source.close()
        self.conn.execute("PRAGMA foreign_keys = ON")
        migrate(self.conn)

    def delete_all(self) -> None:
        """Erase everything: back to exactly what a fresh install has (the default categories only)."""
        fresh = connect(":memory:")
        try:
            fresh.backup(self.conn)  # overwrite this database with a brand-new one
        finally:
            fresh.close()
        self.conn.execute("PRAGMA foreign_keys = ON")

    def _refuse_live_file(self, path: Path) -> None:
        live = self.conn.execute("PRAGMA database_list").fetchone()[2]  # "" for an in-memory database
        if live and path.exists() and path.resolve() == Path(live).resolve():
            raise BackupError("Choose a different file: that's the database SkimWise is using right now.")


def _open_backup(path: Path) -> sqlite3.Connection:
    """Open read-only and check it's really a SkimWise database before anything is overwritten."""
    if not path.is_file():
        raise BackupError("That file doesn't exist.")
    try:
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    except sqlite3.DatabaseError:
        raise BackupError("That file isn't a SkimWise backup.") from None
    if not {"categories", "transactions"} <= tables or version < 2:
        conn.close()
        raise BackupError("That file isn't a SkimWise backup.")
    if version > len(MIGRATIONS):
        conn.close()
        raise BackupError("That backup was made by a newer version of SkimWise. Update the app first.")
    return conn
