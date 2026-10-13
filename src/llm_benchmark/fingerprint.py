"""Explicit, streaming content fingerprints. Never load a model or execute its files."""

import hashlib
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

from llm_benchmark.domain import digest

SUFFIXES = {".safetensors", ".gguf", ".bin", ".json", ".model", ".jinja"}
VOCAB_FILES = {"vocab.txt", "merges.txt"}


def fingerprint_model(path: Path) -> dict:
    root = path.resolve(strict=True)
    if not root.is_file() and not root.is_dir():
        raise ValueError("モデルファイルまたはディレクトリを指定してください")
    base = root.parent if root.is_file() else root
    candidates = [root] if root.is_file() else sorted(root.rglob("*"))
    selected = []
    for file in candidates:
        if file.is_symlink():
            raise ValueError(
                "シンボリックリンクを含むディレクトリは対象外です。実体の保存先を指定してください"
            )
        if file.is_dir():
            continue
        if file.suffix.lower() in SUFFIXES or file.name in VOCAB_FILES:
            if not stat.S_ISREG(file.lstat().st_mode):
                raise ValueError("通常ファイル以外はハッシュできません")
            selected.append(file)
    if not selected:
        raise ValueError("対応するモデル/設定/tokenizerファイルが見つかりません")
    selected.sort(key=lambda file: file.relative_to(base).as_posix())
    records = []
    for file in selected:
        with file.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("通常ファイル以外はハッシュできません")
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
            after = os.fstat(stream.fileno())
        current = file.stat()

        def signature(s):
            return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns

        if signature(before) != signature(after) or signature(after) != signature(current):
            raise ValueError(
                "取得中にファイルが変更されました。モデルの更新完了後に再実行してください"
            )
        records.append(
            {
                "path": file.relative_to(base).as_posix(),
                "size_bytes": after.st_size,
                "sha256": checksum,
            }
        )
    identity = {"schema": "forge-model-fingerprint-v1", "files": records}
    return {
        **identity,
        "manifest_sha256": digest(identity),
        "observed_at": datetime.now(UTC).isoformat(),
        "total_bytes": sum(row["size_bytes"] for row in records),
        "scope": "選択した重み/JSON設定/tokenizer/templateファイルの取得時点の内容。推論での使用、取得後の不変性、モデルの出所は保証しません。",
        "selection": sorted(SUFFIXES | VOCAB_FILES),
    }
