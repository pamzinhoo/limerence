# Backup do PostgreSQL — estratégia de staging

Não existe backup automático hoje (confirmado na auditoria: nenhum cron, nenhum
volume de snapshot, nenhum script). Isto documenta o mínimo aceitável pra não
subir staging/produção sem rede de segurança — não é um sistema enterprise,
é `pg_dump` + cron + retenção, como pedido explicitamente.

## O que fazer

1. **Backup diário via `pg_dump`**, rodando como um serviço adicional (ou cron
   no host) que executa dentro da rede `backend_net` do compose:

   ```bash
   docker compose -f infra/docker/docker-compose.yml exec -T postgres \
     pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB" \
     > "backups/bot_limerence_$(date +%Y-%m-%d).dump"
   ```

   `-Fc` (formato custom) permite `pg_restore` seletivo (tabela a tabela) e é
   compactado por padrão — mais barato de guardar que `.sql` puro.

2. **Retenção**: manter os últimos 14 dumps diários + 1 mensal dos últimos 6
   meses. Rotação simples (`find backups/ -name '*.dump' -mtime +14 -delete`
   pros diários, mais um `cron` mensal que copia o dump do dia 1 pra
   `backups/monthly/`).

3. **Onde armazenar**: fora da própria máquina que roda o Postgres — subir
   pro mesmo bucket R2 (prefixo separado, ex. `db-backups/`, nunca no mesmo
   bucket/prefixo das DLCs) via `rclone`/`aws s3 cp --endpoint-url`. Guardar
   backup só no mesmo disco do container/VM não protege contra falha de
   disco/host.

4. **Teste de restore — obrigatório, não opcional**: um backup nunca testado
   é uma suposição, não uma garantia. Mensalmente (mínimo), restaurar o dump
   mais recente num Postgres descartável e rodar `alembic heads` +
   `SELECT count(*) FROM players, licenses, payments_history` (ou
   equivalente) pra confirmar que os dados batem com o esperado:

   ```bash
   docker run --rm -d --name restore-test -e POSTGRES_PASSWORD=test postgres:16-alpine
   docker exec -i restore-test pg_restore -U postgres -d postgres --create < backups/ultimo.dump
   docker rm -f restore-test
   ```

5. **Frequência mínima aceitável pra staging**: diária. Produção real (fora
   do escopo desta rodada) deveria considerar WAL archiving/PITR — não
   implementado aqui por não ser necessário pro primeiro staging.

## Status desta auditoria

Nenhum destes passos foi automatizado nesta sessão (nenhum script de cron
criado) — documentado como processo mínimo aceitável, execução real fica
como checklist manual do operador do servidor (ver relatório final,
item "checklist de configuração manual").
