import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db_path="trading_bot.db"):
        self.db_path = db_path
        self.init_database()
        
    def init_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT UNIQUE NOT NULL,
                username TEXT NOT NULL,
                is_banned INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Add is_banned column if it doesn't exist (for existing databases)
        try:
            cursor.execute('ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0')
            conn.commit()
            logger.info("Added is_banned column to users table")
        except sqlite3.OperationalError:
            # Column already exists
            pass
        
        # API Keys table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                exchange TEXT NOT NULL,
                api_key TEXT NOT NULL,
                api_secret TEXT NOT NULL,
                api_passphrase TEXT,
                private_key TEXT,
                testnet BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')

        # Ensure legacy databases have the latest columns
        try:
            cursor.execute("PRAGMA table_info(api_keys)")
            columns = {row[1] for row in cursor.fetchall()}
            if 'private_key' not in columns:
                cursor.execute('ALTER TABLE api_keys ADD COLUMN private_key TEXT')
                logger.info("Added missing private_key column to api_keys table")
        except sqlite3.OperationalError as e:
            logger.error(f"Failed to verify or add private_key column: {e}")
        
        # Channels table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT UNIQUE NOT NULL,
                channel_name TEXT NOT NULL,
                is_signal_channel BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Channel subscriptions
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS channel_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                exchange TEXT NOT NULL,
                position_size REAL DEFAULT 1.0,
                max_risk REAL DEFAULT 2.0,
                position_mode TEXT DEFAULT 'percentage',
                fixed_amount REAL DEFAULT 100.0,
                percentage_of_balance REAL DEFAULT 10.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id),
                FOREIGN KEY (channel_id) REFERENCES channels (channel_id)
            )
        ''')
        
        # Add new position sizing columns to existing databases
        try:
            cursor.execute('ALTER TABLE channel_subscriptions ADD COLUMN position_mode TEXT DEFAULT "percentage"')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        try:
            cursor.execute('ALTER TABLE channel_subscriptions ADD COLUMN fixed_amount REAL DEFAULT 100.0')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        try:
            cursor.execute('ALTER TABLE channel_subscriptions ADD COLUMN percentage_of_balance REAL DEFAULT 10.0')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        # Trades table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                size REAL NOT NULL,
                position_size REAL DEFAULT 0,
                price REAL,
                entry_price REAL,
                exit_price REAL DEFAULT 0,
                stop_loss TEXT,
                take_profit TEXT,
                pnl REAL DEFAULT 0,
                channel_id TEXT,
                message_id TEXT,
                status TEXT DEFAULT 'active',
                signal_data TEXT,
                leverage INTEGER DEFAULT 1,
                risk_reward_ratio REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Add missing columns if they don't exist (for existing databases)
        try:
            cursor.execute('ALTER TABLE trades ADD COLUMN entry_price REAL')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        try:
            cursor.execute('ALTER TABLE trades ADD COLUMN stop_loss TEXT')
        except sqlite3.OperationalError:
            pass  # Column already exists
            
        try:
            cursor.execute('ALTER TABLE trades ADD COLUMN take_profit TEXT')
        except sqlite3.OperationalError:
            pass  # Column already exists
            
        try:
            cursor.execute('ALTER TABLE trades ADD COLUMN channel_id TEXT')
        except sqlite3.OperationalError:
            pass  # Column already exists
            
        try:
            cursor.execute('ALTER TABLE trades ADD COLUMN message_id TEXT')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        try:
            cursor.execute('ALTER TABLE trades ADD COLUMN targets_hit TEXT')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        # Add analytics columns (migration for existing databases)
        analytics_columns = [
            ('position_size', 'REAL DEFAULT 0'),
            ('exit_price', 'REAL DEFAULT 0'),
            ('pnl', 'REAL DEFAULT 0'),
            ('closed_at', 'TIMESTAMP'),
            ('leverage', 'INTEGER DEFAULT 1'),
            ('risk_reward_ratio', 'REAL DEFAULT 0')
        ]
        
        for col_name, col_type in analytics_columns:
            try:
                cursor.execute(f'ALTER TABLE trades ADD COLUMN {col_name} {col_type}')
                logger.info(f"Added {col_name} column to trades table")
            except sqlite3.OperationalError:
                pass  # Column already exists
        
        # Copy data from 'size' to 'position_size' if needed
        try:
            cursor.execute("""
                UPDATE trades 
                SET position_size = size 
                WHERE (position_size = 0 OR position_size IS NULL) AND size IS NOT NULL
            """)
            if cursor.rowcount > 0:
                logger.info(f"Migrated {cursor.rowcount} trades: copied 'size' to 'position_size'")
        except sqlite3.OperationalError:
            pass
        
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")
    def get_user_all_api_keys(self, user_id: str) -> List[Dict]:
        """Get all API keys for a user"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT exchange, api_key, api_secret, api_passphrase, testnet, private_key, created_at
                FROM api_keys
                WHERE user_id = ?
                ORDER BY created_at DESC
            ''', (user_id,))
            rows = cursor.fetchall()
            api_keys = []
            for row in rows:
                data = {
                    'exchange': row[0],
                    'api_key': row[1],
                    'api_secret': row[2],
                    'api_passphrase': row[3],
                    'testnet': bool(row[4]),
                    'private_key': row[5] if len(row) > 5 else None,
                    'created_at': row[6] if len(row) > 6 else None
                }
                # Fallback for private_key
                if not data['private_key']:
                    data['private_key'] = data['api_secret']
                # For Hyperliquid, api_passphrase stores wallet_address
                if data['exchange'].lower() == 'hyperliquid':
                    data['wallet_address'] = row[3]
                api_keys.append(data)
            return api_keys
        finally:
            conn.close()

    def delete_api_key(self, user_id: str, exchange: str) -> bool:
        """Delete an API key for a user"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM api_keys
                WHERE user_id = ? AND exchange = ?
            ''', (user_id, exchange))
            deleted = cursor.rowcount > 0
            conn.commit()
            conn.close()
            if deleted:
                logger.info(f"Deleted API key for user {user_id} on {exchange}")
            return deleted
        except Exception as e:
            logger.error(f"Error deleting API key: {e}")
            return False
    
    def get_api_keys(self, user_id: str) -> Optional[Dict]:
        """
        Get the API keys for a user (returns the most recent one)
        
        Args:
            user_id: User ID to get API keys for
        
        Returns:
            Dict with API key details or None if not found
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT exchange, api_key, api_secret, api_passphrase, testnet, private_key
                FROM api_keys
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            ''', (user_id,))
            
            row = cursor.fetchone()
            conn.close()
            
            if not row:
                return None
            
            result = {
                'exchange': row[0],
                'api_key': row[1],
                'api_secret': row[2],
                'api_passphrase': row[3],
                'testnet': bool(row[4]),
                'private_key': row[5] if len(row) > 5 else None
            }
            
            # Fallback for private_key
            if not result['private_key']:
                result['private_key'] = result['api_secret']
            
            # For Hyperliquid, api_passphrase stores wallet_address
            if result['exchange'].lower() == 'hyperliquid':
                result['wallet_address'] = row[3]
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting API keys for user {user_id}: {e}")
            return None

    def get_all_users_count(self) -> int:
        """Get total number of users"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT COUNT(*) FROM users')
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def add_user(self, user_id: str, username: str):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)', 
                         (user_id, username))
            conn.commit()
            logger.info(f"User {username} ({user_id}) added to database")
        finally:
            conn.close()
    
    def ban_user(self, user_id: str) -> bool:
        """Ban a user from using the bot"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET is_banned = 1 WHERE user_id = ?', (user_id,))
            conn.commit()
            success = cursor.rowcount > 0
            conn.close()
            if success:
                logger.info(f"User {user_id} has been banned")
            return success
        except Exception as e:
            logger.error(f"Error banning user: {e}")
            return False
    
    def unban_user(self, user_id: str) -> bool:
        """Unban a user"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET is_banned = 0 WHERE user_id = ?', (user_id,))
            conn.commit()
            success = cursor.rowcount > 0
            conn.close()
            if success:
                logger.info(f"User {user_id} has been unbanned")
            return success
        except Exception as e:
            logger.error(f"Error unbanning user: {e}")
            return False
    
    def is_user_banned(self, user_id: str) -> bool:
        """Check if a user is banned"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT is_banned FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            conn.close()
            return bool(result and result[0]) if result else False
        except Exception as e:
            logger.error(f"Error checking ban status: {e}")
            return False
    
    def add_api_key(self, user_id: str, exchange: str, api_key: str, api_secret: str, 
                    api_passphrase: str = None, testnet: bool = False, private_key: str = None):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            # Delete ALL existing API keys for this user (keep only the latest)
            cursor.execute('''
                DELETE FROM api_keys 
                WHERE user_id = ?
            ''', (user_id,))
            
            # Check if this API key or wallet is already used by ANOTHER user
            # For Hyperliquid, check wallet address (stored in both api_key and api_passphrase)
            # For other exchanges, check api_key
            if exchange.lower() == 'hyperliquid' and api_passphrase:
                # Check both fields for Hyperliquid wallet
                cursor.execute('''
                    SELECT user_id FROM api_keys 
                    WHERE exchange = ? AND (api_passphrase = ? OR api_key = ?) AND user_id != ?
                ''', (exchange, api_passphrase, api_passphrase, user_id))
            elif exchange.lower() == 'hyperliquid' and api_key:
                # If api_passphrase not provided, check api_key
                cursor.execute('''
                    SELECT user_id FROM api_keys 
                    WHERE exchange = ? AND (api_key = ? OR api_passphrase = ?) AND user_id != ?
                ''', (exchange, api_key, api_key, user_id))
            else:
                cursor.execute('''
                    SELECT user_id FROM api_keys 
                    WHERE exchange = ? AND api_key = ? AND user_id != ?
                ''', (exchange, api_key, user_id))
            
            existing_user = cursor.fetchone()
            if existing_user:
                logger.warning(f"API key/wallet already in use by another user on {exchange}")
                conn.rollback()  # Rollback the DELETE since we're not adding new key
                return False  # Indicate that the API key is already in use
            
            # Insert the new API key
            cursor.execute('''
                INSERT INTO api_keys 
                (user_id, exchange, api_key, api_secret, api_passphrase, private_key, testnet) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, exchange, api_key, api_secret, api_passphrase, private_key, testnet))
            conn.commit()
            logger.info(f"API key added for user {user_id} on {exchange}")
            return True  # Success
        except Exception as e:
            logger.error(f"Error adding API key: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    
    def get_user_api_key(self, user_id: str, exchange: str) -> Optional[Dict]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT api_key, api_secret, api_passphrase, testnet, private_key 
                FROM api_keys 
                WHERE user_id = ? AND exchange = ?
            ''', (user_id, exchange))
            result = cursor.fetchone()
            if result:
                data = {
                    'api_key': result[0],
                    'api_secret': result[1],
                    'api_passphrase': result[2],
                    'testnet': bool(result[3]),
                    'private_key': result[4] if len(result) > 4 else None
                }
                if not data['private_key']:
                    data['private_key'] = data['api_secret']
                # For Hyperliquid, api_passphrase stores wallet_address
                if exchange.lower() == 'hyperliquid':
                    data['wallet_address'] = result[2]
                return data
            return None
        finally:
            conn.close()
    
    def add_channel(self, channel_id: str, channel_name: str):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('INSERT OR IGNORE INTO channels (channel_id, channel_name) VALUES (?, ?)', 
                         (channel_id, channel_name))
            conn.commit()
            logger.info(f"Channel {channel_name} ({channel_id}) added as signal channel")
        finally:
            conn.close()
    
    def subscribe_to_channel(self, user_id: str, channel_id: str, exchange: str, 
                           position_size: float = 1.0, max_risk: float = 2.0,
                           position_mode: str = 'percentage', fixed_amount: float = 100.0,
                           percentage_of_balance: float = 10.0):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO channel_subscriptions 
                (user_id, channel_id, exchange, position_size, max_risk, 
                 position_mode, fixed_amount, percentage_of_balance) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, channel_id, exchange, position_size, max_risk,
                  position_mode, fixed_amount, percentage_of_balance))
            conn.commit()
            logger.info(f"User {user_id} subscribed to channel {channel_id} on {exchange} "
                       f"(mode: {position_mode}, max_risk: {max_risk}%)")
        finally:
            conn.close()
    
    def get_subscription(self, user_id: str, channel_id: str) -> Optional[Dict]:
        """Get a user's subscription for a specific channel"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT user_id, channel_id, exchange, position_size, max_risk, 
                       position_mode, fixed_amount, percentage_of_balance, created_at
                FROM channel_subscriptions
                WHERE user_id = ? AND channel_id = ?
            ''', (user_id, channel_id))
            
            result = cursor.fetchone()
            if result:
                return {
                    'user_id': result[0],
                    'channel_id': result[1],
                    'exchange': result[2],
                    'position_size': result[3],
                    'max_risk': result[4],
                    'position_mode': result[5] if len(result) > 5 and result[5] else 'percentage',
                    'fixed_amount': result[6] if len(result) > 6 and result[6] else 100.0,
                    'percentage_of_balance': result[7] if len(result) > 7 and result[7] else 10.0,
                    'created_at': result[8] if len(result) > 8 else result[5]
                }
            return None
        finally:
            conn.close()
    
    def is_signal_channel(self, channel_id: str) -> bool:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT is_signal_channel FROM channels WHERE channel_id = ?', (str(channel_id),))
            result = cursor.fetchone()
            return bool(result[0]) if result else False
        finally:
            conn.close()
    
    def get_channel_users(self, channel_id: str) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
          SELECT cs.user_id, cs.exchange, cs.position_size, cs.max_risk,
              ak.api_key, ak.api_secret, ak.api_passphrase, ak.testnet, ak.private_key,
              cs.position_mode, cs.fixed_amount, cs.percentage_of_balance
                FROM channel_subscriptions cs
                JOIN api_keys ak ON cs.user_id = ak.user_id AND cs.exchange = ak.exchange
                WHERE cs.channel_id = ?
            ''', (str(channel_id),))
            
            results = cursor.fetchall()
            users = []
            for row in results:
                users.append({
                    'user_id': row[0],
                    'exchange': row[1],
                    'position_size': row[2],
                    'max_risk': row[3],
                    'api_key': row[4],
                    'api_secret': row[5],
                    'api_passphrase': row[6],
                    'testnet': bool(row[7]),
                    'private_key': (row[8] if len(row) > 8 else None) or row[5],
                    'position_mode': row[9] if len(row) > 9 and row[9] else 'percentage',
                    'fixed_amount': row[10] if len(row) > 10 and row[10] else 100.0,
                    'percentage_of_balance': row[11] if len(row) > 11 and row[11] else 10.0
                })
            return users
        finally:
            conn.close()
    
    def log_trade(self, user_id: str, exchange: str, symbol: str, side: str, 
                  size: float, price: float = None, signal_data: str = None,
                  channel_id: str = None, message_id: str = None):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO trades (user_id, exchange, symbol, side, size, price, signal_data, channel_id, message_id) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, exchange, symbol, side, size, price, signal_data, channel_id, message_id))
            conn.commit()
            inserted_id = cursor.lastrowid
            logger.info(f"Trade logged: {user_id} {side} {size} {symbol} on {exchange} (ID: {inserted_id})")
            return inserted_id
        finally:
            conn.close()
    
    def get_user_trades(self, user_id: str, limit: int = 10) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT exchange, symbol, side, size, price, status, created_at
                FROM trades 
                WHERE user_id = ? 
                ORDER BY created_at DESC 
                LIMIT ?
            ''', (user_id, limit))
            
            results = cursor.fetchall()
            trades = []
            for row in results:
                trades.append({
                    'exchange': row[0],
                    'symbol': row[1],
                    'side': row[2],
                    'size': row[3],
                    'price': row[4],
                    'status': row[5],
                    'created_at': row[6]
                })
            return trades
        finally:
            conn.close()
    
    def get_user_subscriptions(self, user_id: str) -> List[Dict]:
        """Get all channel subscriptions for a user"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT cs.id, cs.user_id, cs.channel_id, cs.exchange, 
                       cs.position_size, cs.max_risk, cs.created_at, c.channel_name,
                       cs.position_mode, cs.fixed_amount, cs.percentage_of_balance
                FROM channel_subscriptions cs
                LEFT JOIN channels c ON cs.channel_id = c.channel_id
                WHERE cs.user_id = ?
                ORDER BY cs.created_at DESC
            ''', (user_id,))
            
            subscriptions = []
            for row in cursor.fetchall():
                subscriptions.append({
                    'id': row[0],
                    'user_id': row[1],
                    'channel_id': row[2],
                    'exchange': row[3],
                    'position_size': row[4],
                    'max_risk': row[5],
                    'created_at': row[6],
                    'channel_name': row[7] if row[7] else f"Channel-{row[2]}",
                    'position_mode': row[8] if len(row) > 8 and row[8] else 'percentage',
                    'fixed_amount': row[9] if len(row) > 9 and row[9] else 100.0,
                    'percentage_of_balance': row[10] if len(row) > 10 and row[10] else 10.0
                })
            return subscriptions
        finally:
            conn.close()
    
    def remove_channel_subscription(self, user_id: str, channel_id: str):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                DELETE FROM channel_subscriptions 
                WHERE user_id = ? AND channel_id = ?
            ''', (user_id, channel_id))
            conn.commit()
            logger.info(f"User {user_id} unsubscribed from channel {channel_id}")
        finally:
            conn.close()
    
    def update_subscription(self, subscription_id: int, position_mode: str = None, 
                           position_size: float = None, max_risk: float = None) -> bool:
        """Update subscription settings with proper field handling"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            updates = []
            params = []
            
            if position_mode is not None:
                updates.append("position_mode = ?")
                params.append(position_mode)
            
            if position_size is not None:
                # Update the appropriate field based on the current mode
                # First get the current mode if not provided
                if position_mode is None:
                    cursor.execute("SELECT position_mode FROM channel_subscriptions WHERE id = ?", (subscription_id,))
                    result = cursor.fetchone()
                    current_mode = result[0] if result else 'percentage'
                else:
                    current_mode = position_mode
                
                # Update both position_size (for backward compatibility) and the specific field
                updates.append("position_size = ?")
                params.append(position_size)
                
                if current_mode == 'fixed':
                    updates.append("fixed_amount = ?")
                    params.append(position_size)
                else:
                    updates.append("percentage_of_balance = ?")
                    params.append(position_size)
            
            if max_risk is not None:
                updates.append("max_risk = ?")
                params.append(max_risk)
            
            if not updates:
                return False
            
            params.append(subscription_id)
            query = f"UPDATE channel_subscriptions SET {', '.join(updates)} WHERE id = ?"
            
            cursor.execute(query, params)
            conn.commit()
            
            success = cursor.rowcount > 0
            if success:
                logger.info(f"Updated subscription {subscription_id} with mode: {position_mode}, size: {position_size}")
            
            conn.close()
            return success
        except Exception as e:
            logger.error(f"Error updating subscription: {e}")
            return False

    # ---------------- Wallet Management (reuse api_passphrase column) -----------------
    def update_wallet(self, user_id: str, exchange: str, wallet_address: str) -> bool:
        """Store or update a wallet address for an exchange by reusing api_passphrase.

        For Hyperliquid we need the public wallet address to query balances. Instead of a schema
        migration we reuse the existing api_passphrase column (Hyperliquid doesn't need it).
        Returns True on success, False if no API key row exists or failure occurs.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE api_keys
                SET api_passphrase = ?
                WHERE user_id = ? AND exchange = ?
            ''', (wallet_address, user_id, exchange))
            updated = cursor.rowcount
            conn.commit()
            conn.close()
            if updated == 0:
                logger.warning(f"Wallet update failed: No api_key row for user={user_id} exchange={exchange}")
                return False
            logger.info(f"Wallet updated for user {user_id} on {exchange}")
            return True
        except Exception as e:
            logger.error(f"Error updating wallet for {user_id} on {exchange}: {e}")
            return False

    def update_exchange_network(self, user_id: str, exchange: str, testnet: bool) -> bool:
        """Update testnet flag for a stored api key row."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE api_keys SET testnet = ? WHERE user_id = ? AND exchange = ?
            ''', (1 if testnet else 0, user_id, exchange))
            updated = cursor.rowcount
            conn.commit()
            conn.close()
            if updated == 0:
                logger.warning(f"Network update failed: no api key row for user={user_id} exchange={exchange}")
                return False
            logger.info(f"Network flag updated for user {user_id} {exchange} -> testnet={testnet}")
            return True
        except Exception as e:
            logger.error(f"Error updating network flag for {user_id} on {exchange}: {e}")
            return False

    def get_user_all_api_keys(self, user_id: str) -> List[Dict]:
        """Get all API keys for a user"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT exchange, api_key, api_secret, api_passphrase, testnet, private_key, created_at
                FROM api_keys
                WHERE user_id = ?
                ORDER BY created_at DESC
            ''', (user_id,))
            rows = cursor.fetchall()
            api_keys = []
            for row in rows:
                data = {
                    'exchange': row[0],
                    'api_key': row[1],
                    'api_secret': row[2],
                    'api_passphrase': row[3],
                    'testnet': bool(row[4]),
                    'private_key': row[5] if len(row) > 5 else None,
                    'created_at': row[6] if len(row) > 6 else None
                }
                # Fallback for private_key
                if not data['private_key']:
                    data['private_key'] = data['api_secret']
                # For Hyperliquid, api_passphrase stores wallet_address
                if data['exchange'].lower() == 'hyperliquid':
                    data['wallet_address'] = row[3]
                api_keys.append(data)
            return api_keys
        finally:
            conn.close()

    def delete_api_key(self, user_id: str, exchange: str) -> bool:
        """Delete an API key for a user"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM api_keys
                WHERE user_id = ? AND exchange = ?
            ''', (user_id, exchange))
            deleted = cursor.rowcount > 0
            conn.commit()
            conn.close()
            if deleted:
                logger.info(f"Deleted API key for user {user_id} on {exchange}")
            return deleted
        except Exception as e:
            logger.error(f"Error deleting API key: {e}")
            return False

    # Admin Panel Helper Methods
    def get_all_users_count(self) -> int:
        """Get total number of users"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT COUNT(*) FROM users')
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def get_total_subscriptions_count(self) -> int:
        """Get total number of subscriptions"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT COUNT(*) FROM channel_subscriptions')
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def get_all_channels_count(self) -> int:
        """Get total number of channels"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT COUNT(*) FROM channels')
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def get_recent_trades_count(self, days: int = 7) -> int:
        """Get number of trades in the last N days"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT COUNT(*) FROM trades 
                WHERE datetime(created_at) >= datetime('now', '-' || ? || ' days')
            ''', (days,))
            return cursor.fetchone()[0]
        finally:
            conn.close()
    
    def get_total_trades_count(self) -> int:
        """Get total count of all trades"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT COUNT(*) FROM trades')
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def get_all_users_with_details(self) -> List[Dict]:
        """Get all users with their details"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT u.user_id, u.username, u.created_at, u.is_banned,
                       COUNT(DISTINCT cs.id) as subscriptions,
                       COUNT(DISTINCT ak.id) as api_keys
                FROM users u
                LEFT JOIN channel_subscriptions cs ON u.user_id = cs.user_id
                LEFT JOIN api_keys ak ON u.user_id = ak.user_id
                GROUP BY u.user_id
                ORDER BY u.created_at DESC
            ''')
            rows = cursor.fetchall()
            return [{
                'user_id': row[0],
                'username': row[1],
                'created_at': row[2],
                'is_banned': bool(row[3]),
                'subscriptions': row[4],
                'api_keys': row[5]
            } for row in rows]
        finally:
            conn.close()

    def get_all_subscriptions_with_details(self) -> List[Dict]:
        """Get all subscriptions with details"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT cs.id, u.username, c.channel_name, cs.exchange,
                       cs.position_size, cs.max_risk, cs.position_mode,
                       cs.fixed_amount, cs.percentage_of_balance, cs.created_at
                FROM channel_subscriptions cs
                JOIN users u ON cs.user_id = u.user_id
                JOIN channels c ON cs.channel_id = c.channel_id
                ORDER BY cs.created_at DESC
            ''')
            rows = cursor.fetchall()
            return [{
                'id': row[0],
                'username': row[1],
                'channel_name': row[2],
                'exchange': row[3],
                'position_size': row[4],
                'max_risk': row[5],
                'position_mode': row[6],
                'fixed_amount': row[7],
                'percentage_of_balance': row[8],
                'created_at': row[9]
            } for row in rows]
        finally:
            conn.close()

    def get_all_channels(self) -> List[Dict]:
        """Get all channels"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT c.channel_id, c.channel_name, c.is_signal_channel,
                       COUNT(cs.id) as subscribers, c.created_at
                FROM channels c
                LEFT JOIN channel_subscriptions cs ON c.channel_id = cs.channel_id
                GROUP BY c.channel_id
                ORDER BY subscribers DESC
            ''')
            rows = cursor.fetchall()
            return [{
                'channel_id': row[0],
                'channel_name': row[1],
                'is_signal_channel': bool(row[2]),
                'subscribers': row[3],
                'created_at': row[4]
            } for row in rows]
        finally:
            conn.close()

    def get_recent_trades(self, limit: int = 50) -> List[Dict]:
        """Get recent trades"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT t.id, u.username, t.symbol, t.side, t.entry_price,
                       t.size, t.status, t.exchange, t.created_at, t.price,
                       t.stop_loss, t.take_profit, t.channel_id
                FROM trades t
                JOIN users u ON t.user_id = u.user_id
                ORDER BY t.created_at DESC
                LIMIT ?
            ''', (limit,))
            rows = cursor.fetchall()
            return [{
                'id': row[0],
                'username': row[1],
                'symbol': row[2],
                'side': row[3].upper(),
                'entry_price': row[4],
                'quantity': row[5],  # size field mapped to quantity for UI compatibility
                'status': row[6],
                'exchange': row[7],
                'created_at': row[8],
                'price': row[9],
                'stop_loss': row[10],
                'take_profit': row[11],
                'channel_id': row[12],
                'pnl': 0.0  # Placeholder - would need current price to calculate real PnL
            } for row in rows]
        finally:
            conn.close()

    # Channel Management Methods for Admin Panel
    def get_channel_subscribers(self, channel_id: str) -> List[Dict]:
        """Get all subscribers for a specific channel"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT 
                    u.user_id,
                    u.username,
                    cs.exchange,
                    cs.created_at
                FROM channel_subscriptions cs
                JOIN users u ON cs.user_id = u.user_id
                WHERE cs.channel_id = ?
                ORDER BY cs.created_at DESC
            ''', (channel_id,))
            rows = cursor.fetchall()
            return [{
                'user_id': row[0],
                'username': row[1],
                'exchange': row[2],
                'created_at': row[3]
            } for row in rows]
        finally:
            conn.close()

    def update_channel(self, channel_id: str, channel_name: str, is_signal_channel: bool) -> bool:
        """Update channel information"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE channels 
                SET channel_name = ?, is_signal_channel = ?
                WHERE channel_id = ?
            ''', (channel_name, is_signal_channel, channel_id))
            updated = cursor.rowcount > 0
            conn.commit()
            conn.close()
            if updated:
                logger.info(f"Updated channel {channel_id}")
            return updated
        except Exception as e:
            logger.error(f"Error updating channel: {e}")
            return False

    def delete_channel(self, channel_id: str) -> bool:
        """Delete a channel and all its subscriptions"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Delete subscriptions first
            cursor.execute('DELETE FROM channel_subscriptions WHERE channel_id = ?', (channel_id,))
            
            # Delete channel
            cursor.execute('DELETE FROM channels WHERE channel_id = ?', (channel_id,))
            deleted = cursor.rowcount > 0
            
            conn.commit()
            conn.close()
            if deleted:
                logger.info(f"Deleted channel {channel_id}")
            return deleted
        except Exception as e:
            logger.error(f"Error deleting channel: {e}")
            return False

    # NEW: Methods for Admin Panel Analytics
    def get_active_trades_count(self) -> int:
        """Get count of active trades"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM trades WHERE status = 'active'")
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def get_active_trades_detailed(self) -> List[Dict]:
        """Get detailed list of all active trades"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT t.id, t.user_id, u.username, t.symbol, t.side, 
                       t.entry_price, t.price, t.position_size, t.leverage,
                       t.take_profit, t.stop_loss, t.exchange, t.created_at
                FROM trades t
                JOIN users u ON t.user_id = u.user_id
                WHERE t.status = 'active'
                ORDER BY t.created_at DESC
            ''')
            rows = cursor.fetchall()
            
            trades = []
            for row in rows:
                # Parse TP/SL if they are JSON arrays
                take_profit = row[9]
                stop_loss = row[10]
                
                # Handle TP/SL array format
                if isinstance(take_profit, str) and take_profit.startswith('['):
                    try:
                        tp_list = json.loads(take_profit)
                        take_profit = float(tp_list[0]) if tp_list and len(tp_list) > 0 else None
                    except Exception as e:
                        logger.error(f"Error parsing TP: {e}")
                        take_profit = None
                
                if isinstance(stop_loss, str) and stop_loss.startswith('['):
                    try:
                        sl_list = json.loads(stop_loss)
                        stop_loss = float(sl_list[0]) if sl_list and len(sl_list) > 0 else None
                    except Exception as e:
                        logger.error(f"Error parsing SL: {e}")
                        stop_loss = None
                
                # Use entry_price if available, otherwise use price
                entry_price = row[5] if row[5] else row[6]
                
                trades.append({
                    'id': row[0],
                    'user_id': row[1],
                    'username': row[2],
                    'symbol': row[3],
                    'side': row[4],
                    'entry_price': entry_price,
                    'position_size': row[7],
                    'leverage': row[8] or 1,
                    'take_profit': take_profit,
                    'stop_loss': stop_loss,
                    'exchange': row[11],
                    'created_at': row[12]
                })
            
            return trades
        finally:
            conn.close()


    # NEW: Methods for Admin Panel Analytics
    def get_active_trades_count(self) -> int:
        """Get count of active trades"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM trades WHERE status = 'active'")
            return cursor.fetchone()[0]
        finally:
            conn.close()
