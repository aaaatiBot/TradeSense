# TradeSense Production Deployment & Operations Runbook
**Document Version:** 3.1.0  
**Specification:** TradeSense SRS v3.1 §11, §16, §18  

---

## 1. System Requirements

- **Operating System:** Ubuntu 22.04 LTS / 24.04 LTS or Linux kernel ≥ 5.15
- **Python Runtime:** Python 3.11.x (with `python3.11-venv`, `python3.11-dev`)
- **Database Engine:** PostgreSQL 15+ (Production) or SQLite 3.38+ (Staging/Dev)
- **Web Server:** Nginx 1.22+
- **Process Manager:** systemd
- **Blockchain Connectivity:** Ethereum / Polygon Amoy RPC endpoint (HTTPS / WSS)

---

## 2. Environment Configuration Reference (SRS §11.1)

Create `/opt/tradesense/.env` with strict permissions (`chmod 600 /opt/tradesense/.env`):

```bash
# Flask Configuration
FLASK_APP=app:create_app()
FLASK_ENV=production
SECRET_KEY=b29a8f4c2e1b7d5a3e8f6c4b2a0d9e7f5a3c1b8d6e4f2a0c8b6d4e2f0a8c6b4d # Must be >= 32 hex chars

# Database
DATABASE_URL=postgresql://tradesense_user:secure_password@127.0.0.1:5432/tradesense_db

# Market Data & AI
MARKET_DATA_PROVIDER=mock
GEMINI_API_KEY=AIzaSyD-mock-production-key-for-tradesense

# Blockchain & EVM Web3
WEB3_RPC_URL=https://rpc-amoy.polygon.technology
CONTRACT_ADDRESS=0x1111111111111111111111111111111111111111
OPERATOR_PRIVATE_KEY=0x4f3edf983ac636a65a842ce7c78d9aa706d3b113bce9c46f30d7d21715b23b1d
CHAIN_ID=80002

# Background Worker & Polling
WORKER_POLL_INTERVAL_SECONDS=5
WORKER_BATCH_SIZE=20
WORKER_MAX_RETRIES=5
WORKER_LEASE_SECONDS=60

# Telemetry
LOG_LEVEL=INFO
```

---

## 3. Database Migration & Initialization

```bash
cd /opt/tradesense
source .venv/bin/activate

# Execute forward migrations to head
alembic upgrade head

# Seed statutory disclaimers & initial rate cards
python -c "from app import create_app; from app.services.disclaimer_service import DisclaimerService; app = create_app(); app.app_context().push(); DisclaimerService.seed_disclaimers()"
```

---

## 4. Gunicorn Application Service Configuration

Create `/etc/systemd/system/tradesense-web.service`:

```ini
[Unit]
Description=TradeSense Gunicorn Application Server
After=network.target postgresql.service

[Service]
Type=notify
User=tradesense
Group=tradesense
WorkingDirectory=/opt/tradesense
EnvironmentFile=/opt/tradesense/.env
ExecStart=/opt/tradesense/.venv/bin/gunicorn \
    --workers 4 \
    --worker-class gthread \
    --threads 2 \
    --bind 127.0.0.1:8000 \
    --access-logfile /var/log/tradesense/access.log \
    --error-logfile /var/log/tradesense/error.log \
    --capture-output \
    "app:create_app('production')"
ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
TimeoutStopSec=30
PrivateTmp=true
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## 5. Blockchain Background Worker Service

Create `/etc/systemd/system/tradesense-worker.service`:

```ini
[Unit]
Description=TradeSense Durable Blockchain Job Worker
After=network.target postgresql.service tradesense-web.service

[Service]
Type=simple
User=tradesense
Group=tradesense
WorkingDirectory=/opt/tradesense
EnvironmentFile=/opt/tradesense/.env
ExecStart=/opt/tradesense/.venv/bin/python -c "from app import create_app; from app.workers.blockchain_worker import BlockchainWorker; app = create_app('production'); app.app_context().push(); worker = BlockchainWorker(); worker.run_forever()"
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

---

## 6. Nginx Reverse Proxy Configuration

Create `/etc/nginx/sites-available/tradesense.conf`:

```nginx
server {
    listen 80;
    server_name tradesense.local;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name tradesense.local;

    ssl_certificate /etc/ssl/certs/tradesense.crt;
    ssl_certificate_key /etc/ssl/private/tradesense.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Security Headers per SRS §5.2
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Static Assets Cache
    location /static/ {
        alias /opt/tradesense/app/static/;
        expires 7d;
        add_header Cache-Control "public, no-transform";
    }

    # Application Proxy
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Request-ID $request_id;
        proxy_read_timeout 60s;
    }
}
```

---

## 7. Data Retention & Maintenance Cron (SRS §7.18)

Configure daily sweep cron (`crontab -e -u tradesense`):

```bash
# Run automated retention sweep daily at 02:00 AM UTC per SRS §7.18
0 2 * * * /opt/tradesense/.venv/bin/python -c "from app import create_app; from app.services.retention_service import RetentionService; app = create_app('production'); app.app_context().push(); RetentionService.run_retention_sweep()" >> /var/log/tradesense/retention.log 2>&1
```

---

## 8. Backup and Disaster Recovery Procedures

### Automated Database Backup (PostgreSQL)
```bash
# Dump consistent database snapshot with schema and table data
pg_dump -U tradesense_user -h 127.0.0.1 -Fc tradesense_db > /backups/tradesense_$(date +%Y%m%d_%H%M%S).dump

# Verify backup integrity
pg_restore --list /backups/tradesense_*.dump > /dev/null && echo "Backup verified"
```

### Database Restore Procedure
```bash
# Terminate existing connections to database
psql -U postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'tradesense_db';"

# Drop and recreate database
psql -U postgres -c "DROP DATABASE tradesense_db;"
psql -U postgres -c "CREATE DATABASE tradesense_db OWNER tradesense_user;"

# Restore snapshot
pg_restore -U tradesense_user -d tradesense_db -v /backups/tradesense_TARGET.dump
```

### SQLite Backup Procedure (Staging/Dev)
```bash
# SQLite online atomic backup
sqlite3 tradesense.db ".backup 'tradesense_backup_$(date +%Y%m%d_%H%M%S).db'"
```
