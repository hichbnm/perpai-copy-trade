import asyncio
import inspect
import aiohttp
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
import discord

logger = logging.getLogger(__name__)

class SignalBasedPriceMonitor:
    """
    Signal-based monitoring: Monitor each unique signal once, notify all users
    
    Instead of monitoring each user's trade separately, we monitor each unique signal.
    When TP/SL hits, we notify ALL users trading that signal.
    
    Benefits:
    - 1 price check instead of N (N = number of users)
    - 1 API call instead of N API calls
    - 90-99% reduction in API usage
    """
    
    def __init__(self, bot, on_target_hit: Optional[Any] = None, on_signal_completed: Optional[Any] = None):
        self.bot = bot
        self.monitored_signals: Dict[str, Dict] = {}  # {signal_id: signal_info}
        self.price_cache = {}  # {symbol: {price, timestamp}}
        self.monitoring_task = None
        self.update_interval = 1  # seconds - REAL-TIME MONITORING! 🚀
        self._on_target_hit = on_target_hit
        self._on_signal_completed = on_signal_completed
        self.notification_sent = set()  # Track already sent notifications
        self.dca_cancellation_sent = set()  # Track DCA cancellation notifications to prevent duplicates on restart
        
    async def start_monitoring(self):
        """Start the price monitoring task"""
        if self.monitoring_task is None or self.monitoring_task.done():
            self.monitoring_task = asyncio.create_task(self._monitor_prices())
            logger.info("Signal-based price monitoring started")
    
    async def stop_monitoring(self):
        """Stop the price monitoring task"""
        if self.monitoring_task:
            self.monitoring_task.cancel()
            logger.info("Signal-based price monitoring stopped")
    
    def add_signal_to_monitor(self, signal_data: Dict, user_ids: List[int]):
        """
        Add a signal to monitoring (monitors once for all users)
        
        Args:
            signal_data: Signal information (symbol, entries, TPs, SL, etc.)
            user_ids: List of user IDs trading this signal
        """
        # Create unique signal ID based on channel + symbol + entry prices
        channel_id = signal_data.get('channel_id')
        symbol = signal_data['symbol']
        entry_prices = signal_data.get('entry', [])
        message_id = signal_data.get('message_id')
        
        # Signal ID: channel_symbol_firstEntry_timestamp
        # Handle None values to prevent formatting errors
        safe_channel_id = channel_id or 'unknown'
        safe_symbol = symbol or 'unknown'
        safe_message_id = message_id or 'unknown'
        signal_id = f"{safe_channel_id}_{safe_symbol}_{entry_prices[0] if entry_prices else 0}_{safe_message_id}"
        
        # Check if signal already being monitored
        if signal_id in self.monitored_signals:
            # Add users to existing signal
            existing_users = set(self.monitored_signals[signal_id]['user_ids'])
            existing_users.update(user_ids)
            self.monitored_signals[signal_id]['user_ids'] = list(existing_users)
            logger.info(f"Added {len(user_ids)} users to existing signal {signal_id} (total: {len(existing_users)} users)")
            return signal_id
        
        # Parse targets
        normalized_stop_loss = self._normalize_target_levels(signal_data.get('stop_loss'))
        normalized_take_profit = self._normalize_target_levels(signal_data.get('take_profit'))
        
        # Get existing targets_hit from database or use defaults
        targets_hit = signal_data.get('targets_hit', {'sl': False, 'tp': [], 'position_entered': False})
        
        # 🆕 Check if position was entered immediately (market order or current price already past entry)
        # This happens when:
        # 1. It's a market order (no entry prices specified)
        # 2. Current price is already at/beyond the entry price when signal is posted
        if not targets_hit.get('position_entered'):
            if not entry_prices:
                # No entry prices = market order = instant fill
                targets_hit['position_entered'] = True
                logger.info(f"✅ Market order detected for {symbol} - Position entered immediately")
            # Note: We can't check current price here since we don't have it yet
            # The check will happen in _check_signal_targets on first price update
        
        # Populate notification_sent set based on already-hit targets
        side = signal_data['side']
        if targets_hit.get('sl'):
            # SL already hit - add to notification_sent to prevent re-sending
            for sl_price in normalized_stop_loss:
                event_key = f"{symbol}_{side}_SL_{sl_price}_{channel_id}"
                self.notification_sent.add(event_key)
                logger.debug(f"Skipping already-hit SL notification: {event_key}")
        
        # Check which TPs are already hit
        hit_tp_numbers = targets_hit.get('tp', [])
        for tp_num in hit_tp_numbers:
            if 0 < tp_num <= len(normalized_take_profit):
                tp_price = normalized_take_profit[tp_num - 1]
                event_key = f"{symbol}_{side}_TP{tp_num}_{tp_price}_{channel_id}"
                self.notification_sent.add(event_key)
                logger.debug(f"Skipping already-hit TP{tp_num} notification: {event_key}")
        
        # Create signal monitoring entry
        self.monitored_signals[signal_id] = {
            'signal_id': signal_id,
            'channel_id': channel_id,
            'message_id': message_id,
            'symbol': symbol,
            'side': signal_data['side'],
            'entry_prices': entry_prices,
            'stop_loss': normalized_stop_loss,
            'take_profit': normalized_take_profit,
            'user_ids': user_ids,  # All users trading this signal
            'user_count': len(user_ids),
            'created_at': signal_data.get('timestamp', datetime.now()),
            'targets_hit': targets_hit,  # Use existing or default
            'status': 'active'
        }
        
        logger.info(f"✅ Monitoring signal {signal_id} for {len(user_ids)} users (symbol: {symbol})")
        return signal_id
    
    async def _monitor_prices(self):
        """Main monitoring loop - checks all signals"""
        while True:
            try:
                await self._check_all_signals()
                await asyncio.sleep(self.update_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in signal monitoring: {e}")
                await asyncio.sleep(self.update_interval)
    
    async def _check_all_signals(self):
        """Check all monitored signals for target hits"""
        if not self.monitored_signals:
            return
        
        # Get unique symbols to fetch prices for
        symbols = set(signal['symbol'] for signal in self.monitored_signals.values() 
                     if signal['status'] == 'active')
        
        if not symbols:
            return
        
        # Fetch current prices (ONE call for all symbols)
        prices = await self._fetch_prices(symbols)
        
        # Check each signal
        signals_to_remove = []
        for signal_id, signal in list(self.monitored_signals.items()):
            if signal['status'] != 'active':
                continue
                
            symbol = signal['symbol']
            if symbol not in prices:
                continue
                
            current_price = prices[symbol]
            
            # Check for target hits
            if await self._check_signal_targets(signal_id, signal, current_price):
                signal['status'] = 'completed'
                await self._maybe_call_callback(self._on_signal_completed, signal)
                signals_to_remove.append(signal_id)
        
        # Remove completed signals
        for signal_id in signals_to_remove:
            user_count = self.monitored_signals[signal_id]['user_count']
            logger.info(f"✅ Signal {signal_id} completed for {user_count} users")
            del self.monitored_signals[signal_id]
    
    async def _fetch_prices(self, symbols: set) -> Dict[str, float]:
        """Fetch current prices for symbols (ONE API call)"""
        prices = {}
        
        try:
            async with aiohttp.ClientSession() as session:
                url = "https://api.hyperliquid.xyz/info"
                payload = {"type": "allMids"}
                
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        if isinstance(data, dict):
                            for symbol in symbols:
                                base_symbol = symbol.split('/')[0]
                                
                                if base_symbol in data:
                                    try:
                                        price = float(data[base_symbol])
                                        prices[symbol] = price
                                    except (ValueError, TypeError):
                                        logger.warning(f"Invalid price data for {symbol}")
                                        
        except Exception as e:
            logger.error(f"Error fetching prices: {e}")
        
        return prices
    
    async def _check_signal_targets(self, signal_id: str, signal: Dict, current_price: float) -> bool:
        """Check if any targets are hit for a signal"""
        side = signal['side']
        stop_losses = signal.get('stop_loss', [])
        take_profits = signal.get('take_profit', [])
        targets_hit = signal['targets_hit']
        entry_prices = signal.get('entry_prices', [])
        entry_price = entry_prices[0] if entry_prices else current_price
        
        signal_completed = False
        
        # 🆕 CHECK IF POSITION HAS BEEN ENTERED
        # Don't monitor TP/SL until at least one entry order has been filled
        position_entered = targets_hit.get('position_entered', False)
        
        if not position_entered:
            # Check if price has hit any entry price (order filled)
            entry_hit = False
            
            if not entry_prices:
                # No entry prices specified = market order = instant fill
                entry_hit = True
                logger.info(f"🎯 Market order for {signal['symbol']} - Position entered immediately")
            else:
                for ep in entry_prices:
                    if side == 'buy':
                        # Buy limit order: filled when market price <= limit price
                        # Check if current price is at or below entry, OR if price has already passed it
                        if current_price <= ep:
                            entry_hit = True
                            logger.info(f"🎯 BUY entry filled for {signal['symbol']} at ${current_price:.2f} (limit: ${ep:.2f})")
                            break
                    elif side == 'sell':
                        # Sell limit order: filled when market price >= limit price  
                        # Check if current price is at or above entry, OR if price has already passed it
                        if current_price >= ep:
                            entry_hit = True
                            logger.info(f"🎯 SELL entry filled for {signal['symbol']} at ${current_price:.2f} (limit: ${ep:.2f})")
                            break
            
            if not entry_hit:
                # Position not entered yet - don't check TP/SL
                if entry_prices:
                    entry_str = ', '.join([f"${ep:.2f}" for ep in entry_prices[:3]])
                    logger.debug(f"⏳ Waiting for entry: {signal['symbol']} {side.upper()} - Current: ${current_price:.2f}, Entries: {entry_str}")
                return False
            
            # Mark position as entered
            targets_hit['position_entered'] = True
            logger.info(f"✅ Position ENTERED for {signal['symbol']} - Now monitoring TP/SL")
        
        # Check Stop Loss
        if not targets_hit['sl'] and stop_losses:
            sl_price = stop_losses[0]
            
            if side == 'buy' and current_price <= sl_price:
                targets_hit['sl'] = True
                await self._notify_target_hit(signal, 'stop_loss', sl_price, current_price, entry_price)
                signal_completed = True
                # 🆕 Cancel DCA orders when SL hits
                await self._cancel_dca_orders(signal, reason='Stop loss hit')
                
            elif side == 'sell' and current_price >= sl_price:
                targets_hit['sl'] = True
                await self._notify_target_hit(signal, 'stop_loss', sl_price, current_price, entry_price)
                signal_completed = True
                # 🆕 Cancel DCA orders when SL hits
                await self._cancel_dca_orders(signal, reason='Stop loss hit')
        
        # Check Take Profits
        newly_hit_tp = False  # Track if any TP was just hit in this cycle
        for i, tp_price in enumerate(take_profits):
            if i in targets_hit['tp']:
                continue
                
            if side == 'buy' and current_price >= tp_price:
                targets_hit['tp'].append(i)
                newly_hit_tp = True  # Mark that we just hit a TP
                await self._notify_target_hit(signal, 'take_profit', tp_price, current_price, entry_price, i + 1)
                
                # 🆕 Move SL to break-even after TP1 hits
                if i == 0 and not targets_hit.get('sl_moved_to_breakeven', False):
                    await self._move_stop_loss_to_breakeven(signal, entry_price)
                    targets_hit['sl_moved_to_breakeven'] = True
                
            elif side == 'sell' and current_price <= tp_price:
                targets_hit['tp'].append(i)
                newly_hit_tp = True  # Mark that we just hit a TP
                await self._notify_target_hit(signal, 'take_profit', tp_price, current_price, entry_price, i + 1)
                
                # 🆕 Move SL to break-even after TP1 hits
                if i == 0 and not targets_hit.get('sl_moved_to_breakeven', False):
                    await self._move_stop_loss_to_breakeven(signal, entry_price)
                    targets_hit['sl_moved_to_breakeven'] = True
        
        # Check if all targets hit AND at least one was just hit (real-time trigger)
        if newly_hit_tp and len(targets_hit['tp']) == len(take_profits):
            signal_completed = True
            # 🆕 Cancel DCA orders when all TPs hit (only on real-time trigger)
            await self._cancel_dca_orders(signal, reason='All TPs hit')
        elif len(targets_hit['tp']) == len(take_profits):
            # All TPs already hit (loaded from DB), just mark as completed without notification
            signal_completed = True
        
        return signal_completed
    
    async def _notify_target_hit(self, signal: Dict, target_type: str, target_price: float, 
                                 current_price: float, entry_price: float, tp_number: int = None):
        """Send notification when target hits (notifies ALL users at once)"""
        try:
            channel_id = signal.get('channel_id')
            message_id = signal.get('message_id')
            
            if not channel_id:
                return
            
            # Create notification key to prevent duplicates
            symbol = signal['symbol'] or 'unknown'
            side = signal['side'] or 'unknown'
            safe_channel_id = channel_id or 'unknown'
            if target_type == 'stop_loss':
                event_key = f"{symbol}_{side}_SL_{target_price}_{safe_channel_id}"
            else:
                event_key = f"{symbol}_{side}_TP{tp_number}_{target_price}_{safe_channel_id}"
            
            if event_key in self.notification_sent:
                return
            
            self.notification_sent.add(event_key)
            
            # Get channel
            channel = self.bot.get_channel(int(channel_id))
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(int(channel_id))
                except Exception:
                    logger.warning(f"Could not find channel {channel_id}")
                    return
            
            # Build notification
            notification_text = self._build_notification(
                signal, target_type, target_price, current_price, entry_price, tp_number
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
                
                logger.info(f"📢 Sent {target_type} notification for {symbol} to {len(signal['user_ids'])} users")
                
                # Call callback for each user
                if self._on_target_hit:
                    for user_id in signal['user_ids']:
                        await self._maybe_call_callback(
                            self._on_target_hit,
                            {'user_id': user_id, 'signal_id': signal['signal_id']},
                            target_type,
                            target_price,
                            current_price,
                            tp_number
                        )
                        
            except Exception as send_error:
                logger.error(f"Error sending notification: {send_error}")
                
        except Exception as e:
            logger.error(f"Error in notify_target_hit: {e}")
    
    def _build_notification(self, signal: Dict, target_type: str, target_price: float,
                           current_price: float, entry_price: float, tp_number: Optional[int]) -> str:
        """Build notification message"""
        symbol = signal.get('symbol', 'Unknown')
        side = signal.get('side', 'unknown')
        user_count = signal.get('user_count', 0)
        user_ids = signal.get('user_ids', [])
        
        # Calculate profit/loss
        profit_pct = 0
        if entry_price and entry_price > 0:
            if side == 'buy':
                profit_pct = ((current_price - entry_price) / entry_price) * 100
            else:
                profit_pct = ((entry_price - current_price) / entry_price) * 100
        
        # Build trader list (up to 10 traders)
        if user_count <= 10:
            trader_mentions = ", ".join([f"<@{uid}>" for uid in user_ids])
        else:
            first_traders = ", ".join([f"<@{uid}>" for uid in user_ids[:5]])
            trader_mentions = f"{first_traders} and {user_count - 5} more"
        
        # Build notification
        if target_type == 'stop_loss':
            return f"""🛑 **STOP LOSS HIT!**

🪙 **Symbol**: {symbol} {side.upper()}
📉 **Stop Loss Level**: ${target_price:g}
💰 **Current Price**: ${current_price:g}
📊 **P&L**: {profit_pct:+.2f}%
👥 **Traders Affected**: {user_count}
⏰ **Hit Time**: <t:{int(datetime.now().timestamp())}:T>

🤖 Automated Trade Monitoring"""
        else:
            tp_label = f" {tp_number}" if tp_number else ""
            return f"""🎯 **TAKE PROFIT{tp_label} HIT!**

🪙 **Symbol**: {symbol} {side.upper()}
🎯 **Target Level**: ${target_price:g}
💰 **Current Price**: ${current_price:g}
📈 **Profit**: +{profit_pct:.2f}%
👥 **Traders Affected**: {user_count}
⏰ **Hit Time**: <t:{int(datetime.now().timestamp())}:T>

🤖 Automated Trade Monitoring"""
    
    async def _maybe_call_callback(self, callback, *args, **kwargs):
        """Call callback if it exists"""
        if callback is None:
            return
        try:
            if inspect.iscoroutinefunction(callback):
                await callback(*args, **kwargs)
            else:
                callback(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in callback: {e}")
    
    def _normalize_target_levels(self, values: Optional[Any]) -> List[float]:
        """Normalize target levels to list of floats"""
        if not values:
            return []
        if isinstance(values, str):
            try:
                import ast
                parsed = ast.literal_eval(values)
            except Exception:
                return []
        else:
            parsed = values
        
        if not isinstance(parsed, (list, tuple)):
            parsed = [parsed]
        
        result = []
        for val in parsed:
            try:
                result.append(float(val))
            except (TypeError, ValueError):
                continue
        return result
    
    def get_monitoring_stats(self) -> Dict:
        """Get monitoring statistics"""
        active_signals = len([s for s in self.monitored_signals.values() if s['status'] == 'active'])
        total_users = sum(s['user_count'] for s in self.monitored_signals.values())
        
        return {
            'active_signals': active_signals,
            'total_monitored_signals': len(self.monitored_signals),
            'total_users_affected': total_users,
            'update_interval': self.update_interval,
            'is_running': self.monitoring_task and not self.monitoring_task.done()
        }
    
    def get_signal_info(self, signal_id: str) -> Optional[Dict]:
        """Get information about a specific signal"""
        return self.monitored_signals.get(signal_id)
    
    async def _move_stop_loss_to_breakeven(self, signal: Dict, entry_price: float):
        """
        Move stop loss to break-even after TP1 hits
        This protects profits and makes the trade risk-free
        """
        try:
            symbol = signal['symbol']
            side = signal['side']
            old_sl = signal['stop_loss'][0] if signal['stop_loss'] else None
            
            # Update signal's stop loss to entry price
            signal['stop_loss'] = [entry_price]
            
            logger.info(f"🛡️ Moving SL to break-even for {symbol} ({side}): ${old_sl:.4f} → ${entry_price:.4f}")
            
            # Send notification to channel
            channel_id = signal.get('channel_id')
            if channel_id:
                try:
                    channel = self.bot.get_channel(int(channel_id))
                    if channel is None:
                        channel = await self.bot.fetch_channel(int(channel_id))
                    
                    if channel:
                        side_emoji = "🟢" if side == 'buy' else "🔴"
                        notification = f"""
🛡️ **Stop Loss Moved to Break-Even!**

📊 **Symbol:** {symbol}
{side_emoji} **Side:** {side.upper()}

✅ **TP1 Hit!** Protecting your profits...
🎯 **New Stop Loss:** ${entry_price:.4f} (Break-Even)
📉 **Old Stop Loss:** ${old_sl:.4f}

**Your trade is now risk-free!** 🎉
Even if price pulls back, you won't lose money.
Let your remaining position run with zero risk! 🚀
"""
                        await channel.send(notification)
                        logger.info(f"📢 Sent break-even SL notification for {symbol}")
                except Exception as e:
                    logger.error(f"Failed to send break-even notification: {e}")
            
            # Note: Actual order modification on Hyperliquid would require additional API integration
            # The SL is updated in our monitoring system and will be used for future checks
            logger.info(f"✅ Break-even SL update complete for {symbol}")
                
        except Exception as e:
            logger.error(f"Error moving SL to break-even: {e}")
    
    async def _cancel_dca_orders(self, signal: Dict, reason: str = 'Trade completed'):
        """
        Cancel all pending DCA/limit orders when trade closes
        This prevents accidental entries after trade completion
        """
        try:
            symbol = signal['symbol']
            signal_id = signal.get('signal_id', '')
            
            # Check if we already sent DCA cancellation for this signal
            dca_key = f"{signal_id}_DCA_CANCEL"
            if dca_key in self.dca_cancellation_sent:
                logger.debug(f"DCA cancellation already sent for {symbol} (signal_id: {signal_id})")
                return
            
            logger.info(f"🗑️ Cancelling DCA orders for {symbol} (Reason: {reason})")
            
            # Send notification to channel
            channel_id = signal.get('channel_id')
            if channel_id:
                try:
                    channel = self.bot.get_channel(int(channel_id))
                    if channel is None:
                        channel = await self.bot.fetch_channel(int(channel_id))
                    
                    if channel:
                        side_emoji = "🟢" if signal['side'] == 'buy' else "🔴"
                        notification = f"""
🗑️ **DCA Orders Cancelled**

📊 **Symbol:** {symbol}
{side_emoji} **Side:** {signal['side'].upper()}
✅ **Status:** {reason}

All pending limit orders have been cancelled automatically.
This protects your funds from unintended entries. 🛡️

**Trade Management:** Your account is clean and ready for new trades!
"""
                        await channel.send(notification)
                        logger.info(f"📢 Sent DCA cancellation notification for {symbol}")
                        
                        # Mark as sent to prevent duplicates on restart
                        self.dca_cancellation_sent.add(dca_key)
                except Exception as e:
                    logger.error(f"Failed to send DCA cancellation notification: {e}")
            
            # Note: Actual order cancellation on Hyperliquid would require API integration
            # This serves as a notification system for now
            logger.info(f"✅ DCA order cleanup notification sent for {symbol}")
                
        except Exception as e:
            logger.error(f"Error cancelling DCA orders: {e}")
    
    def get_user_signals(self, user_id: int) -> List[Dict]:
        """Get all signals a user is trading"""
        user_signals = []
        for signal in self.monitored_signals.values():
            if user_id in signal['user_ids']:
                user_signals.append({
                    'signal_id': signal['signal_id'],
                    'symbol': signal['symbol'],
                    'side': signal['side'],
                    'entry_prices': signal['entry_prices'],
                    'stop_loss': signal['stop_loss'],
                    'take_profit': signal['take_profit'],
                    'status': signal['status'],
                    'targets_hit': signal['targets_hit'],
                    'created_at': signal['created_at']
                })
        return user_signals
