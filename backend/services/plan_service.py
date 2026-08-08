from __future__ import annotations

import uuid

from core.logger import get_logger
from database.database import Database
from database.models.plan import Plan
from database.models.plan_benefit import PlanBenefit
from database.models.plan_message import PlanMessage, PlanMessageType
from database.repositories.plan_repository import (
    PlanBenefitRepository,
    PlanMessageRepository,
    PlanRepository,
)
from database.repositories.vote_weight_repository import VoteWeightRepository

logger = get_logger("plan_service")

# `render_placeholders` (formatacao de mensagem Discord com mention/embed) e
# os helpers `_format_price`/`_format_discount`/`_format_cents` continuam em
# bot/services/plan_service.py — sao renderizacao de texto pra DM/embed do
# Discord (usadas so por SubscriptionService/SubscriptionReminderService, que
# ficam no bot ate a Fase 3D), nao regra de negocio de catalogo.


class PlanService:
    """Regras de negocio do cadastro de Planos/Beneficios/Mensagens — nenhum
    valor fixo, tudo lido do banco por guild. Cogs/Views nunca tocam nos
    repositorios diretamente, so este servico."""

    def __init__(self, database: Database) -> None:
        self._database = database

    # --- planos -----------------------------------------------------------

    async def list_plans(self, guild_id: int, *, only_active: bool = False) -> list[Plan]:
        async with self._database.session() as session:
            return await PlanRepository(session).list_by_guild(guild_id, only_active=only_active)

    async def get_plan(self, plan_id: uuid.UUID) -> Plan | None:
        async with self._database.session() as session:
            return await PlanRepository(session).get_by_id(plan_id)

    async def list_plans_by_product(self, product_id: uuid.UUID) -> list[Plan]:
        """Todos os planos (de qualquer guild) que vinculam este Product a um
        cargo — usado por `RoleSyncService` (Fase 5.6) pra resolver em quais
        servidores um evento de License precisa conceder/revogar cargo."""
        async with self._database.session() as session:
            return await PlanRepository(session).list_by_product(product_id)

    async def create_plan(
        self,
        guild_id: int,
        name: str,
        *,
        executor_id: int | None = None,
        executor_name: str | None = None,
    ) -> Plan:
        async with self._database.session() as session:
            repo = PlanRepository(session)
            plans = await repo.list_by_guild(guild_id)
            if any(p.name == name for p in plans):
                raise ValueError(f"Já existe um plano chamado '{name}' neste servidor.")
            plan = Plan(guild_id=guild_id, name=name, position=len(plans))
            plan = await repo.add(plan)
        await self._audit(guild_id, action="Plano criado", executor_id=executor_id, executor_name=executor_name, details={"plano": name})
        return plan

    async def update_plan(
        self,
        plan_id: uuid.UUID,
        *,
        executor_id: int | None = None,
        executor_name: str | None = None,
        **fields: object,
    ) -> Plan:
        async with self._database.session() as session:
            repo = PlanRepository(session)
            plan = await repo.get_by_id(plan_id)
            if plan is None:
                raise ValueError("Plano não encontrado.")
            for key, value in fields.items():
                setattr(plan, key, value)
            await session.flush()
            await session.refresh(plan)
        await self._audit(
            plan.guild_id, action="Plano editado", executor_id=executor_id, executor_name=executor_name,
            details={"plano": plan.name, "campos": list(fields.keys())},
        )
        return plan

    async def delete_plan(
        self,
        plan_id: uuid.UUID,
        *,
        executor_id: int | None = None,
        executor_name: str | None = None,
    ) -> None:
        async with self._database.session() as session:
            repo = PlanRepository(session)
            plan = await repo.get_by_id(plan_id)
            if plan is None:
                return
            # sem isso, o FK ondelete=SET NULL so zera source_plan_id e deixa
            # a linha de peso orfa (source="PLAN_BENEFIT" sem plano nenhum)
            weight_repo = VoteWeightRepository(session)
            for weight in await weight_repo.list_by_source_plan(plan_id):
                await weight_repo.delete(weight)
            await repo.delete(plan)
        await self._audit(
            plan.guild_id, action="Plano removido", executor_id=executor_id, executor_name=executor_name, details={"plano": plan.name}
        )

    # --- beneficios ---------------------------------------------------------

    async def list_benefits(self, plan_id: uuid.UUID) -> list[PlanBenefit]:
        async with self._database.session() as session:
            return await PlanBenefitRepository(session).list_by_plan(plan_id)

    async def add_benefit(
        self,
        plan_id: uuid.UUID,
        text: str,
        *,
        executor_id: int | None = None,
        executor_name: str | None = None,
    ) -> PlanBenefit:
        async with self._database.session() as session:
            repo = PlanBenefitRepository(session)
            existing = await repo.list_by_plan(plan_id)
            benefit = PlanBenefit(plan_id=plan_id, text=text, position=len(existing))
            benefit = await repo.add(benefit)
            plan = await PlanRepository(session).get_by_id(plan_id)
        if plan is not None:
            await self._audit(
                plan.guild_id, action="Benefício adicionado", executor_id=executor_id, executor_name=executor_name,
                details={"plano": plan.name, "beneficio": text},
            )
        return benefit

    async def remove_benefit(
        self,
        benefit_id: uuid.UUID,
        *,
        executor_id: int | None = None,
        executor_name: str | None = None,
    ) -> None:
        async with self._database.session() as session:
            repo = PlanBenefitRepository(session)
            benefit = await repo.get_by_id(benefit_id)
            if benefit is None:
                return
            await repo.delete(benefit)
            plan = await PlanRepository(session).get_by_id(benefit.plan_id)
        if plan is not None:
            await self._audit(
                plan.guild_id, action="Benefício removido", executor_id=executor_id, executor_name=executor_name,
                details={"plano": plan.name, "beneficio": benefit.text},
            )

    async def set_benefits(
        self,
        plan_id: uuid.UUID,
        texts: list[str],
        *,
        executor_id: int | None = None,
        executor_name: str | None = None,
    ) -> list[PlanBenefit]:
        """Substitui a lista inteira de beneficios de um plano — usado pelo
        editor de texto multi-linha do painel (1 linha por beneficio)."""
        async with self._database.session() as session:
            repo = PlanBenefitRepository(session)
            await repo.delete_all_for_plan(plan_id)
            created = []
            for position, text in enumerate(t.strip() for t in texts if t.strip()):
                created.append(await repo.add(PlanBenefit(plan_id=plan_id, text=text, position=position)))
            plan = await PlanRepository(session).get_by_id(plan_id)
        if plan is not None:
            await self._audit(
                plan.guild_id, action="Benefícios atualizados", executor_id=executor_id, executor_name=executor_name,
                details={"plano": plan.name, "total": len(created)},
            )
        return created

    # --- auditoria ------------------------------------------------------

    async def _audit(
        self,
        guild_id: int,
        *,
        action: str,
        executor_id: int | None = None,
        executor_name: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        """No bot, isto gravava no audit log do Discord guild (audit_log_service).
        O backend nao fala com Discord — audita via log estruturado (ver mesma
        decisao em CouponService._audit_raw)."""
        logger.info(
            "plan_audit",
            extra={
                "guild_id": guild_id,
                "action": action,
                "executor_id": executor_id,
                "executor_name": executor_name,
                "details": details or {},
            },
        )

    # --- mensagens ------------------------------------------------------

    async def get_message(self, plan_id: uuid.UUID, message_type: PlanMessageType) -> PlanMessage | None:
        async with self._database.session() as session:
            return await PlanMessageRepository(session).get_by_plan_and_type(plan_id, message_type)

    async def list_messages(self, plan_id: uuid.UUID) -> list[PlanMessage]:
        async with self._database.session() as session:
            return await PlanMessageRepository(session).list_by_plan(plan_id)

    async def set_message(
        self, plan_id: uuid.UUID, message_type: PlanMessageType, content: str
    ) -> PlanMessage:
        async with self._database.session() as session:
            repo = PlanMessageRepository(session)
            existing = await repo.get_by_plan_and_type(plan_id, message_type)
            if existing is not None:
                existing.content = content
                await session.flush()
                return existing
            return await repo.add(
                PlanMessage(plan_id=plan_id, message_type=message_type, content=content)
            )
