# Fluxo Launcher → Ren'Py

Como o Launcher (Tauri/Rust) orquestra sessão, licença, download de DLC,
validação de integridade e inicialização do Ren'Py. Complementa
`bot/docs/LIMERENCE_LAUNCHER_ARCHITECTURE.md` (arquitetura aprovada) e
`bot/docs/LAUNCHER_API_CONTRACT.md` (contrato de API, já implementado em
`bot/api/routes/launcher_routes.py` e `bot/api/routes/download_routes.py`).

## Regra de fronteira (não negociável)

**Ren'Py nunca fala com o backend.** Ele não faz HTTP, não sabe o que é uma
licença, não decide se um DLC está liberado, não recebe token nenhum. Toda a
comunicação com o backend (`bot/api`, embarcado no processo do bot) acontece
em Rust, dentro de `launcher/src-tauri/src/`, **antes** de
`game_launcher::spawn` rodar. A partir do momento em que o processo do Ren'Py
é criado, o único vínculo entre ele e o Launcher é o processo do SO
(stdin/stdout/exit code) — nenhuma variável de ambiente de autenticação, URL
de backend ou token é passada para ele.

```
Launcher (Tauri/Rust)                          Backend (bot/api)         Ren'Py
──────────────────────                          ─────────────────         ──────
1. Verificar licença  ──GET /launcher/manifest──▶ 403 license_required
                                                    ou 200 {version,sha256}
2. Baixar DLC          ──POST /download──────────▶ signed URL (R2/S3/B2)
                        ──GET <signed URL>────────▶ storage (direto, sem bot)
                        ──POST /download/{id}/complete──▶ confirma sha256
3. Validar arquivos     (sha256 local, sem rede)
4. Preparar ambiente    (fs local: mkdir, resolve cwd — sem rede)
5. Iniciar Ren'Py       spawn(executable, cwd) ─────────────────────────▶ processo
                                                                          local, sem
                                                                          rede pro
                                                                          backend
```

## Módulos (`launcher/src-tauri/src/`)

| Módulo | Responsabilidade |
|---|---|
| `api_client.rs` | Único lugar que fala HTTP com o backend. Métodos de auth (já existiam) + `get_manifest`, `list_licenses`, `authorize_download`, `complete_download` (novos, nesta fase). |
| `manifest/` | Estado local de conteúdo instalado (`content_state.json`, cache "o que já está no disco"). Nunca é fonte de verdade de licença — só decide "preciso baixar de novo?" |
| `integrity/` | Cálculo de SHA-256 em streaming (arquivos grandes, sem carregar tudo em RAM) e comparação contra o hash esperado do manifest. |
| `download/` | Orquestra verificar licença → baixar → validar → reportar, com retry/reparo automático (até 3 tentativas) quando o hash local diverge. |
| `environment.rs` | Prepara diretório de trabalho e diretório de conteúdo — 100% local, zero chamada de rede. |
| `game_launcher.rs` | Spawna o processo do Ren'Py com o cwd já resolvido; espera o processo terminar e reporta código de saída ao Launcher (nunca ao backend). |
| `lib.rs` | Comando Tauri `play_game`, que encadeia os 5 passos e emite progresso (`game://status`) pro frontend. |

## Os 5 passos

### 1. Verificar licença

`GET /launcher/manifest?product_id=&entry_type=full` com
`Authorization: Bearer <access_token>`. O backend responde `403
license_required` se o player não tiver `License` ACTIVE para aquele
`product_id` — não existe checagem local de licença que decida isso sozinha;
o Launcher só cacheia (`manifest::LocalContentState`) qual versão *já
confirmada* está instalada, nunca decide "posso jogar" sem essa chamada.

Isso é feito tanto para o Base Game (`product_id` fixo, configurado via
`LIMERENCE_BASE_GAME_PRODUCT_ID`) quanto para cada DLC listada como `active`
em `GET /player/licenses`.

### 2. Baixar DLC

Se a versão local (`manifest::LocalContentState`) diverge da versão do
manifest, ou o arquivo local está corrompido (passo 3), o Launcher chama
`POST /download` — que **reconfirma** a licença no backend (nunca reaproveita
a checagem do passo 1) e devolve uma URL assinada de curta duração
(`expires_at`, tipicamente 10 min) apontando direto para o storage
(Cloudflare R2 / S3 / B2). O Launcher baixa os bytes diretamente dessa URL —
o processo do bot nunca serve o conteúdo.

Download é feito em streaming para um arquivo `.part`, só renomeado para o
nome final ao terminar (um download interrompido nunca deixa um arquivo
"completo" corrompido no lugar).

### 3. Validar arquivos

Depois do download, o Launcher calcula o SHA-256 do arquivo local
(`integrity::sha256_file_async`) e:

- Reporta ao backend via `POST /download/{download_id}/complete`
  (`client_sha256`, `bytes_transferred`) — fecha a trilha de auditoria do
  lado do backend.
- Se o hash não bater, descarta o arquivo e tenta de novo (até 3 tentativas)
  — **repara só o arquivo com problema**, não reinicia o pacote inteiro.

A mesma validação roda **a cada início do Launcher**, antes de liberar
"Jogar" — mesmo sem re-download, o hash em disco é sempre recomputado e
comparado contra o manifest atual. Arquivo corrompido detectado nessa
checagem também aciona reparo automático (novo download), nunca deixa o
jogador abrir uma build quebrada.

### 4. Preparar ambiente

`environment::prepare` — puramente local: garante que o diretório de
conteúdo existe e resolve o diretório de trabalho (`cwd`) a partir da
localização do executável. Nenhuma chamada de rede.

### 5. Iniciar Ren'Py

`game_launcher::spawn` cria o processo com `Command::new(executable).current_dir(cwd)`.
O Launcher aguarda o processo terminar numa task separada (não bloqueia o
resto da UI) e emite o código de saída via evento `game://status` — só para
diagnóstico local no próprio Launcher (log/mensagem ao usuário), nunca
reportado ao backend.

## Contrato de API usado (já implementado, não é suposição)

Fonte: `bot/docs/LAUNCHER_API_CONTRACT.md` (autoritativo) +
`bot/api/routes/launcher_routes.py` / `bot/api/routes/download_routes.py` /
`bot/api/schemas/launcher.py` (implementação real, lida diretamente para
gerar os DTOs Rust em `api_client.rs`).

| Rota | Auth | Uso pelo Launcher |
|---|---|---|
| `GET /launcher/manifest?product_id=&entry_type=` | Bearer + License ACTIVE | Passo 1 (verificar licença) e decidir se precisa baixar |
| `GET /player/licenses` | Bearer | Descobrir quais DLCs o player possui (`status == "active"`) |
| `POST /download` `{product_id, entry_type, device_uuid}` | Bearer + License ACTIVE (reconfirmada) | Passo 2 — obtém URL assinada + version/sha256/size |
| `POST /download/{download_id}/complete` `{client_sha256, bytes_transferred}` | Bearer | Passo 3 — fecha auditoria, backend confirma/rejeita o hash |
| `GET /launcher/version?platform=` | pública | Auto-update do próprio binário do Launcher (fora do escopo desta fase — módulo de auto-update ainda não implementado, ver Pendências) |
| `POST /update` `{platform}` | pública | Idem — URL assinada do instalador do Launcher |

Nenhum desses contratos foi inventado: os schemas Rust em `api_client.rs`
(`ManifestResponse`, `LicenseResponse`, `DownloadResponse`,
`DownloadCompleteResponse`) espelham campo a campo os schemas Pydantic reais
em `bot/api/schemas/launcher.py`.

### Ponto assumido pelo Launcher (não definido pelo backend)

O contrato do backend descreve o **artefato** (`version`, `sha256`,
`size_bytes`, uma URL) mas não define o **formato interno** do pacote (zip?
arquivo `.rpa` do Ren'Py pronto para uso? instalador?). Esta implementação
assume que o artefato baixado é usado diretamente (copiado para o diretório
de conteúdo com o nome `<product_id>-<versão>.<extensão da URL>`), sem
extração — compatível com o padrão de distribuição do Ren'Py de soltar
arquivos `.rpa` na pasta `game/` para carregamento automático. **Se o
pipeline de build real empacotar DLC de forma diferente (zip com múltiplos
arquivos, por exemplo), `download::ensure_installed` precisa de um passo de
extração antes de "instalado" — sinalizado aqui como pendência, não decidido
unilateralmente pelo Launcher.**

## Variáveis de ambiente do Launcher

| Variável | Obrigatória | Efeito |
|---|---|---|
| `LIMERENCE_API_BASE_URL` | não (default `http://127.0.0.1:8000`) | Base URL do backend (`bot/api`) |
| `LIMERENCE_GAME_EXECUTABLE` | sim, para jogar | Caminho do executável do Ren'Py |
| `LIMERENCE_BASE_GAME_PRODUCT_ID` | sim, para jogar | UUID do `Product` Base Game no catálogo do backend |
| `LIMERENCE_CONTENT_DIR` | não (default: pasta `game/` irmã do executável) | Onde o conteúdo baixado (base game + DLC) é instalado |

## O que fica de fora desta fase (pendências)

1. **Janela offline de 30 dias com payload HMAC assinado pelo backend**
   (seção 8 de `LIMERENCE_LAUNCHER_ARCHITECTURE.md`) — o endpoint que emite
   esse payload assinado **não existe** no contrato atual
   (`LAUNCHER_API_CONTRACT.md` não o lista). Por isso o Launcher, hoje,
   **sempre exige uma chamada online bem-sucedida** para liberar "Jogar" —
   não há nenhum caminho de "confiar em cache local" implementado (mais
   estrito que o desenho original, nunca menos seguro). Quando o endpoint de
   payload assinado existir, um módulo `offline_grace` pode ser adicionado
   sem tocar no restante do fluxo.
2. **Auto-update do próprio Launcher** (`GET /launcher/version` / `POST
   /update`) — rotas já existem no backend, mas o Launcher ainda não as
   consome; ver `bot/docs/LAUNCHER_API_CONTRACT.md` seções 4 e 10 para o
   contrato pronto.
3. **Formato real do artefato de DLC** — ver seção "Ponto assumido" acima;
   confirmar com quem definir o pipeline de build/publish de manifest
   (`GameManifestEntry.storage_path`) se é preciso um passo de
   extração/instalação mais elaborado do que "copiar o arquivo baixado".
4. **Download paralelo/múltiplos arquivos por manifest** — o contrato atual
   modela cada `product_id`/`entry_type` como um artefato único; se um
   produto passar a precisar de múltiplos arquivos por manifest, o schema
   `ManifestResponse`/`DownloadResponse` do backend precisa mudar primeiro.

## Testes

`launcher/src-tauri/src/{integrity,manifest,download,environment,game_launcher}`
têm testes unitários/integração (`#[cfg(test)]`, framework padrão do Rust +
`tokio::test`), cobrindo:

- `integrity`: hash de arquivo vazio/com conteúdo conhecido, detecção de
  ausência/divergência de hash.
- `manifest`: persistência do estado local em disco, tolerância a arquivo
  ausente/corrompido, extração de extensão de URL assinada.
- `download` (via `wiremock`, backend e storage simulados): download +
  verificação + persistência de estado end-to-end; pular download quando já
  instalado e íntegro; reparo automático quando o arquivo local está
  corrompido; mapeamento de `license_required` para erro específico; falha
  definitiva após esgotar tentativas de reparo.
- `environment`: erro claro quando o executável não existe; criação do
  diretório de conteúdo e resolução do diretório de trabalho.
- `game_launcher`: spawn falha de forma tratada para executável inexistente;
  código de saída (sucesso e falha) é corretamente propagado.

Rodar com `cargo test` dentro de `launcher/src-tauri/`. **Este ambiente de
execução não tem o toolchain Rust instalado (`cargo`/`rustc` ausentes do
PATH)** — os testes foram escritos e revisados por leitura, mas não puderam
ser executados aqui. Rodar `cargo test` numa máquina com Rust antes de
mergear é o próximo passo obrigatório.
