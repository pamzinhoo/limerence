"""
dlc_authorization.py
=====================

Tabela nova, dedicada ao anti-replay REAL de autorizacao de DLC (ponto 14
do pedido: "nao considerar implementado se existir apenas um TODO").

Por que uma tabela separada e nao so um campo em License
-----------------------------------------------------------
License representa POSSE (permanente, de longo prazo). DlcAuthorization
representa um EVENTO pontual: "o backend concedeu, nesta janela curta, o
direito de buscar o material criptografico de uma DLC especifica, pra um
player especifico". Cada tentativa de autorizacao cria uma linha nova. O
`jti` e unico (constraint de banco, nao so verificacao em codigo) e o
status so pode andar ISSUED -> CONSUMED (ou -> EXPIRED por limpeza), nunca
volta. Isso da uma trilha de auditoria completa de toda autorizacao emitida
E de toda tentativa de reuso (rejeitada, mas registrada).

Segue exatamente a convencao do resto do backend (UUIDPrimaryKeyMixin,
TimestampMixin, Base) — ver database/models/license.py e
database/models/product.py, que foram lidos antes de escrever este model.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DlcAuthorizationStatus(enum.Enum):
    ISSUED = "issued"      # autorizacao emitida, ainda nao usada
    CONSUMED = "consumed"  # material criptografico ja foi entregue (uso unico)
    EXPIRED = "expired"    # passou do TTL sem ser consumida (limpeza periodica)


class DlcAuthorization(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """1 linha por tentativa de autorizacao de DLC. `jti` e o identificador
    que o launcher recebe dentro do token de autorizacao (JWT) — o token em
    si NUNCA carrega a chave (ponto 7 do pedido). Pra obter o material
    criptografico de verdade, o launcher tem que apresentar esse token no
    endpoint /material, que so entrega a chave se conseguir fazer a
    transicao atomica ISSUED -> CONSUMED nesta tabela. Se a transicao
    falhar (0 linhas afetadas), a chave nunca e devolvida — isso cobre
    tanto reuso do mesmo token (ataque 7) quanto token expirado.
    """

    __tablename__ = "dlc_authorizations"
    __table_args__ = (
        Index("ix_dlc_authorizations_jti", "jti", unique=True),
    )

    player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )

    jti: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[DlcAuthorizationStatus] = mapped_column(
        Enum(DlcAuthorizationStatus, name="dlc_authorization_status"),
        nullable=False,
        default=DlcAuthorizationStatus.ISSUED,
        index=True,
    )

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # De qual sessao de launcher veio o pedido -- util pra auditoria/abuso
    # (ex.: mesma sessao pedindo autorizacao de dezenas de DLCs em segundos).
    session_id: Mapped[str | None] = mapped_column(String(100))
