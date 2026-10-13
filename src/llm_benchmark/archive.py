"""Bounded part files over one SQLite snapshot; a manifest marks completion."""

import gzip
import hashlib
import json
import re
from contextlib import ExitStack, closing
from pathlib import Path

from llm_benchmark.storage import Store


def file_digest(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def split_archive(store: Store, run_id: str, output: Path, part_bytes: int, compress: bool) -> dict:
    if part_bytes < 1:
        raise ValueError("分割サイズは1バイト以上が必要です")
    # Validate before creating anything; exclusive mkdir also protects an empty existing folder.
    store.run_status(run_id)
    output.mkdir()
    manifest: dict = {
        "schema": "forge-split-v1",
        "record_schema": "forge-stream-v1",
        "compression": "gzip" if compress else "none",
        "target_uncompressed_bytes": part_bytes,
        "parts": [],
    }
    with closing(store.iter_export(run_id)) as rows:
        pending = next(rows)
        manifest.update(
            run_id=pending["id"], set_hash=pending["set_hash"], revision=pending["revision"]
        )
        encoded: bytes | None = (
            json.dumps(pending, ensure_ascii=False, allow_nan=False) + "\n"
        ).encode("utf-8")
        while encoded is not None:
            name = f"part-{len(manifest['parts']) + 1:06d}.jsonl" + (".gz" if compress else "")
            path = output / name
            size = count = 0
            with ExitStack() as stack:
                raw = stack.enter_context(path.open("xb"))
                file = (
                    stack.enter_context(gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0))
                    if compress
                    else raw
                )
                while encoded is not None:
                    if count and size + len(encoded) > part_bytes:
                        break
                    file.write(encoded)
                    size += len(encoded)
                    count += 1
                    row = next(rows, None)
                    encoded = (
                        (json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n").encode(
                            "utf-8"
                        )
                        if row is not None
                        else None
                    )
            manifest["parts"].append(
                {
                    "name": name,
                    "records": count,
                    "uncompressed_bytes": size,
                    "stored_bytes": path.stat().st_size,
                    "sha256": file_digest(path),
                }
            )
    manifest["records"] = sum(part["records"] for part in manifest["parts"])
    # Interrupted output has no manifest. Never present partial files as a complete archive.
    temporary = output / "manifest.json.partial"
    with temporary.open("x", encoding="utf-8", newline="\n") as manifest_file:
        json.dump(manifest, manifest_file, ensure_ascii=False, indent=2, allow_nan=False)
        manifest_file.write("\n")
    temporary.rename(output / "manifest.json")
    return manifest


def verify_archive(directory: Path) -> dict:
    """Verify stored bytes, not the provenance or semantic correctness of the data."""
    with (directory / "manifest.json").open("rb") as file:
        content = file.read(8_000_001)
    if len(content) > 8_000_000:
        raise ValueError("マニフェストが大きすぎます")
    manifest = json.loads(content)
    if not isinstance(manifest, dict) or manifest.get("schema") != "forge-split-v1":
        raise ValueError("未対応のアーカイブ形式です")
    parts = manifest.get("parts")
    compression = manifest.get("compression")
    if not isinstance(parts, list) or not parts or compression not in ("none", "gzip"):
        raise ValueError("不正なアーカイブ構成です")
    total = 0
    for index, part in enumerate(parts, 1):
        name = f"part-{index:06d}.jsonl" + (".gz" if compression == "gzip" else "")
        if not isinstance(part, dict) or part.get("name") != name:
            raise ValueError("分割ファイルの順序または名前が不正です")
        checksum = part.get("sha256")
        if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise ValueError("SHA-256が不正です")
        if type(part.get("records")) is not int or part["records"] < 1:
            raise ValueError("レコード数が不正です")
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"分割ファイルが存在しないか通常ファイルではありません: {name}")
        if path.stat().st_size != part.get("stored_bytes") or file_digest(path) != checksum:
            raise ValueError(f"分割ファイルのサイズまたはSHA-256が一致しません: {name}")
        total += part["records"]
    if total != manifest.get("records"):
        raise ValueError("合計レコード数が一致しません")
    return {
        "verified": True,
        "parts": len(parts),
        "records": total,
        "run_id": manifest.get("run_id"),
    }
