# Local backup and restore verification

Command Center backups must contain PostgreSQL and the `document-blobs` volume from the same quiesced workspace. The backup script refuses to run while any database writer is running. It never stops services automatically.

From the repository root:

```bash
docker compose stop api worker integration-worker execution-worker beat
python3 scripts/backup_restore.py backup-and-verify
docker compose start api worker integration-worker execution-worker beat
```

The script writes a uniquely named directory under `.local/backups/`. Directories use mode `0700`; the custom-format PostgreSQL dump, blob archive, and manifest use mode `0600`. `.local/` is ignored by Git. The manifest contains checksums and aggregate migration, table, and blob inventories. It contains no database password or document contents.

To verify an existing backup again:

```bash
python3 scripts/backup_restore.py verify .local/backups/<backup-id>
```

Verification checks the manifest, restores the dump into a fresh PostgreSQL 17 container backed by a uniquely named temporary volume, restores blobs into a second temporary volume, and compares migration, table, referenced-blob, and stored-file inventories. The PostgreSQL container has `--network none`, publishes no host port, and never connects to the Compose or host test databases. Temporary resources carry a unique `command-center.restore-verify` label and the script removes only its own named container and volumes in a `finally` block.

The workflow uses the pinned PostgreSQL image already declared in Compose and passes the temporary restore password through a mode-`0600` environment file that is deleted after verification. It does not place credentials in command arguments, logs, or the manifest.

`pg_dump` provides one consistent database snapshot. Cross-storage consistency requires the API, Celery workers, and beat to remain stopped until both the database dump and blob archive finish. If the workflow fails, keep writers stopped, correct the problem, and create a new backup. Do not reuse an incomplete directory; the script deletes it on failure.

These backups contain private workspace data. File permissions protect them only from other local accounts; they are not encrypted or off-site. Copy a verified backup to an approved encrypted location before an upgrade that needs disaster recovery. The script verifies local restore mechanics, not remote retention, encryption, or point-in-time recovery.

Migration `0015_connected_context` deliberately refuses downgrade after Calendar-window observations have been recorded. Do not delete observations or disable immutable-row protections to force an application rollback. Keep the compatible schema or restore the verified pre-upgrade backup into an isolated replacement deployment before switching services; restoring an older backup cannot preserve later work automatically.
