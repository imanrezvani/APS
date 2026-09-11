"""phase 10 baseline (empty foundation revision)

Revision ID: 0001_phase10_baseline
Revises:
Create Date: 2026-09-11

The Phase 10 P1 foundation introduces the migration system itself. This
baseline revision intentionally creates no tables; the persistence models
are added in the S10-P2 revision. Keeping an explicit baseline revision
means every database can be stamped/upgraded deterministically.
"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "0001_phase10_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
