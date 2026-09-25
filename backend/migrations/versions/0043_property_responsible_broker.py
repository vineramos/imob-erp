"""responsible broker on property

Revision ID: 0043_property_responsible_broker
Revises: 0042_property_features
"""

from alembic import op
import sqlalchemy as sa

revision = "0043_property_responsible_broker"
down_revision = "0042_property_features"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "properties",
        sa.Column("responsible_broker_person_id", sa.UUID(), nullable=True),
    )
    op.create_index(
        "ix_properties_responsible_broker_person_id",
        "properties",
        ["responsible_broker_person_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_properties_responsible_broker_person_id_persons",
        "properties",
        "persons",
        ["responsible_broker_person_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_properties_responsible_broker_person_id_persons",
        "properties",
        type_="foreignkey",
    )
    op.drop_index("ix_properties_responsible_broker_person_id", table_name="properties")
    op.drop_column("properties", "responsible_broker_person_id")
