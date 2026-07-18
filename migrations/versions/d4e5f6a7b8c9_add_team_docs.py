"""add team docs / wiki (document, document_revision, file_attachment.document_id)

Revision ID: d4e5f6a7b8c9
Revises: b2c3d4e5f6a7
Create Date: 2026-06-21 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c9'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


# tsvector on Postgres, plain Text elsewhere — keeps the column portable.
_SEARCH_VECTOR = sa.Text().with_variant(postgresql.TSVECTOR(), 'postgresql')


def upgrade():
    # ── document ────────────────────────────────────────────────────────────
    op.create_table('document',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('org_id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=False, server_default='Untitled'),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('content_html', sa.Text(), nullable=True),
        sa.Column('content_text', sa.Text(), nullable=True),
        sa.Column('parent_id', sa.Integer(), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_archived', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('search_vector', _SEARCH_VECTOR, nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organization.id'], name=op.f('fk_document_org_id_organization')),
        sa.ForeignKeyConstraint(['project_id'], ['project.id'], name=op.f('fk_document_project_id_project')),
        sa.ForeignKeyConstraint(['parent_id'], ['document.id'], name=op.f('fk_document_parent_id_document')),
        sa.ForeignKeyConstraint(['created_by'], ['user.id'], name=op.f('fk_document_created_by_user')),
        sa.ForeignKeyConstraint(['updated_by'], ['user.id'], name=op.f('fk_document_updated_by_user')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_document'))
    )
    with op.batch_alter_table('document', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_document_org_id'), ['org_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_document_project_id'), ['project_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_document_parent_id'), ['parent_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_document_is_archived'), ['is_archived'], unique=False)
        batch_op.create_index('ix_document_org_parent_sort', ['org_id', 'parent_id', 'sort_order'], unique=False)

    # GIN index for full-text search — Postgres only.
    if op.get_bind().dialect.name == 'postgresql':
        op.create_index('ix_document_search_vector', 'document', ['search_vector'],
                        unique=False, postgresql_using='gin')

    # ── document_revision ─────────────────────────────────────────────────────
    op.create_table('document_revision',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=True),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('edited_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['document_id'], ['document.id'], name=op.f('fk_document_revision_document_id_document')),
        sa.ForeignKeyConstraint(['edited_by'], ['user.id'], name=op.f('fk_document_revision_edited_by_user')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_document_revision'))
    )
    with op.batch_alter_table('document_revision', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_document_revision_document_id'), ['document_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_document_revision_created_at'), ['created_at'], unique=False)

    # ── file_attachment.document_id ───────────────────────────────────────────
    op.add_column('file_attachment', sa.Column('document_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_file_attachment_document_id'), 'file_attachment', ['document_id'], unique=False)


def downgrade():
    with op.batch_alter_table('file_attachment', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_file_attachment_document_id'))
        batch_op.drop_column('document_id')

    with op.batch_alter_table('document_revision', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_document_revision_created_at'))
        batch_op.drop_index(batch_op.f('ix_document_revision_document_id'))
    op.drop_table('document_revision')

    if op.get_bind().dialect.name == 'postgresql':
        op.drop_index('ix_document_search_vector', table_name='document')
    with op.batch_alter_table('document', schema=None) as batch_op:
        batch_op.drop_index('ix_document_org_parent_sort')
        batch_op.drop_index(batch_op.f('ix_document_is_archived'))
        batch_op.drop_index(batch_op.f('ix_document_parent_id'))
        batch_op.drop_index(batch_op.f('ix_document_project_id'))
        batch_op.drop_index(batch_op.f('ix_document_org_id'))
    op.drop_table('document')
