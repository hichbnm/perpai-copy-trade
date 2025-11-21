import discord
from discord.ext import commands
import asyncio
import logging
import os
from typing import Dict
from database.db_manager import DatabaseManager
from signal_parser.parser import SignalParser
from connectors.hyperliquid_connector import HyperliquidConnector
from connectors.bybit_connector import BybitConnector
from commands.trading_commands import TradingCommands
from ui.clean_ui import CleanUICommands
from price_monitor.signal_service import SignalBasedTradeService
from config import Config

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TradingBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=Config.COMMAND_PREFIX, intents=intents)
        
        # Initialize PostgreSQL Database Connection
        self.db = DatabaseManager(
            database_url=Config.DATABASE_URL
        )
        self.signal_parser = SignalParser()
        self.connectors = {
            'hyperliquid': HyperliquidConnector(),
            'bybit': BybitConnector(),
            # Add new exchanges here:
            # 'binance': BinanceConnector(),
            # 'okx': OKXConnector(),
        }
        self.trade_monitor = SignalBasedTradeService(self, self.db)
        
    async def setup_hook(self):
        """Setup hook called when bot is starting"""
        await self.add_cog(TradingCommands(self))
        await self.add_cog(CleanUICommands(self))
        
        # Register persistent views for the dashboard
        from ui.clean_ui import PermanentDashboardView
        self.add_view(PermanentDashboardView(self))
        
    async def on_ready(self):
        logger.info(f'{self.user} has connected to Discord!')
        # Sync ALL commands on startup (not just admin commands)
        await self.sync_commands()
        
        # Start trade monitoring service
        try:
            await self.trade_monitor.start()
            logger.info("Trade monitoring service started successfully")
        except Exception as e:
            logger.error(f"Failed to start trade monitoring: {e}")
        
        # Update bot status
        activity = discord.Activity(type=discord.ActivityType.watching, name="for trading signals | /dashboard")
        await self.change_presence(activity=activity)
        
    async def sync_admin_commands_only(self):
        """Sync only admin control commands"""
        try:
            # Clear everything first
            self.tree.clear_commands(guild=None)
            
            # Manually register only admin commands
            @self.tree.command(name="sync_commands", description="Show all bot commands in autocomplete (Admin only)")
            async def sync_cmd(interaction):
                if not interaction.user.guild_permissions.administrator:
                    await interaction.response.send_message("❌ Admin only", ephemeral=True)
                    return
                await interaction.response.defer(ephemeral=True)
                await self.sync_commands()
                await interaction.followup.send("✅ All commands are now visible in autocomplete!", ephemeral=True)
            
            @self.tree.command(name="hide_commands", description="Hide bot commands from autocomplete (Admin only)")  
            async def hide_cmd(interaction):
                if not interaction.user.guild_permissions.administrator:
                    await interaction.response.send_message("❌ Admin only", ephemeral=True)
                    return
                await interaction.response.defer(ephemeral=True)
                await self.sync_admin_commands_only()
                await interaction.followup.send("✅ User commands hidden. Only admin commands visible.", ephemeral=True)
            
            await self.tree.sync()
            logger.info("Admin commands synced: /sync_commands and /hide_commands")
        except Exception as e:
            logger.error(f"Failed to sync admin commands: {e}")

    async def sync_commands(self):
        """Sync all commands - makes them appear in autocomplete"""
        try:
            # Just sync the command tree - cogs are already loaded
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} command(s) - they will now appear in autocomplete")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")
    
    async def clear_commands(self):
        """Clear all synced commands - removes them from autocomplete"""
        try:
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            logger.info("All commands cleared from autocomplete")
        except Exception as e:
            logger.error(f"Failed to clear commands: {e}")

    async def on_message(self, message):
        if message.author == self.user:
            return
            
        # Check if message is in a monitored channel
        # Convert channel ID to string for database lookup
        channel_id_str = str(message.channel.id)
        is_signal_channel = self.db.is_signal_channel(channel_id_str)
        
        # Get channel name safely (DMs don't have a name attribute)
        channel_name = getattr(message.channel, 'name', f'DM-{message.channel.id}')
        logger.debug(f"Channel {channel_name} (ID: {channel_id_str}) - Is signal channel: {is_signal_channel}")
        
        if is_signal_channel:
            await self.process_signal(message)
        else:
            # Auto-register channels that post signals (for convenience)
            # But only if they have potential subscribers or are explicitly marked as signal channels
            signals = self.signal_parser.parse_signal(message.content)
            if signals:
                # Check if there are any users in this channel before auto-registering
                users = self.db.get_channel_users(channel_id_str)
                if users:
                    logger.info(f"Auto-registering channel {message.channel.name} as signal channel ({len(users)} subscribers)")
                    self.db.add_channel(channel_id_str, message.channel.name)
                    await self.process_signal(message)
                else:
                    logger.info(f"⏩ Skipping auto-registration of channel {message.channel.name} - No subscribers found")
            
        await self.process_commands(message)
        
    async def process_signal(self, message):
        try:
            # Convert channel ID to string for database lookup
            channel_id_str = str(message.channel.id)
            
            # Check if channel has any subscribers before processing signals
            users = self.db.get_channel_users(channel_id_str)
            if not users:
                logger.info(f"⏩ Skipping signal detection in channel {message.channel.name} (ID: {channel_id_str}) - No subscribers")
                return
            
            signals = self.signal_parser.parse_signal(message.content)
            if not signals:
                return
            
            logger.info(f"Signals detected: {len(signals)} signals from channel with {len(users)} subscribers")
            
            # Add reactions and send initial confirmation
            try:
                await message.add_reaction("✅")
            except discord.Forbidden:
                logger.warning(f"Cannot add reaction to message in {message.channel.name} - missing permissions")
            except Exception as reaction_error:
                logger.warning(f"Failed to add success reaction: {reaction_error}")
            
            # Send initial processing message
            # Note: channel_id_str already set above when checking for subscribers
            
            try:
                confirmation_msg = await message.reply(self._format_signals_message(signals, "Processing trades...", channel_id=channel_id_str))
                logger.info(f"Initial confirmation sent successfully - Message ID: {confirmation_msg.id}")
            except Exception as msg_error:
                logger.error(f"Cannot send initial message: {msg_error}")
                return
            
            # Execute trades for all signals
            total_results = {'successful': 0, 'failed': 0, 'total': 0, 'errors': []}
            
            for signal in signals:
                trade_results = await self.execute_trades(signal, channel_id_str, message)
                total_results['successful'] += trade_results['successful']
                total_results['failed'] += trade_results['failed']
                total_results['total'] += trade_results['total']
                total_results['errors'].extend(trade_results['errors'])
            
            # Determine final status and additional lines
            symbol_errors = [err for err in total_results['errors'] if 'Symbol' in err and 'not available' in err]
            balance_errors = [err for err in total_results['errors'] if 'Balance' in err or 'balance' in err]
            other_errors = [err for err in total_results['errors'] if err not in symbol_errors + balance_errors]
            
            final_status = "⚙️ Processing complete"
            additional_lines = []
            private_errors = []

            if total_results['total'] == 0:
                final_status = "⚠️ No subscribed users found"
                additional_lines = [
                    "💡 Add subscribers using `/subscribe` to enable automated execution."
                ]
            elif total_results['successful'] == 0 and len(symbol_errors) > 0:
                # Extract the symbol name from the first signal
                failed_symbol = signals[0]['symbol'] if signals else 'Unknown'
                final_status = f"❌ **{failed_symbol}** is not available on your exchange"
                
                # Try to extract similar symbols from error messages
                similar_symbols = []
                for error in symbol_errors:
                    if 'Similar symbols available:' in error:
                        try:
                            similar_part = error.split('Similar symbols available:')[1].split('\n')[0].strip()
                            similar_symbols.extend([s.strip() for s in similar_part.split(',')])
                        except:
                            pass
                
                additional_lines = []
                additional_lines.append("")
                additional_lines.append("🚫 **This coin cannot be traded on your exchange**")
                additional_lines.append("🔍 Use `/symbols` to view all supported markets")
                additional_lines.append("💡 Check if the symbol name is correct")
                
                if similar_symbols:
                    similar_text = ', '.join(similar_symbols[:5])
                    additional_lines.append("")
                    additional_lines.append(f"🔎 **Similar symbols found**: {similar_text}")
                
                additional_lines.append("")
                additional_lines.append("📋 **Popular Available Symbols**:")
                additional_lines.append("• BTC, ETH, SOL, ARB, AVAX, MATIC, DOGE")
                additional_lines.append("• LINK, UNI, AAVE, APT, SUI, SEI, INJ")
                additional_lines.append("")
                additional_lines.append("💌 Users were notified privately with detailed information.")
                
                private_errors = balance_errors + other_errors

                private_errors = balance_errors + other_errors
            elif total_results['successful'] == 0:
                final_status = "⚠️ All trades failed for subscribed users"
                additional_lines = [
                    "💌 Detailed failure reasons were sent privately to each user.",
                    "🧠 Common causes: insufficient balance or configuration issues."
                ]
                private_errors = total_results['errors']
            elif total_results['failed'] == 0:
                trade_mode_emoji = "🔴 LIVE" if total_results.get('live_trades') else "🔵 SIMULATED"
                final_status = f"✅ {total_results['successful']} {trade_mode_emoji} trades executed successfully"
                additional_lines = [
                    "🔍 Real-time monitoring is active for all positions.",
                    "📊 Use `/dashboard` to review live status."
                ]
            else:
                trade_mode_emoji = "🔴 LIVE" if total_results.get('live_trades') else "🔵 SIMULATED"
                final_status = (
                    f"⚠️ {total_results['successful']} {trade_mode_emoji} trades executed, {total_results['failed']} failed"
                )
                additional_lines = [
                    "💌 Users with issues received private notifications.",
                    "📊 Monitoring continues for successful executions."
                ]
                private_errors = total_results['errors']

            if private_errors:
                await self.send_private_errors(private_errors, message.channel.id)

            final_message = self._format_signals_message(signals, final_status, additional_lines, channel_id=channel_id_str)

            try:
                await confirmation_msg.edit(content=final_message)
            except Exception as edit_error:
                logger.error(f"Error editing confirmation message: {edit_error}")
                await message.reply(final_message)

            logger.info(
                f"Trade completion message updated - {total_results['successful']}/{total_results['total']} successful"
            )
        except Exception as e:
            logger.error(f"Error processing signal: {e}")
            try:
                await message.reply("❌ Error processing trading signal. Please check the format and try again.")
            except Exception as error_msg_error:
                logger.error(f"Cannot send error message: {error_msg_error}")
                
        except Exception as e:
            logger.error(f"Error processing signal: {e}")
            try:
                await message.add_reaction("❌")
            except discord.Forbidden:
                logger.warning(f"Cannot add error reaction to message in {message.channel.name} - missing permissions")
            except Exception as reaction_error:
                logger.warning(f"Failed to add error reaction: {reaction_error}")
            
            # Send error message
            try:
                error_text = "❌ **SIGNAL PROCESSING ERROR**\n\nFailed to process the trading signal. Please check the format and try again."
                await message.reply(error_text, delete_after=15)
            except Exception as error_msg_error:
                logger.error(f"Cannot send error message: {error_msg_error}")
    
    def _format_signals_message(self, signals, status_text, extra_lines=None, channel_id=None):
        """Format message for multiple signals"""
        lines = ["📈 **TRADING SIGNALS DETECTED**", ""]
        
        for i, signal in enumerate(signals, 1):
            side_emoji = "🟢" if signal['side'] == 'buy' else "🔴"
            entry_values = signal.get('entry') or []
            # Show exact values without rounding
            entry_text = ', '.join([
                f"${p:g}" for p in entry_values
            ]) if entry_values else 'Market'
            
            stop_values = signal.get('stop_loss') or []
            stop_text = ', '.join([
                f"${p:g}" for p in stop_values
            ]) if stop_values else 'None'
            
            take_values = signal.get('take_profit') or []
            take_text = ', '.join([
                f"${p:g}" for p in take_values
            ]) if take_values else 'None'
            
            leverage_text = f"{signal.get('leverage')}x" if signal.get('leverage') else 'Not specified'
            
            lines.extend([
                f"**Signal {i}:**",
                f"🪙 **Symbol**: {signal.get('symbol', 'Unknown')}",
                f"{side_emoji} **Direction**: {signal.get('side', 'Unknown').upper()}",
                f"📍 **Entry**: {entry_text}",
                f"🛑 **Stop Loss**: {stop_text}",
                f"🎯 **Take Profit**: {take_text}",
                f"⚡ **Leverage**: {leverage_text}",
                ""
            ])
        
        lines.append(f"⚡ **Status**: {status_text}")
        
        if extra_lines:
            lines.append("")
            lines.extend(extra_lines)
        
        # Get subscriber count using the provided channel_id
        if channel_id:
            users = self.db.get_channel_users(channel_id)
            logger.info(f"Subscriber count for channel {channel_id}: {len(users)}")
        else:
            # Fallback: try to get from signal or use 0
            users = self.db.get_channel_users(signals[0].get('channel_id', '0')) if signals else []
            logger.warning(f"No channel_id provided to _format_signals_message, using fallback")
        
        lines.append("")
        lines.append(f"👥 **Subscribers**: {len(users)}")
        lines.append("")
        lines.append("🤖 Multiple signals processed")
        
        return "\n".join(lines)
    
    async def execute_trades(self, signal, channel_id, message=None):
        # Ensure channel_id is string for database lookup
        channel_id_str = str(channel_id)
        users = self.db.get_channel_users(channel_id_str)
        successful_trades = 0
        failed_trades = 0
        trade_errors = []
        live_trades = False
        user_mappings = []  # For signal-based monitoring
        
        logger.info(f"Executing trades for {len(users)} subscribed users in channel {channel_id_str} (type: {type(channel_id_str)})")
        
        if not users:
            logger.warning(f"No subscribed users found for channel {channel_id_str} (type: {type(channel_id_str)})")
            return {
                'successful': 0,
                'failed': 0,
                'errors': ["No users subscribed to this channel"],
                'total': 0
            }
        
        for user in users:
            user_id = user['user_id']
            exchange = user['exchange']
            
            # Check if user is banned
            if self.db.is_user_banned(user_id):
                logger.info(f"Skipping banned user {user_id}")
                continue
            
            try:
                connector = self.connectors.get(exchange)
                if not connector:
                    failed_trades += 1
                    error_msg = f"Exchange '{exchange}' connector not available"
                    trade_errors.append(f"User {user_id}: {error_msg}")
                    logger.error(f"No connector for exchange '{exchange}' - user {user_id}")
                    continue
                
                # ALWAYS attempt to execute the trade
                logger.info(f"Attempting trade execution for user {user_id} on {exchange}")
                result = await connector.execute_trade(user, signal)
                
                # Check if trade was successful
                if result.get('success', False):
                    # Log successful trades with mode indication
                    trade_mode = "🔴 LIVE" if result.get('live') else "🔵 SIMULATED"
                    logger.info(f"✅ Trade successfully executed for user {user_id} on {exchange} ({trade_mode})")
                    
                    # Log successful trades and get DB ID
                    db_trade_id = self.db.log_trade(
                        user_id, 
                        exchange, 
                        signal['symbol'], 
                        signal['side'],
                        user['position_size'],
                        signal.get('entry', [None])[0] if signal.get('entry') else None,
                        str(signal),
                        channel_id_str,  # Add channel_id
                        str(message.id) if message else None  # Add message_id
                    )
                    
                    # Add to user mappings for signal-based monitoring
                    user_mappings.append({
                        'user_id': user_id,
                        'size': user['position_size'],
                        'db_trade_id': db_trade_id,
                        'exchange': exchange,
                        'api_key': user.get('api_key'),
                        'api_secret': user.get('api_secret'),
                        'testnet': user.get('testnet', False)
                    })
                    
                    successful_trades += 1
                    
                    # Check if this was a live trade
                    if result.get('live'):
                        live_trades = True
                    
                    # Send private DM notification to user
                    await self._send_trade_execution_dm(user_id, signal, result, exchange, trade_mode)
                    
                    # Log successful trades with mode indication
                    logger.info(f"✅ Trade successfully executed for user {user_id} on {exchange} ({trade_mode})")
                else:
                    # Trade failed - log the detailed error
                    failed_trades += 1
                    error_msg = result.get('error', 'Unknown error')
                    trade_errors.append(f"User {user_id}: {error_msg}")
                    
                    # Log different types of failures
                    if 'balance' in error_msg.lower():
                        logger.warning(f"💰 Balance issue for user {user_id}: {error_msg}")
                    elif 'symbol' in error_msg.lower():
                        logger.warning(f"🔍 Symbol issue for user {user_id}: {error_msg}")
                    else:
                        logger.warning(f"⚠️ Trade failed for user {user_id}: {error_msg}")
                        
            except Exception as e:
                failed_trades += 1
                error_msg = f"System error: {str(e)}"
                trade_errors.append(f"User {user_id}: {error_msg}")
                logger.error(f"❌ Exception during trade execution for user {user_id}: {e}")
        
        # Add signal to monitoring (ONE time for ALL users)
        if user_mappings:
            signal_data = {
                'channel_id': channel_id,
                'message_id': message.id if message else None,
                'symbol': signal['symbol'],
                'side': signal['side'],
                'entry': signal.get('entry', []),
                'stop_loss': signal.get('stop_loss', []),
                'take_profit': signal.get('take_profit', []),
                'timestamp': message.created_at if message else None
            }
            await self.trade_monitor.add_trades_from_signal(signal_data, user_mappings)
            logger.info(f"📊 Signal monitoring: 1 signal for {len(user_mappings)} users (saved {len(user_mappings)-1} API calls)")
        
        logger.info(f"Trade execution complete: {successful_trades}/{len(users)} successful")
        
        return {
            'successful': successful_trades,
            'failed': failed_trades,
            'errors': trade_errors,
            'total': len(users),
            'live_trades': live_trades
        }
    
    async def _send_trade_execution_dm(self, user_id: int, signal: Dict, result: Dict, exchange: str, trade_mode: str):
        """Send private DM notification when trade is executed"""
        try:
            # Fetch Discord user
            discord_user = self.get_user(int(user_id))
            if not discord_user:
                try:
                    discord_user = await self.fetch_user(int(user_id))
                except Exception as fetch_error:
                    logger.warning(f"⚠️ Cannot fetch user {user_id} for trade notification: {fetch_error}")
                    return
            
            # Extract trade details
            symbol = signal.get('symbol', 'Unknown')
            side = signal.get('side', 'unknown').upper()
            
            # Get entry price
            entry_values = signal.get('entry', [])
            if entry_values:
                entry_price = entry_values[0] if isinstance(entry_values, list) else entry_values
            else:
                entry_price = result.get('price', 0)
            
            # Get quantity/size from result
            quantity = result.get('quantity', 0)
            position_value = result.get('position_size', 0)
            
            # Get leverage
            leverage = signal.get('leverage', 1)
            
            # Get TP/SL
            take_profits = signal.get('take_profit', [])
            stop_losses = signal.get('stop_loss', [])
            
            tp_text = ', '.join([f"${tp:.2f}" for tp in take_profits]) if take_profits else 'None'
            sl_text = f"${stop_losses[0]:.2f}" if stop_losses else 'None'
            
            # Side emoji
            side_emoji = "🟢" if side == 'BUY' else "🔴"
            
            # Build notification
            dm_notification = (
                f"✅ **YOUR TRADE EXECUTED** {trade_mode}\n\n"
                f"{side_emoji} **{symbol}** {side}\n"
                f"💰 Entry Price: **${entry_price:.2f}**\n"
                f"📊 Quantity: **{quantity:.6f}**\n"
            )
            
            if position_value > 0:
                dm_notification += f"💵 Position Value: **${position_value:.2f}**\n"
            
            dm_notification += (
                f"⚡ Leverage: **{leverage}x**\n"
                f"🎯 Take Profits: {tp_text}\n"
                f"🛑 Stop Loss: {sl_text}\n"
                f"🏦 Exchange: **{exchange.capitalize()}**\n\n"
                f"📡 Your position is now being monitored...\n"
                f"💬 You'll receive DMs when TP/SL hits!\n\n"
                f"📊 Use `/dashboard` to view all your trades"
            )
            
            # Send DM
            try:
                await discord_user.send(dm_notification)
                logger.info(f"✅ Sent trade execution notification to user {user_id}")
            except discord.Forbidden:
                logger.warning(f"⚠️ Cannot send DM to user {user_id} (DMs disabled)")
            except Exception as dm_error:
                logger.error(f"❌ Failed to send trade notification DM to user {user_id}: {dm_error}")
                
        except Exception as e:
            logger.error(f"❌ Error in _send_trade_execution_dm: {e}", exc_info=True)
    
    async def send_private_errors(self, errors, channel_id):
        """Send private error messages to users"""
        if not errors:
            return
            
        users = self.db.get_channel_users(channel_id)
        user_dict = {str(user['user_id']): user for user in users}
        
        for error in errors:
            try:
                # Extract user ID from error message format: "User 123456: error message"
                if ': ' in error:
                    user_id_str = error.split(': ')[0].replace('User ', '')
                    error_msg = error.split(': ', 1)[1]
                    
                    if user_id_str in user_dict:
                        user_id = int(user_id_str)
                        discord_user = self.get_user(user_id)
                        
                        # If not in cache, try fetching from Discord API
                        if not discord_user:
                            try:
                                discord_user = await self.fetch_user(user_id)
                            except discord.NotFound:
                                logger.warning(f"User {user_id} not found on Discord")
                                continue
                            except Exception as fetch_error:
                                logger.error(f"Failed to fetch user {user_id}: {fetch_error}")
                                continue
                        
                        # Send private notification to user
                        try:
                            # Skip certain technical errors that users don't need to see
                            skip_errors = [
                                "asset ",
                                  # Internal exchange error code
                            ]
                            
                            # Check if this error should be skipped
                            should_skip = any(skip_phrase in error_msg.lower() for skip_phrase in skip_errors)
                            
                            if should_skip:
                                logger.info(f"⏭️ Skipping internal error notification for user {user_id}: {error_msg[:50]}...")
                                continue
                            
                            # Format error message based on type
                            if "Symbol Not Available" in error_msg or "not available" in error_msg.lower():
                                notification = (
                                    "🚫 **Trade Failed: Symbol Not Available**\n\n"
                                    f"{error_msg}\n\n"
                                    "💡 **What you can do:**\n"
                                    "• Use `/symbols` to view all available symbols on your exchange\n"
                                    "• Check if the symbol name is correct\n"
                                    "• Contact support if you believe this is an error"
                                )
                            elif "Insufficient Balance" in error_msg or "balance" in error_msg.lower():
                                notification = (
                                    "💰 **Trade Failed: Insufficient Balance**\n\n"
                                    f"{error_msg}\n\n"
                                    "💡 **What you can do:**\n"
                                    "• Check your balance with `/balance`\n"
                                    "• Deposit more funds to your exchange account\n"
                                    "• Adjust your position size settings in `/settings`"
                                )
                            else:
                                notification = (
                                    "⚠️ **Trade Execution Failed**\n\n"
                                    f"{error_msg}\n\n"
                                    "💡 Check `/dashboard` for more details or contact support."
                                )
                            
                            await discord_user.send(notification)
                            logger.info(f"✅ Sent error notification to user {user_id}")
                        except discord.Forbidden:
                            logger.warning(f"Cannot send DM to user {user_id} (DMs disabled)")
                        except Exception as dm_error:
                            logger.error(f"Failed to send DM to user {user_id}: {dm_error}")
                    else:
                        logger.warning(f"User {user_id_str} not found in channel users")
                else:
                    logger.warning(f"Invalid error format: {error}")
                    
            except Exception as e:
                logger.error(f"Error processing private error notification: {e}")

async def main():
    if not Config.DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN not found in environment variables!")
        logger.error("Please copy .env.example to .env and add your Discord bot token")
        return
    
    bot = TradingBot()
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            logger.info(f"Starting bot (attempt {retry_count + 1}/{max_retries})")
            await bot.start(Config.DISCORD_TOKEN)
            break  # If successful, break out of the loop
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
            break
        except Exception as e:
            retry_count += 1
            logger.error(f"Bot failed to start (attempt {retry_count}): {e}")
            if retry_count < max_retries:
                logger.info(f"Retrying in 5 seconds...")
                await asyncio.sleep(5)
            else:
                logger.error("Max retries reached. Bot shutting down.")
    
    # Cleanup
    if not bot.is_closed():
        try:
            logger.info("Stopping trade monitoring service...")
            await bot.trade_monitor.stop()
            logger.info("Trade monitoring service stopped")
        except Exception as e:
            logger.error(f"Error stopping trade monitoring: {e}")
        
        try:
            logger.info("Closing bot connection...")
            await bot.close()
            logger.info("Bot connection closed")
        except Exception as e:
            logger.error(f"Error closing bot: {e}")
    
    # Give time for pending tasks to complete
    await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        # Ensure all asyncio tasks are cancelled
        try:
            pending = asyncio.all_tasks()
            for task in pending:
                task.cancel()
        except:
            pass