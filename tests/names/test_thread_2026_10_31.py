"""The cached NamesDB must answer from a thread other than the one that opened it.

FastMCP runs sync tools on worker threads; with sqlite3's default
check_same_thread=True every names tool raised ProgrammingError once the
cached connection was reached from a second thread (31 Oct 2026).
"""
import os
import sqlite3
import threading

from bibliograph.sources.names.db import NamesDB


def _tiny_index(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE names (kanji TEXT, kana TEXT, rom_plain TEXT, rom_kunrei TEXT)")
    conn.execute("INSERT INTO names VALUES ('田中', 'たなか', 'tanaka', 'tanaka')")
    conn.commit()
    conn.close()


def test_connection_usable_from_another_thread(tmp_path):
    path = os.path.join(tmp_path, "names.sqlite")
    _tiny_index(path)
    db = NamesDB(path)
    db.conn.execute("SELECT COUNT(*) FROM names").fetchone()  # opening thread
    errors = []

    def worker():
        try:
            db.conn.execute("SELECT kanji FROM names WHERE rom_plain = 'tanaka'").fetchone()
        except Exception as exc:  # the defect raised sqlite3.ProgrammingError here
            errors.append(exc)

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert errors == []
