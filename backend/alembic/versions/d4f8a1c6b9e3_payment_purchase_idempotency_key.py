"""payment purchase idempotency key — chave gerada pelo cliente (bot)
antes de chamar start_purchase, permite ao Backend detectar retry/duplo
clique/timeout ANTES de gerar uma nova cobranca no gateway (o UNIQUE
`provider`+`external_id` ja existente so protege depois que o gateway
responde, nao antes)

Revision ID: d4f8a1c6b9e3
Revises: c2f5e8a1d4b7
Create Date: 2026-08-07 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4f8a1c6b9e3'
down_revision: Union[str, None] = 'c2f5e8a1d4b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# idempotente de proposito, mesmo padrao de c2f5e8a1d4b7.
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("payment_history")}

    if "purchase_idempotency_key" not in columns:
        op.add_column(
            "payment_history", sa.Column("purchase_idempotency_key", sa.String(length=64), nullable=True)
        )
        op.create_index(
            "ix_payment_history_purchase_idempotency_key",
            "payment_history",
            ["purchase_idempotency_key"],
            unique=True,
        )


def downgrade() -> None:
    op.drop_index("ix_payment_history_purchase_idempotency_key", table_name="payment_history")
    op.drop_column("payment_history", "purchase_idempotency_key")
