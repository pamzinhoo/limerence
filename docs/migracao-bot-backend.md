# Migração bot → backend

Log de decisão e execução da migração de arquitetura: o `backend/` passa a ser
a única autoridade do sistema (auth, licenças, produtos, players, devices,
sessões, downloads, pagamentos, storage, banco), o `bot/` passa a ser cliente
HTTP dessa API. Ver árvore alvo e fases originais na conversa de kickoff; este
documento é o estado corrente, atualizado a cada fase.

## Estado por fase

| Fase | Escopo | Status |
|---|---|---|
| 0,5 | Esqueleto do backend (config/logging/DB/Alembic/DI/lifespan/middleware/auth interna) | ✅ concluída |
| 1 | Persistência: models, schemas, database, Alembic | ✅ concluída |
| 2 | Repositories | ✅ concluída |
| 3A | Services de baixo risco (Auth/License/Product/Payment/SubscriptionRenewalConfig/LauncherContent) | ✅ concluída |
| 3B | Services com adaptação (Download/Plan/Coupon) | ✅ concluída |
| 3C-1 | `InternalEventsClient` + religar `LicenseService` | ✅ concluída |
| 3C-2 | `ProcessPaymentWebhookUseCase` | ✅ Fase 5.5: implementado e ligado (`WebhookService` do backend despacha pra `SubscriptionDomainService`) — "preparação": Mercado Pago ainda aponta pro webhook do bot em produção |
| 3D-1 | `SubscriptionDomainService` + `SubscriptionNotificationPublisher` | ✅ concluída |
| 3D-2 | `SubscriptionNotificationHandler` (bot) | 🔶 Fase 5.1: `SUBSCRIPTION_CANCELLED`. Fase 5.2: + `CREATED`/`RENEWED`/`EXPIRED` (ramo de cargo direto legado). `PAYMENT_*`/`REFUNDED`/`CHARGEBACK` ainda pendentes |
| 3D-3 | Troca de fonte de dados do `SubscriptionReminderService` | ⏸️ auditado na Fase 5.4: motor de decisão (cálculo dias/carência + ledger) segue local no bot — contrato request/response de duas mãos desenhado, não implementado (risco financeiro/duplicidade de DM, ver Fase 5.4 abaixo) |
| 4 | Routers/API no backend, subir processo independente de fato | ✅ concluída (backend/bot rodando em paralelo) |
| 5 | Cogs → cliente HTTP | 🔶 4/29 cogs com leitura migrada (`subscriptions`, `payment_expiration`, `subscription_renewal` — throttle — , mais `role_sync_service`/`webhook_service`, que não são cogs); `shop.py` auditado e propositalmente não migrado (ver Fase 5.7) |
| 6 | Descomissionamento de `bot/api`, `bot/services/*` migrados | ⏳ não iniciada |

## Revisão arquitetural — Fase 0,5 a 3B

### O que existe hoje em `backend/`

```
backend/
├── api/            main.py (lifespan próprio), dependencies.py (HMAC interno,
│                   rate limit), schemas/ (auth, internal, launcher, webhook),
│                   routes/health_routes.py (único router ativo)
├── config/         settings.py — só campos de negócio, sem token/application_id
│                   de bot Discord
├── core/           logger, rate_limiter (in-memory, TODO Redis), security/
│                   (jwt_service, tokens), event_bus + events (ver Fase 3C)
├── database/       database.py (engine/session), models/ (62 arquivos),
│                   repositories/ (57 arquivos, 63 classes)
├── providers/      base, manual (PIX), mercadopago, storage/s3_compatible
├── services/       auth, license, product, payment, subscription_renewal_config,
│                   launcher_content, download, plan, coupon (9 services)
├── utils/          pix_payload, pix_validation
├── alembic/        52 migrations, revision IDs idênticos ao bot (head c2f5e8a1d4b7)
└── main.py         entrypoint uvicorn standalone, porta 8001
```

**Decisão de estrutura mantida:** `database/models`, `database/repositories`,
`api/schemas`, `alembic/` (em vez da árvore "bonita" `models/`, `repositories/`,
`schemas/`, `migrations/` na raiz) — para preservar todos os imports internos
idênticos ao bot, zero reescrita mecânica em ~130 arquivos copiados. Reavaliar
só depois que a migração estiver 100% funcional (Fase 6+), nunca antes.

### Validações rodadas em cada fase (repetidas a cada mudança)

1. `ast.parse` em todos os `.py` do backend — sintaxe.
2. Import isolado de cada model/repository/service — falha cedo, arquivo a arquivo.
3. `create_app()` — o processo sobe sem depender de `core.bot`/`discord`.
4. `alembic heads` no backend comparado ao bot — precisa bater exatamente
   (`c2f5e8a1d4b7` em ambos, o tempo todo).
5. Grep por `discord`, `core.bot`, `LimerenceBot`, `fastapi` (em repositories),
   `from services` (em repositories) — zero ocorrências fora de nomes de coluna
   (`discord_id`).

### Achados não previstos na matriz de dependências original

A matriz da Fase 3 (auditoria de imports) não pegou dois casos porque a
dependência não estava em `import`, e sim em atributo passado no construtor
sob `TYPE_CHECKING`:

- **`PlanService`** e **`CouponService`** recebiam `bot: LimerenceBot | None`
  no construtor só para chamar `bot.audit_log_service.record(...)` (grava no
  audit log do Discord guild). Como o import de `LimerenceBot` só existe sob
  `if TYPE_CHECKING:`, não aparecia em grep de import direto.
  **Resolução aplicada:** removido `bot` do construtor dos dois; `_audit`/
  `_audit_raw` agora emitem `logger.info(...)` estruturado em vez de gravar no
  audit log do Discord. Se auditoria por guild for necessária no backend, ela
  nasce como evento publicado (mesmo padrão de `LicenseService`), não como
  callback direto para um service do bot.
- **`SubscriptionService._grant_license`/`_revoke_license`** (não migrado,
  fica para Fase 3D) usa exatamente o padrão
  `getattr(self._bot, "license_service", None)` para conceder/revogar
  licença após um pagamento — **isto confirma, com código real, a cadeia que
  motiva o `ProcessPaymentWebhookUseCase`**: hoje é
  `WebhookService → SubscriptionService → (via self._bot) → LicenseService`,
  um acoplamento oculto (via instância do bot, não via import) que o Use Case
  da Fase 3C precisa tornar explícito.

### `render_placeholders` (removido do backend)

`plan_service.py` continha `render_placeholders` (formata `{user}`, `{guild}`,
`{plan_price}` etc. em texto de DM/embed usando atributos reais de
`discord.Member`/`discord.Guild`/`discord.Role`) e 4 helpers privados de
formatação. É chamada só por `subscription_service`/`subscription_reminder_service`
(ambos deferidos à Fase 3D). Removida inteira da cópia do backend — continua
existindo em `bot/services/plan_service.py`, inalterada.

### Assinaturas ajustadas (decoupling de `discord.py`)

| Antes (bot) | Depois (backend) | Onde |
|---|---|---|
| `executor: discord.Member \| discord.User \| None` | `executor_id: int \| None`, `executor_name: str \| None` | `PlanService.*`, `CouponService.set_active/duplicate_coupon/delete_coupon` |
| `member: discord.Member \| None` | `member_id: int \| None`, `member_role_ids: set[int] \| None` | `CouponService.validate_and_price` (checagem de `required_role_id`) |

O chamador (bot, depois da Fase 5) passa a resolver `executor.id`/
`str(executor)`/`{r.id for r in member.roles}` **antes** de chamar a API — o
backend nunca recebe um objeto `discord.*`.

### `GuildService` — reclassificado, fica no bot

`ensure_guild(guild: discord.Guild)` registra o tenant multi-guild do bot
(staff/tickets/config por servidor) — não é domínio Player/License/Launcher.
Não foi copiado.

### Riscos abertos (herdados da auditoria original, ainda não endereçados)

- `RateLimiter` in-memory — TODO explícito no código (`backend/core/rate_limiter.py`),
  trocar por Redis antes de produção/múltiplas instâncias.
- `_pending_logins` do Device Flow OAuth (`AuthService`) — mesmo problema,
  ainda em RAM. Migra junto com o rate limiter.
- `WebhookService.validate_signature` tem fallback `"placeholder"` quando
  `mercadopago_access_token` está vazio — ainda presente em `payment_service`/
  webhook (a migrar na 3D), não corrigido nesta rodada.
- Nenhuma migration nova foi criada — cadeia só copiada, `alembic_version` real
  no banco de produção ainda não foi tocada (isso só acontece na Fase 4, quando
  o backend passar a ser aplicado de verdade).

---

## Fase 3C — Desenho (aguardando aprovação, nada implementado ainda)

### Por que só parte da 3C dá para implementar agora

`ProcessPaymentWebhookUseCase` orquestra `PaymentService` → `SubscriptionService`
→ `LicenseService`. O meio dessa cadeia (`SubscriptionService.confirm_payment`,
`reject_payment`, `expire_payment`, `handle_refund_or_chargeback`,
`_grant_license`/`_revoke_license`) **ainda não foi migrado nem splitado** —
é exatamente o trabalho da Fase 3D. Implementar o Use Case agora significaria
ou (a) copiar `subscription_service.py` pela metade, com `discord` misturado
dentro do backend — quebra a regra que vimos seguindo a fase inteira — ou
(b) escrever o Use Case contra uma interface que ainda não existe.

Por isso separo a 3C em duas fatias:

- **3C-1 — implementável agora**: `InternalEventsClient` (Provider) +
  religar `LicenseService` para usá-lo em vez do `EventBus` in-process.
  Não depende de `SubscriptionService`. Fecha sozinho o risco "EventBus é
  caminho ativo, endpoint HTTP nunca é chamado" da auditoria original.
- **3C-2 — desenhado agora, implementado só depois da Fase 3D**:
  `ProcessPaymentWebhookUseCase`. O contrato abaixo já fixa a interface que
  `SubscriptionDomainService` (Fase 3D) precisa expor, para a 3D já nascer
  compatível.

### 3C-1 — `InternalEventsClient`

**Localização:** `backend/providers/internal_events_client.py` (Provider —
integração externa, mesmo grupo de `MercadoPagoProvider`/`S3CompatibleStorageProvider`;
`LicenseService → InternalEventsClient` continua sendo Service→Provider, hop
único, já aprovado no seu critério).

**Contrato:**

```python
class InternalEventsClient:
    def __init__(self, base_url: str, secret: str, *, timeout_seconds: float = 5.0) -> None: ...

    async def notify_license_event(self, payload: LicenseEventPayload) -> None:
        """POST {base_url}/internal/license-events, HMAC-SHA256 assinado.
        Nunca lança pra cima em falha de rede/timeout/5xx — só loga erro.
        A licença já foi persistida antes desta chamada; a notificação é
        best-effort, igual o EventBus era (handler que falha não derruba o
        publisher)."""
```

**Assinatura HMAC (saída):** espelha exatamente `verify_internal_signature`
que já existe em `backend/api/dependencies.py` (validação de entrada) — mesmo
formato `X-Internal-Timestamp` + `X-Internal-Signature = hex(hmac_sha256(secret, f"{ts}.{corpo}"))`,
mesmo `INTERNAL_API_SECRET` dos dois lados (já existe em `.env.example` de
ambos os processos).

**Retry/timeout:**
- `aiohttp.ClientTimeout(total=5)`, configurável.
- Até 3 tentativas com backoff (0.5s / 1s / 2s) **só** para falha de rede,
  timeout ou HTTP 5xx/429.
- HTTP 4xx (assinatura inválida, payload malformado) não tenta de novo — é
  bug de configuração, não falha transiente; loga em nível `error` com o
  corpo da resposta.
- Esgotadas as tentativas: loga `error` e retorna — **não propaga exceção**.
  A licença no banco já está correta; o pior caso é o Discord ficar
  temporariamente sem o cargo atualizado, e o job `license_reconciliation.py`
  (já existe no bot, roda a cada 60min, comentário no código diz
  "rede de segurança") corrige na próxima passada. Isso já era verdade hoje
  com o `EventBus` in-process — nenhuma garantia nova nem perdida.

**Settings novas (`backend/config/settings.py`):**
- `bot_internal_base_url: str` (ex.: `http://127.0.0.1:8000`, a porta atual do
  bot) — obrigatória só se `internal_api_secret` estiver configurado
  (mesma lógica condicional de `webhook_enabled`/`MERCADOPAGO_WEBHOOK_SECRET_PRODUCTION`).
- `internal_events_timeout_seconds: int = 5` (opcional, default acima).

**Wiring em `LicenseService`:** troca a injeção `event_bus: EventBus | None`
por `internal_events_client: InternalEventsClient | None`. `_publish` vira:

```python
async def _publish(self, license_row, event_type) -> None:
    if self._internal_events_client is None:
        return
    await self._internal_events_client.notify_license_event(
        LicenseEventPayload(license_id=..., ...)
    )
```

Mesmo formato de payload que já existe (`core/events.py`, copiado sem mudança) —
o endpoint `/internal/license-events` no bot **já existe e já aceita esse
formato exato** (`LicenseEventRequest` em `bot/api/schemas/internal.py` espelha
`LicenseEventPayload` campo a campo), só nunca foi chamado de fora. `EventBus`/
`core/event_bus.py` deixam de ser usados pelo backend (continuam existindo lá
por enquanto — remover é Fase 6, não agora).

### 3C-2 — `ProcessPaymentWebhookUseCase` (contrato fixado, implementação após 3D)

**Localização:** `backend/use_cases/process_payment_webhook.py` (pacote novo
`use_cases/` — camada de orquestração, separada de `services/` como você
definiu: Controller → Use Case → Domain Service → Repository).

```python
class ProcessPaymentWebhookUseCase:
    def __init__(
        self,
        payment_repository: PaymentRepository,
        payment_service: PaymentService,
        subscription_domain_service: SubscriptionDomainService,  # nasce na Fase 3D
        settings: Settings,
    ) -> None: ...

    async def execute(self, payload: dict, headers: dict[str, str], raw_body: bytes) -> None:
        """1. valida assinatura MercadoPago (via provider, já em PaymentService)
        2. busca PaymentRepository.get_by_provider_external_id — idempotência
        3. confirma status real via API do gateway (nunca confia só no payload)
        4. roteia por status pro método correto de SubscriptionDomainService
           (confirm_payment/reject_payment/expire_payment/handle_refund_or_chargeback)
        5. SubscriptionDomainService, internamente, chama LicenseService.grant_or_renew
           /revoke_by_player_product quando o plano tem product_id — SEM voltar
           pro Use Case, sem depender de `self._bot` (era assim que funcionava
           antes: getattr(self._bot, "license_service", None))
        """
```

Isso resolve a cadeia oculta encontrada na revisão: hoje é
`WebhookService → SubscriptionService → (via self._bot, getattr) → LicenseService`;
depois vira `WebhookController → ProcessPaymentWebhookUseCase → PaymentService`
e, dentro do Use Case, `→ SubscriptionDomainService → LicenseService` — mesma
cadeia de 3 hops, mas toda explícita em injeção de dependência, sem
`self._bot`/`getattr` escondendo o acoplamento.

**Notificação (DM/embed de renovação) explicitamente fora do Use Case** — vira
responsabilidade do bot reagindo a um evento novo publicado pelo
`SubscriptionDomainService` via o mesmo `InternalEventsClient` (evento
`SUBSCRIPTION_RENEWED`/`SUBSCRIPTION_EXPIRED`/etc., catálogo a definir na 3D
junto com o desenho do `SubscriptionNotificationHandler` no bot).

### Fluxo de eventos (3C-1, o que entra em produção nesta fase)

```
Backend                                          Bot
────────────────────────────────────────────────────────────────────
LicenseService.grant_or_renew()
  │
  ├─ grava License no banco (commit)
  │
  └─ InternalEventsClient.notify_license_event()
        │  POST /internal/license-events
        │  X-Internal-Signature: hmac_sha256(secret, f"{ts}.{body}")
        └──────────────────────────────────────►  verify_internal_signature (já existe)
                                                     │
                                                     ▼
                                                   internal_routes.receive_license_event
                                                     │
                                                     ▼
                                                   RoleSyncService.handle_license_event()
                                                     │
                                                     ▼
                                                   concede/remove cargo Discord

  (falha de rede/timeout/5xx)
  └─ loga erro, licença já persistida            license_reconciliation.py (60min)
                                                     corrige divergência residual
```

### Checklist de aceite da 3C-1

- `InternalEventsClient` importável isoladamente, sem `discord`/`core.bot`.
- `LicenseService` sobe sem `event_bus` (parâmetro passa a aceitar `None` ou
  `InternalEventsClient`, mesma flexibilidade de teste que tinha antes).
- Teste manual: chamar `notify_license_event` contra o bot rodando localmente
  com `INTERNAL_API_SECRET` igual nos dois `.env` — 204 no bot, log de sucesso
  no backend.
- Teste de falha: bot fora do ar — backend loga erro, não lança, `grant_or_renew`
  continua retornando normalmente pro chamador.
- `alembic heads`, `create_app()`, import de todos os services — mesmas 5
  validações de sempre, sem regressão.

---

### 3C-1 — implementada

- `backend/providers/internal_events_client.py` — `InternalEventsClient`,
  contrato exatamente como desenhado (HMAC simétrico, retry 3x com backoff
  0.5/1/2s só em falha transiente/5xx, nunca propaga exceção).
- `backend/config/settings.py` — `bot_internal_base_url`,
  `internal_events_timeout_seconds` (+ `.env.example` atualizado nos dois
  processos).
- `backend/services/license_service.py` — `event_bus: EventBus | None` trocado
  por `internal_events_client: InternalEventsClient | None`; `_publish` chama
  `notify_license_event` em vez de `EventBus.publish`.
- `backend/core/event_bus.py` removido (ficou sem nenhum import real depois da
  troca — só sobrava em comentário/docstring).
- **Teste funcional rodado**: servidor HTTP local replicando a verificação
  HMAC real de `bot/api/dependencies.py.verify_internal_signature` — evento
  chegou, assinatura validou, payload bateu campo a campo. Com o servidor
  fora do ar, 3 tentativas com backoff e retorno normal, sem exceção.
- Validações de sempre (sintaxe, imports, `create_app()`, `alembic heads`) sem
  regressão.

**Nota para a Fase 4:** ninguém ainda instancia `LicenseService` com um
`InternalEventsClient` real em produção — não existe composition root
(routers) no backend ainda. Essa injeção nasce junto com a Fase 4.

### 3C-2 — permanece só como contrato

Aguardando a Fase 3D (split de `SubscriptionService`) antes de implementar
`ProcessPaymentWebhookUseCase`. O contrato acima já está fixado para a 3D
nascer compatível.

---

## Fase 3D — Desenho (aguardando aprovação, nada cortado ainda)

`subscription_service.py` (910 linhas) e `subscription_reminder_service.py`
(479 linhas) foram lidos por inteiro, método a método, antes deste desenho —
é o maior ponto de acoplamento restante entre backend e Discord (achado já
confirmado na Fase 3A/3B: `_grant_license`/`_revoke_license` usam
`getattr(self._bot, "license_service", None)`, um acoplamento via instância,
não via import, que não aparece em grep).

### As quatro responsabilidades

1. **`SubscriptionDomainService`** (backend) — transição de estado pura:
   compra, confirmação/rejeição de pagamento, cancelamento, renovação,
   expiração, reembolso/chargeback, concessão/revogação de `License`. Zero
   `discord`, zero `self._bot`.
2. **`SubscriptionNotificationPublisher`** (backend) — publica um evento
   `SUBSCRIPTION_*` (via `InternalEventsClient`, generalizado) depois de cada
   transição relevante do Domain Service. Só publica, não decide regra.
3. **`SubscriptionNotificationHandler`** (bot) — consome os eventos, resolve
   `discord.Member`/`discord.Guild`/canal, entrega/remove cargo do caminho
   legado (`plan.product_id is None`), manda DM, escreve log de canal e audit
   log do Discord. Todo I/O de Discord vive só aqui.
4. **`SubscriptionReminderService`** (bot, **não migra** — confirmado) —
   continua dona do `@tasks.loop` e da decisão de quando lembrar/dar
   carência/expirar por vencimento de tempo. Só troca a **origem dos dados**:
   `SubscriptionRepository`/`PlanRepository` direto vira leitura via HTTP no
   backend; a ação de expirar vira uma chamada HTTP em vez de chamada Python
   direta em `SubscriptionService`.

### Mapa completo — `subscription_service.py`

| Método | Destino | Observação |
|---|---|---|
| `get_settings`/`update_settings` | Domain | CRUD puro de `MonetizationSettings` |
| `start_purchase` | Domain (adaptado) | `member: discord.Member` → `guild_id/user_id: int` + `member_role_ids: set[int]` (pro `CouponService.validate_and_price`, já preparado desde a 3B); `self._bot.coupon_service.*` → injeção direta de `CouponService` |
| `confirm_payment` | **Split** | Transição de estado + `_grant_license` ficam no Domain. `_deliver_role`, `_send_plan_message`, `_send_payment_dm`, `_log`, `_audit`, `_notify_renewed` saem inteiros — o Domain publica **um** evento (`SUBSCRIPTION_CREATED` ou `SUBSCRIPTION_RENEWED`, conforme `was_renewal`) no fim, e o Handler faz todo o resto |
| `reject_payment` | **Split** | Estado fica; DM/log/audit → evento `SUBSCRIPTION_PAYMENT_REJECTED` |
| `mark_payment_pending` | **Split** | Estado fica; log/audit → evento `SUBSCRIPTION_PAYMENT_PENDING` |
| `cancel_payment` | **Split** | Estado fica; log/audit → evento `SUBSCRIPTION_PAYMENT_CANCELED` |
| `cancel_subscription` | **Split** | Estado + `_revoke_license` ficam; `_remove_role` (caminho legado)/`_send_plan_message`/`_log`/`_audit`/`_audit_subscription` saem → evento `SUBSCRIPTION_CANCELLED` (com `was_active` no payload, pro Handler saber se remove cargo/manda mensagem) |
| `renew_subscription` | **Split** | Estado fica; resto → evento `SUBSCRIPTION_RENEWED` |
| `expire_subscription` | **Split** | Estado + `_revoke_license` ficam; `_remove_role` sai → evento `SUBSCRIPTION_EXPIRED`. Chamado tanto pelo futuro `ProcessPaymentWebhookUseCase` (3C-2) quanto pelo `SubscriptionReminderService` via HTTP (item 4) |
| `expire_payment` | **Split** | Estado fica; log/audit → evento `SUBSCRIPTION_PAYMENT_EXPIRED` |
| `handle_refund_or_chargeback` | **Split** | Estado + `_revoke_license` ficam; resto → evento `SUBSCRIPTION_REFUNDED`/`SUBSCRIPTION_CHARGEBACK` |
| `list_active_subscriptions`/`list_guild_subscriptions`/`list_cancelable_subscriptions` | Domain | consultas puras |
| `_get_member`, `_deliver_role`, `_remove_role`, `_send_plan_message`, `_send_payment_dm`, `_log` | Handler | 100% I/O Discord — inclusive `render_placeholders`, que já ficou só no bot desde a 3B |
| `_audit`, `_audit_subscription` | Removidos do Domain | viram `logger.info` estruturado no backend (mesmo padrão de `PlanService`/`CouponService`); o audit log **real** do Discord é escrito pelo Handler, que já resolve guild/membro ao processar o evento |
| `_grant_license`, `_revoke_license` | Domain | troca `getattr(self._bot, "license_service", None)` por injeção direta de `LicenseService` no construtor — fecha o acoplamento oculto que a Fase 3A/3B revelou |
| `_notify_renewed` | Removido | o evento `SUBSCRIPTION_RENEWED` tem **dois** consumidores no bot: o Handler (mensagem/log/audit genéricos) e `SubscriptionReminderService.handle_renewed` (mensagem específica de renovação, com o próprio livro-razão de idempotência) — mesmo padrão multi-subscriber que os eventos `LICENSE_*` já usam |

### Mapa completo — `subscription_reminder_service.py` (fica 100% no bot)

| Método | Mudança |
|---|---|
| `run_check_cycle`, `_process_subscription`, `_maybe_send_day_reminders`, `_start_grace` | Mesma lógica; `SubscriptionRepository.list_active_with_period`/`PlanRepository.list_by_guild` (leitura direta do banco) viram `GET /internal/subscriptions/reminders?guild_id=...` no backend — **endpoint não existe ainda, contrato fixado abaixo, implementação trava na Fase 4** (backend não tem router além de `/health`) |
| `_finish` (chama `self._subscriptions.expire_subscription(...)`) | Vira `POST {backend}/internal/subscriptions/{id}/expire` — **mesmo bloqueio da Fase 4** |
| `handle_renewed` | Fica, mas passa a ser acionado como consumidor do evento `SUBSCRIPTION_RENEWED` (item acima) em vez de chamada Python direta de `SubscriptionService` |
| `_already_sent`, `_reserve_reminder`, `_finalize_reminder`, `list_reminders` (livro-razão `SubscriptionReminder`) | Dado passa a ser propriedade do backend; bot lê/escreve via HTTP — **mesmo bloqueio da Fase 4** |
| `_send`, `_audit` | Ficam 100% no bot, inalterados — I/O de Discord e audit log de guild |

### Por que a Fase 3D se divide em três fatias, não uma

- **3D-1 (implementável agora, só backend)**: `SubscriptionDomainService` +
  `SubscriptionNotificationPublisher`. Não depende de nenhum router novo —
  mesmo padrão dos 9 services já migrados (código pronto, sem composition
  root ainda, isso é Fase 4). O `InternalEventsClient` da 3C-1 já é
  resiliente a endpoint inexistente (loga erro, não propaga) — publicar um
  evento que o bot ainda não escuta é seguro, só fica sem efeito até o
  Handler existir.
- **3D-2 (contrato fixado agora, código adiado)**: `SubscriptionNotificationHandler`
  — é código **no bot**. A regra que seguimos desde a Fase 1 ("não alterar o
  bot ainda") é deliberada: mexer no bot antes da hora é o tipo de risco que
  motivou migrar por fases. Endpoint novo (`/internal/subscription-events`)
  e handler entram junto da Fase 5 (quando o bot começa a virar
  cliente/consumidor), ou antes se você decidir explicitamente antecipar só
  essa peça.
- **3D-3 (contrato fixado agora, bloqueado por infraestrutura)**: a troca de
  fonte de dados do `SubscriptionReminderService` — não dá pra implementar
  antes da Fase 4 (routers) existir no backend, não é questão de risco, é
  dependência dura.

### Contrato de eventos novo — `SubscriptionEventPayload`

```python
@dataclass(frozen=True, slots=True)
class SubscriptionEventPayload:
    subscription_id: uuid.UUID
    guild_id: int
    user_id: int
    plan_id: uuid.UUID
    status: str                       # SubscriptionStatus.value
    event_type: str                   # SUBSCRIPTION_*
    occurred_at: datetime
    payment_id: uuid.UUID | None = None
    executor_id: int | None = None
    executor_name: str | None = None
    reason: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
```

Catálogo: `SUBSCRIPTION_CREATED`, `SUBSCRIPTION_RENEWED`,
`SUBSCRIPTION_CANCELLED` (com `metadata["was_active"]`),
`SUBSCRIPTION_EXPIRED`, `SUBSCRIPTION_PAYMENT_REJECTED`,
`SUBSCRIPTION_PAYMENT_PENDING`, `SUBSCRIPTION_PAYMENT_CANCELED`,
`SUBSCRIPTION_PAYMENT_EXPIRED`, `SUBSCRIPTION_REFUNDED`,
`SUBSCRIPTION_CHARGEBACK` — mesmo espírito do catálogo `LICENSE_*` já em
produção (`core/events.py`), símbolos como string solta, não enum, pelo mesmo
motivo (quem consome não precisa importar o model de domínio inteiro).

`InternalEventsClient` generaliza: `notify_license_event` continua igual,
mais um `notify_subscription_event(payload: SubscriptionEventPayload)` —
mesma assinatura HMAC, mesmo retry/backoff, mesmo best-effort. Não é uma
classe nova, é um método novo no Provider que já existe.

### Contratos HTTP fixados para a Fase 4 (3D-3, não implementar agora)

- `GET /internal/subscriptions/reminders?guild_id=<int>` → lista de
  `Subscription` ativas com `current_period_end` + `Plan` já resolvido
  (evita N+1 do lado do bot).
- `POST /internal/subscriptions/{id}/expire` → equivalente a
  `expire_subscription`, corpo `{"remove_role": bool, "end_subscription": bool}`.
- `GET /internal/subscriptions/{id}/reminders` / `POST .../reminders` →
  livro-razão de idempotência (`SubscriptionReminder`), hoje
  `SubscriptionReminderRepository`.

### Checklist de aceite da 3D-1

- `SubscriptionDomainService` importável isolado, sem `discord`/`core.bot`/`self._bot`.
- `LicenseService` injetado direto no construtor (sem `getattr`).
- `CouponService.validate_and_price` chamado com `member_id`/`member_role_ids`
  (não `discord.Member`) — mesma assinatura fixada na 3B.
- `InternalEventsClient.notify_subscription_event` testado do mesmo jeito que
  `notify_license_event` foi na 3C-1 (servidor fake replicando HMAC, sucesso
  + falha graciosa).
- 5 validações de sempre sem regressão.
- `bot/services/subscription_service.py` e `subscription_reminder_service.py`
  **não são tocados** nesta fase — continuam rodando exatamente como estão em
  produção até a Fase 5.

---

### 3D-1 — implementada

- `backend/core/events.py` — catálogo `SUBSCRIPTION_*` (10 constantes,
  incluindo `SUBSCRIPTION_REMINDER` reservado pra 3D-3) + `SubscriptionEventEnvelope`
  (`event_id`, `event_type`, `aggregate_id`, `occurred_at`, `version`, `payload`).
- `backend/providers/internal_events_client.py` — `notify_subscription_event`
  novo (reaproveita `_post`/`_sign`/`_json_default` sem duplicar nada);
  `notify_license_event` continua igual.
- `backend/services/subscription_notification_publisher.py` — `SubscriptionNotificationPublisher`,
  monta o envelope e delega ao `InternalEventsClient`. `internal_events_client=None`
  (default) o deixa inofensivo, mesmo padrão de `LicenseService`.
- `backend/services/subscription_domain_service.py` — `SubscriptionDomainService`,
  extraído método a método de `bot/services/subscription_service.py` (910
  linhas) seguindo exatamente o mapeamento da Fase 3D: todas as transições de
  estado + `_grant_license`/`_revoke_license` (agora com `LicenseService`
  injetado direto, sem `getattr(self._bot, ...)`) ficam; todo I/O de Discord
  (`_deliver_role`, `_remove_role`, `_send_plan_message`, `_send_payment_dm`,
  `_log`, `_notify_renewed`) saiu — cada método de escrita publica **um**
  evento no fim via `SubscriptionNotificationPublisher`; `_audit`/`_audit_subscription`
  viraram `logger.info` estruturado (mesmo padrão de `PlanService`/`CouponService`).
- `CouponService.validate_and_price`/`start_purchase`: `discord.Member` →
  `guild_id: int`, `user_id: int`, `member_role_ids: set[int] | None` —
  assinatura já compatível com o `CouponService` decoupled da Fase 3B.

**Decisões de design tomadas durante a extração (não estavam 100% fechadas
no desenho):**
- `start_purchase` e o ramo `cancel_subscription(was_active=False)` não
  publicam evento — só log estruturado. Motivo: no código original, esses
  caminhos só escreviam audit log do Discord (sem DM, sem cargo); um evento
  ali não teria nenhum efeito user-facing pro Handler reagir, então vira
  observabilidade pura no backend, mesmo critério já usado em `PlanService`/`CouponService`.
- `reject_payment`/`cancel_payment`/`expire_payment` tinham dois audit logs
  no original (categoria PAYMENT + categoria SUBSCRIPTION quando havia
  renovação em curso) — colapsados em **um** evento com `metadata["renewal_in_flight"]`,
  já que é o Handler (Fase 3D-2) quem decide quantas entradas de audit log
  escrever a partir do evento, não o Domain Service.

**Validado:**
- 220 arquivos com sintaxe ok; zero import de `discord`/`core.bot`/`LimerenceBot`
  em `services/`, `providers/`, `core/`.
- `create_app()` sobe, `alembic heads` continua `c2f5e8a1d4b7`.
- Teste funcional: `Subscription` montada em memória (sem banco) →
  `SubscriptionNotificationPublisher.publish(...)` → `InternalEventsClient` →
  servidor local replicando a verificação HMAC real do bot — envelope
  chegou, `event_type`/`aggregate_id`/`version`/`payload` bateram campo a
  campo. Publisher sem `internal_events_client` (default) confirmado no-op.
- `bot/tests/` rodado (nenhum arquivo do bot foi tocado nesta fase): 303
  passam; 1 falha + 7 erros pré-existentes por `JWT_SECRET_KEY`/env ausente
  neste shell — não relacionados a esta mudança (confirmado lendo o traceback:
  falha em `Settings.load()`, não em lógica de assinatura/pagamento).

**Nota para a Fase 4:** assim como `LicenseService`, ninguém ainda instancia
`SubscriptionDomainService` com dependências reais em produção — não existe
composition root (routers) no backend. Essa injeção nasce junto com a Fase 4.

### 3D-2 e 3D-3 — permanecem só como contrato

`SubscriptionNotificationHandler` (mexe no bot, Fase 5) e a troca de fonte de
dados do `SubscriptionReminderService` (bloqueada por routers, Fase 4) não
foram tocados, como combinado.

---

## Fase 4 — Routers/API no backend (concluída)

Auditoria de cada router do bot feita antes de copiar (leitura integral de
`bot/api/routes/*.py`), resumida abaixo, seguida da migração.

### Auditoria — o que cada router usa

| Router | Endpoints | Services usados | Acessa repository/discord direto? |
|---|---|---|---|
| `auth_routes.py` | `/auth/device/code`, `/device/authorize`, `/discord/callback`, `/device/token`, `/refresh`, `/logout`, `/logout/all`, `/me` (8) | `AuthService` via `request.app.state.auth_service` | Não — só `AuthError`, sem `discord`/`LimerenceBot` nem em `TYPE_CHECKING` |
| `player_routes.py` | `/player/licenses`, `/player/products` (2) | `LicenseService`, `ProductService` | Não |
| `launcher_routes.py` | `/launcher/news`, `/version`, `/manifest` (3) | `LauncherContentService`, `LicenseService` | Não |
| `download_routes.py` | `/download`, `/download/{id}/complete`, `/update` (3) | `DownloadService` | Não |
| `webhook_routes.py` | `/webhooks/mercadopago` (1) | `WebhookService` **+ `request.app.state.bot.settings`** | Único que referenciava `bot` diretamente (pra ler `webhook_enabled`) — adaptado pra `request.app.state.settings` |
| `internal_routes.py` | `/internal/license-events`, `/internal/reconcile` (2) | `bot.role_sync_service`, `bot.reconciliation_service` | **100% bot-side** — despacha pra services que só existem no processo do bot (recebe eventos que o próprio backend publica via `InternalEventsClient`, Fase 3C-1/3D-1). Não migrado — ver decisão abaixo |
| `health_routes.py` | `/health`, `/payments/status` (2) | — | Já migrado na Fase 0,5 |

Todos os routers (exceto `webhook_routes.py`) já seguiam `Router → Service`
sem acessar repository/SQLAlchemy/discord direto — nenhuma regra de negócio
dentro de router, nenhuma violação das regras arquiteturais desta fase.
`auth_routes.py`/`player_routes.py`/`launcher_routes.py`/`download_routes.py`
foram copiados **verbatim, zero edição** (confirmado por grep: nenhuma
referência a `app.state.bot`/`LimerenceBot`, nem em `TYPE_CHECKING`).

### Decisão: `/internal/*` não duplicado 1:1

O router `internal_routes.py` do bot é lógica que **recebe** eventos (POST
`/internal/license-events`) no processo do bot — despacha pra
`bot.role_sync_service`, que só existe lá. O backend é quem **envia** esses
eventos (`InternalEventsClient`, Fase 3C-1), não quem os recebe — duplicar
esse handler no backend não faria sentido (não há dado nenhum pra ele
processar do lado do backend).

Criado `backend/api/routes/internal_routes.py` como **esqueleto**: prefixo
`/internal`, `verify_internal_signature` + rate limit (120/60) já aplicados
via `dependencies=[...]` do router — mas **sem nenhum endpoint ainda**. Esse
router é o canal reverso (Bot → Backend) desenhado na Fase 3D-3: quando
`GET /internal/subscriptions/reminders`, `POST /internal/subscriptions/{id}/expire`
etc. forem implementados, entram aqui, sem precisar mexer de novo no
composition root.

### `WebhookService` — "processamento inicial", não o Use Case completo

Instrução explícita desta fase: migrar validação de assinatura +
processamento inicial, **não** implementar `ProcessPaymentWebhookUseCase`
completo. `backend/services/webhook_service.py` faz exatamente o "meio do
caminho": valida assinatura HMAC do Mercado Pago (`validate_signature`,
copiado verbatim), busca o pagamento real via API do gateway (nunca confia
só no payload), localiza o `PaymentHistory` local, compara status — e **para
aí**, logando a decisão que tomaria (`webhook_processamento_inicial_concluido`)
em vez de chamar `SubscriptionDomainService`. O `TODO` no código aponta
exatamente pra isso. `webhook_routes.py` foi adaptado só num ponto:
`request.app.state.bot.settings.webhook_enabled` → `request.app.state.settings.webhook_enabled`
(único router que referenciava `bot` diretamente).

### Autenticação — o que migrou e o que não existia pra migrar

- `get_current_player` migrado pra `backend/api/dependencies.py`, idêntico ao
  do bot (usa `request.app.state.auth_service.get_player_from_access_token`).
- **Não existe `get_current_device` nem "validação de sessão" separada no bot
  original** — a validação de device/sessão já acontece **dentro** de
  `AuthService.get_player_from_access_token` (confere que a `LauncherSession`
  referenciada ainda está ativa, achado já registrado na auditoria da Fase
  1). Criar uma dependency nova e separada agora seria feature nova, contra
  a instrução explícita desta fase ("não alterar funcionalidades ainda").
  Documentado como nota no código, não implementado.

### Composition root (`backend/api/main.py`)

`create_app()`/`lifespan` agora instanciam com dependências reais e
publicam em `app.state`: `settings`, `database`, `internal_events_client`
(`None` se `INTERNAL_API_SECRET`/`BOT_INTERNAL_BASE_URL` não configurados —
mesmo fallback gracioso da Fase 3C-1), `auth_service`, `license_service`,
`product_service`, `coupon_service`, `payment_service`,
`launcher_content_service`, `download_service`, `webhook_service`.
`SubscriptionDomainService` **não foi wireado** — nenhum router migrado o
usa ainda (só entra quando o Use Case do webhook ou rotas de assinatura
existirem); evita estado morto em `app.state`.

19 endpoints ativos (2 health + 8 auth + 3 launcher + 2 player + 3 download +
1 webhook), idênticos aos do bot exceto os 2 `/internal/*` (decisão acima).

### Configuração movida

`bot_internal_base_url`/`internal_events_timeout_seconds` (já existiam desde
a 3C-1) são as únicas settings novas necessárias — todo o resto (CORS, API
host/port, `PUBLIC_BASE_URL`, JWT, segredos Mercado Pago/storage) já tinha
sido movido nas Fases 0,5–1. Nada de `DISCORD_TOKEN`/`DISCORD_APPLICATION_ID`/
`TEST_GUILD_ID` no backend, como sempre.

### Validações executadas

- 227 arquivos, sintaxe ok.
- Zero import de `discord`/`core.bot`/`LimerenceBot` em `api/`, `services/`,
  `providers/`, `core/`.
- `create_app()` sobe; `app.openapi()` lista os 19 endpoints esperados,
  campo a campo comparado com a auditoria.
- `alembic heads` continua `c2f5e8a1d4b7`.
- `get_current_player`/`verify_internal_signature` testados isolados (sem
  banco): sem token → 401 `missing_token`; sem `INTERNAL_API_SECRET` → 503
  `internal_api_not_configured`.
- `core/security/jwt_service` (copiado verbatim na Fase 1) testado isolado:
  `encode_access_token`/`decode_access_token` funcionam ida e volta.
- `bot/tests/`: 303 passam, mesma 1 falha + 7 erros pré-existentes de
  `JWT_SECRET_KEY` ausente no shell (não relacionados, bot não foi tocado).
- Não foi possível testar `/health`/`/auth/me` fim a fim contra Postgres real
  (sem instância disponível neste ambiente) — cobertura fica em: sintaxe +
  imports + dependências isoladas + schema OpenAPI + `alembic heads`. Rodar
  contra banco real antes de qualquer deploy é o próximo passo óbvio, fora
  do alcance deste ambiente de desenvolvimento.

### Observação (não relacionada a este trabalho)

`git -C bot status` mostra vários arquivos modificados sem commit
(`api/main.py`, `config/settings.py`, `core/bot.py`, cogs, models, etc.) —
**pré-existente**, não foi causado por nenhuma ação desta sessão (nenhum
`Write`/`Edit` tocou `bot/` em nenhuma fase; só `cp` bot→backend e leitura).
Sinalizando pra você verificar se é trabalho em andamento seu que precisa
ser commitado, ou algo inesperado.

### Riscos restantes

- `webhook_routes.py` está "vivo" mas não muta estado nenhum — se um webhook
  real do Mercado Pago chegar no backend hoje, ele é validado e logado, não
  processado. Só é risco se o `PUBLIC_BASE_URL` do backend for exposto ao
  gateway antes da Fase 3D-2/`ProcessPaymentWebhookUseCase` existir.
- `internal_routes.py` do backend está montado mas vazio — nenhum risco
  novo, só lembrete de que a Fase 3D-3 precisa dele.
- Bot e backend ainda sobem como processos totalmente independentes, sem
  nenhuma sincronização de estado entre os dois além do que já existia
  (banco compartilhado) — cogs do bot continuam chamando services locais do
  bot, não a API nova. Isso só muda na Fase 5.

### Próximo passo (superado — ver Fase 5 abaixo)

---

## Fase 5 — Cogs → cliente HTTP do Backend

### Estado do `bot/` antes de começar

`git -C bot status` mostrava 140 arquivos modificados sem commit (trabalho
pré-existente do usuário, não gerado nesta migração — o próprio sistema de
licenciamento/launcher que auditei e migrei nas Fases 1–4). Por decisão
explícita, commitei como snapshot único (`2412be7`) antes de qualquer edição
em `bot/`, pra separar esse histórico do diff desta fase.

### Etapa 1 — Auditoria dos 29 cogs

Grep sistemático de `self.bot.<service>` e `from database.repositories` em
todos os cogs.

**24 cogs — ficam 100% no bot, zero crossover com domínio migrado pro
backend:** antispam, audit, audit_logs, automod, backup, boosters,
bot_status, claim, config, guild_registry, help, inactivity, invites, logs,
moderation, painel, partnership, polls, ranking, reminders, staff, status,
tickets, verification. Todos usam services/models 100% Discord-guild
(tickets, staff, automod, punições, config por servidor) — o domínio que a
Fase 3 já tinha classificado "fica no bot". `backup.py`/`logs.py` continuam
acessando repository direto (achado da Fase 1), mas de domínio bot-only —
não é candidato a Backend API.

**5 cogs tocam domínio migrado pro backend:**

| Cog | Chama | Service já existe no backend? | Endpoint HTTP existia? |
|---|---|---|---|
| `payment_expiration.py` | `payment_service.list_pending_expired/resolve_provider`, `subscription_service.expire_payment` | ✅ | ❌ |
| `subscriptions.py` | `subscription_service.list_active/list_cancelable/cancel_subscription`, `plan_service.get_plan` | ✅ | ❌ |
| `shop.py` | `plan_service.list_plans/list_benefits` no comando, **mais** `ShopView` reabrindo `list_benefits`/`coupon_service`/`payment_service`/`subscription_service` internamente pro fluxo de compra inteiro | ✅ | ❌ |
| `subscription_renewal.py` | `subscription_renewal_config_service` (+ `subscription_reminder_service`, que fica no bot por decisão da Fase 3D) | ✅ parcial | ❌ |
| `license_reconciliation.py` | só `self.bot.reconciliation_service` (bot-only) | — | — (não precisa migrar) |

**Achado que mudou o plano:** a ordem de migração original (logs → backup →
verification → tickets → staff → moderation → license/role sync → payments →
subscription → reconciliation) não correspondia à realidade — 6 dos 10 itens
não têm nenhum crossover com o backend, e nenhum dos 4 que têm tinha endpoint
disponível (Fase 4 só expôs API JWT pro Launcher/Player, não canal interno
pro bot). `license_reconciliation.py` é falso positivo: o cog só chama
`reconciliation_service` (bot-only); o achado real — `reconciliation_service.py`
lê `LicenseRepository`/`PlanRepository`/`PlayerRepository` direto do banco
compartilhado — é um risco de nível de *service*, não deste cog, e fica fora
do escopo desta fase.

**`shop.py` descartado como prova de conceito** depois de ler `ShopView`
inteira: não é só leitura de catálogo — a View reabre `list_benefits` e
conduz o fluxo de compra completo (`coupon_service`, `payment_service`,
`subscription_service.start_purchase`) internamente. Migrar só o comando
deixaria a exibição no backend e a compra no bot local, inconsistente.
`subscriptions.py` virou a prova de conceito: autocontido, 2 comandos, sem
View, mapeia 1:1 pros métodos já existentes em `SubscriptionDomainService`.

### Etapa 2 — `BackendClient`

`bot/clients/backend_client.py`: timeout, retry só em falha transiente
(rede/timeout/5xx/429, backoff 0.5/1/2s), HMAC simétrico ao
`verify_internal_signature`/`InternalEventsClient` (mesmo `INTERNAL_API_SECRET`
dos dois lados), `BackendClientError` tipado com `status_code` — ao contrário
do `InternalEventsClient` (fire-and-forget, nunca propaga), aqui a falha
propaga porque o cog precisa de uma resposta real pra decidir o que fazer.
Nunca encaminha JWT de player/token Discord/segredo Mercado Pago.

Testado com servidor HTTP local: POST assinado com sucesso, 404
não-retryable propaga `BackendClientError`, servidor fora do ar faz 3
tentativas com backoff e propaga. Ligado em `core/bot.py` como
`self.backend_client` (`None` se `BACKEND_API_BASE_URL`/`INTERNAL_API_SECRET`
não configurados — mesmo fallback gracioso do `InternalEventsClient`).

Settings novas: `BACKEND_API_BASE_URL`, `BACKEND_API_TIMEOUT_SECONDS`
(`bot/config/settings.py` + `.env.example`).

### Etapa 3 — prova de conceito: `subscriptions.py`

Como nenhum endpoint existia, implementei o menor conjunto necessário —
backend primeiro, cog depois:

**Backend** (`backend/api/routes/internal_routes.py`, sob HMAC + rate limit
já existentes do router):
- `GET /internal/subscriptions/active?guild_id=&user_id=`
- `GET /internal/subscriptions/cancelable?guild_id=&user_id=`
- `POST /internal/subscriptions/{id}/cancel` (`executor_id`, `executor_name`, `remove_role`)

Schemas novos em `api/schemas/internal.py` (`SubscriptionSummaryResponse`,
`CancelSubscriptionRequest/Response`). `PlanService` e
`SubscriptionDomainService` (Fase 3D-1, nunca antes instanciado em produção)
entraram no composition root (`backend/api/main.py`) — primeiro uso real.

**Bot** (`bot/cogs/subscriptions.py`): reescrito pra falar exclusivamente com
`self.bot.backend_client` — zero import de `database`/`services` locais
(confirmado por grep). `/assinatura ver` e `/assinatura cancelar` chamam os
3 endpoints acima; falha do backend vira mensagem ephemeral clara, não
exceção não tratada.

### ⚠️ Regressão de comportamento — RESOLVIDA na Fase 5.1

A regressão registrada aqui (`/assinatura cancelar` num plano legado não
removia mais o cargo Discord) está fechada — ver seção "Fase 5.1" abaixo.

### Validações executadas

- 373 arquivos do bot com sintaxe ok (227 do backend, sem mudança de
  contagem — só endpoints/schemas novos nos arquivos já existentes).
- `bot/tests/`: 303 passam, mesmas falhas pré-existentes de env, zero
  regressão.
- Backend: `create_app()` sobe com `INTERNAL_API_SECRET` configurado,
  `app.openapi()` lista os 3 endpoints novos, `alembic heads` continua
  `c2f5e8a1d4b7`, grep confirma zero import de `discord`/`core.bot`.
- `BackendClient` testado isolado (sucesso/erro não-retryable/timeout com
  backoff), mesmo rigor do `InternalEventsClient`.
- **Não testado fim a fim contra Postgres real** (sem instância disponível
  neste ambiente) — mesma limitação já registrada na Fase 4.
- Cog migrado (`subscriptions.py`) confirmado sem nenhum import de
  `database`/`services` locais.

### O que falta pra Fase 5 continuar

- 3 cogs restantes com crossover real (`payment_expiration`, `shop`,
  `subscription_renewal`) seguem bloqueados: `payment_expiration` precisa de
  endpoint pra `list_pending_expired`+`resolve_provider`+`cancel no gateway`+
  `expire_payment` (ou virar reconciliação server-side, redesenho maior);
  `shop` precisa do fluxo de compra inteiro decidido (Fase 3D-2/3C-2
  primeiro); `subscription_renewal` depende da Fase 3D-3 (fonte de dados do
  reminder).
- ~~`SubscriptionNotificationHandler` (Fase 3D-2) devia ser priorizado~~ —
  feito na Fase 5.1 (consumidor mínimo, só `SUBSCRIPTION_CANCELLED`).

---

## Fase 5.1 — Fechar fluxo SUBSCRIPTION_CANCELLED (compatibilidade temporária)

Escopo estrito: só o consumidor mínimo de `SUBSCRIPTION_CANCELLED`, pra
corrigir a regressão de cargo Discord encontrada na Fase 5. Nada de embeds,
DM, reminders ou resto do catálogo de eventos.

### Backend — payload revisado

`SubscriptionNotificationPublisher.publish` (usado por todos os eventos
`SUBSCRIPTION_*`, não só CANCELLED) ganhou 2 campos explícitos no payload:

- `discord_id` — alias de `subscription.user_id`. `Subscription` é
  guild-scoped e já guarda o snowflake do Discord direto (sem FK pra
  `Player`) — nomeado explícito pra o lado bot nunca precisar adivinhar.
- `player_id` — sempre `None`: `Subscription` não referencia `Player`
  (isso só existe pra planos com `Product` vinculado, resolvido via
  `LicenseEventPayload` num canal separado). Mantido no payload pra deixar
  explícito que foi considerado, não esquecido.

`event_id`, `event_type`, `occurred_at`, `version` já existiam no envelope
(`SubscriptionEventEnvelope`, Fase 3D-1) — não precisou adicionar nada aí.
Nenhuma lógica de Discord entrou no backend; `SubscriptionDomainService`
continua só alterando estado, persistindo e publicando.

### Bot — `SubscriptionCancelledHandler`

`bot/services/subscription_cancelled_handler.py` — consumidor mínimo:

- Recebe o payload já parseado (via novo endpoint `POST /internal/subscription-events`
  em `bot/api/routes/internal_routes.py`, protegido pelo mesmo HMAC/rate
  limit do router — mesmo padrão de `/internal/license-events`).
- **Não acessa banco.** Tudo que precisa (`guild_id`, `discord_id`, `role_id`,
  `product_id`, `remove_role`, `was_active`) já vem no `metadata` que
  `SubscriptionDomainService.cancel_subscription` monta desde a Fase 3D-1 —
  zero query nova.
- Se `product_id` não é `None` (plano com `License`), não faz nada — quem
  remove o cargo nesse caso é `RoleSyncService`, reagindo a `LICENSE_REVOKED`
  num canal totalmente separado. `SubscriptionCancelledHandler` só cobre o
  caminho legado (plano com cargo direto, sem `Product`).
- Idempotente por construção: `was_active=False`, `remove_role=False`, cargo
  já ausente, cargo deletado da guild, membro que saiu do servidor, guild
  indisponível — todos os casos retornam limpo, sem exceção, com log
  específico por motivo (`subscription_cancelled_no_op`,
  `subscription_cancelled_role_already_absent`,
  `subscription_cancelled_member_not_found`,
  `subscription_cancelled_guild_not_found`, `subscription_cancelled_forbidden`,
  `subscription_cancelled_discord_error`, `subscription_cancelled_role_removed`).
- Endpoint aceita qualquer outro `event_type` com 204 (evita retry em loop do
  lado do backend) mas só loga (`subscription_event_ignorado`) — o resto do
  catálogo (`SUBSCRIPTION_CREATED/RENEWED/EXPIRED/PAYMENT_*`) continua sem
  consumidor, como antes.

Ligado em `core/bot.py` como `self.subscription_cancelled_handler`.

### Validações executadas

- 374 arquivos do bot + 227 do backend, sintaxe ok.
- `bot/tests/`: 303 passam, mesmas falhas pré-existentes, zero regressão.
- Backend: `create_app()` sobe, `alembic heads` continua `c2f5e8a1d4b7`.
- **7 cenários do Handler testados isolados** (sem HTTP, mocks diretos):
  caminho feliz remove cargo + audita; evento duplicado idempotente; `was_active=False`
  no-op; `product_id` presente no-op; guild não encontrada no-op; `role_id`
  ausente no-op; cargo já removido da guild no-op.
- **Teste de ponta a ponta real via HTTP**: subi o FastAPI real do bot
  (`internal_router` montado, sem mock de framework) numa porta local,
  montei o envelope exatamente como `SubscriptionNotificationPublisher`
  monta, assinei com o mesmo HMAC-SHA256 que `InternalEventsClient` usa, e
  fiz `POST /internal/subscription-events` de verdade — **204, cargo
  removido de fato** (`FakeMember.remove_roles` chamado). Reenviei o mesmo
  evento (mesmo `event_id`, mesmo corpo) — **204 de novo, sem segunda
  remoção** (idempotência confirmada via HTTP real, não só em memória).
- Zero import de `discord`/`LimerenceBot`/`backend` no lado errado (grep
  confirma: backend sem `discord`; Handler não importa nada de `database.repositories`).

### O que ainda falta (fora do escopo desta fase, por decisão explícita)

- `SUBSCRIPTION_CREATED/RENEWED/EXPIRED/PAYMENT_REJECTED/PENDING/CANCELED/EXPIRED/REFUNDED/CHARGEBACK`
  seguem sem consumidor no bot — cada um precisa do mesmo tratamento
  (Handler + endpoint já existe, só falta o dispatch) quando for priorizado.
- Nenhuma notificação ao usuário (DM/embed) foi implementada — só a ação de
  cargo. Mensageria fica pro resto da Fase 3D-2.
- `payment_expiration.py`/`shop.py`/`subscription_renewal.py` continuam
  bloqueados exatamente como no fim da Fase 5.

---

## Fase 5.2 — Auditoria de próximo cog + catálogo `SUBSCRIPTION_*` (CREATED/RENEWED/EXPIRED)

### Auditoria (nenhum cog novo migrado)

Reexecutado o grep sistemático da Fase 5 (`self.bot.<service>` de domínio
migrado + `from database`/`from services` nos 29 cogs), com
`payment_expiration.py`/`subscription_renewal.py`/`payment.py`/reconciliação/
fluxos de licença complexos fora de escopo por decisão explícita. Resultado:
nenhum cog novo atende aos critérios (baixa escrita, baixa dependência
Discord, poucos efeitos colaterais, endpoint simples).

- `subscriptions.py`: já migrado (Fase 5).
- `license_reconciliation.py`: falso positivo — só chama
  `reconciliation_service` (bot-only); o risco real é de nível de *service*
  (`reconciliation_service.py` lendo repositories direto), fora do escopo de
  cog.
- `shop.py`: único cog restante com crossover real, mas alto risco — `/loja`
  em si é leitura pura (`plan_service.list_plans/list_benefits`), só que
  passa objetos `Plan` (ORM) pra `ShopView`, que reabre `coupon_service`/
  `payment_service`/`subscription_service.start_purchase` internamente pro
  fluxo de compra inteiro (cupom, modal de pagador, PIX, aprovação manual) e
  usa ~15 atributos de `Plan` espalhados pela view. Migrar só a leitura
  reabriria a inconsistência já rejeitada no fim da Fase 5 ("shop.py
  descartado como prova de conceito"). Mantido bloqueado.
- Demais 24 cogs: zero crossover com domínio backend, confirmado de novo.

Decisão (usuário, Fase 5.2): sem cog candidato válido nesta rodada, priorizar
fechar a dívida já registrada em "Fase 5.1 — O que ainda falta" — o resto do
catálogo `SUBSCRIPTION_*` no lado bot. Infraestrutura (endpoint
`POST /internal/subscription-events`, `SubscriptionNotificationPublisher`
generalizado desde a Fase 5.1) já cobria todos os event types; faltava só o
dispatch e os handlers de `CREATED`/`RENEWED`/`EXPIRED`.

### Implementação

`bot/services/subscription_cancelled_handler.py` (`SubscriptionCancelledHandler`)
renomeado para `bot/services/subscription_events_handler.py`
(`SubscriptionEventsHandler`) — mesmo consumidor, agora despachando por
`event_type` em vez de só aceitar `SUBSCRIPTION_CANCELLED`:

- `SUBSCRIPTION_CANCELLED`: lógica idêntica à Fase 5.1 (remove cargo do
  caminho legado, no-op se `was_active=False`/`product_id` presente/sem
  `role_id`).
- `SUBSCRIPTION_EXPIRED`: mesmo padrão de remoção de cargo que `CANCELLED`
  (metadata já publicada por `SubscriptionDomainService.expire_subscription`
  desde a Fase 3D-1 — `role_id`/`remove_role`/`product_id`), sem o passo
  `was_active` (evento só dispara com assinatura que estava `ACTIVE`).
- `SUBSCRIPTION_CREATED`/`SUBSCRIPTION_RENEWED`: caminho novo, concede cargo
  (`member.add_roles`) — espelha `_deliver_role` do
  `bot/services/subscription_service.py` local (mesma guarda: no-op se
  `product_id` presente — quem entrega nesse caso é `RoleSyncService` via
  `LICENSE_GRANTED` — ou se `role_id` ausente, ou se o cargo já está
  presente no membro).
- Qualquer outro `event_type` (`PAYMENT_*`, `REFUNDED`, `CHARGEBACK`): logado
  e ignorado, sem exceção — endpoint sempre 204.
- Continua sem acessar banco: todo dado vem do `metadata` do payload. Único
  import de `database` é o enum `AuditLogCategory`, mesmo padrão da Fase 5.1.
- `core/events.py` (bot) ganhou `SUBSCRIPTION_CREATED`/`SUBSCRIPTION_RENEWED`/
  `SUBSCRIPTION_EXPIRED` (só faltavam essas três — `CANCELLED` já existia).
- `core/bot.py`: `self.subscription_cancelled_handler` →
  `self.subscription_events_handler`.
- `api/routes/internal_routes.py`: `receive_subscription_event` não filtra
  mais por `event_type` — repassa tudo pro handler, que decide dispatch vs.
  log-e-ignora (endpoint sempre 204, comportamento externo idêntico ao da
  Fase 5.1 pros tipos ainda sem consumidor).

Nenhuma notificação ao usuário (DM/embed) — só ação de cargo + audit log,
mesmo escopo estrito da Fase 5.1.

### Validações executadas

- `py_compile` nos 5 arquivos alterados + 2 arquivos de teste novos: ok.
- `ruff check`: sem apontamentos.
- `pytest bot`: 322 passam (era 303 na Fase 5.1 antes desta fase, +19 testes
  novos: `test_subscription_events_handler.py` cobrindo os 4 event types +
  no-op de `product_id`/`role_id` ausente/idempotência de cargo
  já-no-estado-alvo/guild ou membro não encontrado; `test_internal_routes.py`
  ganhou dispatch parametrizado pros 4 tipos + um tipo desconhecido). 1
  falha (`test_help_views`) e 7 erros (`test_audit_fixes_validation`, falta
  `JWT_SECRET_KEY` no ambiente) pré-existentes, sem relação com esta
  mudança — confirmado lendo o traceback (setup de fixture de outro módulo,
  nada envolvendo `subscription_events_handler`/`internal_routes`).
- `pytest backend`: `tests/` do backend está vazio (zero arquivos de teste
  hoje) — nada a rodar; nenhum arquivo do backend foi tocado nesta fase
  (publisher/endpoint já cobriam o catálogo completo desde a Fase 3D-1/5.1).
- Grep confirma zero referência solta ao nome antigo
  (`subscription_cancelled_handler`/`SubscriptionCancelledHandler`) em
  `bot/`.
- Backend offline: comportamento inalterado — `BackendClient`/
  `InternalEventsClient` já tratavam isso desde as Fases 5/3C-1; esta fase
  não mexeu no caminho Bot→Backend, só Backend→Bot.
- Não testado fim a fim contra Postgres real (mesma limitação recorrente,
  sem instância disponível neste ambiente) — mas `CREATED`/`RENEWED`/
  `EXPIRED` nesta fase nem dependem de banco no lado bot (só o payload já
  publicado), então o risco é o mesmo da Fase 5.1 (já validada via HTTP
  real).

### O que ainda falta

- `SUBSCRIPTION_PAYMENT_REJECTED/PENDING/CANCELED/EXPIRED/REFUNDED/CHARGEBACK`
  seguem sem consumidor.
- Nenhum cog novo migrado — `shop.py` continua o único candidato com
  crossover real, e continua bloqueado (ver Auditoria acima).
  `payment_expiration.py`/`subscription_renewal.py` seguem excluídos por
  decisão do usuário.

---

## Execução em lote — Fases 5.3 a 5.7

Fases 5.3–5.7 executadas em sequência, sem parar para aprovação entre elas
(pedido explícito do usuário). Regra seguida em cada uma: auditar
dependências, identificar riscos, escolher a menor alteração possível; parar
e documentar (sem implementar) quando o risco de uma mudança maior não desse
pra validar com segurança neste ambiente (sem Postgres/Discord reais).

### Fase 5.3 — `payment_expiration.py`

Auditoria: cog é 100% loop (`tasks.loop` 5 min), zero comando/interação.
Único ponto de leitura pura: `payment_service.list_pending_expired`. Escrita
(cancelar no gateway + `subscription_service.expire_payment`) é
"cancelamento" — explicitamente fora de escopo.

Implementado: `GET /internal/payments/pending-expired?before=` no backend
(`PaymentService.list_pending_expired`, já migrado desde a Fase 3A — só
faltava o endpoint). Cog troca a leitura local por
`BackendClient.list_pending_expired_payments`; a expiração em si (cancelar
no gateway, `expire_payment`) continua local, chamando os services do bot
como antes — não migrada por decisão explícita do escopo. Cog não importa
mais `database.models.payment` (só usa o dict que vem do Backend).

Riscos: nenhum novo — a escrita, que é onde um bug custaria caro
(cancelamento indevido de cobrança), não mudou de lugar.

### Fase 5.4 — `subscription_renewal.py`

Auditoria completa do motor: `SubscriptionReminderService`
(`bot/services/subscription_reminder_service.py`, ~480 linhas) calcula
dias/carência, mantém um livro-razão de idempotência
(`SubscriptionReminderRepository.reserve/finalize`) pra nunca mandar o mesmo
aviso duas vezes, monta e envia DM/embed/botão, e no fim de linha chama
`expire_subscription`. Tudo hoje lendo `Subscription`/`Plan` direto do banco
do bot.

**Decisão: só a leitura de throttle migrou; o motor de decisão fica.**
Migrado: `GET /internal/subscription-renewal/enabled-settings`
(`SubscriptionRenewalConfigService.list_enabled_settings`, já existia no
backend desde a Fase 3A — só faltava o endpoint e ligar o service no
composition root, que também não estava). Cog troca a leitura do throttle
por `BackendClient`; `run_check_cycle` continua 100% local.

**Não migrado (documentado, não implementado):** o motor de decisão em si.
Migrar corretamente exigiria portar o cálculo de dias/carência pro backend
(mecânico — mesma fórmula, troca só a fonte da sessão) **e** um contrato
novo de duas mãos que hoje não existe: o backend reserva a entrada do
livro-razão e decide "mandar aviso tipo X pra assinatura Y", devolve isso
pro bot, o bot manda DM/embed/botão e **confirma de volta** o resultado da
entrega (`sent`/`failed`/`skipped`) pra fechar a mesma linha do livro-razão
— sem esse fechamento em duas etapas, uma falha de rede no meio do caminho
duplica ou perde avisos. Infra de repositório pro contrato já existe no
backend (`SubscriptionReminderRepository`, copiado desde a Fase 1/2), mas o
protocolo HTTP de duas mãos não. Risco de implementar às cegas: duplicar DM
de renovação pro usuário ou deixar de expirar assinatura vencida — nenhum
dos dois é testável sem Postgres/Discord reais neste ambiente. Fica para uma
fase própria, focada só nisso.

### Fase 5.5 — Payment workflows / `ProcessPaymentWebhookUseCase`

Auditoria: `backend/services/webhook_service.py` já validava a assinatura e
confirmava o status real no Mercado Pago desde a Fase 4, mas **não**
despachava a transição de estado — só logava "ação pendente". A transição
de verdade só acontecia no webhook do bot
(`bot/services/webhook_service.py`), que já estava completo e é o que
recebe tráfego real hoje (Mercado Pago aponta pro domínio do bot; `bot/api`
roda em paralelo até a Fase 6).

Implementado: `WebhookService` do backend ganhou `PaymentService` +
`SubscriptionDomainService` no construtor e o mesmo dispatch do bot
(`APPROVED`→`confirm_payment`, `REJECTED`/`CANCELED`→`reject_payment`,
`EXPIRED`→`expire_payment`, `REFUNDED`/`CHARGEBACK`→`set_status` +
`handle_refund_or_chargeback`) — **não duplicou regra nova**, só espelhou a
já existente trocando os services locais do bot pelos do backend.
`api/main.py` reordenado (`SubscriptionDomainService` construído antes de
`WebhookService`, que passou a depender dele). Sem trânsito real: como o
Mercado Pago não aponta pra este endpoint em produção, ligar isso aqui é
"preparação" pura — zero mudança de comportamento observável hoje.
Eventos de pagamento (`SUBSCRIPTION_PAYMENT_REJECTED/PENDING/...`) e
sincronização Backend→Bot: infraestrutura já existia (`SubscriptionNotificationPublisher`
publica em cada uma dessas transições desde a Fase 3D-1) — só faltava o
dispatch acima estar ligado pra elas dispararem de verdade a partir do
webhook do backend.

Não decidido nesta fase (fora de escopo, é decisão de infraestrutura/deploy,
não de código): quando trocar a URL cadastrada no painel do Mercado Pago do
domínio do bot pro do backend. Enquanto isso não acontecer, os dois
`WebhookService` (bot e backend) ficam funcionalmente equivalentes e prontos,
só um deles recebendo tráfego.

### Fase 5.6 — Licença e sincronização

Auditoria: `RoleSyncService.handle_license_event` lia `PlayerRepository`/
`PlanRepository` direto do banco compartilhado do bot pra resolver
discord_id e planos vinculados a um Product — violação direta da regra
"bot nunca acessa banco pra regra já migrada" (Player/Plan são domínio
backend desde a Fase 1/3B). `ReconciliationService` tem o mesmo padrão, só
que em lote (2 queries batched por guild, cruzando membros reais do cargo
Discord com License ativa). `LicenseService` (backend) já é a única
autoridade real de licença desde a Fase 3C-1 — sem duplicação aí.

**Migrado:** `RoleSyncService` — endpoint novo
`GET /internal/role-sync/targets?player_id=&product_id=` (backend),
combinando `PlayerService.get_discord_id` (serviço novo, só essa resolução)
+ `PlanService.list_plans_by_product` (método novo no service já existente).
`RoleSyncService` no bot não importa mais `database.repositories.*` — só
chama `BackendClient.get_role_sync_targets` e aplica o grant/revoke no
Discord. Testes reescritos (`test_role_sync_service.py`,
`test_license_event_bus_integration.py`) trocando os fakes de
repository por mock do `BackendClient`.

**Não migrado (documentado, não implementado):** `ReconciliationService`.
Mesmo risco já registrado na Fase 5.2 ("risco de nível de service") — a
reconciliação decide grant/revoke em massa (todos os membros de um cargo,
todos os planos de uma guild) e uma migração malfeita erra pro lado
oposto de um evento pontual: em vez de 1 cargo errado, um lote inteiro.
Moveria pra um novo endpoint tipo `POST /internal/reconciliation/guild-plan`
recebendo a lista de `discord_id` dos membros do cargo (isso só existe no
cache do Discord, não pode migrar) e devolvendo as duas listas de
divergência — desenho válido, não implementado nesta rodada pela mesma razão
da Fase 5.4: sem Postgres/Discord reais aqui pra validar de forma segura uma
mudança que aplica ações em massa.

**Achado não corrigido (pré-existente, fora de escopo):** `bot/services/subscription_service.py`
(local) ainda usa a própria cópia de `LicenseService` do bot
(`getattr(self._bot, "license_service", None)`) pro fluxo de compra da Loja
— duplicação já registrada nas Fases 3A/3B, só se resolve quando o fluxo de
compra migrar (Fase 5.7).

### Fase 5.7 — Shop

**Auditoria confirmada, nenhuma mudança de código.** `bot/cogs/shop.py`
(comando `/loja`) é leitura pura (`plan_service.list_plans/list_benefits`),
mas passa os objetos `Plan` (ORM) pra `ShopView`
(`bot/views/shop_view.py`, ~760 linhas), que reabre `coupon_service`/
`payment_service`/`subscription_service.start_purchase` internamente pro
fluxo de compra inteiro: seleção de ciclo de cobrança, prompt de cupom
(modal), prompt de "quem vai pagar" (PIX manual), geração de cobrança,
notificação do canal de aprovação, botões de aprovar/rejeitar/pendente/
cancelar. `Plan` é usado em ~15 pontos espalhados da view (cor, emoji,
preços por ciclo, etc.).

Migrar só a leitura do `/loja` reabriria exatamente a inconsistência que a
Fase 5 já rejeitou por nome ("shop.py descartado como prova de conceito"):
catálogo exibido via Backend, compra decidida local — um híbrido permanente,
que esta própria instrução proibiu explicitamente ("não deixar fluxo
híbrido permanente"). Migrar o fluxo inteiro (leitura + compra + cupom +
pagamento + entrega) nesta rodada replicaria o mesmo risco não-testável das
Fases 5.4/5.6-reconciliação, multiplicado: envolve cobrança real
(Mercado Pago/PIX), concessão de cargo/licença e é o único fluxo do sistema
que gera receita — o pior lugar possível pra um bug de integração não
validado contra Postgres/Discord/Mercado Pago reais.

**Decisão: fase parada, não implementada.** Auditoria de leitura/escrita
documentada acima serve de ponto de partida pra quando o fluxo de compra
completo for priorizado como fase própria (não uma sub-tarefa de uma
execução em lote maior).

---

## Fase de consolidação — auditoria de "migração completa" (sem implementação)

Pedido: eliminar todo acesso Bot → PostgreSQL pra domínio do Backend, cortar
Mercado Pago → Backend, remover API do Bot, introduzir Redis. Reauditoria
completa (130+ arquivos do bot tocam `database`/SQLAlchemy direto) confirma
que a classificação Discord-only vs domínio-backend já feita nas Fases 5/5.2
está correta — nenhum cog novo com crossover apareceu além do que já foi
migrado (5.3/5.4-leitura/5.6) ou já parado com motivo documentado
(5.4-motor/5.6-reconciliation/5.7-shop).

**Nenhum código alterado nesta rodada.** Migrar o resto de verdade (services
locais inteiros de payment/coupon/subscription/license/download/product/auth,
corte de Mercado Pago, corte do Launcher, Redis) não é "menor alteração
possível" — é reescrever o núcleo financeiro/de licenciamento sem
Postgres/Mercado Pago/Discord reais pra validar. Forçar isso às cegas seria
a "migração superficial" que a própria instrução proíbe.

### Achado crítico — Launcher aponta pro Bot, não pro Backend

`launcher/src-tauri/src/lib.rs:43`: `LIMERENCE_API_BASE_URL` default é
`http://127.0.0.1:8000` (porta do **Bot**), não `:8001` (**Backend**). A
Fase 4 registrava "Backend passa a ser fonte de verdade da API HTTP" —
isso descrevia a capacidade (backend com endpoints prontos), não o corte de
tráfego real. O corte nunca aconteceu: o Bot ainda roda FastAPI completa
(`bot/api/main.py` — health/webhook/auth/launcher/player/download/internal)
e é, pelo código-fonte, o destino padrão do Launcher hoje. Não alterado
aqui — trocar a porta é decisão de corte de tráfego real, não mudança de
código Python; precisa confirmar paridade completa Backend↔Bot antes.
Consequência direta: `bot/api` não pode ser removido (item 8 da instrução)
enquanto esse corte não acontecer — há consumidor real.

### Verificação final (respostas diretas)

- Bot ainda acessa PostgreSQL? **Sim** — maioria do domínio de negócio
  (payment/plan/coupon/subscription/license/download/product/auth) ainda
  tem service local no bot com acesso direto.
- Existe API de negócio rodando no Bot? **Sim** — `bot/api` completa, com
  consumidor real (Launcher, por padrão).
- Mercado Pago ainda envia webhook para o Bot? **Sim** — dashboard externo
  do Mercado Pago aponta pro Bot; backend está pronto (Fase 5.5) mas sem
  tráfego real.
- Existe regra de negócio duplicada? **Sim** — `bot/services/subscription_service.py`
  local ainda instancia cópia própria de `LicenseService`/`PaymentService`/
  `CouponService` pro fluxo de compra da Loja.
- Backend é a única autoridade para Products/Licenses/Payments/Subscriptions?
  **Não** — é autoridade de *dado* pros fluxos já migrados (assinaturas via
  `subscriptions.py`, eventos de licença via `role_sync_service`), mas o
  bot ainda decide e escreve local pra compra/pagamento/renovação/reconciliação.
- O Launcher depende exclusivamente do Backend? **Não** — aponta pro Bot
  por padrão (achado acima).

Migração **não pode ser declarada concluída** — contradiz a arquitetura-alvo
em várias respostas acima, conforme a própria instrução exige reportar sem
maquiagem.

### Pendências (ordem sugerida, não decidida aqui)

1. Confirmar paridade Backend↔Bot pros endpoints que o Launcher usa, depois
   trocar `LIMERENCE_API_BASE_URL` no deploy do Launcher pra `:8001`.
2. Motor de renovação (`SubscriptionReminderService`) — contrato de duas
   mãos (reserva+finalize) ainda não implementado.
3. ~~`reconciliation_service.py` — migração em lote~~ — **implementado na
   Fase Consolidação-2, ver abaixo.**
4. `shop.py`/fluxo de compra completo — Fase 5.7, alto risco financeiro.
5. Corte Mercado Pago → Backend no dashboard externo (fora de código).
6. Consumidor no bot pra `PAYMENT_*/REFUNDED/CHARGEBACK` (infra já publica).
7. Redis pra rate limit/device flow (hoje in-memory, single-process) —
   decisão de infraestrutura nova, não tomada.
8. Só depois de 1–6: remoção de `bot/api`.

---

## Fase Consolidação-2 — Execução real (Reconciliation, Payment Expiration, Mercado Pago deprecation)

Rodada com instrução explícita de **implementar**, não só auditar. Ordem
seguida: Reconciliation → Subscription Renewal → Payment Expiration →
Shop → Mercado Pago → auditoria de `bot/api`. Cada item abaixo é código
real alterado, não desenho.

### 1. Reconciliation — migrado

`bot/services/reconciliation_service.py` não importa mais `database.database.Database`
nem os repositories (`LicenseRepository`/`PlanRepository`/`PlayerRepository`).
Construtor mudou de `ReconciliationService(database, bot)` pra
`ReconciliationService(bot)`.

Backend:
- `PlayerService.resolve_reconciliation_divergence(product_id, role_member_discord_ids)`
  (`backend/services/player_service.py`) — as duas mesmas queries batched
  (Player por discord_id, License ativa por produto) que existiam no bot,
  agora no backend. Devolve `ReconciliationDivergence` (`revoke_discord_ids`,
  `active_license_discord_ids`).
- `GET /internal/reconciliation/guild-plans?guild_id=` e
  `POST /internal/reconciliation/divergence` (`backend/api/routes/internal_routes.py`,
  schemas em `backend/api/schemas/internal.py`).

Bot: `BackendClient.list_reconciliation_guild_plans`/`get_reconciliation_divergence`
novos; `ReconciliationService` só resolve `discord.Guild.get_role`/`get_member`
(cache local, nunca migra) e aplica grant/revoke com o resultado do backend.
`reconcile_guild` retorna cedo (0 mudanças, `errors=0`) se `bot.backend_client`
for `None` — mesmo fallback gracioso dos outros consumidores.

Teste: `bot/tests/test_reconciliation_service.py` reescrito — `FakeBackendClient`
replica a divergência em memória (sem repository fake), 9 cenários (incluindo
backend indisponível, novo). 9/9 passam.

### 2. Subscription Renewal — não implementado (bloqueio real, documentado desde a Fase 5.4)

Motor de decisão (`SubscriptionReminderService`: cálculo de dias/carência +
livro-razão de idempotência + DM/embed) **não foi tocado nesta rodada**.
Motivo, reavaliado e confirmado, não um "não quis fazer": migrar exige um
contrato HTTP de duas mãos (backend reserva a entrada do livro-razão →
devolve pro bot → bot entrega DM → bot confirma de volta
`sent`/`failed`/`skipped` pra fechar a linha) que ainda não existe em
nenhum dos dois lados, e não há Postgres/Discord real neste ambiente pra
validar que uma falha no meio do caminho não duplica DM de renovação nem
deixa de expirar uma assinatura vencida. Implementar às cegas aqui é
exatamente o "invente solução" que a instrução desta rodada proíbe.
Infraestrutura de repositório (`SubscriptionReminderRepository`) já existe
nos dois lados desde a Fase 1/2 — só falta o protocolo.

### 3. Payment Expiration — fechado (era leitura-só desde a Fase 5.3)

`POST /internal/payments/{payment_id}/expire` novo no backend
(`backend/api/routes/internal_routes.py`) — espelha `PaymentExpirationCog._expire`
campo a campo: resolve provider, cancela no gateway se não for
`ManualProvider` (best-effort, `PaymentGatewayError` só loga warning),
chama `SubscriptionDomainService.expire_payment`. `PaymentService.get`/
`resolve_provider`/`cancel` e `SubscriptionDomainService.expire_payment` já
existiam (Fases 3A/3D-1) — zero regra nova, só orquestração explícita no
router (mesmo padrão dos outros endpoints `/internal/*`).

`bot/cogs/payment_expiration.py`: `_expire` agora só chama
`BackendClient.expire_payment(payment_id)`. Zero import de
`providers.base`/`providers.manual` no cog — a decisão de cancelar no
gateway saiu de vez do bot. `BackendClient.expire_payment` novo.

Teste: `bot/tests/test_payment_expiration_cog.py` reescrito (a classe
`TestExpire` antiga testava lógica que não existe mais no bot — testes
antigos de "cancela no gateway"/"pula pra manual" removidos porque essa
decisão agora é backend-side, coberta pelos testes do endpoint). 6/6 passam.

### 4. Shop — não implementado (bloqueio real, confirmado desde a Fase 5.7)

Mesma auditoria da Fase 5.7 revalidada, mesma conclusão: `ShopView`
(~760 linhas) reabre `coupon_service`/`payment_service`/
`subscription_service.start_purchase` internamente pro fluxo de compra
inteiro (cupom, modal de pagador, PIX, aprovação manual). É o único fluxo
do sistema que move dinheiro real. Migrar às cegas, sem Postgres/Discord/
Mercado Pago reais pra validar, é o risco mais alto do sistema — a
instrução desta rodada pede "não invente solução" quando um bloqueio é
real; este é. Não implementado. Continua sendo o maior item pendente da
migração.

### 5. Mercado Pago — endpoint do bot marcado deprecated, sem corte de tráfego

`bot/api/routes/webhook_routes.py::mercadopago_webhook` ganhou docstring
`DEPRECATED` explícita + `logger.info("mercadopago_webhook_bot_deprecated_endpoint_hit")`
em toda chamada. **Não removido nem desligado** — o dashboard do Mercado
Pago continua apontando pra ele (decisão de infraestrutura externa, fora de
código, já registrada na Fase de Consolidação anterior). Verificado que
processar nos dois lados ao mesmo tempo é seguro: tanto
`bot/services/webhook_service.py` quanto `backend/services/webhook_service.py`
comparam `payment.status == remote.status` antes de agir e retornam cedo
se o pagamento já estiver no status final — idempotência por dado
persistido no Postgres compartilhado, não por não haver corrida. Nenhuma
duplicação de transição de estado é possível mesmo que os dois endpoints
recebam o mesmo webhook.

**Webhook final continua sendo o Bot** (destino real de tráfego) — o
Backend está pronto e equivalente desde a Fase 5.5, mas a troca de URL no
painel do Mercado Pago não é uma mudança de código.

### 6. Auditoria de `bot/api` — nenhum endpoint removido (bloqueio real)

Reconfirmado: `launcher/src-tauri/src/lib.rs` continua com
`LIMERENCE_API_BASE_URL` default `:8000` (Bot). Todo endpoint de
`bot/api` (`auth`, `player`, `launcher`, `download`, `webhook`, `internal`)
tem consumidor real hoje — o próprio Launcher, no destino padrão. Remover
qualquer um deles agora quebraria o Launcher em produção. Item 8 da
instrução ("não remover nada que ainda tenha consumidor") barra a remoção
até o corte de tráfego (pendência 1, decisão de deploy/infra, fora de
código) acontecer. `bot/api` continua subindo FastAPI/Uvicorn.

### Validações executadas nesta rodada

- `python -m compileall` bot/ e backend/: sem erro.
- `python -m ruff check bot backend`: 34 apontamentos pré-existentes (estilo
  `SIM105`/etc. em arquivos não tocados — `views/pending_punishments_view.py`,
  `views/ticket_actions_view.py`, etc.) — **zero apontamento nos arquivos
  alterados** (`reconciliation_service.py`, `payment_expiration.py`,
  `backend_client.py`, `internal_routes.py`, `schemas/internal.py`,
  `player_service.py`, `webhook_routes.py`).
- `pytest bot`: 335 passam (era 322 antes desta rodada), 1 falha +
  7 erros — mesmos pré-existentes de sempre (`test_help_views` categoria
  extra, `JWT_SECRET_KEY` ausente no shell) — zero relação com esta
  mudança.
- `pytest backend`: 10 passam (suíte de testes do backend criada em rodada
  anterior — nada quebrado).
- `alembic heads` (backend): `c2f5e8a1d4b7`, inalterado — nenhuma migration
  nova (nenhuma mudança de schema nesta rodada).
- Não testado fim a fim contra Postgres/Discord/Mercado Pago reais — mesma
  limitação de ambiente de todas as fases anteriores.

### Verificação final (respostas diretas, revisadas)

- Bot ainda acessa PostgreSQL? **Sim** — domínio Discord-only (esperado,
  fica) + domínio pendente: `shop.py`/`subscription_service.py` (compra),
  `subscription_reminder_service.py` (motor de renovação),
  `auth_service`/`license_service`/`payment_service`/`plan_service`/
  `product_service`/`download_service`/`coupon_service`/`launcher_content_service`
  locais (ainda usados por `bot/api` pro Launcher e pelos dois fluxos
  acima) — `reconciliation_service.py` e a decisão de `payment_expiration.py`
  **saíram** desta lista nesta rodada.
- Existe API de negócio rodando no Bot? **Sim** — `bot/api` completa, com
  consumidor real (Launcher, por padrão) — item 6 acima.
- Mercado Pago ainda envia webhook para o Bot? **Sim** — dashboard externo
  aponta pro Bot; endpoint marcado deprecated no código, backend pronto e
  equivalente desde a Fase 5.5, idempotência garantida se algum dia os dois
  receberem tráfego simultâneo.
- Existe regra de negócio duplicada? **Sim, reduzida** — `shop.py`/fluxo de
  compra continua duplicando `LicenseService`/`PaymentService`/`CouponService`
  local. `reconciliation_service.py` e `payment_expiration.py` **não
  duplicam mais** — chamam o backend.
- Backend é única autoridade pra Products/Licenses/Payments/Subscriptions/
  Players/Devices/Sessions? **Não** — autoridade de *dado* pros fluxos
  migrados (agora incluindo reconciliação e expiração de pagamento); bot
  ainda decide/escreve local pra compra e renovação.
- O Launcher depende exclusivamente do Backend? **Não** — mesmo achado de
  sempre, default `:8000`.

Migração **segue não concluída** — dois blocos de risco financeiro/duplicidade
real (Shop, motor de renovação) e uma decisão de infraestrutura (troca de
URL do Launcher e do Mercado Pago) restam, documentados acima com motivo
específico, não "falta implementar" genérico.

---

## Fase Shop — Migração completa do fluxo de compra

Motor de renovação migrado na Fase Final (acima). Esta fase fecha o último
bloco de risco financeiro: **Shop/Cupom**.

### Achado central da auditoria

`SubscriptionDomainService.start_purchase`/`confirm_payment`/`reject_payment`/
`mark_payment_pending`/`cancel_payment` **já existiam migrados desde a Fase
3D-1** — decisão de negócio inteira (preço, cupom, elegibilidade, criação de
Payment/Subscription, concessão de License) já vivia no backend, ninguém
tinha exposto via HTTP nem religado o bot pra usar. `CouponService.validate_and_price`/
`record_redemption` também (Fase 3B). Migrar o Shop foi, na maior parte,
**expor + religar**, não reescrever regra de negócio do zero — reduz
drasticamente o risco em relação ao que a Fase 5.7 tinha estimado.

### Backend — `backend/api/routes/shop_routes.py` (13 endpoints novos)

`GET /internal/shop/catalog`, `/plans/{id}`, `/payments/{id}`,
`/coupons/available`, `/payment-provider`, `/approval-settings`,
`/subscriptions/{id}`; `POST /coupons/validate`, `/purchase/start`,
`/payments/{id}/{confirm,reject,mark-pending,cancel,refresh}`. Cada rota é
fina — só busca a entidade e chama `PlanService`/`CouponService`/
`PaymentService`/`SubscriptionDomainService`, sem regra nova. Erros de
domínio (`CouponError`, `DuplicateSubscriptionError`, `MissingPriceError`)
viram `HTTPException` 422 com `{"error": ..., "message": str(exc)}` — o bot
extrai `message` (`BackendClientError.user_message`, novo) e mostra pro
usuário igual mostrava antes.

### Idempotência (obrigatória pela instrução) — chave nova, migration nova

**Achado real:** o `UNIQUE(provider, external_id)` que já existia em
`PaymentHistory` só protege *depois* que o gateway responde — não impede
duas chamadas (duplo clique, timeout+retry do `BackendClient`) de gerar
*duas cobranças diferentes* no gateway antes disso. Fechado com:

- `payment_history.purchase_idempotency_key` (nova coluna, `UNIQUE`,
  nullable — NULLs não colidem no Postgres, pagamentos fora do fluxo de
  compra como webhook nunca setam) — migration `d4f8a1c6b9e3`
  (`down_revision=c2f5e8a1d4b7`), **espelhada em `backend/alembic/versions/`
  e `bot/alembic/versions/`** (mesmo arquivo, mesmo padrão de revision ID
  idêntico nos dois processos desde sempre). Idempotente (`if column not in
  columns`), `downgrade()` reverte limpo. Modelo `PaymentHistory` atualizado
  nos dois lados (bot: comentário deixando explícito que nenhum código do
  bot lê/escreve o campo — só existe pra manter o schema idêntico na tabela
  compartilhada).
- `SubscriptionDomainService.start_purchase(..., idempotency_key: str |
  None)`: se a chave já foi usada, devolve o `Subscription`/`PaymentHistory`
  já persistidos (reconstrói um `ChargeResult` a partir da linha, sem
  chamar `PaymentService.charge`/o gateway de novo). Bot gera um
  `uuid.uuid4()` novo por **clique** em "Comprar" (uma tentativa lógica) —
  `BackendClient._request` reenvia o mesmo corpo (mesma chave) em retry de
  rede/5xx da mesma tentativa; um clique novo do usuário sempre gera uma
  chave nova. Testado (`test_subscription_domain_service_purchase.py`):
  replay não chama `charge()`; sem chave, comportamento igual a antes.

`confirm_payment`/`reject_payment`/`mark_payment_pending`/`cancel_payment`/
`expire_payment` já eram idempotentes desde a Fase 3A/3D-1
(`PaymentRepository.get_by_id_locked` + `SELECT...FOR UPDATE` +
`expected_statuses` — segunda chamada concorrente encontra o status já
mudado e recebe `None`/`False`) — nada novo aqui, só confirmado na
reauditoria desta fase.

### Bot — `ShopView`/`PaymentEmbedView`/`SubscriptionRenewalButtons` reescritos

`bot/views/shop_view.py` (760 linhas): `Plan` (ORM) trocado por
`dict[str, Any]` (o schema `ShopPlanResponse` do backend) em toda a
superfície — catálogo, card do plano, seleção de ciclo, prompt/modal de
cupom, modal de "quem vai pagar", confirmação de compra, painel de
aprovação (Aprovar/Rejeitar/Pendente/Cancelar). Zero import de
`services.coupon_service`/`services.subscription_service`/
`services.payment_service`/`database.repositories`/`providers.manual`.
`bot/views/payment_view.py` (embed "Atualizar status"/"Cancelar cobrança"
da cobrança PIX) reescrito do mesmo jeito — `refresh_button` chama
`POST /internal/shop/payments/{id}/refresh` (novo, espelha a lógica antiga
ponto a ponto: consulta gateway, persiste, confirma se aprovado);
`cancel_button` reaproveita `POST /internal/payments/{id}/expire` (já
existia da Fase Consolidação — mesma decisão, cancelamento pelo comprador
é literalmente o mesmo caminho que o scheduler de pagamentos vencidos).
`bot/views/subscription_renewal_buttons.py` (botões "Renovar"/"Ver
Plano"/"Abrir Loja" das DMs de renovação) — mesma troca, usando o
`get_shop_subscription`/`get_shop_plan`/`get_shop_catalog` novos do
`BackendClient`. `bot/services/painel_service.py` (painel fixo da loja,
auto-atualiza quando plano muda) também migrado — `_fetch_shop_catalog`
novo, zero `plan_service` local.

### Código morto removido (`bot/services/subscription_service.py`)

Reauditoria de consumidores reais (grep, não suposição) encontrou zero
chamador restante pra: `start_purchase`, `mark_payment_pending`,
`cancel_payment`, `cancel_subscription`, `get_subscription`,
`list_active_subscriptions`, `list_cancelable_subscriptions` — todos
removidos, junto com `DuplicateSubscriptionError`/`MissingPriceError`
(só usadas por `start_purchase`) e o import de `ChargeRequest`/`ChargeResult`
que ficou sem uso. **Mantidos** (consumidor real confirmado):
`confirm_payment`/`reject_payment`/`expire_payment`/`handle_refund_or_chargeback`
— chamados por `bot/services/webhook_service.py`, que ainda recebe tráfego
real do Mercado Pago (INFRA BLOCKER, ver seção abaixo) — e
`list_guild_subscriptions`, usado pelo painel administrativo de renovação
(fora de escopo, CRUD de configuração).

**Não removido (disclosed, não escondido):** `bot/services/coupon_service.py::validate_and_price`/
`record_redemption` continuam existindo no bot — zero chamador real
(`coupon_panel_view.py`, que fica, é só CRUD administrativo: criar/editar/
listar/excluir cupons, nunca valida nem resgata), mas
`bot/tests/test_audit_fixes_validation.py::test_coupon_redemption_race_respects_global_limit`
(teste de integração contra Postgres real, um dos 7 erros pré-existentes
neste ambiente por falta de banco) ainda exercita `record_redemption`
diretamente. Remover o método sem primeiro portar esse teste pra
`backend/tests/` quebraria cobertura de regressão de uma corrida de cupom
já documentada como achado de auditoria — decisão consciente de não
remover às cegas nesta rodada; pendência registrada, não escondida.

### Mercado Pago — revalidado, ainda INFRA BLOCKER

Sem mudança de código nesta fase. `bot/services/webhook_service.py`
continua sendo quem processa o webhook real (endpoint já marcado
`DEPRECATED`, idempotente, ver Fase Consolidação-2) — troca de URL no
dashboard do Mercado Pago é decisão de infraestrutura externa, fora de
código.

### Validações executadas

- `python -m compileall` bot/ e backend/: sem erro.
- `python -m ruff check bot backend`: 32 apontamentos pré-existentes (era
  33 no início desta fase — 1 a menos por causa de um `Database` import
  morto corrigido de passagem), **zero nos arquivos alterados** (13
  arquivos de código + 3 de teste).
- `pytest bot`: 355 passam (era 345 no início desta fase — +10: `test_shop_view.py`
  novo), 1 falha + 7 erros pré-existentes (mesmos de sempre), zero
  regressão nova.
- `pytest backend`: 45 passam (era 24 — +21: `test_shop_routes.py` (19) +
  `test_subscription_domain_service_purchase.py` (2)).
- `alembic heads`: `d4f8a1c6b9e3` nos dois processos (bot e backend,
  idêntico) — 1 migration nova, aditiva, idempotente, `downgrade()`
  simétrico. **Não executado contra Postgres real** (sem instância
  disponível neste ambiente) — sintaxe/estrutura da migration revisada
  manualmente contra o padrão já usado em `c2f5e8a1d4b7`.
- `pytest backend/tests/test_shop_routes.py` usa `httpx.ASGITransport`
  montando só o router (`shop_router`) com HMAC real assinado — mesmo
  padrão de `bot/tests/test_internal_routes.py` — cobre: plano/produto
  inexistente, preço ausente, cupom rejeitado (mensagem propagada),
  assinatura duplicada, compra bem-sucedida, aprovação/rejeição/pendência/
  cancelamento (inclusive conflito 409), refresh de pagamento (gateway
  manual pulado, mudança de status confirma pagamento).
- **Não testado contra Postgres/Mercado Pago reais** — mesma limitação de
  ambiente de todas as fases anteriores. `SubscriptionDomainService.start_purchase`/
  `confirm_payment`/etc. já tinham essa mesma limitação antes desta fase
  (nunca foram testados fim a fim aqui, só a decisão de expô-los é nova).

### Verificação final (respostas diretas)

```
Shop ainda acessa PostgreSQL? NÃO
Shop ainda usa Repository? NÃO
Shop ainda usa BusinessService local? NÃO
Shop usa exclusivamente BackendClient? SIM
```

Confirmado por grep estrutural (`database.repositories`/`payment_service.`/
`subscription_service.`/`coupon_service.`/`license_service.`/
`product_service.` fora de `bot.backend_client`) em `shop_view.py`,
`payment_view.py`, `shop.py`, `subscription_renewal_buttons.py`: zero
ocorrência.

**MIGRAÇÃO DO SHOP CONCLUÍDA.** Migração geral do sistema **segue não
concluída** — motor de renovação (Fase Final) e Shop (esta fase) fecharam
os dois blocos de risco financeiro; restam infra blockers (Launcher em
produção, dashboard Mercado Pago) e itens de escopo consciente (admin CRUD
de cupom/planos/renovação, `reconciliation_service` em lote — já
documentado —, Redis pro Device Flow, `bot/api` — todos com consumidor
real ou motivo técnico específico, não "esquecido").

---

## Fase Final — Motor de renovação, Launcher, Redis (execução real)

Ordem seguida: Reconciliation (feito na rodada anterior) → Motor de
renovação → Shop/Cupom (bloqueio real, ver abaixo) → Mercado Pago (infra
blocker, revalidado) → Launcher → auditoria `bot/api` → Postgres → Redis →
segurança.

### 1. Motor de renovação — migrado por completo

`bot/services/subscription_reminder_service.py` (480 linhas, calculava
dias/carência, mantinha o livro-razão de idempotência e decidia expirar)
virou um consumidor puro: `run_check_cycle`/`handle_renewed` chamam
`BackendClient`, recebem `ReminderNotification` já prontas (template cru,
dados do plano, botões) e só fazem o que exige processo do bot — resolver
`discord.Member`/`discord.Guild`/`discord.Role`, `render_placeholders`,
`member.send`/`channel.send`, e confirmar de volta (`finalize_renewal_reminder`)
o resultado real da entrega. Zero import de `database`/repository.

Backend: `backend/services/subscription_renewal_engine_service.py`
(`SubscriptionRenewalEngineService`) — extraído método a método do
original: `run_check_cycle`, `_process_subscription`, `_maybe_build_day_reminders`,
`_start_grace`, `_finish` (chama `SubscriptionDomainService.expire_subscription`,
já existente desde a Fase 3D-1), `handle_renewed`. Ledger
(`SubscriptionReminderRepository.reserve/finalize/exists`) é a mesma tabela
compartilhada de sempre — zero migração de dado, bot e backend sempre
apontaram pro mesmo Postgres. 3 endpoints novos em `internal_routes.py`:
`POST /internal/subscription-renewal/run-cycle`,
`POST /internal/subscription-renewal/reminders/{id}/finalize`,
`POST /internal/subscription-renewal/renewed-notification`; +
`GET /internal/subscription-renewal/{id}/reminders` pro histórico que o
painel de staff (`subscription_renewal_view.py`) lia direto do banco.

`SubscriptionEventsHandler` (bot) ganhou `_notify_renewal_reminder`: ao
receber `SUBSCRIPTION_RENEWED` (publicado pelo webhook do backend), além de
conceder o cargo (já fazia desde a Fase 5.2) agora também aciona a mensagem
de "renovado com sucesso" via `handle_renewed` — fecha o loop pro caminho
de renovação processado pelo backend, não só pelo fluxo local da Loja.

**Não migrado nesta fatia (decisão de escopo, não bloqueio técnico):** o
painel de administração (`subscription_renewal_view.py`, 821 linhas — CRUD
de `SubscriptionRenewalSettings`/dias de lembrete/templates/botões) continua
lendo/escrevendo `subscription_renewal_config_service` local. É
configuração administrativa, não a decisão de renovação em si (que é o que
a instrução desta rodada pediu: "identificar vencidas, elegibilidade,
tentar renovação, atualizar Payment/Subscription/License, histórico,
estados, eventos" — tudo isso migrou). Migrar o CRUD também é mecânico
(mesmo padrão dos outros ~15 métodos de `SubscriptionRenewalConfigService`,
já existem no backend) mas é outra fatia de trabalho, não implementada por
decisão de escopo/tempo, não por risco.

Validado: `pytest bot` 345 passam (+10 desde a rodada anterior — 21 testes
novos em `test_subscription_reminder_service.py`/`test_subscription_renewal.py`,
11 obsoletos removidos junto com `days_left_until`), mesma 1 falha + 7 erros
pré-existentes; `pytest backend` 18 passam nesta fatia (+8 —
`test_subscription_renewal_engine_service.py`); `ruff`/`compileall` limpos
nos arquivos alterados; `create_app()` sobe com os 4 endpoints novos.

### 2. Shop / Compra + Cupons — CODE BLOCKER (não implementado)

Reauditado com a lente desta rodada: migrar só `CouponService.validate_and_price`/
`record_redemption` (item 3 da instrução) **sem** migrar o resto do fluxo de
compra criaria exatamente o problema que a Fase 5.7 já tinha identificado e
que esta rodada proíbe explicitamente — hoje `bot/services/subscription_service.py::start_purchase`
chama `coupon_service.validate_and_price` e, mais adiante na mesma
transação lógica, `record_redemption`, como duas etapas do mesmo fluxo de
compra que também cria `PaymentHistory` e decide a `Subscription`. Migrar
só o cupom deixaria a checagem de elegibilidade em duas implementações
potencialmente divergentes chamadas em momentos diferentes do mesmo
fluxo (preview em `shop_view.py` vs. autorização em `start_purchase`) — ou
exigiria migrar `start_purchase` inteiro, que é o Shop completo (item 2).

`ShopView` (~760 linhas, `bot/views/shop_view.py`) continua orquestrando
cupom → PIX/pagamento → aprovação manual → `subscription_service.start_purchase`
→ `_grant_license`, tudo local. Esse é o único fluxo do sistema que move
dinheiro real, e não há Postgres/Discord/Mercado Pago reais neste ambiente
pra validar uma reescrita completa sem risco de cobrança duplicada ou
licença não entregue. **CODE BLOCKER, não INFRA BLOCKER** — é trabalho de
código genuíno, só grande e arriscado demais pra essa rodada; motivo
técnico específico registrado, não adiado por padrão.

### 3. Mercado Pago — INFRA BLOCKER (revalidado, sem mudança de código)

Mesmo estado documentado na Fase Consolidação-2: endpoint do bot marcado
deprecated no código, idempotência confirmada nos dois lados
(`payment.status == remote.status`). O que falta é só configuração externa:
trocar a URL cadastrada no **dashboard do Mercado Pago** (fora deste
repositório) do domínio do bot pro do backend. `INFRA BLOCKER` — não
implementável em código.

### 4. Launcher → Backend — migrado (default), corte real pendente de deploy

Mapeados os 8 endpoints que `launcher/src-tauri/src/api_client.rs` de fato
chama: `/auth/device/code`, `/auth/device/token`, `/auth/refresh`,
`/auth/logout`, `/launcher/manifest`, `/player/licenses`, `/download`,
`/download/{id}/complete` — todos com paridade confirmada no backend desde
a Fase 4 (verificado via `app.openapi()`, os 8 paths batem exatamente).
`/launcher/news`, `/launcher/version`, `/update` existem no backend mas não
têm consumidor no client Rust hoje (nenhum `fetch`/`invoke` os chama) —
achado novo, não migração pendente.

`launcher/src-tauri/src/lib.rs::api_base_url()`: default trocado de
`http://127.0.0.1:8000` (Bot) pra `http://127.0.0.1:8001` (Backend).
`BACKEND_BASE_URL` é o nome novo (documentado em `launcher/.env.example`,
criado nesta rodada); `LIMERENCE_API_BASE_URL` (nome antigo) continua
aceito, mesma prioridade — sem quebra de deploys existentes que já setam a
variável antiga explicitamente.

**Isto é mudança de código, não de infraestrutura — mas o efeito só é real
depois de: (a) rebuild do Launcher com este código, (b) confirmar que o
Backend está de fato rodando e acessível no endereço configurado em
produção.** Não pude validar isso fim a fim (sem ambiente de produção
aqui) — sinalizado explicitamente, não maquiado como "corte concluído".
`cargo check` não rodou limpo neste ambiente por motivo não relacionado
(ícone `.ico` ausente em `launcher/src-tauri/icons/`, problema
pré-existente do projeto, confirmado antes desta mudança).

### 5. Auditoria `bot/api` — nenhum endpoint removido (dependência real)

Com o default do Launcher só trocado em código (não implantado), o Bot
continua sendo o destino real até confirmação de deploy — remover qualquer
endpoint de `bot/api` agora quebraria produção. Mantido 100% intacto,
igual à rodada anterior.

### 6. PostgreSQL — auditoria revalidada

`grep -rl "from database.repositories\|from database.database import Database" bot/services/*.py`
lista 31 arquivos (era 33 na rodada anterior — `reconciliation_service.py`
e `payment_expiration`'s decisão saíram; `subscription_reminder_service.py`
sai nesta rodada). Todos os 31 restantes são: domínio Discord-only
(esperado, correto ficar) **ou** domínio pendente já classificado
(`auth_service`/`coupon_service`/`download_service`/`launcher_content_service`/
`license_service`/`payment_service`/`plan_service`/`product_service`/
`subscription_service`/`subscription_renewal_config_service`/`webhook_service`
— usados por `bot/api` pro Launcher e pelo fluxo local de compra/renovação-admin,
Migration pending, motivo documentado acima).

### 7. Redis — implementado (rate limiter), Device Flow adiado

`backend/core/redis_rate_limiter.py` (`RedisRateLimiter`, sorted-set por
janela deslizante, mesma interface `hit(key)`) +
`backend/core/rate_limiter_factory.py` (`create_rate_limiter`): com
`REDIS_URL` configurado e pacote `redis` instalado, todo rate limiter do
backend (8 pontos: `download`/`internal`/`launcher`×2/`player`/`webhook`
nos routers + 5 buckets do `AuthService`) passa a usar Redis; sem
`REDIS_URL`, ou sem o pacote instalado, cai pro `RateLimiter` em memória de
sempre — fallback gracioso, mesmo comportamento de hoje, sem quebrar nada.
`redis>=5.0,<6.0` adicionado a `requirements.txt`; `REDIS_URL` documentado
em `.env.example`. Testado com um fake Redis in-memory (sorted set em
dict) — 6 cenários (permite sob o limite, estoura o limite, chaves
independentes, janela expira, fallback sem `REDIS_URL`, fallback sem
pacote instalado). **Não testado contra um Redis real** — nenhuma
instância disponível neste ambiente.

**Não implementado nesta rodada:** Device Authorization Flow
(`AuthService._pending_logins`, dict in-memory com um dataclass por login
pendente) continua em RAM. Mesmo problema estrutural do rate limiter
(não escala pra múltiplas instâncias), mas migrar pra Redis exige
serializar um dataclass com campos de estado OAuth (nem todos primitivos)
e tocar ~7 pontos de leitura/escrita — mudança real, não decidida às
cegas nesta rodada por tempo, não por risco técnico alto. `CODE BLOCKER`
registrado, não escondido.

### 8. Segurança — revisão sem achados novos

Checados: HMAC interno (`hmac.compare_digest`, comparação de tempo
constante, timestamp amarrado na assinatura, janela de idade — já estava
correto); JWT (`core/security/jwt_service`, testado isolado desde a Fase
4); idempotência de webhook (confirmada Fase Consolidação-2); signed URLs
de download (TTL + `signed_url_expires_at` rastreado); CORS
(`cors_allowed_origins` configurável via `Settings`, não hardcoded); Client
Secret do Discord **não** aparece em nenhum arquivo do Launcher (grep
confirma). Nenhum achado novo — os controles já existentes desde fases
anteriores seguem corretos. Único ponto sinalizado (não novo): Device Flow
em memória (item 7 acima) é também uma superfície de segurança (estado de
login pendente perdido num restart/múltiplas instâncias), não só de
escala.

### Testes desta rodada

- `pytest bot`: 345 passam (era 335), 1 falha + 7 erros pré-existentes
  (mesmos de sempre — `test_help_views`, `JWT_SECRET_KEY` ausente no
  shell), zero regressão nova.
- `pytest backend`: 24 passam (era 10 no início desta sessão, 18 depois da
  Fase Consolidação-2 desta mesma sessão).
- `ruff check bot backend`: 33 apontamentos pré-existentes (mesma lista de
  sempre, arquivos não tocados), zero nos arquivos alterados nesta rodada.
- `python -m compileall` bot/ e backend/: sem erro.
- `alembic heads`: `c2f5e8a1d4b7`, inalterado — zero mudança de schema.
- `alembic upgrade head` / `downgrade -1` / `upgrade head`: **não
  executado** — sem instância Postgres disponível neste ambiente; como não
  há migration nova, o risco é nulo, mas o ciclo real não foi exercitado.
- `cargo check` (launcher): não rodou limpo — falha pré-existente
  (`icon.ico` ausente), não relacionada a esta mudança; sintaxe do Rust
  alterado revisada manualmente.
- Testes de integração reais (Postgres/Redis/Discord/Mercado Pago): **não
  executados, nenhuma instância disponível neste ambiente** — registrado
  explicitamente, não simulado como sucesso.

---

## Fase Consolidação Staging — `bot/api` reduzido, Redis obrigatório em produção, infra criada

Execução real (não desenho) de uma auditoria anterior que apontou: zero
Dockerfile/compose/reverse-proxy em todo o repositório, `bot/api` ainda 100%
intacto, Redis sem exigência em produção, Device Flow ainda em memória.

### `bot/api` — reduzido de 7 routers pra 3

Reauditados os 4 routers ainda idênticos ao Backend (`auth_routes.py`,
`download_routes.py`, `launcher_routes.py`, `player_routes.py`): grep
confirmou zero consumidor real fora deles mesmos e dos próprios testes —
nenhum cog, nenhum service do bot os chama (o Launcher já fala com o Backend
por padrão desde a "Fase Final", e nenhuma infraestrutura deste projeto foi
implantada em lugar nenhum até agora, confirmado por auditoria: `infra/docker`,
`infra/deploy`, `infra/cloudflare-r2` estavam vazios, zero Dockerfile em
`backend/` ou `bot/`). Diferente da decisão da "Fase Final" (que manteve tudo
intacto por não conseguir confirmar ausência de deploy real) — esta rodada
teve essa confirmação, então a remoção seguiu.

**Removido** (arquivo excluído, não só desregistrado): `api/routes/auth_routes.py`,
`download_routes.py`, `launcher_routes.py`, `player_routes.py`;
`api/schemas/auth.py`, `launcher.py`; `services/auth_service.py`,
`download_service.py`, `launcher_content_service.py`, `product_service.py`;
`core/security/jwt_service.py`, `tokens.py` (só tinham consumidor dentro de
`auth_service.py`, confirmado por grep antes de apagar). Testes removidos
junto (testavam código que deixou de existir):
`test_auth_routes.py`, `test_auth_service.py`, `test_jwt_service.py`,
`test_tokens.py`, `_fakes_auth.py`, `test_download_service.py`,
`_fakes_download.py`, `test_launcher_download_routes.py`,
`test_launcher_content_service.py`, `_fakes_launcher_content.py`,
`test_product_service.py`, `_fakes_product.py`.

**Mantido** (consumidor real confirmado): `health_routes.py` (healthcheck do
container); `internal_routes.py` (canal Backend→Bot ativo, único jeito do
Backend notificar `RoleSyncService`/`SubscriptionEventsHandler`/reconciliação
sob demanda — não é duplicação, é o lado receptor de um canal que só existe
uma vez); `webhook_routes.py` (`/webhooks/mercadopago`, **INFRA BLOCKER
externo, não removido** — dashboard do Mercado Pago ainda não foi trocado pro
Backend, fora deste repositório).

`bot/core/bot.py`: removida a instanciação de `ProductService` (zero
consumidor fora do router removido). `bot.license_service` **ficou** — ainda é
dependência real de `subscription_service._grant_license`/`_revoke_license`,
usadas por `confirm_payment`/`handle_refund_or_chargeback` do
`webhook_service.py` do bot, que continua recebendo o Mercado Pago real.

`bot/api/main.py`: `create_app()` monta só 3 routers agora. `bot/api/dependencies.py`:
removida `get_current_player` (só usada pelas rotas apagadas).

**Não removido, apesar de virar dead code**: `bot/config/settings.py` ainda
exige (`_require`) `JWT_SECRET_KEY`, `DISCORD_OAUTH_CLIENT_ID`,
`DISCORD_OAUTH_CLIENT_SECRET` no boot, e ainda declara campos `storage_*` —
nenhum consumidor real depois desta rodada (confirmado por grep), mas remover
esses campos toca `tests/test_settings.py` e as fixtures de `conftest.py`
compartilhadas por toda a suíte — decisão consciente de não mexer nesta
rodada (risco desproporcional ao benefício, que é só operacional: bot exige
3 env vars que não usa mais pra nada). Pendência registrada, MEDIUM, não
escondida.

**bot/main.py**: continua subindo Discord bot + Uvicorn no mesmo processo
(`asyncio.gather`) — não virou "só Discord Bot" porque `internal_routes.py` e
`webhook_routes.py` (Mercado Pago, INFRA BLOCKER) ainda precisam de um
servidor HTTP vivo no bot. Só fica 100% Discord-only depois que o dashboard
do Mercado Pago apontar pro Backend.

### Redis obrigatório em produção

`backend/config/settings.py`: campo novo `redis_url`, `Settings.load()` agora
recusa subir (`SettingsError`) se `ENVIRONMENT=production` e `REDIS_URL`
ausente — mesmo padrão de validação já usado pra `JWT_SECRET_KEY`/
`PUBLIC_BASE_URL` https/`MERCADOPAGO_WEBHOOK_SECRET_PRODUCTION`. Não migra o
Device Flow (`AuthService._pending_logins`, ainda em RAM) — CODE BLOCKER já
registrado na "Fase Final", reavaliado nesta rodada e conscientemente **não
implementado**: é código de segurança (guarda token/PKCE efêmeros) sem
Redis real disponível neste ambiente pra validar a migração fim a fim: risco
de quebrar login inteiro sem forma de testar supera o benefício nesta rodada.
Continua HIGH, não escondido.

### Infra de staging criada (`infra/docker/`)

`Dockerfile.backend`, `Dockerfile.bot`, `docker-compose.yml`,
`docker-compose.staging.yml`, `Caddyfile`, `.env.example`, `BACKUP.md` — todos
novos (pasta estava vazia). Postgres/Redis sem `ports:` (nunca expostos ao
host nem à internet, só `backend_net` interna); reverse proxy (Caddy, HTTPS
automático) na `edge_net`, domínio placeholder explícito
(`SEU-DOMINIO-AQUI.example`) documentado como tal, nunca inventado como se
fosse real. Healthcheck/restart/volumes/networks definidos pros 5 serviços.
`infra/cloudflare-r2/README.md` documenta passo a passo de conta (bucket,
token com escopo restrito, endpoint) — nada disso é executável por mim, é
configuração de conta de terceiro.

### Processo de migration — decisão explícita

**Só o Backend roda `alembic upgrade head`.** O Bot nunca deve rodar alembic
em deploy/CI — `bot/alembic/` continua no repo só porque os arquivos de
migration são literalmente idênticos aos do Backend (mesma cadeia, mesmo
banco compartilhado, sempre foi assim desde a Fase 1) e apagá-los quebraria
`bot/database`/testes que importam o pacote; não representa uma segunda
autoridade — é o mesmo schema, lido, nunca aplicado por lá. Nenhum comando
`alembic upgrade`/`downgrade` foi executado contra Postgres real nesta
rodada (nenhuma instância disponível neste ambiente) — só `alembic heads`
(metadata dos arquivos), confirmando head único `d4f8a1c6b9e3` nos dois
lados, sem mudança nesta rodada.

### Validado

- `python -m compileall bot/` e `backend/`: sem erro.
- `pytest backend`: 45 passed (inalterado).
- `pytest bot`: 280 passed, 3 failed + 7 errors — **mesmos 3 failed + 7
  errors pré-existentes de sempre** (dependem de Postgres real/env ausente
  neste shell, não relacionados a esta mudança); queda de 353→280 é só os
  testes deletados junto com o código que testavam, zero regressão nova.
- `ruff check bot`: 23 apontamentos (era 26, queda por arquivos deletados,
  zero apontamento novo). `ruff check backend`: 6 (inalterado).
- `alembic heads` bot e backend: `d4f8a1c6b9e3` nos dois, sem branch.
- **Não executado**: `alembic upgrade head`/`downgrade` contra Postgres real,
  `docker compose up` real, `cargo check` do Launcher — sem instância/toolchain
  disponível neste ambiente.
