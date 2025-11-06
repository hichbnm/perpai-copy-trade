import asyncio
import logging
import json
from ast import literal_eval
from datetime import datetime
from typing import Dict, List, Optional
from database.db_manager import DatabaseManager
from .signal_monitor import SignalBasedPriceMonitor
from .position_monitor import APIBasedPositionMonitor

logger = logging.getLogger(__name__)

class SignalBasedTradeService:
    """
    Signal-based trade monitoring service with API-based position tracking
    
    Uses TWO monitoring strategies:
    1. **API-Based (Primary)**: Monitors actual positions from exchange API
       - 100% accurate entry detection
       - Real fill prices
       - No false notifications
    
    2. **Price-Based (Fallback)**: Estimates entry based on price movements
       - Used when API credentials unavailable
       - Less accurate but still useful
    
    The system automatically chooses the best method for each signal.
    """
    
    def __init__(self, bot, db_manager: DatabaseManager):
        self.bot = bot
        self.db_manager = db_manager
        
        # Primary: API-based position monitoring
        self.api_monitor = APIBasedPositionMonitor(bot)
        
        # Fallback: Price-based signal monitoring
        self.signal_monitor = SignalBasedPriceMonitor(
            bot,
            on_target_hit=self._handle_target_hit,
            on_signal_completed=self._handle_signal_completed
        )
        
        self.is_running = False
        self.signal_to_trade_ids = {}  # {signal_id: [db_trade_ids]}
        self.monitoring_mode = {}  # {signal_id: 'api' or 'price'}
        
    async def start(self):
        """Start the signal-based monitoring service"""
        if self.is_running:
            return
            
        try:
            # Load existing active trades and group by signal
            await self._load_and_group_trades()
            
            # Start BOTH monitoring systems
            await self.api_monitor.start_monitoring()
            await self.signal_monitor.start_monitoring()
            
            self.is_running = True
            logger.info("✅ Trade monitoring started (API + Price-based)")
            
        except Exception as e:
            logger.error(f"Failed to start signal monitoring: {e}")
            raise
    
    async def stop(self):
        """Stop the signal-based monitoring service"""
        if not self.is_running:
            return
            
        try:
            await self.api_monitor.stop_monitoring()
            await self.signal_monitor.stop_monitoring()
            self.is_running = False
            logger.info("⏸️ Trade monitoring stopped")
            
        except Exception as e:
            logger.error(f"Error stopping signal monitoring: {e}")
    
    async def add_trades_from_signal(self, signal_data: Dict, user_trade_mappings: List[Dict]):
        """
        Add trades from a signal execution
        
        Tries API-based monitoring first, falls back to price-based if needed.
        
        Args:
            signal_data: Signal information (symbol, entries, TPs, SL, etc.)
            user_trade_mappings: List of {user_id, size, db_trade_id} mappings
        """
        try:
            # Extract user IDs
            user_ids = [mapping['user_id'] for mapping in user_trade_mappings]
            
            # Parse targets
            signal_data['stop_loss'] = self._parse_target_levels(signal_data.get('stop_loss'))
            signal_data['take_profit'] = self._parse_target_levels(signal_data.get('take_profit'))
            
            # Enrich user mappings with API credentials from database
            enriched_mappings = []
            for mapping in user_trade_mappings:
                user_id = mapping['user_id']
                
                # Get user's API credentials from database
                api_keys = self.db_manager.get_api_keys(user_id)
                if api_keys:
                    mapping['api_key'] = api_keys.get('api_key')
                    mapping['api_secret'] = api_keys.get('api_secret')
                    mapping['exchange'] = api_keys.get('exchange')
                    mapping['testnet'] = api_keys.get('testnet', False)
                
                enriched_mappings.append(mapping)
            
            # Try API-based monitoring FIRST (more accurate)
            signal_id = self.api_monitor.add_signal_to_monitor(signal_data, enriched_mappings)
            
            if signal_id:
                # API-based monitoring is active
                self.monitoring_mode[signal_id] = 'api'
                logger.info(
                    f"📡 API-based monitoring for signal {signal_id}\n"
                    f"   ✅ Will track actual positions via exchange API\n"
                    f"   👥 {len(user_ids)} users"
                )
            else:
                # Fallback to price-based monitoring
                signal_id = self.signal_monitor.add_signal_to_monitor(signal_data, user_ids)
                self.monitoring_mode[signal_id] = 'price'
                logger.info(
                    f"📊 Price-based monitoring for signal {signal_id}\n"
                    f"   ⚠️ Estimating entry based on price movements\n"
                    f"   👥 {len(user_ids)} users"
                )
            
            # Store mapping from signal to trade IDs
            trade_ids = [mapping.get('db_trade_id') for mapping in user_trade_mappings 
                        if mapping.get('db_trade_id')]
            self.signal_to_trade_ids[signal_id] = trade_ids
            
        except Exception as e:
            logger.error(f"Error adding trades from signal: {e}")
    
    async def _load_and_group_trades(self):
        """Load active trades from database and group by signal"""
        try:
            # Get all active trades using DatabaseManager's connection
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                query = """
                    SELECT id, user_id, symbol, side, entry_price, stop_loss, take_profit,
                           channel_id, message_id, created_at, targets_hit
                    FROM trades 
                    WHERE status = 'active' 
                    AND created_at > CURRENT_TIMESTAMP - INTERVAL '7 days'
                    ORDER BY channel_id, symbol, side, entry_price
                """
                cursor.execute(query)
                active_trades = cursor.fetchall()
            
            # Group trades by signal
            signal_groups = {}  # {signal_key: [trades]}
            
            for trade in active_trades:
                db_id = trade[0]
                user_id = trade[1]
                symbol = trade[2]
                side = trade[3]
                entry_price = trade[4]
                stop_loss_data = trade[5]
                take_profit_data = trade[6]
                channel_id = trade[7]
                message_id = trade[8]
                created_at = trade[9]
                targets_hit_str = trade[10]
                
                # Handle JSONB data (PostgreSQL returns as dict/list)
                if isinstance(stop_loss_data, list):
                    stop_loss = stop_loss_data
                elif isinstance(stop_loss_data, str):
                    stop_loss = self._parse_target_levels(stop_loss_data)
                else:
                    stop_loss = []
                
                if isinstance(take_profit_data, list):
                    take_profit = take_profit_data
                elif isinstance(take_profit_data, str):
                    take_profit = self._parse_target_levels(take_profit_data)
                else:
                    take_profit = []
                
                # Parse targets_hit
                targets_hit = {'sl': False, 'tp': []}
                if targets_hit_str:
                    try:
                        if isinstance(targets_hit_str, str):
                            targets_hit = json.loads(targets_hit_str)
                        elif isinstance(targets_hit_str, dict):
                            targets_hit = targets_hit_str
                    except:
                        pass
                
                # Create signal key (channel + symbol + entry + SL + TP)
                # Handle None values to prevent formatting errors
                safe_channel_id = channel_id or 'unknown'
                safe_symbol = symbol or 'unknown'
                safe_entry_price = entry_price or 0
                safe_message_id = message_id or 'unknown'
                signal_key = f"{safe_channel_id}_{safe_symbol}_{safe_entry_price}_{safe_message_id}"
                
                if signal_key not in signal_groups:
                    signal_groups[signal_key] = {
                        'signal_data': {
                            'channel_id': channel_id,
                            'message_id': message_id,
                            'symbol': symbol or 'Unknown',
                            'side': side or 'unknown',
                            'entry': [entry_price] if entry_price else [],
                            'stop_loss': stop_loss,
                            'take_profit': take_profit,
                            'timestamp': created_at,
                            'targets_hit': targets_hit  # Use from first trade
                        },
                        'users': [],
                        'trade_ids': []
                    }
                
                signal_groups[signal_key]['users'].append(user_id)
                signal_groups[signal_key]['trade_ids'].append(db_id)
            
            # Add each signal to monitoring
            for signal_key, group_data in signal_groups.items():
                signal_data = group_data['signal_data']
                user_ids = group_data['users']
                trade_ids = group_data['trade_ids']
                
                # Add to signal monitor
                signal_id = self.signal_monitor.add_signal_to_monitor(signal_data, user_ids)
                self.signal_to_trade_ids[signal_id] = trade_ids
            
            total_trades = len(active_trades)
            total_signals = len(signal_groups)
            saved_checks = total_trades - total_signals
            
            logger.info(f"✅ Loaded {total_trades} trades grouped into {total_signals} signals")
            
            if total_trades > 0:
                reduction_percent = (saved_checks / total_trades * 100)
                logger.info(f"💰 Saved {saved_checks} redundant price checks ({reduction_percent:.1f}% reduction)")
            else:
                logger.info(f"💡 No active trades to monitor - ready for new signals")
            
        except Exception as e:
            logger.error(f"Error loading and grouping trades: {e}")
    
    async def _handle_target_hit(self, trade_info: Dict, target_type: str, 
                                target_price: float, current_price: float, tp_number: Optional[int] = None):
        """Handle when a target is hit for a signal"""
        try:
            signal_id = trade_info.get('signal_id')
            user_id = trade_info.get('user_id')
            
            # Update this user's trade in database
            await self._update_user_trade_target(user_id, signal_id, target_type, tp_number)
            
            logger.debug(f"✅ Updated {target_type} for user {user_id} on signal {signal_id}")
            
        except Exception as e:
            logger.error(f"Error handling target hit: {e}")
    
    async def _handle_signal_completed(self, signal: Dict):
        """Handle when all targets for a signal are hit"""
        try:
            signal_id = signal.get('signal_id')
            
            # Get all trade IDs for this signal
            trade_ids = self.signal_to_trade_ids.get(signal_id, [])
            
            if trade_ids:
                # Update all trades to completed using DatabaseManager
                with self.db_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    placeholders = ','.join(['%s'] * len(trade_ids))
                    query = f"UPDATE trades SET status = 'completed' WHERE id IN ({placeholders})"
                    cursor.execute(query, trade_ids)
                    updated = cursor.rowcount
                
                logger.info(f"✅ Marked {updated} trades as completed for signal {signal_id}")
                
                # Remove mapping
                del self.signal_to_trade_ids[signal_id]
            
        except Exception as e:
            logger.error(f"Error handling signal completion: {e}")
    
    async def _update_user_trade_target(self, user_id: int, signal_id: str, 
                                       target_type: str, tp_number: Optional[int]):
        """Update targets_hit for a specific user's trade"""
        try:
            # Get trade ID for this user on this signal
            trade_ids = self.signal_to_trade_ids.get(signal_id, [])
            
            # Find user's trade using DatabaseManager
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                placeholders = ','.join(['%s'] * len(trade_ids))
                query = f"SELECT id, targets_hit FROM trades WHERE user_id = %s AND id IN ({placeholders}) AND status = 'active'"
                cursor.execute(query, [str(user_id)] + trade_ids)
                result = cursor.fetchone()
            
            if result:
                trade_id = result[0]
                targets_hit_data = result[1]
                
                # Parse current targets_hit
                targets_hit = {'sl': False, 'tp': []}
                if targets_hit_data:
                    try:
                        if isinstance(targets_hit_data, str):
                            targets_hit = json.loads(targets_hit_data)
                        elif isinstance(targets_hit_data, dict):
                            targets_hit = targets_hit_data
                    except:
                        pass
                
                # Update based on target type
                if target_type == 'stop_loss':
                    targets_hit['sl'] = True
                elif target_type == 'take_profit' and tp_number:
                    if tp_number - 1 not in targets_hit['tp']:
                        targets_hit['tp'].append(tp_number - 1)
                
                # Save back to database
                with self.db_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    update_query = "UPDATE trades SET targets_hit = %s WHERE id = %s"
                    cursor.execute(update_query, (json.dumps(targets_hit), trade_id))
                
                logger.debug(f"Updated targets_hit for trade {trade_id}: {targets_hit}")
            
        except Exception as e:
            logger.error(f"Error updating user trade target: {e}")
    
    def _parse_target_levels(self, value) -> List[float]:
        """Parse target levels from various formats"""
        if not value:
            return []
        
        if isinstance(value, str):
            try:
                parsed = literal_eval(value)
            except:
                return []
        else:
            parsed = value
        
        if not isinstance(parsed, (list, tuple)):
            parsed = [parsed]
        
        result = []
        for v in parsed:
            try:
                result.append(float(v))
            except:
                continue
        
        return result
    
    def get_monitoring_stats(self) -> Dict:
        """Get monitoring statistics"""
        stats = self.signal_monitor.get_monitoring_stats()
        stats['total_db_trades'] = sum(len(ids) for ids in self.signal_to_trade_ids.values())
        return stats
    
    async def get_user_active_trades(self, user_id: int) -> List[Dict]:
        """Get active trades for a user"""
        try:
            # Use DatabaseManager's connection
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                query = """
                    SELECT id, symbol, side, entry_price, size, stop_loss, take_profit, 
                           targets_hit, created_at
                    FROM trades
                    WHERE user_id = %s AND status = 'active'
                    ORDER BY created_at DESC
                """
                cursor.execute(query, (str(user_id),))
                trades = cursor.fetchall()
            
            result = []
            for trade in trades:
                targets_hit_data = trade[7]
                targets_hit = {'sl': False, 'tp': []}
                if targets_hit_data:
                    try:
                        if isinstance(targets_hit_data, str):
                            targets_hit = json.loads(targets_hit_data)
                        elif isinstance(targets_hit_data, dict):
                            targets_hit = targets_hit_data
                    except:
                        pass
                
                result.append({
                    'id': trade[0],
                    'symbol': trade[1],
                    'side': trade[2],
                    'entry': trade[3],
                    'size': trade[4],
                    'stop_loss': self._parse_target_levels(trade[5]),
                    'take_profit': self._parse_target_levels(trade[6]),
                    'targets_hit': targets_hit,
                    'timestamp': trade[8]
                })
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting user trades: {e}")
            return []
    
    async def create_user_monitoring_text(self, user_id: str) -> str:
        """Create monitoring summary text for a user (for UI compatibility)"""
        try:
            user_id_int = int(user_id)
            trades = await self.get_user_active_trades(user_id_int)
            
            if not trades:
                return "📊 **Active Monitoring**\n\n🔍 No active trades being monitored."
            
            lines = ["📊 **Active Monitoring**", ""]
            
            for i, trade in enumerate(trades, 1):
                symbol = trade.get('symbol', 'UNKNOWN')
                side = trade.get('side', 'BUY').upper()
                entry = trade.get('entry')
                stop_loss = trade.get('stop_loss', [])
                take_profit = trade.get('take_profit', [])
                targets_hit = trade.get('targets_hit', {'sl': False, 'tp': []})
                
                # Side emoji
                side_emoji = "🟢" if side == "BUY" else "🔴"
                
                lines.append(f"**{i}. {side_emoji} {symbol} {side}**")
                
                # Entry price with None check
                if entry is not None:
                    lines.append(f"   Entry: ${entry:g}")
                else:
                    lines.append(f"   Entry: N/A")
                
                # Stop loss status
                if stop_loss and len(stop_loss) > 0 and stop_loss[0] is not None:
                    sl_status = "✅ Hit" if targets_hit.get('sl') else "⏳ Active"
                    lines.append(f"   SL: ${stop_loss[0]:g} {sl_status}")
                
                # Take profit status
                if take_profit and len(take_profit) > 0:
                    tp_hits = targets_hit.get('tp', [])
                    tp_text = []
                    for idx, tp in enumerate(take_profit):
                        if tp is not None:
                            status = "✅" if idx in tp_hits else "⏳"
                            tp_text.append(f"{status} ${tp:g}")
                    if tp_text:
                        lines.append(f"   TP: {', '.join(tp_text)}")
                
                lines.append("")
            
            # Add summary
            total_signals = len(set(self.signal_monitor.get_user_signals(user_id_int)))
            lines.append(f"📡 **Signals**: {total_signals}")
            lines.append(f"📊 **Trades**: {len(trades)}")
            lines.append(f"🔄 **Update**: Every 30 seconds")
            
            return "\n".join(lines)
            
        except Exception as e:
            logger.error(f"Error creating monitoring text: {e}")
            return f"❌ Error loading monitoring data: {str(e)}"
    
    async def create_monitoring_embed(self):
        """Create monitoring embed for dashboard (for UI compatibility)"""
        import discord
        from datetime import datetime
        
        try:
            stats = self.get_monitoring_stats()
            
            embed = discord.Embed(
                title="📊 Signal-Based Monitoring Status",
                color=discord.Color.green() if stats['is_running'] else discord.Color.red(),
                timestamp=datetime.now()
            )
            
            # Status
            status_emoji = "🟢" if stats['is_running'] else "🔴"
            status_text = "Active" if stats['is_running'] else "Stopped"
            embed.add_field(
                name=f"{status_emoji} Status",
                value=status_text,
                inline=True
            )
            
            # Signals being monitored
            embed.add_field(
                name="🎯 Active Signals",
                value=str(stats['active_signals']),
                inline=True
            )
            
            # Total users affected
            embed.add_field(
                name="👥 Total Users",
                value=str(stats['total_users_affected']),
                inline=True
            )
            
            # Database trades
            embed.add_field(
                name="📊 Database Trades",
                value=str(stats.get('total_db_trades', 0)),
                inline=True
            )
            
            # Update interval
            embed.add_field(
                name="🔄 Check Interval",
                value=f"{stats.get('update_interval', 30)}s",
                inline=True
            )
            
            # Efficiency
            if stats['total_users_affected'] > 0 and stats['active_signals'] > 0:
                saved = stats['total_users_affected'] - stats['active_signals']
                efficiency = (saved / stats['total_users_affected'] * 100)
                embed.add_field(
                    name="💰 API Efficiency",
                    value=f"{efficiency:.0f}% reduction\n({saved} calls saved)",
                    inline=True
                )
            
            embed.set_footer(text="Signal-based monitoring groups trades by signal for maximum efficiency")
            
            return embed
            
        except Exception as e:
            logger.error(f"Error creating monitoring embed: {e}")
            embed = discord.Embed(
                title="❌ Monitoring Status Error",
                description=f"Error loading status: {str(e)}",
                color=discord.Color.red()
            )
            return embed
    
    async def get_monitoring_status(self) -> Dict:
        """Get monitoring status (for UI compatibility)"""
        stats = self.get_monitoring_stats()
        total_trades = stats.get('total_db_trades', 0)
        return {
            'service_running': stats['is_running'],
            'active_trades': total_trades,
            'total_monitored': total_trades,  # Same as active_trades for signal-based monitoring
            'active_signals': stats['active_signals'],
            'total_users': stats['total_users_affected'],
            'update_interval': stats.get('update_interval', 30),
            'price_feed_connected': True,  # WebSocket always connected for signal-based monitoring
            'subscribed_symbols': stats['active_signals']  # Each signal = 1 symbol subscription
        }
