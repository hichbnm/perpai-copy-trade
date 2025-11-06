# Discord Trading Bot with Hyperliquid Integration

A production-ready Discord bot for automated cryptocurrency trading with signal parsing, position monitoring, and real-time notifications.

## 🚀 Features

- **Signal Parsing**: Automatically parse trading signals from Discord channels
- **Multi-Exchange Support**: Hyperliquid, Bybit (extensible to other exchanges)
- **Position Monitoring**: Real-time position tracking with TP/SL hit notifications
- **Risk Management**: Configurable position sizing and risk limits
- **Admin Panel**: Web-based dashboard for monitoring and management
- **PostgreSQL Database**: Production-grade data persistence with JSONB support
- **Docker Deployment**: Containerized services with persistent volumes
- **Interactive UI**: Clean Discord UI with buttons and dropdowns

## 📋 Prerequisites

- Docker and Docker Compose
- Discord Bot Token ([Create one here](https://discord.com/developers/applications))
- Trading exchange API keys (Hyperliquid, Bybit, etc.)

## 🛠️ Quick Start

### 1. Clone and Configure

```bash
git clone <repository-url>
cd exchange-monitor

# Copy environment template
cp .env.example .env

# Edit .env with your configuration
nano .env
```

### 2. Configure Environment Variables

**Required**:
```bash
DISCORD_TOKEN=your_discord_bot_token_here
POSTGRES_PASSWORD=change_this_secure_password
```

**Optional** (defaults provided):
```bash
POSTGRES_HOST=postgres
POSTGRES_DB=trading_bot
POSTGRES_USER=trader
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin123
```

### 3. Start Services

```bash
# Start all services (bot + admin panel + PostgreSQL)
docker-compose up -d --build

# Check status
docker-compose ps

# View logs
docker-compose logs -f trading-bot
```

### 4. Access Admin Panel

Navigate to http://localhost:8000

Default credentials:
- Username: `admin`
- Password: `admin123` (change in `.env`)

## 📊 Database

### PostgreSQL (Production)

This bot uses PostgreSQL for production deployments:

- **Connection Pooling**: Efficient connection management
- **JSONB Support**: Native storage for TP/SL arrays
- **Concurrent Access**: Bot and admin panel can access simultaneously
- **Data Integrity**: ACID compliance with foreign key constraints
- **Persistent Volume**: `./data/postgres` for data persistence

### Migration from SQLite

If you have an existing SQLite database:

```bash
# Set SQLite path in .env
SQLITE_DB_PATH=data/trading_bot.db

# Run migration
python migrate_to_postgres.py
```

See [POSTGRES_MIGRATION.md](POSTGRES_MIGRATION.md) for detailed migration guide.

## 🎮 Usage

### Setup Trading

1. **Add API Keys**:
   ```
   !setup
   ```
   - Choose your exchange (Hyperliquid/Bybit)
   - Enter API credentials
   - Select network (Mainnet/Testnet)

2. **Subscribe to Signal Channels**:
   ```
   !dashboard
   ```
   - Click "Subscribe to Channel"
   - Configure position size and risk limits
   - Choose position mode (Fixed USD or % of Balance)

### Signal Format

The bot automatically parses signals in this format:

```
🚀 BTC Long
Entry: 50000
TP: 51000, 52000, 53000
SL: 49000
Leverage: 10x
```

### Monitoring

**Discord Notifications**:
- Position opened confirmations
- TP hit alerts
- SL hit alerts
- Position status updates

**Admin Panel**:
- Dashboard with key metrics
- Active trades overview
- User management
- Channel subscriptions
- Trade history

## 📁 Project Structure

```
exchange-monitor/
├── main.py                     # Discord bot entry point
├── config.py                   # Configuration and env vars
├── docker-compose.yml          # Multi-container orchestration
├── Dockerfile                  # Bot container definition
├── requirements.txt            # Python dependencies
├── migrate_to_postgres.py      # Database migration script
│
├── database/
│   ├── db_manager.py          # PostgreSQL database manager
│   └── db_manager_sqlite.py   # SQLite backup (legacy)
│
├── signal_parser/
│   └── parser.py              # Signal parsing logic
│
├── connectors/
│   ├── base_connector.py      # Base exchange connector
│   ├── hyperliquid_connector.py
│   └── bybit_connector.py
│
├── price_monitor/
│   ├── position_monitor.py    # Position monitoring service
│   ├── signal_service.py      # Signal-based trade service
│   └── websocket_feed.py      # Real-time price feeds
│
├── ui/
│   └── clean_ui.py            # Discord UI components
│
├── commands/
│   ├── trading_commands.py    # Trading slash commands
│   └── analytics_commands.py  # Analytics commands
│
├── utils/
│   ├── risk_manager.py        # Risk management utilities
│   ├── trade_analytics.py     # Trade analytics
│   └── partial_fill_handler.py
│
└── admin_panel/
    ├── main.py                # FastAPI admin panel
    ├── templates/             # HTML templates
    └── static/                # CSS, JS assets
```

## 🔧 Configuration Options

### Position Sizing Modes

**Fixed Amount**:
```
Fixed USD per trade (e.g., $100)
```

**Percentage of Balance**:
```
% of account balance (e.g., 10%)
```

### Risk Management

- **Max Risk**: Maximum % of position at risk per trade
- **Stop Loss**: Automatic SL placement based on signal
- **Take Profit**: Multiple TP levels with partial closures
- **Leverage**: Configurable per exchange

### Monitoring Settings

Located in `price_monitor/position_monitor.py`:
- Check interval: 3 seconds (default)
- Position status tracking
- Target hit detection
- Duplicate notification prevention

## 🐛 Debugging

### Enable Debug Logging

```python
# In main.py or config.py
logging.basicConfig(level=logging.DEBUG)
```

### View Logs

```bash
# Bot logs
docker-compose logs -f trading-bot

# Admin panel logs
docker-compose logs -f admin-panel

# PostgreSQL logs
docker-compose logs -f postgres

# All logs
docker-compose logs -f
```

### Notification Debugging

See [NOTIFICATION_DEBUG_GUIDE.md](NOTIFICATION_DEBUG_GUIDE.md) for detailed troubleshooting.

## 🔒 Security

### API Key Storage

- API keys encrypted at rest in PostgreSQL
- Never logged in plaintext
- Access controlled per user

### Admin Panel

- Session-based authentication
- Configurable credentials via environment variables
- HTTPS recommended for production

### Database

- Persistent volume outside container
- Regular backups recommended
- Connection credentials in `.env`

## 📦 Backup & Restore

### Backup PostgreSQL

```bash
docker-compose exec postgres pg_dump -U trader trading_bot > backup.sql
```

### Restore from Backup

```bash
cat backup.sql | docker-compose exec -T postgres psql -U trader trading_bot
```

### Automated Backups

Use the provided PowerShell script:
```powershell
.\backup_database.ps1
```

Schedule in Windows Task Scheduler for regular backups.

## 🚀 Production Deployment

### 1. Secure Configuration

```bash
# Generate secure passwords
openssl rand -base64 32

# Update .env
POSTGRES_PASSWORD=<generated-password>
ADMIN_SECRET_KEY=<generated-secret>
ADMIN_PASSWORD=<secure-password>
```

### 2. Enable HTTPS (Admin Panel)

Use a reverse proxy (Nginx, Traefik) with SSL certificates:

```nginx
server {
    listen 443 ssl;
    server_name admin.yourdomain.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://localhost:8000;
    }
}
```

### 3. Monitoring

Set up monitoring for:
- Bot uptime
- PostgreSQL health
- Disk space (for volume)
- Error rates in logs

### 4. Backups

Configure automated daily backups:
```bash
# Cron job (Linux)
0 2 * * * /path/to/backup_database.ps1

# Task Scheduler (Windows)
# Run daily at 2 AM
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📝 License

[Your License Here]

## 🆘 Support

- **Issues**: GitHub Issues
- **Documentation**: See `docs/` folder
- **Migration Guide**: [POSTGRES_MIGRATION.md](POSTGRES_MIGRATION.md)
- **Notification Debugging**: [NOTIFICATION_DEBUG_GUIDE.md](NOTIFICATION_DEBUG_GUIDE.md)

## 🔄 Version History

### v2.0.0 (Current)
- ✅ Migrated to PostgreSQL for production
- ✅ JSONB support for TP/SL arrays
- ✅ Connection pooling
- ✅ Enhanced notification system with detailed logging
- ✅ Docker Compose orchestration
- ✅ Admin panel improvements

### v1.0.0
- Initial release with SQLite
- Basic signal parsing
- Hyperliquid connector
- Discord UI

## 🛣️ Roadmap

- [ ] Additional exchange connectors (Binance, OKX)
- [ ] Advanced analytics dashboard
- [ ] Telegram notifications
- [ ] Backtesting framework
- [ ] Strategy marketplace
- [ ] Mobile app

## ⚙️ Technical Details

### Database Schema

**Tables**:
- `users`: User accounts and ban status
- `api_keys`: Exchange API credentials
- `channels`: Signal channels
- `channel_subscriptions`: User subscriptions with settings
- `trades`: Trade history with JSONB TP/SL

**Indexes**:
- User ID, channel ID, exchange lookups
- Status filtering for active trades
- Timestamp-based queries

### API Integration

**Hyperliquid**:
- REST API for orders and positions
- WebSocket for real-time price updates
- Support for mainnet and testnet

**Bybit**:
- Unified Trading API v5
- Position management
- Order execution

### Performance

- PostgreSQL connection pooling (1-20 connections)
- Async Discord bot operations
- Efficient position polling (3-second interval)
- Cached channel subscriptions

## 📞 Contact

For questions or support, please open an issue on GitHub.
