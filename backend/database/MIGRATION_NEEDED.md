# Migração necessária (não gerada automaticamente)

Duas mudanças de schema são necessárias pro sistema de DLC funcionar. **Não
gerei o arquivo de migration do Alembic** porque isso exigiria adivinhar o
`down_revision` correto (o topo atual da cadeia de `backend/alembic/versions/`)
sem ter certeza de qual é — gerar um errado corrompe a árvore de migrations
do projeto. Rode você mesmo, é seguro e padrão:

```bash
cd backend
alembic revision --autogenerate -m "dlc authorization anti-replay + product encryption key"
# revise o arquivo gerado, depois:
alembic upgrade head
```

Isso vai detectar automaticamente as duas mudanças abaixo, já que os models
Python já estão corretos:

## 1. Tabela nova: `dlc_authorizations`

Já criada em `backend/database/models/dlc_authorization.py`
(`DlcAuthorization`). Usada pelo anti-replay real (ver
`dlc_authorization_repository.py`, método `consume_atomically`).

## 2. Coluna nova em `products`: `encryption_key_encrypted`

**Ainda não adicionei esta coluna em `backend/database/models/product.py`**
de propósito — é um model existente, em produção, e adicionar uma coluna
nele sem gerar a migration junto quebraria o `SELECT`/`INSERT` no primeiro
deploy (SQLAlchemy tentaria ler/escrever uma coluna que ainda não existe no
banco). Adicione manualmente esta linha em `Product`:

```python
# database/models/product.py, dentro da classe Product
encryption_key_encrypted: Mapped[str | None] = mapped_column(Text)
```

Guarda a chave AES-256 da DLC, já protegida (wrapped) pela `DLC_MASTER_KEY`
— nunca em texto claro (ver `crypto_service.wrap_dlc_key`/`unwrap_dlc_key`).
Populada por `backend/scripts/package_dlc.py` no momento do empacotamento.

Depois de adicionar a linha acima, rode o `alembic revision --autogenerate`
do topo deste arquivo — ele vai pegar as duas mudanças (tabela nova + coluna
nova) numa migration só.
