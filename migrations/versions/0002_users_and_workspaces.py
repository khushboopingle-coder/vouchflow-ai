"""users and workspaces (Phase 2)

- new tables: users (login accounts, bcrypt hashes only) and workspaces
- workspace_id column (+ index + named foreign key) on suppliers, contracts,
  purchase_orders, goods_received_notes, invoices, invoice_decisions and audit_logs
- PO and GRN numbers become unique PER WORKSPACE (were unique in the whole database)
- data: creates the workspace "sample" and assigns ALL existing rows to it

Portable: runs on SQLite (batch mode) and PostgreSQL.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-05 00:06:53.064844

"""
from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCOPED_TABLES = [
    "suppliers",
    "contracts",
    "purchase_orders",
    "goods_received_notes",
    "invoices",
    "invoice_decisions",
    "audit_logs",
]
SAMPLE_WORKSPACE_NAME = "sample"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_email'), ['email'], unique=True)
        batch_op.create_index(batch_op.f('ix_users_id'), ['id'], unique=False)

    op.create_table('workspaces',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('owner_user_id', sa.Integer(), nullable=True),
    sa.Column('is_sample', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], name='fk_workspaces_owner_user_id_users'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('workspaces', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_workspaces_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_workspaces_owner_user_id'), ['owner_user_id'], unique=True)

    for table in SCOPED_TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column('workspace_id', sa.Integer(), nullable=True))
            batch_op.create_index(batch_op.f(f'ix_{table}_workspace_id'), ['workspace_id'], unique=False)
            batch_op.create_foreign_key(f'fk_{table}_workspace_id_workspaces', 'workspaces',
                                        ['workspace_id'], ['id'])

    # PO / GRN numbers: unique per workspace instead of database-wide
    for table, column in (("purchase_orders", "po_number"), ("goods_received_notes", "grn_number")):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_index(batch_op.f(f'ix_{table}_{column}'))
            batch_op.create_index(batch_op.f(f'ix_{table}_{column}'), [column], unique=False)
            batch_op.create_unique_constraint(f'uq_{table}_workspace_{column}', ['workspace_id', column])

    # ---- data: every existing row belongs to the "sample" workspace ----
    bind = op.get_bind()
    workspaces = sa.table(
        'workspaces',
        sa.column('id', sa.Integer), sa.column('name', sa.String),
        sa.column('owner_user_id', sa.Integer), sa.column('is_sample', sa.Boolean),
        sa.column('created_at', sa.DateTime),
    )
    bind.execute(workspaces.insert().values(
        name=SAMPLE_WORKSPACE_NAME, owner_user_id=None, is_sample=True, created_at=datetime.utcnow(),
    ))
    sample_id = bind.execute(
        sa.select(workspaces.c.id).where(workspaces.c.is_sample.is_(True)).order_by(workspaces.c.id)
    ).scalars().first()
    for table in SCOPED_TABLES:
        t = sa.table(table, sa.column('workspace_id', sa.Integer))
        bind.execute(t.update().where(t.c.workspace_id.is_(None)).values(workspace_id=sample_id))


def downgrade() -> None:
    """Downgrade schema (removes workspaces and users; the data rows stay)."""
    for table, column in (("purchase_orders", "po_number"), ("goods_received_notes", "grn_number")):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_constraint(f'uq_{table}_workspace_{column}', type_='unique')
            batch_op.drop_index(batch_op.f(f'ix_{table}_{column}'))
            batch_op.create_index(batch_op.f(f'ix_{table}_{column}'), [column], unique=True)
    for table in reversed(SCOPED_TABLES):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_constraint(f'fk_{table}_workspace_id_workspaces', type_='foreignkey')
            batch_op.drop_index(batch_op.f(f'ix_{table}_workspace_id'))
            batch_op.drop_column('workspace_id')

    with op.batch_alter_table('workspaces', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_workspaces_owner_user_id'))
        batch_op.drop_index(batch_op.f('ix_workspaces_id'))
    op.drop_table('workspaces')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_id'))
        batch_op.drop_index(batch_op.f('ix_users_email'))
    op.drop_table('users')
