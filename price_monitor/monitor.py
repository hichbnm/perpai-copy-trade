import asyncio
import inspect
import aiohttp
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
import discord

logger = logging.getLogger(__name__)

class PriceMonitor:
    def __init__(self, bot, on_target_hit: Optional[Any] = None, on_trade_completed: Optional[Any] = None):
        self.bot = bot
        self.monitored_trades: Dict[str, Dict] = {}  # {trade_id: trade_info}
        self.price_cache = {}  # {symbol: {price, timestamp}}
        self.monitoring_task = None
        self.update_interval = 30  # seconds
        self._on_target_hit = on_target_hit
        self._on_trade_completed = on_trade_completed
        self.pending_notifications = {}  # Group notifications by signal
        self.notification_sent = set()  # Track already sent notifications to avoid duplicates
        
    async def start_monitoring(self):
        """Start the price monitoring task"""
        if self.monitoring_task is None or self.monitoring_task.done():
            self.monitoring_task = asyncio.create_task(self._monitor_prices())
            logger.info("Price monitoring started")
    
    async def stop_monitoring(self):
        """Stop the price monitoring task"""
        if self.monitoring_task:
            self.monitoring_task.cancel()
            logger.info("Price monitoring stopped")
    
    def add_trade_to_monitor(self, trade_data: Dict):
        """Add a trade to monitoring list"""
        trade_db_id = trade_data.get('db_id')
        trade_unique_id = str(trade_db_id) if trade_db_id is not None else (
            f"{trade_data['user_id']}_{trade_data['symbol']}_{trade_data.get('timestamp', datetime.now())}"
        )

        normalized_stop_loss = self._normalize_target_levels(trade_data.get('stop_loss'))
        normalized_take_profit = self._normalize_target_levels(trade_data.get('take_profit'))

        created_at = trade_data.get('timestamp', datetime.now())
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at)
            except ValueError:
                created_at = datetime.now()
        
        targets_hit = trade_data.get('targets_hit')
        if isinstance(targets_hit, dict):
            targets_hit = {
                'sl': bool(targets_hit.get('sl', False)),
                'tp': [int(tp) for tp in targets_hit.get('tp', []) if isinstance(tp, (int, float))]
            }
        else:
            targets_hit = {'sl': False, 'tp': []}

        self.monitored_trades[trade_unique_id] = {
            'db_id': trade_db_id,
            'trade_key': trade_unique_id,
            'user_id': trade_data['user_id'],
            'symbol': trade_data['symbol'],
            'side': trade_data['side'],
            'entry_price': trade_data.get('entry_price'),
            'stop_loss': normalized_stop_loss,
            'take_profit': normalized_take_profit,
            'size': float(trade_data.get('size', 1.0) or 0),
            'channel_id': trade_data.get('channel_id'),
            'message_id': trade_data.get('message_id'),
            'created_at': created_at,
            'targets_hit': targets_hit,
            'status': trade_data.get('status', 'active')
        }
        
        logger.info(f"Added trade {trade_unique_id} to monitoring")
    
    async def _monitor_prices(self):
        """Main monitoring loop"""
        while True:
            try:
                await self._check_all_trades()
                await asyncio.sleep(self.update_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in price monitoring: {e}")
                await asyncio.sleep(self.update_interval)
    
    async def _check_all_trades(self):
        """Check all monitored trades for target hits"""
        if not self.monitored_trades:
            return
        
        # Get unique symbols to fetch prices for
        symbols = set(trade['symbol'] for trade in self.monitored_trades.values() 
                     if trade['status'] == 'active')
        
        if not symbols:
            return
        
        # Fetch current prices
        prices = await self._fetch_prices(symbols)
        
        # Clear pending notifications for this check cycle
        self.pending_notifications = {}
        
        # Check each trade
        trades_to_remove = []
        for trade_id, trade in list(self.monitored_trades.items()):
            if trade['status'] != 'active':
                continue
                
            symbol = trade['symbol']
            if symbol not in prices:
                continue
                
            current_price = prices[symbol]
            trade['last_price'] = current_price
            
            # Check for target hits
            if await self._check_targets(trade_id, trade, current_price):
                trade['status'] = 'completed'
                await self._maybe_call_callback(self._on_trade_completed, trade)
                trades_to_remove.append(trade_id)
        
        # Send grouped notifications after all trades checked
        await self._send_grouped_notifications()
        
        # Clear pending notifications after sending
        self.pending_notifications.clear()
        
        # Remove completed trades
        for trade_id in trades_to_remove:
            del self.monitored_trades[trade_id]
    
    async def _fetch_prices(self, symbols: set) -> Dict[str, float]:
        """Fetch current prices for symbols"""
        prices = {}
        
        try:
            # Use Hyperliquid API for price data
            async with aiohttp.ClientSession() as session:
                # Hyperliquid provides all prices in one API call
                url = "https://api.hyperliquid.xyz/info"
                payload = {
                    "type": "allMids"
                }
                
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        if isinstance(data, dict):
                            for symbol in symbols:
                                # Convert our symbol format to Hyperliquid format
                                # e.g., "BTC/USDC" -> "BTC"
                                base_symbol = symbol.split('/')[0]
                                
                                if base_symbol in data:
                                    try:
                                        price = float(data[base_symbol])
                                        prices[symbol] = price
                                        logger.debug(f"Fetched price for {symbol}: ${price}")
                                    except (ValueError, TypeError) as e:
                                        logger.warning(f"Invalid price data for {symbol}: {data[base_symbol]}")
                                else:
                                    logger.warning(f"Symbol {base_symbol} not found in Hyperliquid price data")
                    else:
                        logger.error(f"Failed to fetch prices from Hyperliquid API: HTTP {response.status}")
                        
        except Exception as e:
            logger.error(f"Error in price fetching: {e}")
        
        return prices
    
    async def _check_targets(self, trade_id: str, trade: Dict, current_price: float) -> bool:
        """
        Check if any targets are hit for a trade based on PRICE ONLY
        
        ⚠️ WARNING: This is price-based monitoring and does NOT verify actual positions!
        Use API-based monitoring (position_monitor.py) for accurate position verification.
        
        This method assumes user has an open position if price hits target.
        False positives can occur if:
        - User manually closed position early
        - Position was liquidated
        - Entry order never filled
        """
        side = trade['side']
        stop_losses = trade.get('stop_loss', [])
        take_profits = trade.get('take_profit', [])
        targets_hit = trade['targets_hit']
        
        trade_completed = False
        
        # Check Stop Loss
        if not targets_hit['sl'] and stop_losses:
            sl_price = stop_losses[0]  # Use first SL
            
            if side == 'buy' and current_price <= sl_price:
                # Long position hit stop loss
                targets_hit['sl'] = True  # ✅ Mark as hit BEFORE sending notification
                # Store the hit for group notification
                await self._queue_target_hit(trade, 'stop_loss', sl_price, current_price)
                trade_completed = True
                
            elif side == 'sell' and current_price >= sl_price:
                # Short position hit stop loss
                targets_hit['sl'] = True  # ✅ Mark as hit BEFORE sending notification
                # Store the hit for group notification
                await self._queue_target_hit(trade, 'stop_loss', sl_price, current_price)
                trade_completed = True
        
        # Check Take Profits
        for i, tp_price in enumerate(take_profits):
            if i in targets_hit['tp']:
                continue  # Already hit
                
            if side == 'buy' and current_price >= tp_price:
                # Long position hit take profit
                targets_hit['tp'].append(i)  # ✅ Add to list BEFORE sending notification
                # Store the hit for group notification
                await self._queue_target_hit(trade, 'take_profit', tp_price, current_price, i + 1)
                
            elif side == 'sell' and current_price <= tp_price:
                # Short position hit take profit
                targets_hit['tp'].append(i)  # ✅ Add to list BEFORE sending notification
                # Store the hit for group notification
                await self._queue_target_hit(trade, 'take_profit', tp_price, current_price, i + 1)
        
        # Check if all targets hit
        if len(targets_hit['tp']) == len(take_profits):
            trade_completed = True
        
        return trade_completed
    
    async def _queue_target_hit(self, trade: Dict, target_type: str, target_price: float, 
                               current_price: float, tp_number: int = None):
        """Queue a target hit for grouped notification"""
        # Create a unique key for this signal event
        symbol = trade['symbol']
        side = trade['side']
        channel_id = trade.get('channel_id')
        message_id = trade.get('message_id')
        
        if target_type == 'stop_loss':
            event_key = f"{symbol}_{side}_SL_{target_price}_{channel_id}"
        else:
            event_key = f"{symbol}_{side}_TP{tp_number}_{target_price}_{channel_id}"
        
        # Check if we already sent notification for this event
        if event_key in self.notification_sent:
            logger.debug(f"Skipping duplicate notification for {event_key}")
            return
        
        # Initialize if not exists
        if event_key not in self.pending_notifications:
            self.pending_notifications[event_key] = {
                'symbol': symbol,
                'side': side,
                'target_type': target_type,
                'target_price': target_price,
                'current_price': current_price,
                'tp_number': tp_number,
                'channel_id': channel_id,
                'message_id': message_id,
                'trades': [],
                'entry_price': trade.get('entry_price')
            }
        
        # Add this trade to the group
        self.pending_notifications[event_key]['trades'].append({
            'user_id': trade['user_id'],
            'size': trade.get('size', 1.0)
        })
    
    async def _send_grouped_notifications(self):
        """Send one notification per signal event with all affected users"""
        sent_events = []
        
        for event_key, event_data in self.pending_notifications.items():
            try:
                # Mark as sent to avoid duplicate sends in this cycle
                self.notification_sent.add(event_key)
                sent_events.append(event_key)
                
                channel_id = event_data['channel_id']
                message_id = event_data['message_id']
                
                if not channel_id:
                    continue
                
                channel = self.bot.get_channel(int(channel_id))
                if channel is None:
                    try:
                        channel = await self.bot.fetch_channel(int(channel_id))
                    except Exception:
                        channel = None
                
                if channel is None:
                    logger.warning(f"Could not find channel {channel_id} for notification")
                    continue
                
                # Build grouped notification
                notification_text = self._build_grouped_notification(event_data)
                
                # Send notification
                try:
                    if message_id:
                        try:
                            original_message = await channel.fetch_message(int(message_id))
                            await original_message.reply(notification_text)
                        except Exception:
                            await channel.send(notification_text)
                    else:
                        await channel.send(notification_text)
                    
                    logger.info(f"Sent grouped {event_data['target_type']} notification for {event_data['symbol']} "
                              f"affecting {len(event_data['trades'])} trader(s)")
                    
                    # Call callbacks for each trade
                    for trade_info in event_data['trades']:
                        await self._maybe_call_callback(
                            self._on_target_hit, 
                            trade_info, 
                            event_data['target_type'], 
                            event_data['target_price'], 
                            event_data['current_price'], 
                            event_data['tp_number']
                        )
                        
                except Exception as send_error:
                    logger.error(f"Error sending grouped notification: {send_error}")
                    
            except Exception as e:
                logger.error(f"Error processing grouped notification for {event_key}: {e}")
        
        # Clean up old notification tracking (keep last 100 to prevent memory leak)
        if len(self.notification_sent) > 100:
            # Remove oldest 50 entries
            to_remove = list(self.notification_sent)[:50]
            for key in to_remove:
                self.notification_sent.discard(key)
            logger.debug(f"Cleaned up {len(to_remove)} old notification tracking entries")
    
    def _build_grouped_notification(self, event_data: Dict) -> str:
        """Build a single notification for all affected traders"""
        symbol = event_data['symbol']
        side = event_data['side']
        target_type = event_data['target_type']
        target_price = event_data['target_price']
        current_price = event_data['current_price']
        tp_number = event_data['tp_number']
        trades = event_data['trades']
        entry_price = event_data['entry_price']
        
        # Calculate profit/loss
        profit_pct = 0
        if entry_price:
            if side == 'buy':
                profit_pct = ((current_price - entry_price) / entry_price) * 100
            else:
                profit_pct = ((entry_price - current_price) / entry_price) * 100
        
        # Count total traders and positions
        trader_count = len(trades)
        total_size = sum(trade['size'] for trade in trades)
        
        # Build trader list (up to 10 traders, then summarize)
        if trader_count <= 10:
            trader_mentions = ", ".join([f"<@{trade['user_id']}>" for trade in trades])
        else:
            first_traders = ", ".join([f"<@{trade['user_id']}>" for trade in trades[:5]])
            trader_mentions = f"{first_traders} and {trader_count - 5} more"
        
        # Build notification based on type
        if target_type == 'stop_loss':
            notification_text = f"""🛑 **STOP LOSS HIT!**

🪙 **Symbol**: {symbol} {side.upper()}
📉 **Stop Loss Level**: ${target_price:,.4f}
💰 **Current Price**: ${current_price:,.4f}
📊 **P&L**: {profit_pct:+.2f}%
👥 **Traders Affected**: {trader_count}
📊 **Total Position Size**: {total_size:,.2f}
⏰ **Hit Time**: <t:{int(datetime.now().timestamp())}:T>

🤖 Automated Trade Monitoring"""
        else:
            tp_label = f" {tp_number}" if tp_number else ""
            notification_text = f"""🎯 **TAKE PROFIT{tp_label} HIT!**

🪙 **Symbol**: {symbol} {side.upper()}
🎯 **Target Level**: ${target_price:,.4f}
💰 **Current Price**: ${current_price:,.4f}
📈 **Profit**: +{profit_pct:.2f}%
👥 **Traders Affected**: {trader_count}
📊 **Total Position Size**: {total_size:,.2f}
⏰ **Hit Time**: <t:{int(datetime.now().timestamp())}:T>

🤖 Automated Trade Monitoring"""
        
        return notification_text
    
    async def _send_target_notification(self, trade: Dict, target_type: str, target_price: float, 
                                      current_price: float, tp_number: int = None):
        """Send notification when a target is hit"""
        try:
            channel_id = trade.get('channel_id')
            message_id = trade.get('message_id')
            
            if not channel_id:
                return
            
            channel = self.bot.get_channel(int(channel_id))
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(int(channel_id))
                except Exception:
                    channel = None
            
            if channel is None:
                user = self.bot.get_user(int(trade['user_id'])) if trade.get('user_id') else None
                if user is None and trade.get('user_id'):
                    try:
                        user = await self.bot.fetch_user(int(trade['user_id']))
                    except Exception:
                        user = None
                
                if user:
                    try:
                        await user.send(self._build_notification_text(trade, target_type, target_price, current_price, tp_number))
                        logger.info("Sent %s notification via direct message to user %s", target_type, trade.get('user_id'))
                    except Exception as dm_exc:
                        logger.error("Failed to DM user %s for trade notification: %s", trade.get('user_id'), dm_exc)
                    await self._maybe_call_callback(self._on_target_hit, trade, target_type, target_price, current_price, tp_number)
                return
            
            notification_text = self._build_notification_text(
                trade, target_type, target_price, current_price, tp_number
            )
            
            # Send notification
            try:
                if message_id:
                    try:
                        original_message = await channel.fetch_message(int(message_id))
                        await original_message.reply(notification_text)
                    except Exception:
                        await channel.send(notification_text)
                else:
                    await channel.send(notification_text)
            finally:
                await self._maybe_call_callback(self._on_target_hit, trade, target_type, target_price, current_price, tp_number)
            logger.info(f"Sent {target_type} notification for {trade['symbol']} to {channel.name}")
            
        except Exception as e:
            logger.error(f"Error sending target notification: {e}")

    def _build_notification_text(self, trade: Dict, target_type: str, target_price: float,
                                 current_price: float, tp_number: Optional[int]) -> str:
        entry_price = trade.get('entry_price')

        if target_type == 'stop_loss':
            loss_pct = 0
            if entry_price:
                if trade['side'] == 'buy':
                    loss_pct = ((current_price - entry_price) / entry_price) * 100
                else:
                    loss_pct = ((entry_price - current_price) / entry_price) * 100

            notification_text = f"""🛑 **STOP LOSS HIT!**

🪙 **Symbol**: {trade['symbol']} {trade['side'].upper()}
📉 **Stop Loss Level**: ${target_price:,.4f}
💰 **Current Price**: ${current_price:,.4f}
📊 **P&L**: {loss_pct:+.2f}%
 **Position Size**: {trade.get('size', 1.0)}
⏰ **Hit Time**: <t:{int(datetime.now().timestamp())}:T>

🤖 Automated Trade Monitoring"""
        else:
            profit_pct = 0
            if entry_price:
                if trade['side'] == 'buy':
                    profit_pct = ((current_price - entry_price) / entry_price) * 100
                else:
                    profit_pct = ((entry_price - current_price) / entry_price) * 100

            tp_label = f" {tp_number}" if tp_number else ""
            notification_text = f"""🎯 **TAKE PROFIT{tp_label} HIT!**

🪙 **Symbol**: {trade['symbol']} {trade['side'].upper()}
🎯 **Target Level**: ${target_price:,.4f}
💰 **Current Price**: ${current_price:,.4f}
📈 **Profit**: +{profit_pct:.2f}%
📊 **Position Size**: {trade.get('size', 1.0)}
⏰ **Hit Time**: <t:{int(datetime.now().timestamp())}:T>

🤖 Automated Trade Monitoring"""

        return notification_text
    
    def get_monitoring_stats(self) -> Dict:
        """Get monitoring statistics"""
        active_trades = len([t for t in self.monitored_trades.values() if t['status'] == 'active'])
        
        return {
            'active_trades': active_trades,
            'total_monitored': len(self.monitored_trades),
            'update_interval': self.update_interval,
            'is_running': self.monitoring_task and not self.monitoring_task.done()
        }

    def get_user_trade_snapshot(self, user_id: int) -> List[Dict]:
        """Return a snapshot of trades currently monitored for a user."""
        snapshot = []
        for trade in self.monitored_trades.values():
            if trade.get('user_id') == user_id:
                snapshot.append({
                    **trade,
                    'last_price': trade.get('last_price'),
                    'stop_loss': list(trade.get('stop_loss', [])),
                    'take_profit': list(trade.get('take_profit', [])),
                    'targets_hit': {
                        'sl': trade.get('targets_hit', {}).get('sl', False),
                        'tp': list(trade.get('targets_hit', {}).get('tp', []))
                    }
                })
        return snapshot

    def _normalize_target_levels(self, values: Optional[Any]) -> List[float]:
        if not values:
            return []
        if isinstance(values, str):
            try:
                import ast
                parsed = ast.literal_eval(values)
            except Exception:
                parsed = []
        else:
            parsed = values

        normalized = []
        for value in parsed:
            try:
                normalized.append(float(value))
            except (TypeError, ValueError):
                continue
        return normalized

    async def _maybe_call_callback(self, callback, *args, **kwargs) -> bool:
        if not callback:
            return False
        try:
            if inspect.iscoroutinefunction(callback):
                await callback(*args, **kwargs)
            else:
                result = callback(*args, **kwargs)
                if inspect.isawaitable(result):
                    await result
        except Exception as exc:
            logger.error(f"PriceMonitor callback error: {exc}")
            return False
        return True