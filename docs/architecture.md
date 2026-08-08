# Arquitetura — LIMERENCE

Visão geral do sistema e como os módulos se conectam.

> **Migração bot → backend em andamento — NÃO CONCLUÍDA.** A arquitetura
> alvo (backend como única autoridade, bot como cliente HTTP e só Discord)
> ainda não é o estado real. Achado crítico (fase de consolidação):
> `launcher/src-tauri/src/lib.rs` aponta por padrão pro **Bot**
> (`:8000`), não pro Backend (`:8001`) — o corte de tráfego real do
> Launcher nunca aconteceu, só a capacidade do backend foi construída.
> Mercado Pago também segue apontando pro Bot (dashboard externo). O
> diagrama "Estado final" abaixo é a meta, não o presente — ver seção
> "Estado atual" logo depois. Log completo (o que foi movido, decisões de
> design, riscos, o que falta) em
> [`docs/migracao-bot-backend.md`](./migracao-bot-backend.md).

## Estado atual (real, não a meta)

```text
Discord ──▶ Bot ──┬──▶ PostgreSQL (domínio Discord-only: tickets, staff,
                   │    automod; + admin CRUD local fora de escopo: cupom/
                   │    plano/renovação — configuração, não decisão;
                   │    auth/player/device/session locais usados pelo
                   │    bot/api pro Launcher)
                   └──▶ Backend (HTTP/HMAC — assinaturas, expiração de
                        pagamento, reconciliação em lote, motor de
                        renovação completo, fluxo de compra completo
                        (Shop) via /internal/shop/*, eventos de licença
                        via role-sync)

Launcher ──HTTPS──▶ Backend (:8001, novo default de BACKEND_BASE_URL/
                     LIMERENCE_API_BASE_URL no código) ──▶ PostgreSQL
                     (default trocado nesta rodada — paridade dos 8
                      endpoints reais confirmada — mas o corte só é
                      efetivo depois de rebuild+deploy do Launcher e
                      confirmação de que o Backend está no ar; não
                      verificado fim a fim neste ambiente)

Mercado Pago ──Webhook──▶ Bot (:8000) ──▶ PostgreSQL
                     (Backend tem WebhookService completo desde a Fase 5.5,
                      sem tráfego real — dashboard do Mercado Pago não foi
                      trocado; endpoint do bot marcado DEPRECATED no código,
                      idempotente por status já persistido — seguro receber
                      nos dois lados)
```

## Estado final (meta — ver `docs/migracao-bot-backend.md` pro que falta)

```text
Discord ──▶ Bot (Discord only) ──HTTP/HMAC──▶ Backend (FastAPI) ──▶ PostgreSQL

Launcher ──HTTPS──▶ Backend ──Signed URL──▶ Cloudflare R2

Mercado Pago ──Webhook──▶ Backend
```

Bot nunca acessa PostgreSQL/repository/SQLAlchemy pra domínio já migrado;
nunca é segunda autoridade de negócio; API própria removida só depois de
confirmado zero consumidor restante.

## Módulos

### backend/ — EM MIGRAÇÃO (ver `docs/migracao-bot-backend.md`)
API central em FastAPI. Responsável por autenticação (JWT), OAuth Discord, licenças,
catálogo de produtos, downloads, pagamentos e banco de dados — única autoridade
do sistema. O bot deixa de acessar banco/regra de negócio diretamente e passa a
ser cliente HTTP desta API.

> **Status:** processo próprio (porta 8001, independente do bot), com
> persistência completa (models/repositories/alembic — mesmos revision IDs do
> bot), domínio de licenças/assinaturas/pagamentos/download/launcher migrado
> (Fase 3A–3D-1) e **25 endpoints HTTP ativos** (auth, player, launcher,
> download, health, webhook — Fase 4; + 6 endpoints internos —
> `/internal/subscriptions/*` da Fase 5, + `/internal/payments/pending-expired`,
> `/internal/subscription-renewal/enabled-settings` e
> `/internal/role-sync/targets` das Fases 5.3/5.4/5.6 — consumidos pelo bot
> via `BackendClient`), servidos por `backend/main.py` (`uvicorn`, porta
> 8001). `bot/api` continua rodando em paralelo, sem nenhuma alteração, até
> o corte final (Fase 6). Canal de eventos Backend→Bot
> (`InternalEventsClient`) funcional, consumido no bot por
> `SubscriptionEventsHandler`: `SUBSCRIPTION_CANCELLED` (Fase 5.1) +
> `CREATED`/`RENEWED`/`EXPIRED` (Fase 5.2) fecham o ciclo completo pro ramo
> de cargo direto legado (Backend muda estado → publica evento → Bot
> concede/remove cargo Discord). `ProcessPaymentWebhookUseCase` implementado
> na Fase 5.5 (`WebhookService` do backend despacha pra
> `SubscriptionDomainService`) — preparação, sem tráfego real ainda (Mercado
> Pago aponta pro webhook do bot em produção). Log completo e decisões em
> `docs/migracao-bot-backend.md`.

Estrutura atual (mantida igual ao layout do bot de propósito, ver rationale no
log de migração):
- `api/` — FastAPI app, dependencies, schemas, routers
- `database/models/`, `database/repositories/` — SQLAlchemy
- `services/` — regras de negócio já migradas
- `providers/` — gateways externos (Mercado Pago, storage S3/R2)
- `core/` — config, logger, JWT, rate limiter, event bus
- `alembic/` — migrations (cadeia idêntica à do bot)

### launcher/ (Fases 4, 5, 6, 9, 10)
Aplicação desktop em Tauri (Rust + TypeScript). Interface do launcher que consome a API do backend: login, listagem de produtos, download e atualização do jogo/DLCs.

Estrutura sugerida:
- `src-tauri/` — camada Rust (janela nativa, updater, filesystem)
- `src/` — frontend TypeScript/UI do launcher
- `public/` — assets estáticos

### bot/ (Fase 7 + parte da 10)
Bot de Discord. Escuta eventos, sincroniza estado entre Discord/backend (ex.: roles de acordo com licença) e mantém auditoria de ações.

> **Status (Fase 5–5.7, em andamento):** `bot/clients/backend_client.py` —
> único ponto de chamada HTTP Bot → Backend (`self.bot.backend_client`, HMAC,
> retry, timeout), com um método dedicado por operação (Fase 5.3+, em vez de
> `get`/`post` genérico direto no cog). `subscriptions.py` fala
> exclusivamente com o backend via `/internal/subscriptions/*`;
> `payment_expiration.py` e `subscription_renewal.py` migraram a parte de
> leitura (consulta de pagamentos vencidos / throttle de renovação), mantendo
> a escrita local por decisão explícita de escopo (Fases 5.3/5.4).
> `role_sync_service.py` parou de acessar `Player`/`Plan` direto do banco
> compartilhado — resolve via `/internal/role-sync/targets` (Fase 5.6).
> `subscription_events_handler.py` recebe o catálogo
> `SUBSCRIPTION_CANCELLED/CREATED/RENEWED/EXPIRED` do backend
> (`POST /internal/subscription-events`, mesmo HMAC do canal de licença) e
> concede/remove o cargo Discord do ramo legado (plano sem `Product`).
> `reconciliation_service.py` migrado nesta rodada (Fase Consolidação):
> zero acesso a `Player`/`License`/`Plan` — decisão via
> `/internal/reconciliation/guild-plans` +
> `/internal/reconciliation/divergence`, só aplica grant/revoke de cargo com
> o resultado. `payment_expiration.py` também fechado nesta rodada: cog é
> só o `@tasks.loop`, cancelamento no gateway + `expire_payment` decididos
> inteiros no backend (`POST /internal/payments/{id}/expire`).
> `subscription_reminder_service.py` migrado nesta rodada (Fase Final):
> motor de decisão inteiro (dias/carência, ledger, expiração) mudou pro
> backend (`SubscriptionRenewalEngineService`); bot só resolve
> Member/Guild/Role, renderiza o template e entrega DM/canal, confirmando
> o resultado de volta. Admin CRUD das configurações de renovação
> (`subscription_renewal_view.py`) continua local, fora de escopo.
> `shop.py`/fluxo de compra — **migrado (Fase Shop)**: `shop_view.py`/
> `payment_view.py`/`subscription_renewal_buttons.py`/`painel_service.py`
> falam exclusivamente com `BackendClient` (13 endpoints novos em
> `backend/api/routes/shop_routes.py`) — zero `database`/`repositories`/
> `payment_service`/`subscription_service`/`coupon_service`/`license_service`
> local nesses arquivos (confirmado por grep estrutural). Nova coluna
> `payment_history.purchase_idempotency_key` (migration `d4f8a1c6b9e3`,
> espelhada bot+backend) fecha o gap de retry/duplo clique gerando cobrança
> duplicada no gateway. `bot/services/coupon_service.py::validate_and_price`/
> `record_redemption` continuam existindo (sem chamador real) só por causa
> de um teste de integração pré-existente que os exercita — pendência
> registrada, não escondida. Ver `docs/migracao-bot-backend.md#fase-shop`.

Estrutura atual:
- `clients/` — `backend_client.py` (Bot → Backend, um método por operação)
- `services/subscription_events_handler.py` — consumidor de eventos (Backend → Bot)
- `services/role_sync_service.py` — consumidor de eventos de licença, resolve Player/Plan via Backend
- `cogs/` — comandos e listeners (parte ainda local, parte já cliente HTTP)
- `services/`, `database/` — domínio ainda não migrado (Discord-guild: tickets, staff, automod, etc.; motor de renovação; reconciliação em lote; fluxo de compra da Loja)

### game/
Projeto Ren'Py.
- `Limerence/` — jogo base
- `DLCs/` — conteúdo adicional/expansões

### infra/
- `docker/` — Dockerfiles e compose para backend/bot
- `cloudflare-r2/` — configuração de storage para builds/downloads
- `deploy/` — scripts/configuração de deploy

## Fluxo resumido

1. Usuário compra/recebe licença → backend registra em `Products`/`Licenses`.
2. Launcher autentica via JWT no backend, consulta licenças e produtos liberados.
3. Launcher baixa o jogo/DLC (armazenado via Cloudflare R2, referenciado pelo backend).
4. Bot do Discord sincroniza cargos/acesso com o status da licença e registra auditoria.

## Próximos passos

- Detalhar contratos de API (rotas, payloads) em `docs/database.md` e specs próprias.
- Definir modelo de dados completo (usuários, licenças, produtos, pagamentos).
- Especificar política de segurança em `docs/security.md`.
