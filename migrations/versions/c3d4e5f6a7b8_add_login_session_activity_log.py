"""add login_session + activity_log models (device/login tracking)

Revision ID: c3d4e5f6a7b8
Revises: a1f2c3d4e5b6
Create Date: 2026-06-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b8'
down_revision = 'a1f2c3d4e5b6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'login_session',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('session_token', sa.String(length=64), nullable=False),
        sa.Column('ip_address', sa.String(length=64), nullable=True),
        sa.Column('location', sa.String(length=150), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('browser', sa.String(length=80), nullable=True),
        sa.Column('os', sa.String(length=80), nullable=True),
        sa.Column('device', sa.String(length=40), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('last_seen', sa.DateTime(), nullable=True),
        sa.Column('revoked', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], name=op.f('fk_login_session_user_id_user')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_login_session')),
    )
    with op.batch_alter_table('login_session', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_login_session_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_login_session_session_token'), ['session_token'], unique=True)
        batch_op.create_index(batch_op.f('ix_login_session_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_login_session_last_seen'), ['last_seen'], unique=False)
        batch_op.create_index(batch_op.f('ix_login_session_revoked'), ['revoked'], unique=False)

    op.create_table(
        'activity_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(length=255), nullable=False),
        sa.Column('method', sa.String(length=10), nullable=True),
        sa.Column('path', sa.String(length=255), nullable=True),
        sa.Column('ip_address', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], name=op.f('fk_activity_log_user_id_user')),
        sa.ForeignKeyConstraint(['session_id'], ['login_session.id'], name=op.f('fk_activity_log_session_id_login_session')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_activity_log')),
    )
    with op.batch_alter_table('activity_log', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_activity_log_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_activity_log_session_id'), ['session_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_activity_log_created_at'), ['created_at'], unique=False)


def downgrade():
    with op.batch_alter_table('activity_log', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_activity_log_created_at'))
        batch_op.drop_index(batch_op.f('ix_activity_log_session_id'))
        batch_op.drop_index(batch_op.f('ix_activity_log_user_id'))
    op.drop_table('activity_log')

    with op.batch_alter_table('login_session', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_login_session_revoked'))
        batch_op.drop_index(batch_op.f('ix_login_session_last_seen'))
        batch_op.drop_index(batch_op.f('ix_login_session_created_at'))
        batch_op.drop_index(batch_op.f('ix_login_session_session_token'))
        batch_op.drop_index(batch_op.f('ix_login_session_user_id'))
    op.drop_table('login_session')
