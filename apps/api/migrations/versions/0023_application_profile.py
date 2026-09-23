"""Explicit identity and address fields for application autofill."""

import sqlalchemy as sa
from alembic import op

revision = "0023_application_profile"
down_revision = "0022_record_work"
branch_labels = None
depends_on = None

SCALAR = "'full_name', 'email', 'phone', 'location', 'headline', 'website', 'linkedin', 'summary'"
CAREER = (
    "'skill', 'experience', 'education', 'answer', 'certification', 'project', 'course', "
    "'language', 'publication', 'recommendation'"
)
ADDED = (
    "'first_name', 'last_name', 'address_line1', 'address_line2', "
    "'city', 'region', 'postal_code', 'country', 'github'"
)


def change(fields: str, scalar: str) -> None:
    op.drop_constraint(op.f("ck_profile_facts_field"), "profile_facts", type_="check")
    op.create_check_constraint(
        op.f("ck_profile_facts_field"), "profile_facts", f"field IN ({fields})"
    )
    op.drop_index("uq_profile_facts_active_scalar", table_name="profile_facts")
    op.create_index(
        "uq_profile_facts_active_scalar",
        "profile_facts",
        ["owner_id", "field"],
        unique=True,
        postgresql_where=sa.text(f"active_revision_id IS NOT NULL AND field IN ({scalar})"),
    )


def upgrade() -> None:
    change(f"{SCALAR}, {CAREER}, {ADDED}", f"{SCALAR}, {ADDED}")
    op.drop_constraint(
        op.f("uq_application_preparations_task_id"), "application_preparations", type_="unique"
    )
    op.create_index(
        op.f("ix_application_preparations_task_id"), "application_preparations", ["task_id"]
    )


def downgrade() -> None:
    count = (
        op.get_bind()
        .execute(sa.text(f"SELECT count(*) FROM profile_facts WHERE field IN ({ADDED})"))
        .scalar_one()
    )
    if count:
        raise RuntimeError(
            "Application profile facts exist; refusing to drop their allowed fields."
        )
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM application_preparations "
                "GROUP BY task_id HAVING count(*) > 1 LIMIT 1"
            )
        )
        .first()
    ):
        raise RuntimeError(
            "Continued application captures exist; refusing to discard their history."
        )
    op.drop_index(
        op.f("ix_application_preparations_task_id"), table_name="application_preparations"
    )
    op.create_unique_constraint(
        op.f("uq_application_preparations_task_id"), "application_preparations", ["task_id"]
    )
    change(f"{SCALAR}, {CAREER}", SCALAR)
