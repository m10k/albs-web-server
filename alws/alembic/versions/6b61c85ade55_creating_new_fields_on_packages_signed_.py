"""Creating new fields on packages: signed_by_key

Revision ID: 6b61c85ade55
Revises: aa0a3bdf68d4
Create Date: 2022-01-17 14:49:42.284932

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6b61c85ade55'
down_revision = 'aa0a3bdf68d4'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('binary_rpms', sa.Column('signed_by_key_id', sa.Integer(), nullable=True))
    op.create_foreign_key(None, 'binary_rpms', 'sign_keys', ['signed_by_key_id'], ['id'])
    op.add_column('source_rpms', sa.Column('signed_by_key_id', sa.Integer(), nullable=True))
    op.create_foreign_key(None, 'source_rpms', 'sign_keys', ['signed_by_key_id'], ['id'])
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(None, 'source_rpms', type_='foreignkey')
    op.drop_column('source_rpms', 'signed_by_key_id')
    op.drop_constraint(None, 'binary_rpms', type_='foreignkey')
    op.drop_column('binary_rpms', 'signed_by_key_id')
    # ### end Alembic commands ###
