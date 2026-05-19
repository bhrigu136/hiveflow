"""add theme preference

Revision ID: 5c9d3a4f8e2b
Revises: 4b8c011c25c1
Create Date: 2026-05-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5c9d3a4f8e2b'
down_revision = '4b8c011c25c1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('theme_preference', sa.String(length=20), nullable=False, server_default='dark'))
    
    # Remove the server default so the Python model default takes over for new rows
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.alter_column('theme_preference', server_default=None)


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('theme_preference')
