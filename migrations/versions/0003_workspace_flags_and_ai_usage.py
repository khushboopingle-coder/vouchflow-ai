"""workspace flags and ai usage (Phase 3)

- workspaces.sample_loaded / workspaces.has_user_data: drive the "Demo data" vs
  "Live workspace" badge and banner (demo = sample loaded and nothing the user added)
- ai_usage: real Gemini explanations per user per day (limit 5)
- data: existing user workspaces that already hold invoices got them from the sample copy
  (Phase 2), so they start with sample_loaded = true

Portable: runs on SQLite (batch mode) and PostgreSQL. New NOT NULL columns get a server
default so tables that already have rows can be altered.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-05 01:40:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('ai_usage',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('count', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_ai_usage_user_id_users'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'day', name='uq_ai_usage_user_day')
    )
    with op.batch_alter_table('ai_usage', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ai_usage_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ai_usage_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('workspaces', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sample_loaded', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('has_user_data', sa.Boolean(), nullable=False, server_default=sa.false()))

    # user workspaces that already have invoices got them from the sample copy
    bind = op.get_bind()
    workspaces = sa.table('workspaces', sa.column('id', sa.Integer), sa.column('is_sample', sa.Boolean),
                          sa.column('sample_loaded', sa.Boolean))
    invoices = sa.table('invoices', sa.column('workspace_id', sa.Integer))
    has_invoices = sa.exists().where(invoices.c.workspace_id == workspaces.c.id)
    bind.execute(workspaces.update().where(workspaces.c.is_sample.is_(False)).where(has_invoices)
                 .values(sample_loaded=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('workspaces', schema=None) as batch_op:
        batch_op.drop_column('has_user_data')
        batch_op.drop_column('sample_loaded')

    with op.batch_alter_table('ai_usage', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ai_usage_user_id'))
        batch_op.drop_index(batch_op.f('ix_ai_usage_id'))
    op.drop_table('ai_usage')
