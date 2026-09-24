"""Add conservative Gmail read/session rates to app-managed default plans."""

import hashlib
import json
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0033_gmail_sessions"
down_revision = "0032_linkedin_connector"
branch_labels = None
depends_on = None

SESSION_OPERATIONS = ("COMPOSIO_SESSION_CREATE", "GMAIL_FETCH_EMAILS")


def upgrade() -> None:
    # Preserve immutable cards and historical run/reservation snapshots. Extend
    # only the app-managed default plan; retain all limits and existing rates.
    connection = op.get_bind()
    plans = (
        connection.execute(
            sa.text(
                "SELECT p.owner_id, c.rates FROM spending_policies p "
                "JOIN spending_rate_cards c ON c.id=p.active_rate_card_id "
                "WHERE c.name='Standard Developer Rates' AND c.source_label='Default Plan'"
            )
        )
        .mappings()
        .all()
    )
    for plan in plans:
        rates = plan["rates"]
        existing = {row["slug"] for row in rates["tools"]}
        additions = [
            {"slug": slug, "fixed_micros": 10_000}
            for slug in SESSION_OPERATIONS
            if slug not in existing
        ]
        if not additions:
            continue
        rates["tools"] = sorted(rates["tools"] + additions, key=lambda row: row["slug"])
        encoded = json.dumps(rates, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        card_id = connection.scalar(
            sa.text("SELECT id FROM spending_rate_cards WHERE owner_id=:owner AND sha256=:sha"),
            {"owner": plan["owner_id"], "sha": digest},
        )
        if card_id is None:
            card_id = uuid4()
            connection.execute(
                sa.text(
                    "INSERT INTO spending_rate_cards "
                    "(id,owner_id,name,source_label,currency,rates,sha256,created_at) "
                    "VALUES (:id,:owner,'Standard Developer Rates','Default Plan','USD',"
                    "CAST(:rates AS jsonb),:sha,now())"
                ),
                {"id": card_id, "owner": plan["owner_id"], "rates": encoded, "sha": digest},
            )
        connection.execute(
            sa.text(
                "UPDATE spending_policies SET active_rate_card_id=:card, "
                "row_version=row_version+1, updated_at=now() WHERE owner_id=:owner"
            ),
            {"card": card_id, "owner": plan["owner_id"]},
        )


def downgrade() -> None:
    # Retain immutable cost evidence and historical policy references.
    pass
