import psycopg2
from psycopg2 import pool, sql
from psycopg2.extras import RealDictCursor, Json
import json
from datetime import datetime
from typing import List, Dict, Optional
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, database_url=None, host=None, port=None, database=None, user=None, password=None):
        """
        Initialize DatabaseManager with PostgreSQL connection pool
        
        Args:
            database_url: Full PostgreSQL connection URL (postgresql://user:pass@host:port/db)
            OR individual parameters:
            host, port, database, user, password
        """
        try:
            if database_url:
                # Parse connection URL
                self.conn_params = database_url
                self.pool = psycopg2.pool.SimpleConnectionPool(
                    1, 20,
                    database_url
                )
            else:
                # Use individual parameters
                self.conn_params = {
                    'host': host,
                    'port': port or 5432,
                    'database': database,
                    'user': user,
                    'password': password
                }
                self.pool = psycopg2.pool.SimpleConnectionPool(
                    1, 20,
                    **self.conn_params
                )
            
            self.init_database()
            logger.info("PostgreSQL connection pool initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL connection pool: {e}", exc_info=True)
            raise

    @contextmanager
    def get_connection(self):
        """Context manager for getting and releasing connections from pool"""
        conn = None
        try:
            conn = self.pool.getconn()
            yield conn
            conn.commit()
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Database error: {e}", exc_info=True)
            raise
        finally:
            if conn:
                self.pool.putconn(conn)

    def init_database(self):
        """Initialize database schema"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Users table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    user_id TEXT UNIQUE NOT NULL,
                    username TEXT NOT NULL,
                    is_banned BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # API Keys table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS api_keys (
                    id SERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    api_key TEXT NOT NULL,
                    api_secret TEXT NOT NULL,
                    api_passphrase TEXT,
                    private_key TEXT,
                    testnet BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                )
            ''')
            
            # Channels table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS channels (
                    id SERIAL PRIMARY KEY,
                    channel_id TEXT UNIQUE NOT NULL,
                    channel_name TEXT NOT NULL,
                    is_signal_channel BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Channel subscriptions
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS channel_subscriptions (
                    id SERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    position_size REAL DEFAULT 1.0,
                    max_risk REAL DEFAULT 2.0,
                    position_mode TEXT DEFAULT 'percentage',
                    fixed_amount REAL DEFAULT 100.0,
                    percentage_of_balance REAL DEFAULT 10.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
                    FOREIGN KEY (channel_id) REFERENCES channels (channel_id) ON DELETE CASCADE
                )
            ''')
            
            # Trades table with JSONB for TP/SL arrays
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    id SERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    size REAL NOT NULL,
                    position_size REAL DEFAULT 0,
                    price REAL,
                    entry_price REAL,
                    exit_price REAL DEFAULT 0,
                    stop_loss JSONB,
                    take_profit JSONB,
                    pnl REAL DEFAULT 0,
                    channel_id TEXT,
                    message_id TEXT,
                    status TEXT DEFAULT 'active',
                    signal_data TEXT,
                    leverage INTEGER DEFAULT 1,
                    risk_reward_ratio REAL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    closed_at TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                )
            ''')
            
            # Create indexes for better performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_api_keys_exchange ON api_keys(user_id, exchange)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_channels_channel_id ON channels(channel_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON channel_subscriptions(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_subscriptions_channel ON channel_subscriptions(channel_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_user_id ON trades(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_channel ON trades(channel_id)')
            
            conn.commit()
            logger.info("PostgreSQL database schema initialized successfully")

    def add_user(self, user_id: str, username: str):
        """Add a new user"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO NOTHING',
                (user_id, username)
            )
            logger.info(f"User {username} ({user_id}) added to database")

    def ban_user(self, user_id: str) -> bool:
        """Ban a user from using the bot"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE users SET is_banned = TRUE WHERE user_id = %s', (user_id,))
                success = cursor.rowcount > 0
                if success:
                    logger.info(f"User {user_id} has been banned")
                return success
        except Exception as e:
            logger.error(f"Error banning user: {e}")
            return False

    def unban_user(self, user_id: str) -> bool:
        """Unban a user"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE users SET is_banned = FALSE WHERE user_id = %s', (user_id,))
                success = cursor.rowcount > 0
                if success:
                    logger.info(f"User {user_id} has been unbanned")
                return success
        except Exception as e:
            logger.error(f"Error unbanning user: {e}")
            return False

    def is_user_banned(self, user_id: str) -> bool:
        """Check if a user is banned"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT is_banned FROM users WHERE user_id = %s', (user_id,))
                result = cursor.fetchone()
                return bool(result and result[0]) if result else False
        except Exception as e:
            logger.error(f"Error checking ban status: {e}")
            return False

    def add_api_key(self, user_id: str, exchange: str, api_key: str, api_secret: str,
                    api_passphrase: str = None, testnet: bool = False, private_key: str = None):
        """Add or update API key for a user"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Delete existing API keys for this user
                cursor.execute('DELETE FROM api_keys WHERE user_id = %s', (user_id,))
                
                # Check if this API key or wallet is already used by another user
                if exchange.lower() == 'hyperliquid' and api_passphrase:
                    cursor.execute('''
                        SELECT user_id FROM api_keys
                        WHERE exchange = %s AND (api_passphrase = %s OR api_key = %s) AND user_id != %s
                    ''', (exchange, api_passphrase, api_passphrase, user_id))
                elif exchange.lower() == 'hyperliquid' and api_key:
                    cursor.execute('''
                        SELECT user_id FROM api_keys
                        WHERE exchange = %s AND (api_key = %s OR api_passphrase = %s) AND user_id != %s
                    ''', (exchange, api_key, api_key, user_id))
                else:
                    cursor.execute('''
                        SELECT user_id FROM api_keys
                        WHERE exchange = %s AND api_key = %s AND user_id != %s
                    ''', (exchange, api_key, user_id))
                
                existing_user = cursor.fetchone()
                if existing_user:
                    logger.warning(f"API key/wallet already in use by another user on {exchange}")
                    return False
                
                # Insert new API key
                cursor.execute('''
                    INSERT INTO api_keys
                    (user_id, exchange, api_key, api_secret, api_passphrase, private_key, testnet)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                ''', (user_id, exchange, api_key, api_secret, api_passphrase, private_key, testnet))
                
                logger.info(f"API key added for user {user_id} on {exchange}")
                return True
        except Exception as e:
            logger.error(f"Error adding API key: {e}")
            return False

    def get_user_api_key(self, user_id: str, exchange: str) -> Optional[Dict]:
        """Get API key for a specific exchange"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute('''
                    SELECT api_key, api_secret, api_passphrase, testnet, private_key
                    FROM api_keys
                    WHERE user_id = %s AND exchange = %s
                ''', (user_id, exchange))
                result = cursor.fetchone()
                
                if result:
                    data = dict(result)
                    if not data['private_key']:
                        data['private_key'] = data['api_secret']
                    if exchange.lower() == 'hyperliquid':
                        data['wallet_address'] = result['api_passphrase']
                    return data
                return None
        except Exception as e:
            logger.error(f"Error getting API keys for user {user_id}: {e}")
            return None

    def get_api_keys(self, user_id: str) -> Optional[Dict]:
        """Get the most recent API keys for a user"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute('''
                    SELECT exchange, api_key, api_secret, api_passphrase, testnet, private_key
                    FROM api_keys
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                ''', (user_id,))
                
                result = cursor.fetchone()
                if result:
                    data = dict(result)
                    if not data['private_key']:
                        data['private_key'] = data['api_secret']
                    if data['exchange'].lower() == 'hyperliquid':
                        data['wallet_address'] = result['api_passphrase']
                    return data
                return None
        except Exception as e:
            logger.error(f"Error getting API keys for user {user_id}: {e}")
            return None

    def get_user_all_api_keys(self, user_id: str) -> List[Dict]:
        """Get all API keys for a user"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute('''
                    SELECT exchange, api_key, api_secret, api_passphrase, testnet, private_key, created_at
                    FROM api_keys
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                ''', (user_id,))
                
                rows = cursor.fetchall()
                api_keys = []
                for row in rows:
                    data = dict(row)
                    if not data['private_key']:
                        data['private_key'] = data['api_secret']
                    if data['exchange'].lower() == 'hyperliquid':
                        data['wallet_address'] = data['api_passphrase']
                    api_keys.append(data)
                return api_keys
        except Exception as e:
            logger.error(f"Error getting all API keys: {e}")
            return []

    def delete_api_key(self, user_id: str, exchange: str) -> bool:
        """Delete an API key for a user"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM api_keys WHERE user_id = %s AND exchange = %s',
                             (user_id, exchange))
                deleted = cursor.rowcount > 0
                if deleted:
                    logger.info(f"Deleted API key for user {user_id} on {exchange}")
                return deleted
        except Exception as e:
            logger.error(f"Error deleting API key: {e}")
            return False

    def update_wallet(self, user_id: str, exchange: str, wallet_address: str) -> bool:
        """Update wallet address (stored in api_passphrase)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE api_keys
                    SET api_passphrase = %s
                    WHERE user_id = %s AND exchange = %s
                ''', (wallet_address, user_id, exchange))
                updated = cursor.rowcount > 0
                if not updated:
                    logger.warning(f"Wallet update failed: No api_key row for user={user_id} exchange={exchange}")
                    return False
                logger.info(f"Wallet updated for user {user_id} on {exchange}")
                return True
        except Exception as e:
            logger.error(f"Error updating wallet: {e}")
            return False

    def update_exchange_network(self, user_id: str, exchange: str, testnet: bool) -> bool:
        """Update testnet flag for an API key"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE api_keys SET testnet = %s WHERE user_id = %s AND exchange = %s
                ''', (testnet, user_id, exchange))
                updated = cursor.rowcount > 0
                if not updated:
                    logger.warning(f"Network update failed: no api key row for user={user_id} exchange={exchange}")
                    return False
                logger.info(f"Network flag updated for user {user_id} {exchange} -> testnet={testnet}")
                return True
        except Exception as e:
            logger.error(f"Error updating network flag: {e}")
            return False

    def add_channel(self, channel_id: str, channel_name: str):
        """Add a signal channel"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO channels (channel_id, channel_name) VALUES (%s, %s) ON CONFLICT (channel_id) DO NOTHING',
                (channel_id, channel_name)
            )
            logger.info(f"Channel {channel_name} ({channel_id}) added as signal channel")

    def subscribe_to_channel(self, user_id: str, channel_id: str, exchange: str,
                           position_size: float = 1.0, max_risk: float = 2.0,
                           position_mode: str = 'percentage', fixed_amount: float = 100.0,
                           percentage_of_balance: float = 10.0):
        """Subscribe user to a channel"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO channel_subscriptions
                (user_id, channel_id, exchange, position_size, max_risk,
                 position_mode, fixed_amount, percentage_of_balance)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT ON CONSTRAINT channel_subscriptions_pkey
                DO UPDATE SET
                    position_size = EXCLUDED.position_size,
                    max_risk = EXCLUDED.max_risk,
                    position_mode = EXCLUDED.position_mode,
                    fixed_amount = EXCLUDED.fixed_amount,
                    percentage_of_balance = EXCLUDED.percentage_of_balance
            ''', (user_id, channel_id, exchange, position_size, max_risk,
                  position_mode, fixed_amount, percentage_of_balance))
            logger.info(f"User {user_id} subscribed to channel {channel_id} on {exchange}")

    def get_subscription(self, user_id: str, channel_id: str) -> Optional[Dict]:
        """Get a user's subscription for a specific channel"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute('''
                    SELECT user_id, channel_id, exchange, position_size, max_risk,
                           position_mode, fixed_amount, percentage_of_balance, created_at
                    FROM channel_subscriptions
                    WHERE user_id = %s AND channel_id = %s
                ''', (user_id, channel_id))
                result = cursor.fetchone()
                return dict(result) if result else None
        except Exception as e:
            logger.error(f"Error getting subscription: {e}")
            return None

    def is_signal_channel(self, channel_id: str) -> bool:
        """Check if a channel is a signal channel"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT is_signal_channel FROM channels WHERE channel_id = %s', (str(channel_id),))
                result = cursor.fetchone()
                return bool(result[0]) if result else False
        except Exception as e:
            logger.error(f"Error checking signal channel: {e}")
            return False

    def get_channel_users(self, channel_id: str) -> List[Dict]:
        """Get all users subscribed to a channel"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute('''
                    SELECT cs.user_id, cs.exchange, cs.position_size, cs.max_risk,
                           ak.api_key, ak.api_secret, ak.api_passphrase, ak.testnet, ak.private_key,
                           cs.position_mode, cs.fixed_amount, cs.percentage_of_balance
                    FROM channel_subscriptions cs
                    JOIN api_keys ak ON cs.user_id = ak.user_id AND cs.exchange = ak.exchange
                    WHERE cs.channel_id = %s
                ''', (str(channel_id),))
                
                results = cursor.fetchall()
                users = []
                for row in results:
                    user_data = dict(row)
                    if not user_data.get('private_key'):
                        user_data['private_key'] = user_data['api_secret']
                    users.append(user_data)
                return users
        except Exception as e:
            logger.error(f"Error getting channel users: {e}")
            return []

    def log_trade(self, user_id: str, exchange: str, symbol: str, side: str,
                  size: float, price: float = None, signal_data: str = None,
                  channel_id: str = None, message_id: str = None):
        """Log a new trade"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO trades (user_id, exchange, symbol, side, size, price, signal_data, channel_id, message_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            ''', (user_id, exchange, symbol, side, size, price, signal_data, channel_id, message_id))
            inserted_id = cursor.fetchone()[0]
            logger.info(f"Trade logged: {user_id} {side} {size} {symbol} on {exchange} (ID: {inserted_id})")
            return inserted_id

    def get_user_trades(self, user_id: str, limit: int = 10) -> List[Dict]:
        """Get recent trades for a user"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute('''
                    SELECT exchange, symbol, side, size, price, status, created_at
                    FROM trades
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                ''', (user_id, limit))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting user trades: {e}")
            return []

    def get_user_subscriptions(self, user_id: str) -> List[Dict]:
        """Get all channel subscriptions for a user"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute('''
                    SELECT cs.id, cs.user_id, cs.channel_id, cs.exchange,
                           cs.position_size, cs.max_risk, cs.created_at, c.channel_name,
                           cs.position_mode, cs.fixed_amount, cs.percentage_of_balance
                    FROM channel_subscriptions cs
                    LEFT JOIN channels c ON cs.channel_id = c.channel_id
                    WHERE cs.user_id = %s
                    ORDER BY cs.created_at DESC
                ''', (user_id,))
                
                subscriptions = []
                for row in cursor.fetchall():
                    sub = dict(row)
                    if not sub.get('channel_name'):
                        sub['channel_name'] = f"Channel-{sub['channel_id']}"
                    subscriptions.append(sub)
                return subscriptions
        except Exception as e:
            logger.error(f"Error getting user subscriptions: {e}")
            return []

    def remove_channel_subscription(self, user_id: str, channel_id: str):
        """Remove a channel subscription"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM channel_subscriptions
                WHERE user_id = %s AND channel_id = %s
            ''', (user_id, channel_id))
            logger.info(f"User {user_id} unsubscribed from channel {channel_id}")

    def update_subscription(self, subscription_id: int, position_mode: str = None,
                           position_size: float = None, max_risk: float = None) -> bool:
        """Update subscription settings"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                updates = []
                params = []
                
                if position_mode is not None:
                    updates.append("position_mode = %s")
                    params.append(position_mode)
                
                if position_size is not None:
                    # Get current mode if not provided
                    if position_mode is None:
                        cursor.execute("SELECT position_mode FROM channel_subscriptions WHERE id = %s", (subscription_id,))
                        result = cursor.fetchone()
                        current_mode = result[0] if result else 'percentage'
                    else:
                        current_mode = position_mode
                    
                    updates.append("position_size = %s")
                    params.append(position_size)
                    
                    if current_mode == 'fixed':
                        updates.append("fixed_amount = %s")
                        params.append(position_size)
                    else:
                        updates.append("percentage_of_balance = %s")
                        params.append(position_size)
                
                if max_risk is not None:
                    updates.append("max_risk = %s")
                    params.append(max_risk)
                
                if not updates:
                    return False
                
                params.append(subscription_id)
                query = f"UPDATE channel_subscriptions SET {', '.join(updates)} WHERE id = %s"
                
                cursor.execute(query, params)
                success = cursor.rowcount > 0
                if success:
                    logger.info(f"Updated subscription {subscription_id}")
                return success
        except Exception as e:
            logger.error(f"Error updating subscription: {e}")
            return False

    # Admin Panel Methods
    def get_all_users_count(self) -> int:
        """Get total number of users"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM users')
                return cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"Error getting users count: {e}")
            return 0

    def get_total_subscriptions_count(self) -> int:
        """Get total number of subscriptions"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM channel_subscriptions')
                return cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"Error getting subscriptions count: {e}")
            return 0

    def get_all_channels_count(self) -> int:
        """Get total number of channels"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM channels')
                return cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"Error getting channels count: {e}")
            return 0

    def get_recent_trades_count(self, days: int = 7) -> int:
        """Get number of trades in the last N days"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT COUNT(*) FROM trades
                    WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '%s days'
                ''', (days,))
                return cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"Error getting recent trades count: {e}")
            return 0

    def get_total_trades_count(self) -> int:
        """Get total count of all trades"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM trades')
                return cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"Error getting total trades count: {e}")
            return 0

    def get_active_trades_count(self) -> int:
        """Get count of active trades"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM trades WHERE status = 'active'")
                return cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"Error getting active trades count: {e}")
            return 0

    def get_all_users_with_details(self) -> List[Dict]:
        """Get all users with their details"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute('''
                    SELECT u.user_id, u.username, u.created_at, u.is_banned,
                           COUNT(DISTINCT cs.id) as subscriptions,
                           COUNT(DISTINCT ak.id) as api_keys
                    FROM users u
                    LEFT JOIN channel_subscriptions cs ON u.user_id = cs.user_id
                    LEFT JOIN api_keys ak ON u.user_id = ak.user_id
                    GROUP BY u.user_id, u.username, u.created_at, u.is_banned
                    ORDER BY u.created_at DESC
                ''')
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting users with details: {e}")
            return []

    def get_all_subscriptions_with_details(self) -> List[Dict]:
        """Get all subscriptions with details"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute('''
                    SELECT cs.id, u.username, c.channel_name, cs.exchange,
                           cs.position_size, cs.max_risk, cs.position_mode,
                           cs.fixed_amount, cs.percentage_of_balance, cs.created_at
                    FROM channel_subscriptions cs
                    JOIN users u ON cs.user_id = u.user_id
                    JOIN channels c ON cs.channel_id = c.channel_id
                    ORDER BY cs.created_at DESC
                ''')
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting subscriptions with details: {e}")
            return []

    def get_all_channels(self) -> List[Dict]:
        """Get all channels"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute('''
                    SELECT c.channel_id, c.channel_name, c.is_signal_channel,
                           COUNT(cs.id) as subscribers, c.created_at
                    FROM channels c
                    LEFT JOIN channel_subscriptions cs ON c.channel_id = cs.channel_id
                    GROUP BY c.channel_id, c.channel_name, c.is_signal_channel, c.created_at
                    ORDER BY subscribers DESC
                ''')
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting all channels: {e}")
            return []

    def get_recent_trades(self, limit: int = 50) -> List[Dict]:
        """Get recent trades"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute('''
                    SELECT t.id, u.username, t.symbol, t.side, t.entry_price,
                           t.size, t.status, t.exchange, t.created_at, t.price,
                           t.stop_loss, t.take_profit, t.channel_id
                    FROM trades t
                    JOIN users u ON t.user_id = u.user_id
                    ORDER BY t.created_at DESC
                    LIMIT %s
                ''', (limit,))
                
                trades = []
                for row in cursor.fetchall():
                    trade = dict(row)
                    # Map 'size' to 'quantity' for UI compatibility
                    trade['quantity'] = trade['size']
                    trade['side'] = trade['side'].upper()
                    trade['pnl'] = 0.0  # Placeholder
                    trades.append(trade)
                return trades
        except Exception as e:
            logger.error(f"Error getting recent trades: {e}")
            return []

    def get_active_trades_detailed(self) -> List[Dict]:
        """Get detailed list of all active trades"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute('''
                    SELECT t.id, t.user_id, u.username, t.symbol, t.side,
                           t.entry_price, t.price, t.position_size, t.leverage,
                           t.take_profit, t.stop_loss, t.exchange, t.created_at
                    FROM trades t
                    JOIN users u ON t.user_id = u.user_id
                    WHERE t.status = 'active'
                    ORDER BY t.created_at DESC
                ''')
                
                trades = []
                for row in cursor.fetchall():
                    trade = dict(row)
                    
                    # Handle JSONB TP/SL (extract first value if array)
                    take_profit = trade.get('take_profit')
                    stop_loss = trade.get('stop_loss')
                    
                    if isinstance(take_profit, list) and take_profit:
                        trade['take_profit'] = float(take_profit[0])
                    elif isinstance(take_profit, str):
                        try:
                            tp_list = json.loads(take_profit)
                            trade['take_profit'] = float(tp_list[0]) if tp_list else None
                        except:
                            trade['take_profit'] = None
                    
                    if isinstance(stop_loss, list) and stop_loss:
                        trade['stop_loss'] = float(stop_loss[0])
                    elif isinstance(stop_loss, str):
                        try:
                            sl_list = json.loads(stop_loss)
                            trade['stop_loss'] = float(sl_list[0]) if sl_list else None
                        except:
                            trade['stop_loss'] = None
                    
                    # Use entry_price if available, otherwise use price
                    if not trade.get('entry_price'):
                        trade['entry_price'] = trade.get('price')
                    
                    if not trade.get('leverage'):
                        trade['leverage'] = 1
                    
                    trades.append(trade)
                
                return trades
        except Exception as e:
            logger.error(f"Error getting active trades detailed: {e}")
            return []

    def get_channel_subscribers(self, channel_id: str) -> List[Dict]:
        """Get all subscribers for a specific channel"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute('''
                    SELECT u.user_id, u.username, cs.exchange, cs.created_at
                    FROM channel_subscriptions cs
                    JOIN users u ON cs.user_id = u.user_id
                    WHERE cs.channel_id = %s
                    ORDER BY cs.created_at DESC
                ''', (channel_id,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting channel subscribers: {e}")
            return []

    def update_channel(self, channel_id: str, channel_name: str, is_signal_channel: bool) -> bool:
        """Update channel information"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE channels
                    SET channel_name = %s, is_signal_channel = %s
                    WHERE channel_id = %s
                ''', (channel_name, is_signal_channel, channel_id))
                updated = cursor.rowcount > 0
                if updated:
                    logger.info(f"Updated channel {channel_id}")
                return updated
        except Exception as e:
            logger.error(f"Error updating channel: {e}")
            return False

    def delete_channel(self, channel_id: str) -> bool:
        """Delete a channel and all its subscriptions"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # Subscriptions will cascade delete due to FOREIGN KEY constraint
                cursor.execute('DELETE FROM channels WHERE channel_id = %s', (channel_id,))
                deleted = cursor.rowcount > 0
                if deleted:
                    logger.info(f"Deleted channel {channel_id}")
                return deleted
        except Exception as e:
            logger.error(f"Error deleting channel: {e}")
            return False

    def close(self):
        """Close the connection pool"""
        if hasattr(self, 'pool') and self.pool:
            self.pool.closeall()
            logger.info("PostgreSQL connection pool closed")
