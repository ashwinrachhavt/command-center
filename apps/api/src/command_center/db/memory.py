from sqlalchemy import CheckConstraint, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from command_center.db.base import Base
from command_center.db.crm import OwnedRecord


class MemoryItem(OwnedRecord, Base):
    """Workspace context, never an authorization grant or a verified candidate fact."""

    __tablename__ = "memory_items"
    __table_args__ = (
        CheckConstraint("kind IN ('note', 'preference')", name="kind"),
        CheckConstraint("source IN ('human', 'agent')", name="source"),
    )
    editable = frozenset({"title", "content", "kind"})
    required_text = frozenset({"title", "content", "kind"})
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20), default="note")
    source: Mapped[str] = mapped_column(String(20), default="human")
