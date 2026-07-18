"""add meeting + meeting attendee models (team calendar scheduling)

Revision ID: a1f2c3d4e5b6
Revises: 768730e141fb
Create Date: 2026-06-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1f2c3d4e5b6'
down_revision = '768730e141fb'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('meeting',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=150), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('org_id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('scheduled_for', sa.DateTime(), nullable=False),
        sa.Column('duration_minutes', sa.Integer(), nullable=False),
        sa.Column('room_name', sa.String(length=120), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organization.id'], name=op.f('fk_meeting_org_id_organization')),
        sa.ForeignKeyConstraint(['project_id'], ['project.id'], name=op.f('fk_meeting_project_id_project')),
        sa.ForeignKeyConstraint(['created_by'], ['user.id'], name=op.f('fk_meeting_created_by_user')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_meeting'))
    )
    with op.batch_alter_table('meeting', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_meeting_org_id'), ['org_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_meeting_project_id'), ['project_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_meeting_scheduled_for'), ['scheduled_for'], unique=False)
        batch_op.create_index(batch_op.f('ix_meeting_created_by'), ['created_by'], unique=False)

    op.create_table('meeting_attendee',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('meeting_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('google_event_id', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['meeting_id'], ['meeting.id'], name=op.f('fk_meeting_attendee_meeting_id_meeting')),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], name=op.f('fk_meeting_attendee_user_id_user')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_meeting_attendee')),
        sa.UniqueConstraint('meeting_id', 'user_id', name='uq_meeting_attendee')
    )
    with op.batch_alter_table('meeting_attendee', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_meeting_attendee_meeting_id'), ['meeting_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_meeting_attendee_user_id'), ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('meeting_attendee', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_meeting_attendee_user_id'))
        batch_op.drop_index(batch_op.f('ix_meeting_attendee_meeting_id'))
    op.drop_table('meeting_attendee')

    with op.batch_alter_table('meeting', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_meeting_created_by'))
        batch_op.drop_index(batch_op.f('ix_meeting_scheduled_for'))
        batch_op.drop_index(batch_op.f('ix_meeting_project_id'))
        batch_op.drop_index(batch_op.f('ix_meeting_org_id'))
    op.drop_table('meeting')
