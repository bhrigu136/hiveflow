"""add task.completed_at (for analytics velocity / cycle-time)

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-21 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('task', sa.Column('completed_at', sa.DateTime(), nullable=True))
    op.create_index(op.f('ix_task_completed_at'), 'task', ['completed_at'], unique=False)
    # Backfill: existing completed tasks get their created_at as a stand-in so
    # historical velocity charts aren't empty on day one.
    op.execute("UPDATE task SET completed_at = created_at "
               "WHERE status = 'Completed' AND completed_at IS NULL")


def downgrade():
    with op.batch_alter_table('task', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_task_completed_at'))
        batch_op.drop_column('completed_at')
