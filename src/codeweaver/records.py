"""An application-owned journal; interrupted tool calls are never automatically replayed."""

import json
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path


class Journal:
    def __init__(self, root: Path):
        directory = root / ".codeweaver"
        if directory.is_symlink():
            raise ValueError("Session directory must not be a symlink")
        directory.mkdir(mode=0o700, exist_ok=True)
        os.chmod(directory, 0o700)
        path = directory / "sessions.sqlite3"
        if path.is_symlink():
            raise ValueError("Session database must not be a symlink")
        self.db = sqlite3.connect(path)
        os.chmod(path, 0o600)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, identity TEXT, messages TEXT, updated REAL);
            CREATE TABLE IF NOT EXISTS operations (session TEXT, call TEXT, tool TEXT, state TEXT, result TEXT, PRIMARY KEY(session,call));
            CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, session TEXT, kind TEXT, payload TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS memories (name TEXT PRIMARY KEY, text TEXT, updated REAL);
        """)

    def new(self, identity: str) -> str:
        key = uuid.uuid4().hex
        self.db.execute("INSERT INTO sessions VALUES (?,?,?,?)", (key, identity, "[]", time.time()))
        self.db.commit()
        return key

    def load(self, key: str, identity: str) -> list[dict]:
        row = self.db.execute("SELECT identity,messages FROM sessions WHERE id=?", (key,)).fetchone()
        if row is None or row[0] != identity:
            raise ValueError("Unknown session or different provider/model/workspace")
        return json.loads(row[1])

    def save(self, key: str, messages: list[dict]):
        self.db.execute(
            "UPDATE sessions SET messages=?,updated=? WHERE id=?", (json.dumps(messages), time.time(), key)
        )
        self.db.commit()

    def sessions(self) -> list[dict]:
        return [
            dict(id=r[0], identity=r[1], updated=r[2])
            for r in self.db.execute(
                "SELECT id,identity,updated FROM sessions ORDER BY updated DESC LIMIT 50"
            )
        ]

    def begin(self, session: str, call: str, tool: str) -> dict | None:
        row = self.db.execute(
            "SELECT state,result FROM operations WHERE session=? AND call=?", (session, call)
        ).fetchone()
        if row:
            return (
                json.loads(row[1])
                if row[0] == "done"
                else {
                    "error": "Interrupted or in-flight operation; inspect workspace before requesting a new call"
                }
            )
        self.db.execute("INSERT INTO operations VALUES (?,?,?,?,?)", (session, call, tool, "started", "{}"))
        self.db.commit()
        return None

    def finish(self, session: str, call: str, result: dict):
        self.db.execute(
            "UPDATE operations SET state='done',result=? WHERE session=? AND call=?",
            (json.dumps(result), session, call),
        )
        self.db.commit()

    def event(self, session: str, kind: str, payload: dict):
        self.db.execute(
            "INSERT INTO events(session,kind,payload,created) VALUES (?,?,?,?)",
            (session, kind, json.dumps(payload), time.time()),
        )
        self.db.commit()

    def remember(self, name: str, text: str):
        if not re.fullmatch(r"[\w-]{1,64}", name) or len(text) > 8000:
            raise ValueError("Memory requires a short name and at most 8000 characters")
        self.db.execute("INSERT OR REPLACE INTO memories VALUES (?,?,?)", (name, text, time.time()))
        self.db.commit()

    def memories(self) -> list[dict]:
        return [
            dict(name=r[0], text=r[1])
            for r in self.db.execute("SELECT name,text FROM memories ORDER BY updated DESC LIMIT 20")
        ]

    def close(self):
        self.db.close()
