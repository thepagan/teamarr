# Teamarr

Dynamic EPG Generator for Sports Channels

## Quick Start

SQLite:

```yaml
services:
  teamarr:
    image: ghcr.io/pharaoh-labs/teamarr:latest
    container_name: teamarr
    restart: unless-stopped
    ports:
      - 9195:9195
    volumes:
      - ./data:/app/data
    environment:
      - TZ=America/Detroit
```

```bash
docker compose up -d
```

PostgreSQL:

```yaml
services:
  postgres:
    image: postgres:16
    restart: unless-stopped
    environment:
      POSTGRES_DB: teamarr
      POSTGRES_USER: teamarr
      POSTGRES_PASSWORD: teamarr

  teamarr:
    image: ghcr.io/pharaoh-labs/teamarr:latest
    depends_on:
      - postgres
    ports:
      - 9195:9195
    environment:
      - TZ=America/Detroit
      - DATABASE_URL=postgresql://teamarr:teamarr@postgres:5432/teamarr
```

SQLite remains the default backend. Teamarr only uses PostgreSQL when `DATABASE_URL` is set to a `postgres://` or `postgresql://` DSN.

Backups remain backend-native:
- SQLite instances create and restore `.db` backups
- PostgreSQL instances create and restore `.sql` dumps

## Upgrading from Legacy (1.x)

**There is no automatic migration path from legacy 1.x releases** due to significant architectural changes.

If you're upgrading from 1.x, you have two options:

1. **Start Fresh** - Archive your old database and begin with a clean setup. The app will detect your legacy database and guide you through the process, including downloading a backup of your data.

2. **Continue Using 1.x** - If you're not ready to migrate, use the archived image:
   ```yaml
   image: ghcr.io/pharaoh-labs/teamarr:1.4.9-archive
   ```
   Note: 1.x will continue to function but will not receive future updates.

## Image Tags

| Tag | Description |
|-----|-------------|
| `latest` | Stable release |
| `dev` | Development builds |
| `1.4.9-archive` | Final 1.x release (no longer maintained) |

## Documentation

**Official Docs**: [pharaoh-labs.github.io/teamarr](https://pharaoh-labs.github.io/teamarr/) — User Guide, Technical Reference, Supported Leagues

**Community Guide**: https://teamarr-v2.jesmann.com/

## License

MIT
