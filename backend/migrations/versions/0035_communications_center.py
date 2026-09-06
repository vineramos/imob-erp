"""communication center, queue and preferences

Revision ID: 0035_communications_center
Revises: 0034_lease_exit_settlement
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0035_communications_center"
down_revision = "0034_lease_exit_settlement"
branch_labels = None
depends_on = None


PERMISSIONS = (
    ("communications.view", "Visualizar comunicações", "Permite consultar fila, histórico, modelos e preferências de comunicação."),
    ("communications.manage", "Gerenciar comunicações", "Permite criar, editar, cancelar e preparar comunicações e modelos."),
    ("communications.send", "Enviar comunicações", "Permite confirmar envio e reenvio por provedores externos configurados."),
)


def upgrade() -> None:
    op.create_table(
        "communication_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("channel", sa.String(length=30), nullable=False, server_default="email"),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("subject_template", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_system_default", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "key", "channel", name="uq_communication_templates_org_key_channel"),
    )
    op.create_index("ix_communication_templates_organization_id", "communication_templates", ["organization_id"])
    op.create_index("ix_communication_templates_key", "communication_templates", ["key"])
    op.create_index("ix_communication_templates_channel", "communication_templates", ["channel"])

    op.create_table(
        "communication_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("whatsapp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("transactional_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("preferred_channel", sa.String(length=30), nullable=False, server_default="email"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "person_id", name="uq_communication_preferences_org_person"),
    )
    op.create_index("ix_communication_preferences_organization_id", "communication_preferences", ["organization_id"])
    op.create_index("ix_communication_preferences_person_id", "communication_preferences", ["person_id"])

    op.create_table(
        "communication_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("internal_number", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recipient_name", sa.String(length=180), nullable=False),
        sa.Column("recipient_email", sa.String(length=180), nullable=True),
        sa.Column("recipient_phone", sa.String(length=50), nullable=True),
        sa.Column("recipient_role", sa.String(length=30), nullable=False, server_default="other"),
        sa.Column("channel", sa.String(length=30), nullable=False, server_default="email"),
        sa.Column("category", sa.String(length=80), nullable=False, server_default="manual"),
        sa.Column("origin", sa.String(length=30), nullable=False, server_default="manual"),
        sa.Column("subject", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("source_module", sa.String(length=80), nullable=True),
        sa.Column("source_type", sa.String(length=80), nullable=True),
        sa.Column("source_id", sa.String(length=180), nullable=True),
        sa.Column("dedupe_key", sa.String(length=300), nullable=True),
        sa.Column("attachment_manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("provider_name", sa.String(length=80), nullable=True),
        sa.Column("provider_message_id", sa.String(length=220), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("suggested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sent_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["app_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sent_by_user_id"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("internal_number"),
        sa.UniqueConstraint("organization_id", "dedupe_key", name="uq_communication_messages_org_dedupe"),
    )
    for column in (
        "organization_id", "person_id", "recipient_email", "recipient_role", "channel", "category", "origin", "status",
        "source_module", "source_type", "source_id", "suggested_at", "sent_at", "failed_at", "cancelled_at", "created_at",
    ):
        op.create_index(f"ix_communication_messages_{column}", "communication_messages", [column])

    op.create_table(
        "communication_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("event_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["communication_messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_communication_events_organization_id", "communication_events", ["organization_id"])
    op.create_index("ix_communication_events_message_id", "communication_events", ["message_id"])
    op.create_index("ix_communication_events_event_type", "communication_events", ["event_type"])
    op.create_index("ix_communication_events_created_at", "communication_events", ["created_at"])

    connection = op.get_bind()
    for key, name, description in PERMISSIONS:
        connection.execute(
            sa.text(
                "INSERT INTO permissions (id, key, module, name, description) "
                "VALUES (gen_random_uuid(), :key, 'communications', :name, :description) "
                "ON CONFLICT (key) DO UPDATE SET module = EXCLUDED.module, name = EXCLUDED.name, description = EXCLUDED.description"
            ),
            {"key": key, "name": name, "description": description},
        )
    connection.execute(
        sa.text(
            "INSERT INTO role_permissions (id, role_id, permission_id) "
            "SELECT gen_random_uuid(), r.id, p.id FROM roles r JOIN permissions p ON p.module = 'communications' "
            "WHERE r.key IN ('admin', 'administrative', 'finance') "
            "AND NOT EXISTS (SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id)"
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE key IN ('communications.view','communications.manage','communications.send'))"
        )
    )
    connection.execute(
        sa.text("DELETE FROM permissions WHERE key IN ('communications.view','communications.manage','communications.send')")
    )
    op.drop_table("communication_events")
    op.drop_table("communication_messages")
    op.drop_table("communication_preferences")
    op.drop_table("communication_templates")
