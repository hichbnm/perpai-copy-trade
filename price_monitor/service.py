import asyncio
import logging
from ast import literal_eval
from datetime import datetime
from typing import Dict, List, Optional
import discord
from database.db_manager import DatabaseManager
from .monitor import PriceMonitor
from .websocket_feed import HybridPriceFeed

logger = logging.getLogger(__name__)

class TradeMonitoringService:
    """
    Enhanced trade monitoring service that tracks all active trades
    and provides real-time updates when targets are hit
    """
    
    def __init__(self, bot, db_manager: DatabaseManager):
        self.bot = bot
        self.db_manager = db_manager
        self.price_monitor = PriceMonitor(
            bot,
            on_target_hit=self._handle_target_hit,
            on_trade_completed=self._handle_trade_completed
        )
        self.price_feed = HybridPriceFeed()
        self.is_running = False
        
    async def start(self):
        """Start the trade monitoring service"""
        if self.is_running:
            return
            
        try:
            # Set up price feed callbacks
            self.price_feed.add_callback(self._on_price_update)
            
            # Start price feed
            await self.price_feed.start()
            
            # Load existing trades from database
            await self._load_active_trades()
            
            # Start monitoring
            await self.price_monitor.start_monitoring()
            
            self.is_running = True
            logger.info("Trade monitoring service started successfully")
            
        except Exception as e:
            logger.error(f"Failed to start trade monitoring service: {e}")
            raise
    
    async def stop(self):
        """Stop the trade monitoring service"""
        if not self.is_running:
            return
            
        try:
            await self.price_monitor.stop_monitoring()
            await self.price_feed.stop()
            self.is_running = False
            logger.info("Trade monitoring service stopped")
            
        except Exception as e:
            logger.error(f"Error stopping trade monitoring service: {e}")
    
    async def add_trade_from_signal(self, trade_data: Dict):
        """Add a new trade to monitoring from signal processing"""
        try:
            trade_data.setdefault('timestamp', datetime.now().isoformat())
            trade_data['stop_loss'] = self._parse_target_levels(trade_data.get('stop_loss'))
            trade_data['take_profit'] = self._parse_target_levels(trade_data.get('take_profit'))
            
            # Save trade to database for persistence
            inserted_id = await self._save_trade_to_db(trade_data)
            if inserted_id is not None:
                trade_data['db_id'] = inserted_id
            
            # Add to price monitor with enriched data
            self.price_monitor.add_trade_to_monitor(trade_data)
            
            # Subscribe to price updates for this symbol
            symbol = trade_data.get('symbol')
            if symbol:
                self.price_feed.subscribe(symbol)
                logger.info(f"Subscribed to price updates for {symbol}")
            
        except Exception as e:
            logger.error(f"Error adding trade to monitoring: {e}")
    
    async def _load_active_trades(self):
        """Load active trades from database on startup"""
        try:
            # Get all active trades from database
            query = """
                SELECT id, user_id, exchange, symbol, side, size, price, entry_price, 
                       stop_loss, take_profit, channel_id, message_id, status, targets_hit, created_at
                FROM trades 
                WHERE status = 'active' 
                AND created_at > NOW() - INTERVAL '7 days'
                ORDER BY created_at DESC
            """
            
            import json
            with self.db_manager.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query)
                    active_trades = cursor.fetchall()
            
            for trade in active_trades:
                try:
                    # Safely parse stop_loss and take_profit
                    stop_loss = []
                    take_profit = []
                    
                    stop_loss = self._parse_target_levels(trade[8])
                    take_profit = self._parse_target_levels(trade[9])
                    
                    # Parse targets_hit from JSON
                    targets_hit = {'sl': False, 'tp': []}
                    if trade[13]:  # targets_hit column
                        try:
                            targets_hit = json.loads(trade[13])
                            logger.info(f"Loaded targets_hit for trade {trade[0]}: {targets_hit}")
                        except json.JSONDecodeError:
                            logger.warning(f"Failed to parse targets_hit for trade {trade[0]}, using default")
                    
                    trade_data = {
                        'db_id': trade[0],        # id
                        'user_id': trade[1],      # user_id
                        'exchange': trade[2],     # exchange  
                        'symbol': trade[3],       # symbol
                        'side': trade[4],         # side
                        'size': trade[5],         # size
                        'entry_price': trade[7],  # entry_price
                        'stop_loss': stop_loss,
                        'take_profit': take_profit,
                        'channel_id': trade[10],  # channel_id
                        'message_id': trade[11],  # message_id
                        'timestamp': trade[14],   # created_at (moved by 1 position)
                        'status': trade[12],       # status
                        'targets_hit': targets_hit  # Load from database
                    }
                except Exception as e:
                    logger.error(f"Error parsing trade data: {e}")
                    continue
                
                # Add to monitoring
                self.price_monitor.add_trade_to_monitor(trade_data)
                
                # Subscribe to price updates
                self.price_feed.subscribe(trade_data['symbol'])
            
            logger.info(f"Loaded {len(active_trades)} active trades for monitoring")
            
        except Exception as e:
            logger.error(f"Error loading active trades: {e}")
    
    async def _save_trade_to_db(self, trade_data: Dict):
        """Save trade to database"""
        try:
            query = """
                INSERT INTO trades (
                    user_id, exchange, symbol, side, size, price, entry_price, stop_loss, 
                    take_profit, channel_id, message_id, status, targets_hit, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """
            
            # Serialize targets_hit to JSON
            import json
            targets_hit_json = json.dumps(trade_data.get('targets_hit', {'sl': False, 'tp': []}))
            
            values = (
                trade_data.get('user_id'),
                trade_data.get('exchange', 'hyperliquid'),  # Default exchange
                trade_data.get('symbol'),
                trade_data.get('side'),
                trade_data.get('size', 1.0),
                trade_data.get('entry_price'),  # price column
                trade_data.get('entry_price'),  # entry_price column
                str(trade_data.get('stop_loss', [])),
                str(trade_data.get('take_profit', [])),
                trade_data.get('channel_id'),
                trade_data.get('message_id'),
                'active',
                targets_hit_json,  # Store targets_hit as JSON
                trade_data.get('timestamp', datetime.now().isoformat())
            )
            
            with self.db_manager.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, values)
                    inserted_id = cursor.fetchone()[0]
                    conn.commit()
            return inserted_id
            
        except Exception as e:
            logger.error(f"Error saving trade to database: {e}")
            return None
    
    async def _on_price_update(self, symbol: str, price: float):
        """Handle real-time price updates"""
        # The PriceMonitor will handle the actual target checking
        # This is just for logging/debugging
        logger.debug(f"Price update: {symbol} = ${price:.4f}")
    
    async def get_monitoring_status(self) -> Dict:
        """Get current monitoring status"""
        stats = self.price_monitor.get_monitoring_stats()
        
        return {
            'service_running': self.is_running,
            'price_feed_connected': hasattr(self.price_feed, 'websocket_feed') and 
                                  self.price_feed.websocket_feed.websocket is not None and
                                  not self.price_feed.websocket_feed.websocket.closed,
            'active_trades': stats['active_trades'],
            'total_monitored': stats['total_monitored'],
            'update_interval': stats['update_interval'],
            'subscribed_symbols': len(self.price_feed.websocket_feed.subscriptions) 
                                if hasattr(self.price_feed, 'websocket_feed') else 0
        }
    
    async def remove_trade(self, trade_id: str):
        """Remove a trade from monitoring"""
        try:
            # Remove from price monitor
            if trade_id in self.price_monitor.monitored_trades:
                symbol = self.price_monitor.monitored_trades[trade_id]['symbol']
                del self.price_monitor.monitored_trades[trade_id]
                
                # Check if we can unsubscribe from this symbol
                still_monitoring = any(
                    trade['symbol'] == symbol 
                    for trade in self.price_monitor.monitored_trades.values()
                )
                
                if not still_monitoring:
                    self.price_feed.unsubscribe(symbol)
                
                logger.info(f"Removed trade {trade_id} from monitoring")
            
        except Exception as e:
            logger.error(f"Error removing trade from monitoring: {e}")
    
    async def update_trade_status(self, trade_id: str, status: str):
        """Update trade status in database"""
        try:
            query = "UPDATE trades SET status = %s WHERE id = %s"
            with self.db_manager.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (status, trade_id))
                    rows_affected = cursor.rowcount
                    conn.commit()
            
            if rows_affected > 0:
                logger.info(f"Updated trade {trade_id} status to '{status}' ({rows_affected} row(s))")
            else:
                logger.warning(f"No rows updated for trade {trade_id} - trade might not exist in database")
            
        except Exception as e:
            logger.error(f"Error updating trade status for {trade_id}: {e}")
    
    async def get_user_active_trades(self, user_id: int) -> List[Dict]:
        """Get all active trades for a user"""
        try:
            query = """
                SELECT id, user_id, exchange, symbol, side, size, price, entry_price, 
                       stop_loss, take_profit, channel_id, message_id, status, targets_hit, created_at
                FROM trades 
                WHERE user_id = %s AND status = 'active'
                ORDER BY created_at DESC
            """
            
            import json
            with self.db_manager.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (user_id,))
                    trades = cursor.fetchall()
            
            result = []
            for trade in trades:
                try:
                    stop_loss = self._parse_target_levels(trade[8])
                    take_profit = self._parse_target_levels(trade[9])
                    
                    # Parse targets_hit from JSON
                    targets_hit = {'sl': False, 'tp': []}
                    if trade[13]:  # targets_hit column
                        try:
                            targets_hit = json.loads(trade[13])
                        except json.JSONDecodeError:
                            logger.warning(f"Failed to parse targets_hit for trade {trade[0]}, using default")
                    
                    result.append({
                        'id': trade[0],
                        'db_id': trade[0],
                        'symbol': trade[3],       # symbol
                        'side': trade[4],         # side
                        'entry_price': trade[7],  # entry_price
                        'stop_loss': stop_loss,
                        'take_profit': take_profit,
                        'size': trade[5],         # size
                        'created_at': trade[14],  # created_at (moved by 1 position)
                        'status': trade[12],      # status
                        'targets_hit': targets_hit  # Load from database
                    })
                except Exception as e:
                    logger.error(f"Error parsing trade {trade[0]}: {e}")
                    continue
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting user active trades: {e}")
            return []
    
    async def cleanup_orphaned_trades(self):
        """Find and complete trades that are in memory but not in DB or vice versa"""
        try:
            with self.db_manager.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Get all active trades from database
                    cursor.execute("SELECT id FROM trades WHERE status = 'active'")
                    db_trade_ids = set(str(row[0]) for row in cursor.fetchall())
            
            # Get all monitored trade IDs (extract db_id from monitored trades)
            monitored_db_ids = set()
            for trade in self.price_monitor.monitored_trades.values():
                db_id = trade.get('db_id')
                if db_id:
                    monitored_db_ids.add(str(db_id))
            
            # Find trades that are in DB but not being monitored
            orphaned_in_db = db_trade_ids - monitored_db_ids
            if orphaned_in_db:
                logger.warning(f"Found {len(orphaned_in_db)} trades in DB not being monitored: {orphaned_in_db}")
            
            # Find trades being monitored but not in DB
            orphaned_in_memory = monitored_db_ids - db_trade_ids
            if orphaned_in_memory:
                logger.warning(f"Found {len(orphaned_in_memory)} trades being monitored but not active in DB: {orphaned_in_memory}")
            
            return {
                'db_only': list(orphaned_in_db),
                'memory_only': list(orphaned_in_memory)
            }
            
        except Exception as e:
            logger.error(f"Error checking orphaned trades: {e}")
            return {'db_only': [], 'memory_only': []}
    
    async def create_monitoring_embed(self) -> discord.Embed:
        """Create an embed showing monitoring status"""
        status = await self.get_monitoring_status()
        
        embed = discord.Embed(
            title="📊 Trade Monitoring Status",
            description="Real-time trade monitoring and alerts",
            color=0x00d2d3 if status['service_running'] else 0xff4757
        )
        
        # Service status
        service_status = "🟢 Running" if status['service_running'] else "🔴 Stopped"
        embed.add_field(
            name="Service Status",
            value=service_status,
            inline=True
        )
        
        # Connection status
        connection_status = "🟢 Connected" if status['price_feed_connected'] else "🔴 Disconnected"
        embed.add_field(
            name="Price Feed",
            value=connection_status,
            inline=True
        )
        
        # Active trades
        embed.add_field(
            name="Active Trades",
            value=f"{status['active_trades']} monitored",
            inline=True
        )
        
        # Subscribed symbols
        embed.add_field(
            name="Tracked Symbols",
            value=f"{status['subscribed_symbols']} symbols",
            inline=True
        )
        
        # Update interval
        embed.add_field(
            name="Update Frequency",
            value=f"Every {status['update_interval']}s",
            inline=True
        )
        
        # Total monitored
        embed.add_field(
            name="Total Monitored",
            value=f"{status['total_monitored']} trades",
            inline=True
        )
        
        embed.set_footer(text="🤖 Automated monitoring with real-time alerts")
        embed.timestamp = datetime.now()
        
        return embed
    
    async def create_user_monitoring_text(self, user_id: str) -> str:
        """Create a user-specific monitoring status as text message"""
        try:
            # Get user-specific trades
            resolved_user_id: Optional[int]
            if isinstance(user_id, int):
                resolved_user_id = user_id
            else:
                try:
                    resolved_user_id = int(user_id)
                except (TypeError, ValueError):
                    logger.warning(
                        "Invalid user_id '%s' provided to create_user_monitoring_text",
                        user_id,
                    )
                    resolved_user_id = None

            user_trades = []
            monitoring_snapshot = []
            if resolved_user_id is not None:
                user_trades = await self.get_user_active_trades(resolved_user_id)
                monitoring_snapshot = self.price_monitor.get_user_trade_snapshot(resolved_user_id)
                snapshot_by_db_id = {
                    trade.get('db_id'): trade for trade in monitoring_snapshot if trade.get('db_id') is not None
                }
                for trade in user_trades:
                    monitor_row = snapshot_by_db_id.get(trade.get('db_id'))
                    if monitor_row:
                        trade['targets_hit'] = monitor_row.get('targets_hit', {'sl': False, 'tp': []})
                        trade['status'] = monitor_row.get('status', trade.get('status', 'active'))
                        trade['current_price'] = monitor_row.get('last_price')
            else:
                user_trades = []
            
            message = """🔍 **YOUR PERSONAL TRADING MONITOR**

Real-time monitoring status for your trades

"""
            
            if user_trades:
                # Count by symbol
                symbol_counts = {}
                for trade in user_trades:
                    symbol = trade.get('symbol', 'Unknown')
                    symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
                
                # Active trades summary
                message += f"**📊 Your Active Trades:**\n{len(user_trades)} trades being monitored\n\n"
                
                # Symbols being tracked
                symbols_text = ', '.join([f"{symbol} ({count})" for symbol, count in symbol_counts.items()])
                if len(symbols_text) > 100:
                    symbols_text = symbols_text[:100] + "..."
                message += f"**📈 Tracked Symbols:**\n{symbols_text}\n\n"
                
                # Recent trades (last 3)
                recent_trades = user_trades[:3]
                message += "**🕒 Recent Trades:**\n"
                for trade in recent_trades:
                    symbol = trade.get('symbol', 'Unknown')
                    side = trade.get('side', 'Unknown').upper()
                    tp_hits = trade.get('targets_hit', {}).get('tp', []) if trade.get('targets_hit') else []
                    sl_hit = trade.get('targets_hit', {}).get('sl', False) if trade.get('targets_hit') else False
                    status_bits = []
                    if tp_hits:
                        status_bits.append(f"TP hit: {', '.join(str(i + 1) for i in tp_hits)}")
                    if sl_hit:
                        status_bits.append("SL triggered")
                    if trade.get('status') and trade['status'] != 'active':
                        status_bits.append(trade['status'].capitalize())
                    last_price = trade.get('current_price')
                    entry_price = trade.get('entry_price')
                    price_chunk = ""
                    if last_price is not None:
                        price_chunk = f" — Last ${float(last_price):,.4f}"
                    if entry_price:
                        price_chunk += f" • Entry ${float(entry_price):,.4f}"
                    status_suffix = f" ({' | '.join(status_bits)})" if status_bits else ""
                    message += f"• {symbol} {side}{price_chunk}{status_suffix}\n"
                
                message += "\n**🎯 Monitoring Features:**\n"
                message += "• Real-time price tracking\n"
                message += "• TP/SL hit detection\n"
                message += "• Instant Discord notifications\n"
                
            else:
                message += "**📭 No Active Trades**\n"
                message += "You don't have any trades being monitored currently\n\n"
                message += "**🚀 Get Started:**\n"
                message += "• Subscribe to signal channels\n"
                message += "• Post or wait for trading signals\n"
                message += "• Your trades will appear here automatically\n"
            
            from datetime import datetime
            timestamp = int(datetime.now().timestamp())
            message += f"\n───────────────────────────\n"
            message += f"Personal monitoring dashboard • Updated <t:{timestamp}:R>"
            
            return message
            
        except Exception as e:
            logger.error(f"Error creating user monitoring text for {user_id}: {e}")
            
            # Fallback message
            message = """🔍 **PERSONAL TRADING MONITOR**

❌ Unable to load monitoring data

**Error**
Please try again later or contact support

───────────────────────────
Personal monitoring dashboard"""
            return message
    
    async def create_user_monitoring_embed(self, user_id: str) -> discord.Embed:
        """Create a user-specific monitoring status embed (DEPRECATED - use create_user_monitoring_text)"""
        try:
            # Get user-specific trades
            resolved_user_id: Optional[int]
            if isinstance(user_id, int):
                resolved_user_id = user_id
            else:
                try:
                    resolved_user_id = int(user_id)
                except (TypeError, ValueError):
                    logger.warning(
                        "Invalid user_id '%s' provided to create_user_monitoring_embed",
                        user_id,
                    )
                    resolved_user_id = None

            user_trades = []
            monitoring_snapshot = []
            if resolved_user_id is not None:
                user_trades = await self.get_user_active_trades(resolved_user_id)
                monitoring_snapshot = self.price_monitor.get_user_trade_snapshot(resolved_user_id)
                snapshot_by_db_id = {
                    trade.get('db_id'): trade for trade in monitoring_snapshot if trade.get('db_id') is not None
                }
                for trade in user_trades:
                    monitor_row = snapshot_by_db_id.get(trade.get('db_id'))
                    if monitor_row:
                        trade['targets_hit'] = monitor_row.get('targets_hit', {'sl': False, 'tp': []})
                        trade['status'] = monitor_row.get('status', trade.get('status', 'active'))
                        trade['current_price'] = monitor_row.get('last_price')
            else:
                user_trades = []
            
            embed = discord.Embed(
                title="🔍 Your Personal Trading Monitor",
                description="Real-time monitoring status for your trades",
                color=0x00ff00 if user_trades else 0xffa500
            )
            
            if user_trades:
                # Count by symbol
                symbol_counts = {}
                for trade in user_trades:
                    symbol = trade.get('symbol', 'Unknown')
                    symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
                
                # Active trades summary
                embed.add_field(
                    name="📊 Your Active Trades",
                    value=f"{len(user_trades)} trades being monitored",
                    inline=True
                )
                
                # Symbols being tracked
                symbols_text = ', '.join([f"{symbol} ({count})" for symbol, count in symbol_counts.items()])
                embed.add_field(
                    name="📈 Tracked Symbols",
                    value=symbols_text[:100] + "..." if len(symbols_text) > 100 else symbols_text,
                    inline=True
                )
                
                # Recent trades (last 3)
                recent_trades = user_trades[:3]
                trades_text_parts = []
                for trade in recent_trades:
                    symbol = trade.get('symbol', 'Unknown')
                    side = trade.get('side', 'Unknown').upper()
                    tp_hits = trade.get('targets_hit', {}).get('tp', []) if trade.get('targets_hit') else []
                    sl_hit = trade.get('targets_hit', {}).get('sl', False) if trade.get('targets_hit') else False
                    status_bits = []
                    if tp_hits:
                        status_bits.append(f"TP hit: {', '.join(str(i + 1) for i in tp_hits)}")
                    if sl_hit:
                        status_bits.append("SL triggered")
                    if trade.get('status') and trade['status'] != 'active':
                        status_bits.append(trade['status'].capitalize())
                    last_price = trade.get('current_price')
                    entry_price = trade.get('entry_price')
                    price_chunk = ""
                    if last_price is not None:
                        price_chunk = f" — Last ${float(last_price):,.4f}"
                    if entry_price:
                        price_chunk += f" • Entry ${float(entry_price):,.4f}"
                    status_suffix = f" ({' | '.join(status_bits)})" if status_bits else ""
                    trades_text_parts.append(f"• {symbol} {side}{price_chunk}{status_suffix}")
                trades_text = "\n".join(trades_text_parts)
                embed.add_field(
                    name="🕒 Recent Trades",
                    value=trades_text,
                    inline=False
                )
                
                embed.add_field(
                    name="🎯 Monitoring Features",
                    value="• Real-time price tracking\n• TP/SL hit detection\n• Instant Discord notifications",
                    inline=False
                )
                
            else:
                embed.add_field(
                    name="📭 No Active Trades",
                    value="You don't have any trades being monitored currently",
                    inline=False
                )
                
                embed.add_field(
                    name="🚀 Get Started",
                    value="• Subscribe to signal channels\n• Post or wait for trading signals\n• Your trades will appear here automatically",
                    inline=False
                )
            
            embed.set_footer(text=f"Personal monitoring dashboard • Updated every few seconds")
            embed.timestamp = datetime.now()
            
            return embed
            
        except Exception as e:
            logger.error(f"Error creating user monitoring embed for {user_id}: {e}")
            
            # Fallback embed
            embed = discord.Embed(
                title="🔍 Personal Trading Monitor",
                description="❌ Unable to load monitoring data",
                color=0xff0000
            )
            embed.add_field(
                name="Error",
                value="Please try again later or contact support",
                inline=False
            )
            return embed

    async def _handle_target_hit(self, trade: Dict, target_type: str, target_price: float,
                                 current_price: float, tp_number: Optional[int] = None):
        try:
            trade_id = trade.get('db_id')
            if trade_id is not None:
                logger.info(
                    "Recorded target hit for trade %s: %s at %.4f (current %.4f)",
                    trade_id,
                    f"TP{tp_number}" if target_type == 'take_profit' else 'SL',
                    target_price,
                    current_price
                )
                
                # Update targets_hit in database to persist across restarts
                await self._update_trade_targets_hit(trade_id, trade.get('targets_hit', {'sl': False, 'tp': []}))
        except Exception as exc:
            logger.error(f"Error handling target hit callback: {exc}")
    
    async def _update_trade_targets_hit(self, trade_id: int, targets_hit: Dict):
        """Update the targets_hit field in the database"""
        try:
            import json
            
            targets_hit_json = json.dumps(targets_hit)
            
            with self.db_manager.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "UPDATE trades SET targets_hit = %s WHERE id = %s",
                        (targets_hit_json, trade_id)
                    )
                    conn.commit()
            
            logger.info(f"✅ Updated targets_hit in DB for trade {trade_id}: {targets_hit}")
        except Exception as e:
            logger.error(f"❌ Error updating targets_hit in database: {e}")

    async def _handle_trade_completed(self, trade: Dict):
        """Handle trade completion - update database status"""
        try:
            trade_id = trade.get('db_id')
            if trade_id is None:
                logger.warning(f"Trade completed but no db_id found: {trade.get('trade_key', 'unknown')}")
                logger.warning(f"Trade data: {trade}")
                return
            
            logger.info(f"Trade {trade_id} completed, updating database status...")
            await self.update_trade_status(trade_id, 'completed')
            logger.info(f"✅ Trade {trade_id} marked as completed in database")
            
        except Exception as exc:
            logger.error(f"Error handling trade completion: {exc}")

    def _parse_target_levels(self, value) -> List[float]:
        if not value:
            return []
        parsed = value
        if isinstance(value, str):
            try:
                parsed = literal_eval(value)
            except Exception:
                return []
        if not isinstance(parsed, (list, tuple)):
            return []
        results: List[float] = []
        for entry in parsed:
            try:
                results.append(float(entry))
            except (TypeError, ValueError):
                continue
        return results