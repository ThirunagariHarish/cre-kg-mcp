"""Tests for core/file_writer.py — atomic file writes."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from core.file_writer import append_jsonl, atomic_write_json, atomic_write_text, read_json


class TestAtomicWriteJson:
    def test_writes_valid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "out.json"
        data = {"key": "value", "num": 42}
        atomic_write_json(path, data)
        assert json.loads(path.read_text()) == data

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        path = tmp_path / "deep" / "nested" / "out.json"
        atomic_write_json(path, {"x": 1})
        assert path.exists()

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        path = tmp_path / "out.json"
        atomic_write_json(path, {"v": 1})
        atomic_write_json(path, {"v": 2})
        assert json.loads(path.read_text())["v"] == 2

    def test_no_tmp_suffix_debris(self, tmp_path: Path) -> None:
        """No .tmp files should be left after successful write."""
        path = tmp_path / "out.json"
        atomic_write_json(path, {"ok": True})
        tmp_files = list(tmp_path.glob("*.tmp*")) + list(tmp_path.glob(".tmp_*"))
        assert len(tmp_files) == 0

    def test_concurrent_writes_do_not_corrupt(self, tmp_path: Path) -> None:
        """
        Multiple threads writing simultaneously must not produce corrupt files.
        Legacy bug: shared .tmp suffix caused writers to stomp each other.
        """
        path = tmp_path / "concurrent.json"
        errors: list[Exception] = []

        def write(n: int) -> None:
            try:
                atomic_write_json(path, {"writer": n, "data": "x" * 100})
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=write, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Write errors: {errors}"
        # File must contain valid JSON after all concurrent writes
        result = json.loads(path.read_text())
        assert "writer" in result


class TestAtomicWriteText:
    def test_writes_text(self, tmp_path: Path) -> None:
        path = tmp_path / "out.txt"
        atomic_write_text(path, "hello world")
        assert path.read_text() == "hello world"


class TestReadJson:
    def test_reads_existing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "data.json"
        path.write_text('{"a": 1}')
        assert read_json(path) == {"a": 1}

    def test_missing_file_returns_default(self, tmp_path: Path) -> None:
        path = tmp_path / "missing.json"
        assert read_json(path) is None
        assert read_json(path, default={}) == {}

    def test_malformed_json_returns_default(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{bad json}")
        assert read_json(path, default="fallback") == "fallback"


class TestAppendJsonl:
    def test_appends_multiple_records(self, tmp_path: Path) -> None:
        path = tmp_path / "log.jsonl"
        append_jsonl(path, {"n": 1})
        append_jsonl(path, {"n": 2})
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["n"] == 1
        assert json.loads(lines[1])["n"] == 2

    def test_creates_file_if_missing(self, tmp_path: Path) -> None:
        path = tmp_path / "new.jsonl"
        append_jsonl(path, {"x": 1})
        assert path.exists()
