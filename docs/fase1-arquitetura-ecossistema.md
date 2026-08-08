# Fase 1 — Arquitetura Geral do Ecossistema Limerence

> Documento de arquitetura apenas. Sem implementação nesta fase.

## 0. Estado real do repositório (pré-requisito desta análise)

Antes de propor arquitetura, mapeamento do repo mostrou:

- `backend/` — só estrutura de pastas (`app/api`, `app/models`, `app/schemas`, `app/services`, `app/core`, `alembic/versions`), **sem nenhum arquivo `.py`**. Nenhum service existe ainda (nem `SubscriptionService`, `PaymentService`, `WebhookService`, `ConfigService`, `AuditLogService`).
- `bot/src/` — pastas `events/`, `commands/`, `sync/`, `audit/` vazias.
- `launcher/` — `src/`, `src-tauri/src/`, `public/` vazios.
- `infra/` — `docker/`, `cloudflare-r2/`, `deploy/` vazios.
- `game/Limerence/` — só assets Ren'Py (imagens, fontes, `.gitignore`, um `glitch_tag.rpy`). Sem lógica de licença/DLC.
- `docs/architecture.md` e `docs/database.md` já descrevem um plano por fases (2,3,5,6,8,10 pro backend; 4,5,6,9,10 pro launcher; 7+10 pro bot) e um modelo de dados inicial (`User`, `License`, `Product`, `Download`, `Payment`).

Conclusão: projeto é greenfield. Esta arquitetura assume construção do zero, seguindo o modelo já esboçado em `docs/architecture.md` e `docs/database.md`, sem reutilizar services que ainda não existem.

**Pagamentos/monetização ficam fora de escopo desta fase** — a definir depois. Aqui `License`/`Product` existem no modelo mas o fluxo de aquisição (compra, webhook, assinatura) é tratado como caixa-preta futura.

## 1. Visão geral

```
Discord
   │  (identidade OAuth)
   ▼
Backend FastAPI  ──── PostgreSQL (fonte única da verdade)
   │        ▲
   │        │ sync de benefícios/roles
   │        │
   │   Bot Discord
   │
   ▼
Launcher Limerence (Tauri)
   │  login, update, download DLCs
   ▼
Jogo Ren'Py (apenas executa)
```

## 2. Responsabilidades por módulo

### Backend FastAPI — autoridade central
- Único dono do estado: usuários, licenças, produtos/DLCs, versões, downloads.
- Autenticação: emite JWT a partir de OAuth Discord (Discord só prova identidade, backend decide autorização).
- Expõe API consumida por Launcher e Bot — nenhum dos dois lê o banco diretamente.
- Decide o que cada usuário pode baixar (`License.status`, `Product` liberado).

### PostgreSQL
- Schema já esboçado em `docs/database.md` (`User`, `License`, `Product`, `Download`, `Payment`).
- Toda mutação de estado passa pelo backend — Bot e Launcher nunca escrevem direto no banco.

### Bot Discord — sincronizador, não autoridade
- Não decide quem tem acesso a quê. Consulta backend (via API interna/webhook) e aplica cargos Discord conforme resposta.
- Emite eventos ao backend (ex.: usuário saiu do servidor → backend registra) mas não é dono de regra de negócio.
- Auditoria de ações do bot fica registrada no backend (tabela de audit, a modelar), não em log local.

### Launcher (Tauri) — porta de entrada do jogador
- Login: OAuth Discord → token trocado no backend → JWT armazenado localmente.
- Consulta `GET /products` / `GET /licenses/me` no backend pra saber o que mostrar/baixar.
- Download/update de jogo e DLCs via URLs assinadas (R2), fornecidas pelo backend — launcher nunca fala direto com storage sem passar pelo backend autorizar.
- Aplica update no diretório do jogo Ren'Py local.

### Jogo Ren'Py — só o jogo
- Não conhece backend, não faz chamada de rede de licenciamento.
- Recebe conteúdo (DLCs) já baixado e instalado pelo launcher no filesystem local.
- Qualquer verificação de "DLC ativa" é resolvida por presença de arquivo local, não por chamada de API dentro do Ren'Py.

## 3. Comunicação entre módulos

| De → Para | Protocolo | Autenticação |
|---|---|---|
| Launcher → Backend | HTTPS/REST (JSON) | JWT (Bearer) |
| Bot → Backend | HTTPS/REST interno | API key de serviço (bot é client confiável, não usuário) |
| Backend → Discord | Discord OAuth2 + REST API | Client secret do app Discord |
| Backend → Bot | Webhook/evento (ex.: licença mudou → backend chama endpoint do bot, ou bot faz polling) | assinatura de webhook (HMAC) |
| Launcher → Storage (R2) | HTTPS GET com URL assinada | URL pré-assinada com expiração, emitida pelo backend |

Ren'Py não comunica com nada — fim de linha.

## 4. Fluxo completo (exemplo: jogador ativa DLC)

1. Jogador compra/recebe DLC por algum canal (fora de escopo agora) → registro em `License`/`Product` no backend.
2. Backend detecta mudança de licença → notifica bot (webhook) → bot aplica cargo Discord correspondente.
3. Jogador abre launcher → launcher já tem JWT salvo ou refaz login via Discord OAuth.
4. Launcher chama `GET /licenses/me` → backend responde produtos liberados.
5. Launcher chama `GET /products/{id}/download` → backend valida licença, gera URL assinada R2, devolve.
6. Launcher baixa e extrai DLC na pasta do jogo Ren'Py.
7. Ren'Py, na próxima abertura, detecta arquivos da DLC localmente e libera conteúdo — sem saber que licença existe.

## 5. Vantagens

- Fonte única da verdade evita divergência (ex.: cargo Discord dizendo "tem DLC" mas launcher não deixando baixar).
- Ren'Py fica burro/simples — reduz superfície de pirataria só um pouco (arquivo local sempre é copiável), mas centraliza controle de distribuição no launcher.
- Bot fica substituível/reiniciável sem perder estado — ele é só um sync, backend é quem lembra tudo.
- Facilita auditoria: todo evento de negócio passa pelo backend, um único lugar pra logar.

## 6. Riscos e problemas em aberto

- **DLC piratável localmente**: uma vez baixada pelo launcher, arquivo fica no disco. Backend não protege contra cópia após download — decisão consciente, não bug.
- **Bot como single point of failure de sync**: se bot cair, cargos Discord ficam desatualizados até reconectar. Precisa de reconciliação periódica (job que revalida cargos vs. licenças).
- **Latência OAuth Discord → JWT**: se Discord estiver fora do ar, ninguém loga no launcher. Sem fallback de login definido ainda.
- **Versionamento de DLC/game**: `docs/database.md` tem `Product.version_atual`, mas não define ainda estratégia de delta update vs. full download — impacta tamanho de download e UX do launcher.
- **Pagamentos out of scope agora**: `License`/`Payment` já estão no modelo de dados mas ninguém decidiu ainda gateway, webhook, fluxo de assinatura — vai ser definido depois, conforme combinado.

## 7. Impacto no que já existe

- Nenhum código a alterar — repo está vazio de implementação. Esta fase só formaliza a arquitetura antes de `backend/app/` ganhar arquivos.
- `docs/architecture.md` e `docs/database.md` continuam válidos como base; este documento adiciona a visão de ecossistema completo (Discord + Launcher + Ren'Py) que os outros dois não cobriam explicitamente.
- Próxima fase (implementação) deve seguir a estrutura de pastas já sugerida em `docs/architecture.md`, começando por `backend/app/core` (config, JWT) e `backend/app/models` (schema de `docs/database.md`), sem tocar em pagamentos.

## 8. Próximos passos (após aprovação deste documento)

1. Definir contratos de API (rotas/payloads) pra Launcher e Bot — novo doc ou seção em `docs/database.md`.
2. Implementar `backend/app/core` (config, JWT, OAuth Discord).
3. Implementar `backend/app/models` conforme `docs/database.md`.
4. Implementar endpoints mínimos: auth, products, licenses/me, download (URL assinada).
5. Bot: módulo `sync/` consumindo API do backend.
6. Launcher: login + listagem + download.
7. Pagamentos/monetização: fase separada, a definir depois.
