"""add meeting intelligence (transcript segments, summary, action items)

Revision ID: b2c3d4e5f6a7
Revises: c3d4e5f6a7b8
Create Date: 2026-06-21 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade():
    # ── New table: transcript_segment ──────────────────────────────────────
    op.create_table('transcript_segment',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('meeting_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('is_final', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('seq', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['meeting_id'], ['meeting.id'], name=op.f('fk_transcript_segment_meeting_id_meeting')),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], name=op.f('fk_transcript_segment_user_id_user')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_transcript_segment')),
        sa.UniqueConstraint('meeting_id', 'user_id', 'seq', name='uq_segment_meeting_user_seq')
    )
    with op.batch_alter_table('transcript_segment', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_transcript_segment_meeting_id'), ['meeting_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_transcript_segment_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_transcript_segment_started_at'), ['started_at'], unique=False)

    # ── New columns on meeting (all additive; existing rows unaffected) ─────
    # Plain add_column is native on both SQLite (ADD COLUMN) and Postgres, so
    # we avoid a full table rebuild.
    op.add_column('meeting', sa.Column('transcript_full', sa.Text(), nullable=True))
    op.add_column('meeting', sa.Column('summary', sa.Text(), nullable=True))
    op.add_column('meeting', sa.Column('action_items', sa.Text(), nullable=True))
    op.add_column('meeting', sa.Column('decisions', sa.Text(), nullable=True))
    op.add_column('meeting', sa.Column('intel_status', sa.String(length=20), nullable=False, server_default='none'))
    op.add_column('meeting', sa.Column('summarized_at', sa.DateTime(), nullable=True))
    op.add_column('meeting', sa.Column('summarizer_engine', sa.String(length=20), nullable=True))
    op.create_index(op.f('ix_meeting_intel_status'), 'meeting', ['intel_status'], unique=False)

    # ── New column on task: link a converted task back to its meeting ──────
    # Shipped as a plain indexed Integer (no DB-level FK) to keep the change
    # safe on the existing, populated SQLite task table. The ORM relationship
    # in models.py still declares the foreign key for joins.
    op.add_column('task', sa.Column('source_meeting_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_task_source_meeting_id'), 'task', ['source_meeting_id'], unique=False)


def downgrade():
    with op.batch_alter_table('task', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_task_source_meeting_id'))
        batch_op.drop_column('source_meeting_id')

    with op.batch_alter_table('meeting', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_meeting_intel_status'))
        batch_op.drop_column('summarizer_engine')
        batch_op.drop_column('summarized_at')
        batch_op.drop_column('intel_status')
        batch_op.drop_column('decisions')
        batch_op.drop_column('action_items')
        batch_op.drop_column('summary')
        batch_op.drop_column('transcript_full')

    with op.batch_alter_table('transcript_segment', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_transcript_segment_started_at'))
        batch_op.drop_index(batch_op.f('ix_transcript_segment_user_id'))
        batch_op.drop_index(batch_op.f('ix_transcript_segment_meeting_id'))
    op.drop_table('transcript_segment')
