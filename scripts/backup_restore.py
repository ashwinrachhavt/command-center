#!/usr/bin/env python3
"""Back up local Compose data and verify restore in isolated Docker resources."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKUPS = ROOT / ".local" / "backups"
IMAGE = (
    "postgres:17-alpine@sha256:"
    "b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24"
)
WRITERS = {"api", "worker", "integration-worker", "execution-worker", "beat"}
DUMP, BLOBS, MANIFEST = "database.dump", "document-blobs.tar", "manifest.json"
SHA = re.compile(r"[0-9a-f]{64}")
MAX_ROWS = 100_000


class Failure(RuntimeError):
    pass


def run(args, label, *, stdin=None, stdout=subprocess.PIPE, timeout=300):
    try:
        result = subprocess.run(
            args,
            cwd=ROOT,
            stdin=stdin,
            stdout=stdout,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Failure(f"{label} did not complete") from exc
    if result.returncode:
        raise Failure(f"{label} failed")
    return result.stdout or b""


def text(args, label):
    value = run(args, label)
    if len(value) > 16 * 1024 * 1024:
        raise Failure(f"{label} returned too much output")
    return value.decode().strip()


def docker(*args, label, **kwargs):
    return run(["docker", *args], label, **kwargs)


def compose(*args, label):
    return text(["docker", "compose", *args], label)


def private(path, mode):
    path.chmod(mode)
    if path.stat().st_mode & 0o777 != mode:
        raise Failure(f"Could not set private permissions on {path.name}")


def file_sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def names_sha(names):
    payload = "".join(f"{name}\n" for name in sorted(names)).encode()
    return hashlib.sha256(payload).hexdigest()


def database_inventory(query):
    revision = query(
        "SELECT string_agg(version_num, ',' ORDER BY version_num) FROM alembic_version"
    )
    tables = query(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
        "ORDER BY tablename LIMIT 100001"
    ).splitlines()
    rows = query(
        "SELECT sha256, byte_size FROM blobs ORDER BY sha256 LIMIT 100001"
    ).splitlines()
    if len(tables) > MAX_ROWS or len(rows) > MAX_ROWS:
        raise Failure("Database inventory exceeds 100000 rows")
    blob_names, blob_bytes = [], 0
    for row in rows:
        values = row.split("|", 1)
        if len(values) != 2 or SHA.fullmatch(values[0]) is None:
            raise Failure("Database blob inventory is invalid")
        blob_names.append(values[0])
        blob_bytes += int(values[1])
    return {
        "migration_revision": revision,
        "table_count": len(tables),
        "table_names_sha256": names_sha(tables),
        "referenced_blob_count": len(blob_names),
        "referenced_blob_bytes": blob_bytes,
        "referenced_blob_names_sha256": names_sha(blob_names),
        "_blob_names": blob_names,
    }


def archive_inventory(path):
    names, size = [], 0
    with tarfile.open(path, "r:") as archive:
        for member in archive:
            name = member.name.removeprefix("./").rstrip("/")
            if name in {"", ".", "sha256"} and member.isdir():
                continue
            parts = name.split("/")
            if (
                len(parts) != 2
                or parts[0] != "sha256"
                or SHA.fullmatch(parts[1]) is None
                or not member.isfile()
                or member.issym()
                or member.islnk()
            ):
                raise Failure("Blob archive contains an unsupported entry")
            names.append(parts[1])
            size += member.size
    return {
        "blob_file_count": len(names),
        "blob_file_bytes": size,
        "blob_file_names_sha256": names_sha(names),
        "_blob_names": names,
    }


def live_query(user, database, sql):
    return compose(
        "exec",
        "-T",
        "db",
        "psql",
        "-U",
        user,
        "-d",
        database,
        "-At",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        sql,
        label="database inventory",
    )


def preconditions():
    running = set(
        compose(
            "ps", "--status", "running", "--services", label="Compose status"
        ).splitlines()
    )
    if "db" not in running:
        raise Failure("The Compose database must be running")
    active = sorted(running & WRITERS)
    if active:
        raise Failure("Stop database writers before backup: " + ", ".join(active))
    volume = text(
        [
            "docker",
            "volume",
            "ls",
            "--filter",
            "label=com.docker.compose.project=command-center",
            "--filter",
            "label=com.docker.compose.volume=document-blobs",
            "--format",
            "{{.Name}}",
        ],
        "document blob volume lookup",
    ).splitlines()
    if len(volume) != 1:
        raise Failure("Expected exactly one Command Center document blob volume")
    docker("image", "inspect", IMAGE, label="pinned Postgres image check")
    user = compose(
        "exec", "-T", "db", "printenv", "POSTGRES_USER", label="database user"
    )
    database = compose(
        "exec", "-T", "db", "printenv", "POSTGRES_DB", label="database name"
    )
    return volume[0], user, database


def create_backup():
    volume, user, database = preconditions()
    BACKUPS.mkdir(parents=True, mode=0o700, exist_ok=True)
    private(BACKUPS, 0o700)
    path = BACKUPS / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + secrets.token_hex(4)
    )
    path.mkdir(mode=0o700)
    try:
        dump = path / DUMP
        with dump.open("xb") as output:
            private(dump, 0o600)
            run(
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "db",
                    "pg_dump",
                    "-U",
                    user,
                    "-d",
                    database,
                    "--format=custom",
                    "--no-owner",
                    "--no-acl",
                ],
                "PostgreSQL backup",
                stdout=output,
                timeout=600,
            )
        blobs = path / BLOBS
        with blobs.open("xb") as output:
            private(blobs, 0o600)
            docker(
                "run",
                "--rm",
                "--pull",
                "never",
                "--network",
                "none",
                "--read-only",
                "--user",
                "0:0",
                "--mount",
                f"type=volume,src={volume},dst=/blobs,readonly",
                IMAGE,
                "tar",
                "-C",
                "/blobs",
                "-cf",
                "-",
                ".",
                label="document blob backup",
                stdout=output,
                timeout=600,
            )
        db_info = database_inventory(lambda sql: live_query(user, database, sql))
        blob_info = archive_inventory(blobs)
        if not set(db_info.pop("_blob_names")).issubset(blob_info.pop("_blob_names")):
            raise Failure("Blob archive is missing database-referenced content")
        manifest = {
            "format": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "postgres_image": IMAGE,
            "database_dump": {"sha256": file_sha(dump), **db_info},
            "document_blobs": {"sha256": file_sha(blobs), **blob_info},
        }
        manifest_path = path / MANIFEST
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        private(manifest_path, 0o600)
    except Exception:
        shutil.rmtree(path, ignore_errors=True)
        raise
    print(path.relative_to(ROOT))
    return path


def load_backup(path):
    path = path.resolve()
    if path.parent != BACKUPS.resolve() or not path.is_dir():
        raise Failure("Choose one backup directory directly under .local/backups")
    try:
        manifest = json.loads((path / MANIFEST).read_text())
    except (OSError, ValueError) as exc:
        raise Failure("Backup manifest is invalid") from exc
    dump, blobs = path / DUMP, path / BLOBS
    for item in (path / MANIFEST, dump, blobs):
        if not item.is_file() or item.is_symlink():
            raise Failure("Backup files must be regular files")
        private(item, 0o600)
    if file_sha(dump) != manifest["database_dump"]["sha256"]:
        raise Failure("Database dump checksum does not match")
    if file_sha(blobs) != manifest["document_blobs"]["sha256"]:
        raise Failure("Blob archive checksum does not match")
    inventory = archive_inventory(blobs)
    inventory.pop("_blob_names")
    if any(
        manifest["document_blobs"].get(key) != value for key, value in inventory.items()
    ):
        raise Failure("Blob archive inventory does not match")
    return manifest, dump, blobs


def restored_query(container, sql):
    return text(
        [
            "docker",
            "exec",
            container,
            "psql",
            "-U",
            "restore_verify",
            "-d",
            "restore_verify",
            "-At",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            sql,
        ],
        "restored database inventory",
    )


def wait_for_database(container):
    successes = 0
    for _ in range(90):
        result = subprocess.run(
            [
                "docker",
                "exec",
                container,
                "psql",
                "-U",
                "restore_verify",
                "-d",
                "restore_verify",
                "-Atqc",
                "SELECT 1",
            ],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        successes = successes + 1 if result.returncode == 0 else 0
        if successes == 2:
            return
        time.sleep(0.5)
    raise Failure("Isolated restore database did not become ready")


def restored_blob_inventory(volume, label):
    script = r'''set -eu
count=0; bytes=0; : > /tmp/names
for file in /blobs/sha256/*; do
  [ -f "$file" ] || continue
  name="${file##*/}"; actual="$(sha256sum "$file" | cut -d ' ' -f 1)"
  [ "$name" = "$actual" ]; size="$(wc -c < "$file")"
  count=$((count + 1)); bytes=$((bytes + size)); printf '%s\n' "$name" >> /tmp/names
done
printf '%s|%s|%s\n' "$count" "$bytes" "$(sha256sum /tmp/names | cut -d ' ' -f 1)"'''
    value = text(
        [
            "docker",
            "run",
            "--rm",
            "--pull",
            "never",
            "--label",
            label,
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=2m",
            "--user",
            "0:0",
            "--mount",
            f"type=volume,src={volume},dst=/blobs,readonly",
            IMAGE,
            "sh",
            "-ec",
            script,
        ],
        "restored blob inventory",
    ).split("|")
    if len(value) != 3 or SHA.fullmatch(value[2]) is None:
        raise Failure("Restored blob inventory is invalid")
    return {
        "blob_file_count": int(value[0]),
        "blob_file_bytes": int(value[1]),
        "blob_file_names_sha256": value[2],
    }


def cleanup(commands):
    for args in commands:
        try:
            subprocess.run(
                ["docker", *args],
                cwd=ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass


def verify(path):
    manifest, dump, _ = load_backup(path)
    docker("image", "inspect", IMAGE, label="pinned Postgres image check")
    token = secrets.token_hex(8)
    container = f"cc-restore-verify-{token}"
    db_volume = f"cc_restore_verify_db_{token}"
    blob_volume = f"cc_restore_verify_blobs_{token}"
    resource_label = f"command-center.restore-verify={token}"
    env_file = BACKUPS / f".verify-{token}.env"
    env_file.write_text(
        "POSTGRES_USER=restore_verify\n"
        f"POSTGRES_PASSWORD={secrets.token_urlsafe(32)}\n"
        "POSTGRES_DB=restore_verify\n"
    )
    private(env_file, 0o600)
    try:
        for volume in (db_volume, blob_volume):
            docker(
                "volume",
                "create",
                "--label",
                resource_label,
                volume,
                label="volume creation",
            )
        docker(
            "run",
            "-d",
            "--pull",
            "never",
            "--name",
            container,
            "--label",
            resource_label,
            "--network",
            "none",
            "--env-file",
            str(env_file),
            "--mount",
            f"type=volume,src={db_volume},dst=/var/lib/postgresql/data",
            IMAGE,
            label="isolated restore database startup",
        )
        wait_for_database(container)
        with dump.open("rb") as source:
            docker(
                "exec",
                "-i",
                container,
                "pg_restore",
                "-U",
                "restore_verify",
                "-d",
                "restore_verify",
                "--no-owner",
                "--no-acl",
                "--exit-on-error",
                label="isolated PostgreSQL restore",
                stdin=source,
                stdout=subprocess.DEVNULL,
                timeout=600,
            )
        db_info = database_inventory(lambda sql: restored_query(container, sql))
        db_info.pop("_blob_names")
        if any(
            manifest["database_dump"].get(key) != value
            for key, value in db_info.items()
        ):
            raise Failure("Restored database inventory does not match")
        docker(
            "run",
            "--rm",
            "--pull",
            "never",
            "--label",
            resource_label,
            "--network",
            "none",
            "--read-only",
            "--user",
            "0:0",
            "--mount",
            f"type=volume,src={blob_volume},dst=/blobs",
            "--mount",
            f"type=bind,src={path.resolve()},dst=/backup,readonly",
            IMAGE,
            "tar",
            "-xf",
            f"/backup/{BLOBS}",
            "-C",
            "/blobs",
            label="isolated blob restore",
            stdout=subprocess.DEVNULL,
            timeout=600,
        )
        blob_info = restored_blob_inventory(blob_volume, resource_label)
        if any(
            manifest["document_blobs"].get(key) != value
            for key, value in blob_info.items()
        ):
            raise Failure("Restored blob inventory does not match")
        print(
            f"Verified {path.resolve().relative_to(ROOT)} in isolated temporary resources"
        )
    finally:
        env_file.unlink(missing_ok=True)
        cleanup(
            [
                ["rm", "-f", container],
                ["volume", "rm", "-f", db_volume],
                ["volume", "rm", "-f", blob_volume],
            ]
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("backup")
    restore = commands.add_parser("verify")
    restore.add_argument("backup", type=Path)
    commands.add_parser("backup-and-verify")
    args = parser.parse_args()
    try:
        if args.command == "backup":
            create_backup()
        elif args.command == "verify":
            verify(args.backup)
        else:
            verify(create_backup())
    except (Failure, KeyError, TypeError, ValueError) as exc:
        print(f"Backup workflow stopped: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
