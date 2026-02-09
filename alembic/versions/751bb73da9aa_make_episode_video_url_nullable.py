"""make_episode_video_url_nullable

Revision ID: 751bb73da9aa
Revises: e71b43455b3f
Create Date: 2026-02-04 00:13:19.415869

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '751bb73da9aa'
down_revision: Union[str, None] = 'e71b43455b3f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade():
    op.alter_column("episodes", "video_url",
        existing_type=sa.String(length=500),
        nullable=True
    )

def downgrade():
    op.alter_column("episodes", "video_url",
        existing_type=sa.String(length=500),
        nullable=False
    )
