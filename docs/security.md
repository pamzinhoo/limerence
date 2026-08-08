# Segurança — LIMERENCE

> Arquitetura real: **não existe um serviço "backend" separado**. O
> `bot/` (Python/FastAPI + discord.py) embute a API HTTP no mesmo processo
> — `bot/api/main.py` sobe o FastAPI (`bot/api/routes/*.py`) junto do bot
> Discord, compartilhando a mesma conexão com o Postgres
> (`bot/database/`). O diretório `backend/` na raiz do repo é um scaffold
> vazio, não usado. O `launcher/` (Tauri 2 + Rust + TS) e o `game/`
> (Ren'Py) são clientes dessa API embutida.

## Autenticação (Discord OAuth + JWT)

- Login do Launcher via Discord OAuth2 com **PKCE + state** (`bot/api/routes/auth_routes.py`),
  nunca client-secret exposto ao cliente.
- Backend emite JWT (HS256) — access token de curta duração
  (`jwt_access_ttl_seconds`, default 900s) e refresh token
  (`refresh_token_ttl_days`, default 30 dias), com **rotação a cada uso**
  e **detecção de reuso** (refresh token usado duas vezes revoga a sessão
  inteira, não só o token).
- JWT inclui `kid` no header para suportar rotação de chave sem invalidar
  tokens em voo.
- `JWT_SECRET_KEY` e `INTERNAL_API_SECRET` exigem mínimo de 32 bytes
  (`bot/config/settings.py::_MIN_SECRET_LENGTH`) — chave curta é forjável
  por força bruta offline contra HS256 (RFC 7518 §3.2); `Settings.load()`
  recusa subir com chave abaixo do mínimo.
- Launcher (Tauri) guarda tokens no keychain/local seguro do SO via
  plugin do Tauri — nunca em texto puro em disco nem hardcoded no
  bundle.

## Licenças

- Toda validação de licença acontece no bot/API (`bot/services/license_service.py`,
  `bot/database/repositories/license_repository.py`) — o launcher nunca decide
  sozinho se um produto está liberado.
- Endpoints de download (`bot/api/routes/download_routes.py`) exigem
  token válido **+** licença ativa para o produto solicitado, checada no
  momento da assinatura da URL (não só no login).
- **Gap conhecido**: validação offline de licença (grace window
  assinado por HMAC, descrito na arquitetura §8) não tem implementação
  no servidor ainda — o launcher hoje depende de estar online para
  validar. Ver `docs/architecture.md` §8 para o design pretendido.

## Sessões e Devices

- `launcher_sessions` e `devices` (`bot/database/models/`) rastreiam de
  qual device/sessão cada refresh token válido se origina — revogar uma
  sessão (ex.: staff banindo, usuário deslogando remotamente) propaga
  para todos os refresh tokens daquela sessão.
- Reuso de refresh token revogado derruba a sessão inteira (contramedida
  a token roubado sendo usado em paralelo pelo dono legítimo e por um
  atacante).

## Multi-tenant (guilds)

- Todo dado guild-scoped tem `guild_id` e os repositórios expõem
  `list_by_guild(...)` — modelos globais (ex.: `CommandHelp`) são a
  exceção explícita documentada em `BaseRepository.list_all`.
  `reconciliation_service.py` e `role_sync_service.py` sempre filtram
  por guild/produto antes de tocar cargo Discord, evitando vazamento
  cross-guild.

## Bot do Discord

- Bot nunca escreve licença/cargo sem passar pela camada de serviço
  (`bot/services/`), que audita a ação — nunca ação silenciosa.
- Toda ação que afeta licença/role é registrada em auditoria via
  `bot/database/repositories/audit_log_repository.py` (auditoria geral)
  e `bot/database/repositories/audit_log_launcher_repository.py`
  (auditoria específica do fluxo de login do Launcher). Configuração de
  quais categorias auditar fica em `audit_log_settings_repository.py`.
- `bot/services/reconciliation_service.py` roda periodicamente como rede
  de segurança: nunca confia só em evento do Discord (bot offline,
  membro saiu/voltou, edição manual de cargo por staff) — corrige
  divergência nas duas direções e audita cada correção.

## Pagamentos (Mercado Pago)

- Gateway é Mercado Pago (`bot/providers/mercadopago.py`), não
  Stripe — sandbox/produção controlados por `PAYMENT_MODE` e tokens
  separados por modo (`mercadopago_access_token_sandbox/production`).
- Webhook (`bot/api/routes/webhook_routes.py`) valida assinatura HMAC
  antes de processar, e **sempre re-busca o status direto na API do
  Mercado Pago** em vez de confiar no payload do webhook — mitiga
  webhook forjado com assinatura vazada ou payload adulterado em
  trânsito.
- Processamento de webhook é idempotente (reprocessar a mesma
  notificação não duplica efeito colateral).
- Backend nunca processa dado de cartão diretamente — checkout delega
  ao Mercado Pago (Checkout Pro / Pix).

## Downloads (Cloudflare R2)

- URLs de download assinadas via boto3 (S3-compatible, `bot/providers/storage/`),
  TTL curto (`storage_download_ttl_seconds`, default 600s).
- Licença é **re-checada no momento de assinar a URL**, não só no login
  — uma licença revogada entre o login e o clique em "baixar" não recebe
  URL nova.
- Rotas de download são GET-only, sem side effect.

## Canal interno Bot<->processos internos

- `/internal/*` (`bot/api/routes/internal_routes.py`, eventos de
  licença, reconciliação sob demanda) autentica via HMAC compartilhado
  (`INTERNAL_API_SECRET`), mesmo esquema de `providers/mercadopago.py::validate_webhook`.
  Sem o secret configurado, a rota responde 503 em vez de aceitar sem
  autenticação.
- Janela de replay de 300s nas requisições HMAC — timestamp fora da
  janela é rejeitado mesmo com assinatura válida.

## Rate limiting

- `bot/core/rate_limiter.py` protege rotas sensíveis (auth, download,
  webhook). Sweep periódico evita crescimento de memória sem limite no
  dicionário de hits (bug corrigido nesta auditoria — chaves antigas
  agora são varridas, não só quando `deque` local esvazia).

## CORS / MITM / Downgrade

- CORS nega toda origem por padrão (lista vazia) — API é consumida via
  Bearer token pelo Launcher (Tauri), não por cookie de navegador, então
  não há CSRF clássico via browser; `cors_allowed_origins` só deve ser
  preenchido se um painel web vier a existir.
- `PUBLIC_BASE_URL` com `ENVIRONMENT=production` é obrigado a usar
  `https://` (`Settings.load()` recusa subir caso contrário) — evita
  downgrade de HTTPS para HTTP em produção expondo token/refresh
  token/assinatura de webhook em texto claro.

## Engenharia reversa / Launcher

- Nenhum segredo (client secret OAuth, chaves de assinatura, tokens de
  API de terceiros) fica embutido no bundle do Launcher — só o
  `discord_oauth_client_id` (público por natureza no fluxo PKCE).
- Toda decisão de negócio (licença válida? cargo correto? preço?) é
  resolvida no servidor; o cliente Tauri não pode ser adulterado para
  contornar essas checagens porque elas nunca rodam nele.

## Infra

- Segredos (JWT secret, credenciais de banco, chaves do gateway, chaves
  R2) via variáveis de ambiente (`bot/.env`, nunca commitado) —
  `bot/.env.example` documenta todas as chaves esperadas com placeholder
  vazio.
- `infra/` (IaC/deploy) ainda não existe neste repo — gap conhecido, sem
  provisionamento automatizado documentado.

## Checklist mínimo antes de deploy

- [ ] Rotação de secrets configurada (`JWT_SECRET_KEY`, `INTERNAL_API_SECRET`, credenciais Mercado Pago, credenciais R2)
- [ ] Rate limiting ativo nos endpoints de autenticação, download e webhook
- [ ] Logs de auditoria persistidos e não editáveis (`audit_log_entries`, `audit_log_launcher`)
- [ ] HTTPS obrigatório em produção (`PUBLIC_BASE_URL` com `https://`, já validado em `Settings.load()`)
- [ ] `WEBHOOK_ENABLED=true` só com `MERCADOPAGO_WEBHOOK_SECRET_*` configurado
- [ ] `alembic upgrade head` executado e único head confirmado antes do deploy
