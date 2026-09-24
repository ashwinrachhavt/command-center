"""Keep explicitly waiting business tasks separate from actionable work."""

import sqlalchemy as sa
from alembic import op

revision = "0037_task_waiting"
down_revision = "0036_email_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_tasks_state"), "tasks", type_="check")
    op.create_check_constraint(
        op.f("ck_tasks_state"),
        "tasks",
        "state IN ('open', 'in_progress', 'waiting', 'snoozed', 'done', 'cancelled')",
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM tasks WHERE state='waiting')")):
        raise RuntimeError("Resolve waiting tasks before downgrading")
    op.drop_constraint(op.f("ck_tasks_state"), "tasks", type_="check")
    op.create_check_constraint(
        op.f("ck_tasks_state"),
        "tasks",
        "state IN ('open', 'in_progress', 'snoozed', 'done', 'cancelled')",
    )
