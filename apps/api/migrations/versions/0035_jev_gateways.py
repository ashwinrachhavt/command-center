"""Add Jev gateway rates without changing historical cost records."""

import hashlib
import json
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0035_jev_gateways"
down_revision = "0034_routing_rates"
branch_labels = None
depends_on = None

MODEL_RATES = [
    {
        "provider": provider,
        "model": model,
        "input_per_million_micros": incoming,
        "output_per_million_micros": outgoing,
        "fixed_micros": 0,
    }
    for provider, model, incoming, outgoing in (
        ("gateway", "typesafe-ai/jev", 42_000, 0),
        ("venice", "jev-latest", 42_000, 0),
    )
]


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
        existing = {(row["provider"], row["model"]) for row in rates["models"]}
        additions = [row for row in MODEL_RATES if (row["provider"], row["model"]) not in existing]
        if not additions:
            continue
        rates["models"] = sorted(
            rates["models"] + additions, key=lambda row: (row["provider"], row["model"])
        )
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
