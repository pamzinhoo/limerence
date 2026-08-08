# Banco de Dados — LIMERENCE

Modelo de dados inicial (SQLAlchemy + Alembic), a refinar durante as Fases 2/3/6/8.

## Entidades principais

### User
- id (PK)
- discord_id (único, para vincular com o bot)
- email
- hashed_password
- created_at

### License
- id (PK)
- user_id (FK -> User)
- product_id (FK -> Product)
- status (active, expired, revoked)
- issued_at
- expires_at (nullable)

### Product
- id (PK)
- name
- slug
- type (game, dlc)
- version_atual
- storage_path (referência ao Cloudflare R2)

### Download
- id (PK)
- user_id (FK -> User)
- product_id (FK -> Product)
- version
- downloaded_at
- ip / device (auditoria)

### Payment
- id (PK)
- user_id (FK -> User)
- product_id (FK -> Product)
- valor
- status (pending, paid, refunded, failed)
- gateway (ex: stripe)
- gateway_reference
- created_at

## Migrations (Alembic)

- Cada mudança de schema deve gerar uma revision em `backend/alembic/versions/`.
- Nunca editar migration já aplicada em produção — criar uma nova.

## Relacionamentos

```
User 1---N License N---1 Product
User 1---N Download N---1 Product
User 1---N Payment  N---1 Product
```

## Índices sugeridos

- `users.discord_id` (único)
- `licenses.user_id, licenses.product_id`
- `payments.gateway_reference`
