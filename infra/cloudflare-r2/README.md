# Cloudflare R2 — configuração

O Backend já implementa o fluxo completo (`backend/providers/storage/s3_compatible.py`,
`backend/services/download_service.py`, `backend/api/routes/download_routes.py` e
`launcher_routes.py`). Esta página documenta só a configuração de infraestrutura
que fica fora do repositório (conta Cloudflare) — nenhum código muda aqui.

## Fluxo (já implementado, revalidado nesta auditoria)

```
Launcher --HTTPS--> Backend
                       │
                       ├─ valida License (player tem acesso ao Product?)
                       ├─ gera Signed URL (presigned S3v4, TTL curto)
                       │
Launcher <-------------┘
   │
   └─ baixa direto do R2 usando a Signed URL (Backend não fica no meio dos bytes)
```

Sem License válida → Backend nunca gera a URL → 403/404 antes de qualquer
acesso ao bucket. Credenciais do R2 nunca chegam no Launcher — só o Backend
tem `STORAGE_ACCESS_KEY_ID`/`STORAGE_SECRET_ACCESS_KEY`.

## Passo a passo (conta Cloudflare — fora deste repo)

1. **Criar o bucket**: painel Cloudflare → R2 → Create bucket. Nome sugerido:
   `limerence-dlc-staging` (staging) e `limerence-dlc` (produção) — buckets
   separados, nunca o mesmo bucket pros dois ambientes.
2. **Criar API Token com escopo restrito ao bucket**: R2 → Manage R2 API
   Tokens → Create API Token → permissão "Object Read & Write", restrito ao
   bucket criado no passo 1 (não "Apply to all buckets"). Gera
   `Access Key ID` + `Secret Access Key`.
3. **Endpoint S3-compatível**: `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`
   (Account ID aparece no painel R2, canto superior direito).
4. **Preencher `backend/.env`** (nunca `bot/.env` — Bot não guarda mais
   credencial de storage nenhuma, desde a consolidação desta sessão):
   ```
   STORAGE_PROVIDER=r2
   STORAGE_BUCKET=limerence-dlc-staging
   STORAGE_ENDPOINT_URL=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
   STORAGE_REGION=auto
   STORAGE_ACCESS_KEY_ID=<access_key_do_passo_2>
   STORAGE_SECRET_ACCESS_KEY=<secret_key_do_passo_2>
   STORAGE_DOWNLOAD_TTL_SECONDS=600
   ```
5. **Upload dos arquivos de DLC/jogo base**: fora do escopo desta migração —
   usar `rclone`/`aws s3 cp --endpoint-url ...`/painel R2. O manifest
   (`game_manifest`/`launcher_version`, `backend/database/models/`) precisa
   referenciar as mesmas chaves de objeto que forem enviadas.

## Já validado nesta auditoria (código, não infraestrutura)

- TTL: configurável via `STORAGE_DOWNLOAD_TTL_SECONDS` (default 600s), aplicado
  em `generate_presigned_url(..., ExpiresIn=...)`.
- Permissões: o Backend só pede `get_object` — nunca lista nem deleta bucket
  em nome do player.
- SHA256: verificado client-side no Launcher (`launcher/src-tauri/src/integrity/mod.rs`)
  contra o hash do manifest.
- Manifest/versionamento: `GET /launcher/manifest` compara versão local vs.
  remota antes de decidir baixar.
- Repair: reusa o mesmo fluxo de download quando o hash local não bate.
- Acesso negado sem licença: `DownloadService` consulta `LicenseService`
  antes de chamar o storage provider — sem License ativa, 403 antes de
  qualquer URL ser gerada.

## Explicitamente fora de escopo desta rodada (por instrução)

Downloads paralelos e resume por offset **não foram implementados** — não são
necessários pro primeiro staging (instrução explícita desta consolidação) e o
Launcher já tem retry (3 tentativas) + verificação de integridade, suficiente
pra um MVP de staging.
