from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from database.database import Database
from database.repositories.license_repository import LicenseRepository
from database.repositories.player_repository import PlayerRepository


@dataclass(frozen=True, slots=True)
class ReconciliationDivergence:
    """Resultado da comparacao entre membros de um cargo Discord (dados pelo
    bot, que e quem tem o cache de guild) e License ativa (autoridade do
    backend) para um product. O bot nunca resolve License/Player direto do
    banco — so aplica grant/revoke local com o resultado desta consulta."""

    revoke_discord_ids: list[int] = field(default_factory=list)
    active_license_discord_ids: list[int] = field(default_factory=list)


class PlayerService:
    """So a resolucao Player <-> discord_id que outros services precisam
    (ex.: `RoleSyncService` no bot, via `/internal/role-sync/targets`,
    Fase 5.6). Nao decide nada — Player e so a ponte entre a identidade
    global (License/Product) e o snowflake do Discord."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def get_discord_id(self, player_id: uuid.UUID) -> int | None:
        async with self._database.session() as session:
            player = await PlayerRepository(session).get_by_id(player_id)
            return player.discord_id if player is not None else None

    async def resolve_reconciliation_divergence(
        self, product_id: uuid.UUID, role_member_discord_ids: list[int]
    ) -> ReconciliationDivergence:
        """Equivalente as duas direcoes que `ReconciliationService._reconcile_plan`
        (bot) fazia direto no banco (Fase 5.6 fechou o gap so pro caminho de
        evento; este metodo fecha o gap da reconciliacao em lote, mesmas duas
        queries batched, zero N+1)."""
        async with self._database.session() as session:
            player_repo = PlayerRepository(session)
            license_repo = LicenseRepository(session)

            players_by_discord_id = {
                p.discord_id: p for p in await player_repo.list_by_discord_ids(role_member_discord_ids)
            }
            player_ids_with_role = [p.id for p in players_by_discord_id.values()]
            player_ids_with_active_license = {
                lic.player_id
                for lic in await license_repo.list_active_by_players_and_product(player_ids_with_role, product_id)
            }
            revoke_discord_ids = [
                discord_id
                for discord_id, player in players_by_discord_id.items()
                if player.id not in player_ids_with_active_license
            ]
            revoke_discord_ids += [
                discord_id for discord_id in role_member_discord_ids if discord_id not in players_by_discord_id
            ]

            active_licenses = await license_repo.list_active_by_product(product_id)
            active_players_by_id = {
                p.id: p for p in await player_repo.list_by_ids([lic.player_id for lic in active_licenses])
            }
            active_license_discord_ids = [
                p.discord_id for p in active_players_by_id.values()
            ]

        return ReconciliationDivergence(
            revoke_discord_ids=revoke_discord_ids,
            active_license_discord_ids=active_license_discord_ids,
        )
