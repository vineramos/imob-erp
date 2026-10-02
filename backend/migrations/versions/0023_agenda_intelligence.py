"""agenda intelligence hierarchy availability meetings and immutable history

Revision ID: 0023_agenda_intelligence
Revises: 0022_agenda_tasks
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_agenda_intelligence"
down_revision: str | None = "0022_agenda_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _index(table: str, *columns: str) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column], unique=False)


def upgrade() -> None:
    op.create_table(
        "agenda_departments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "name", name="uq_agenda_departments_org_name"),
    )
    _index("agenda_departments", "organization_id", "is_active")

    op.create_table(
        "agenda_user_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("department_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agenda_departments.id", ondelete="SET NULL")),
        sa.Column("access_level", sa.String(20), nullable=False, server_default="collaborator"),
        sa.Column("work_start", sa.String(5), nullable=False, server_default="08:30"),
        sa.Column("work_end", sa.String(5), nullable=False, server_default="18:00"),
        sa.Column("lunch_start", sa.String(5), server_default="12:00"),
        sa.Column("lunch_end", sa.String(5), server_default="13:00"),
        sa.Column("work_days", postgresql.JSONB(), nullable=False, server_default=sa.text("'[0,1,2,3,4]'::jsonb")),
        sa.Column("buffer_minutes", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("default_duration_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("timezone", sa.String(60), nullable=False, server_default="America/Sao_Paulo"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", name="uq_agenda_user_profiles_user"),
    )
    _index("agenda_user_profiles", "organization_id", "user_id", "department_id", "access_level")

    op.create_table(
        "agenda_delegations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("delegate_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("can_view_availability", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("can_view_details", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_create", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_reschedule", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("owner_user_id", "delegate_user_id", name="uq_agenda_delegations_owner_delegate"),
    )
    _index("agenda_delegations", "organization_id", "owner_user_id", "delegate_user_id")

    with op.batch_alter_table("agenda_tasks") as batch:
        batch.add_column(sa.Column("kind", sa.String(30), nullable=False, server_default="task"))
        batch.add_column(sa.Column("ends_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("privacy", sa.String(20), nullable=False, server_default="normal"))
        batch.add_column(sa.Column("location", sa.String(300)))
        batch.add_column(sa.Column("department_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agenda_departments.id", ondelete="SET NULL")))
        batch.add_column(sa.Column("automatic", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("mandatory_action", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("completion_source", sa.String(20), nullable=False, server_default="agenda"))
        batch.add_column(sa.Column("original_scheduled_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("original_task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agenda_tasks.id", ondelete="SET NULL")))
        batch.add_column(sa.Column("previous_task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agenda_tasks.id", ondelete="SET NULL")))
        batch.add_column(sa.Column("reschedule_sequence", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("missed_justification", sa.Text()))
        batch.add_column(sa.Column("missed_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("immutable_history", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("recurrence_group_id", postgresql.UUID(as_uuid=True)))
        batch.add_column(sa.Column("recurrence_sequence", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("recurrence_rule", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
        batch.create_unique_constraint("uq_agenda_tasks_system_occurrence", ["organization_id", "source_type", "source_id", "original_scheduled_at", "reschedule_sequence"])
    _index("agenda_tasks", "kind", "ends_at", "privacy", "department_id", "automatic", "mandatory_action", "original_scheduled_at", "original_task_id", "previous_task_id", "recurrence_group_id")

    op.create_table(
        "agenda_meeting_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("internal_number", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("organizer_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id"), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("privacy", sa.String(20), nullable=False, server_default="normal"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("selected_option_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    _index("agenda_meeting_requests", "organization_id", "organizer_user_id", "status", "selected_option_id")

    op.create_table(
        "agenda_meeting_participants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("meeting_request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agenda_meeting_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("responded_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("meeting_request_id", "user_id", name="uq_agenda_meeting_participant_user"),
    )
    _index("agenda_meeting_participants", "meeting_request_id", "user_id")

    op.create_table(
        "agenda_meeting_options",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("meeting_request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agenda_meeting_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("proposed_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    _index("agenda_meeting_options", "meeting_request_id", "starts_at", "status")

    op.create_table(
        "agenda_meeting_votes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("meeting_option_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agenda_meeting_options.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("meeting_option_id", "user_id", name="uq_agenda_meeting_vote_user"),
    )
    _index("agenda_meeting_votes", "meeting_option_id", "user_id")

    op.create_table(
        "agenda_daily_briefings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("briefing_date", sa.Date(), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "briefing_date", name="uq_agenda_daily_briefing_user_date"),
    )
    _index("agenda_daily_briefings", "organization_id", "user_id", "briefing_date")


def downgrade() -> None:
    op.drop_table("agenda_daily_briefings")
    op.drop_table("agenda_meeting_votes")
    op.drop_table("agenda_meeting_options")
    op.drop_table("agenda_meeting_participants")
    op.drop_table("agenda_meeting_requests")
    with op.batch_alter_table("agenda_tasks") as batch:
        batch.drop_constraint("uq_agenda_tasks_system_occurrence", type_="unique")
        for column in ("recurrence_rule", "recurrence_sequence", "recurrence_group_id", "immutable_history", "missed_at", "missed_justification", "reschedule_sequence", "previous_task_id", "original_task_id", "original_scheduled_at", "completion_source", "mandatory_action", "automatic", "department_id", "location", "privacy", "ends_at", "kind"):
            batch.drop_column(column)
    op.drop_table("agenda_delegations")
    op.drop_table("agenda_user_profiles")
    op.drop_table("agenda_departments")
