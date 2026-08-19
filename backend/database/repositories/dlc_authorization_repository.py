"""
dlc_authorization_repository.py
=================================

O metodo `consume_atomically` e o coracao do anti-replay real (ponto 14).
Nao faz "SELECT status, checa em Python, depois UPDATE" -- isso teria uma
race condition classica (duas requisicoes simultaneas com o mesmo token
poderiam ambas passar no SELECT antes de qualquer UPDATE acontecer). Em vez
disso, faz um UPDATE condicional numa unica ida ao banco: só a primeira
chamada que bater na linha com status=ISSUED consegue mudar pra CONSUMED;
qualquer chamada concorrente ou posterior encontra 0 linhas afetadas.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update

from database.models.dlc_authorization import DlcAuthorization, DlcAuthorizationStatus
from database.repositories.base_repository import BaseRepository


class DlcAuthorizationRepository(BaseRepository[DlcAuthorization]):
    model = DlcAuthorization

    async def get_by_jti(self, jti: str) -> DlcAuthorization | None:
        result = await self.session.execute(select(DlcAuthorization).where(DlcAuthorization.jti == jti))
        return result.scalar_one_or_none()

    async def consume_atomically(self, jti: str, *, now: datetime) -> bool:
        """Tenta transicionar ISSUED -> CONSUMED pra este jti, SO SE ainda
        nao expirou. Retorna True se esta chamada foi quem consumiu (ou
        seja: pode liberar a chave). Retorna False se: o jti nao existe, ja
        foi consumido antes (replay), ou ja expirou -- em qualquer um
        desses casos, NUNCA libere a chave.
        """
        result = await self.session.execute(
            update(DlcAuthorization)
            .where(
                DlcAuthorization.jti == jti,
                DlcAuthorization.status == DlcAuthorizationStatus.ISSUED,
                DlcAuthorization.expires_at > now,
            )
            .values(status=DlcAuthorizationStatus.CONSUMED, consumed_at=now)
        )
        # rowcount == 1 significa que esta chamada especifica venceu a corrida
        # e fez a transicao. rowcount == 0 significa que outra requisicao ja
        # consumiu, ou o registro nao satisfaz mais a condicao (expirado).
        return result.rowcount == 1

    async def expire_stale(self, *, now: datetime, limit: int = 500) -> int:
        """Job de limpeza periodica (rodar a cada poucos minutos, ex. via
        scheduler que ja existe no bot/backend): marca como EXPIRED
        autorizacoes ISSUED cujo TTL passou e nunca foram consumidas. Nao e
        estritamente necessario pra seguranca (consume_atomically ja rejeita
        pela condicao expires_at > now), mas mantem a tabela limpa/auditavel
        e evita a ilusao de "autorizacoes pendentes" acumulando pra sempre.
        """
        result = await self.session.execute(
            update(DlcAuthorization)
            .where(
                DlcAuthorization.status == DlcAuthorizationStatus.ISSUED,
                DlcAuthorization.expires_at <= now,
            )
            .values(status=DlcAuthorizationStatus.EXPIRED)
        )
        return result.rowcount or 0
