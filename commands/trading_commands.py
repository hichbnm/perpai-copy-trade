import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import logging
from functools import wraps

logger = logging.getLogger(__name__)

def require_api_key(func):
    """Decorator to ensure user has API key before accessing trading commands"""
    @wraps(func)
    async def wrapper(self, interaction: discord.Interaction, *args, **kwargs):
        # Check if user is banned
        user_id = str(interaction.user.id)
        
        # Add user to database if not exists
        self.bot.db.add_user(user_id, interaction.user.name)
        
        # Check ban status first
        if self.bot.db.is_user_banned(user_id):
            banned_text = """🚫 **ACCESS DENIED**

❌ **Your account has been banned**

You cannot use this bot. If you believe this is a mistake, please contact the administrator.

📧 For appeals, contact server staff."""
            
            await interaction.response.send_message(banned_text, ephemeral=True)
            return
        
        # Check for API keys using DatabaseManager
        api_keys = self.bot.db.get_user_all_api_keys(user_id)
        
        if not api_keys:
            # No API key found - show setup message
            setup_text = """🔒 **API KEY REQUIRED**

❌ **Access Denied**: You need to add your API key first

🛠️ **Setup Steps**:
1️⃣ Use `/add_api_key` command
2️⃣ Enter your exchange credentials
3️⃣ All other features will be unlocked

🔐 **Supported Exchanges**:
• Hyperliquid (Mainnet Only)
• Bybit (Mainnet & Testnet)
• Binance Futures (Mainnet & Testnet)
• OKX Perpetuals (Mainnet & Demo)

💡 **Why Required?**
API keys are needed to execute trades on your behalf. Your credentials are encrypted and stored securely.

✅ **Get Started**: 
`/add_api_key exchange:hyperliquid api_key:YOUR_WALLET api_secret:YOUR_PRIVATE_KEY`
`/add_api_key exchange:bybit api_key:YOUR_API_KEY api_secret:YOUR_API_SECRET`
`/add_api_key exchange:binance api_key:YOUR_API_KEY api_secret:YOUR_API_SECRET`
`/add_api_key exchange:okx api_key:YOUR_API_KEY api_secret:YOUR_API_SECRET passphrase:YOUR_PASSPHRASE`"""
            
            await interaction.response.send_message(setup_text, ephemeral=True)
            return
        
        # API key exists, proceed with original function
        return await func(self, interaction, *args, **kwargs)
    
    return wrapper

# Import the permanent dashboard view
from ui.clean_ui import PermanentDashboardView

class TradingCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="add_api_key", description="Add your API key for trading")
    @app_commands.describe(
        exchange="The exchange name (hyperliquid, bybit, binance, okx)",
        api_key="Your API key or wallet address",
        api_secret="Your API secret or private key",
        passphrase="API passphrase (OKX only)"
    )
    async def add_api_key(self, interaction: discord.Interaction, exchange: str, 
                          api_key: str, api_secret: str, passphrase: str = None):
        try:
            # Add user to database
            user_id = str(interaction.user.id)
            self.bot.db.add_user(user_id, interaction.user.name)
            
            # Force mainnet for both Hyperliquid and Bybit
            testnet = False
            
            # Check if user is banned
            if self.bot.db.is_user_banned(user_id):
                banned_embed = discord.Embed(
                    title="🚫 ACCESS DENIED",
                    description="❌ **Your account has been banned**\n\nYou cannot use this bot. If you believe this is a mistake, please contact the administrator.",
                    color=0xff0000
                )
                banned_embed.add_field(
                    name="📧 Appeals",
                    value="Contact server staff for ban appeals.",
                    inline=False
                )
                await interaction.response.send_message(embed=banned_embed, ephemeral=True)
                return
            
            # Try to add API key (returns False if already in use)
            success = self.bot.db.add_api_key(
                user_id, 
                exchange.lower(), 
                api_key, 
                api_secret,
                api_passphrase=passphrase,
                testnet=testnet
            )
            
            if not success:
                # API key is already registered by another user
                embed = discord.Embed(
                    title="❌ API Key Already In Use",
                    description=f"This API key/wallet is already registered by another user on {exchange}.",
                    color=0xff0000
                )
                embed.add_field(
                    name="🚫 Why This Matters",
                    value="To prevent duplicate trades on the same account, each API key can only be used by one user.",
                    inline=False
                )
                embed.add_field(
                    name="💡 Solution",
                    value="• Create a new API key on your exchange\n• Or use a different wallet address\n• Make sure you're using YOUR OWN credentials",
                    inline=False
                )
                embed.set_footer(text="Security feature: One API key per user")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            embed = discord.Embed(
                title="✅ API Key Added",
                description=f"API key for {exchange} has been added successfully!",
                color=0x00ff00
            )
            embed.add_field(name="Exchange", value=exchange.capitalize(), inline=True)
            embed.add_field(name="Testnet", value="Yes" if testnet else "No", inline=True)
            embed.set_footer(text="Your API keys are encrypted and stored securely.")
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error adding API key: {e}")
            embed = discord.Embed(
                title="❌ Error",
                description="Failed to add API key. Please try again.",
                color=0xff0000
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="subscribe", description="Subscribe to signal channel with simplified position sizing")
    @app_commands.describe(
        exchange="Exchange to use for trading",
        position_mode="Position sizing mode: 'fixed' (dollar amount) or 'percentage' (% of balance)",
        fixed_amount="Fixed dollar amount per trade (e.g., 100 for $100) - used if mode is 'fixed'",
        percentage="Percentage of balance per trade (e.g., 10 for 10%) - used if mode is 'percentage'",
        max_risk="Maximum risk percentage - safety cap (default: 2.0%)"
    )
    @require_api_key
    async def subscribe(self, interaction: discord.Interaction, exchange: str,
                       position_mode: str = 'percentage',
                       fixed_amount: float = 100.0,
                       percentage: float = 10.0,
                       max_risk: float = 2.0):
        try:
            # Validate position mode
            if position_mode.lower() not in ['fixed', 'percentage']:
                embed = discord.Embed(
                    title="❌ Invalid Position Mode",
                    description="Position mode must be either 'fixed' or 'percentage'",
                    color=0xff0000
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Validate amounts
            if position_mode.lower() == 'fixed' and fixed_amount <= 0:
                embed = discord.Embed(
                    title="❌ Invalid Amount",
                    description="Fixed amount must be greater than 0",
                    color=0xff0000
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            if position_mode.lower() == 'percentage' and (percentage <= 0 or percentage > 100):
                embed = discord.Embed(
                    title="❌ Invalid Percentage",
                    description="Percentage must be between 0 and 100",
                    color=0xff0000
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            if max_risk <= 0 or max_risk > 10:
                embed = discord.Embed(
                    title="❌ Invalid Max Risk",
                    description="Max risk must be between 0 and 10%",
                    color=0xff0000
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Check if user has API key for this exchange
            api_key = self.bot.db.get_user_api_key(str(interaction.user.id), exchange.lower())
            if not api_key:
                embed = discord.Embed(
                    title="❌ No API Key",
                    description=f"Please add your API key for {exchange} first using `/add_api_key`",
                    color=0xff0000
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Add channel if not exists
            self.bot.db.add_channel(str(interaction.channel.id), interaction.channel.name)
            
            # Subscribe user to channel with new simplified settings
            self.bot.db.subscribe_to_channel(
                str(interaction.user.id),
                str(interaction.channel.id),
                exchange.lower(),
                1.0,  # Legacy position_size (kept for compatibility)
                max_risk,
                position_mode.lower(),
                fixed_amount,
                percentage
            )
            
            # Create example calculation
            example_balance = 1000
            if position_mode.lower() == 'fixed':
                example_text = f"**Example:** Every trade uses ${fixed_amount:.2f}"
            else:
                example_amount = example_balance * (percentage / 100)
                example_text = f"**Example:** With ${example_balance} balance:\n• {percentage}% = ${example_amount:.2f} per trade"
            
            embed = discord.Embed(
                title="✅ Subscribed Successfully!",
                description=f"You're now subscribed to signals in this channel with simplified position sizing.",
                color=0x00ff00
            )
            embed.add_field(name="📊 Exchange", value=exchange.capitalize(), inline=True)
            embed.add_field(name="💰 Position Mode", value=position_mode.upper(), inline=True)
            embed.add_field(name="🛡️ Max Risk", value=f"{max_risk}%", inline=True)
            
            if position_mode.lower() == 'fixed':
                embed.add_field(name="💵 Fixed Amount", value=f"${fixed_amount:.2f} per trade", inline=False)
            else:
                embed.add_field(name="📈 Percentage", value=f"{percentage}% of balance per trade", inline=False)
            
            embed.add_field(name="📝 Example", value=example_text, inline=False)
            embed.add_field(
                name="⚖️ How Leverage Works",
                value=f"If signal has 20x leverage:\n• Your ${fixed_amount if position_mode.lower() == 'fixed' else f'{percentage}% of balance'} × 20 = position size\n• Max Risk {max_risk}% protects you",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error subscribing: {e}")
            embed = discord.Embed(
                title="❌ Error",
                description="Failed to subscribe. Please try again.",
                color=0xff0000
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="unsubscribe", description="Unsubscribe from signal channel")
    @require_api_key
    async def unsubscribe(self, interaction: discord.Interaction):
        try:
            self.bot.db.remove_channel_subscription(
                str(interaction.user.id),
                str(interaction.channel.id)
            )
            
            embed = discord.Embed(
                title="✅ Unsubscribed",
                description="You've been unsubscribed from this channel.",
                color=0x00ff00
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error unsubscribing: {e}")
            embed = discord.Embed(
                title="❌ Error",
                description="Failed to unsubscribe. Please try again.",
                color=0xff0000
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="balance", description="Check your exchange balance")
    @app_commands.describe(exchange="Exchange to check balance for (e.g., hyperliquid)")
    @require_api_key
    async def balance(self, interaction: discord.Interaction, exchange: str):
        # Defer the response to prevent timeout
        await interaction.response.defer(ephemeral=True)
        
        try:
            logger.info(f"Balance command called by {interaction.user.name} for exchange: {exchange}")
            
            # Get user API key
            api_key_data = self.bot.db.get_user_api_key(str(interaction.user.id), exchange.lower())
            if not api_key_data:
                embed = discord.Embed(
                    title="❌ No API Key",
                    description=f"Please add your API key for {exchange} first.",
                    color=0xff0000
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Get connector
            connector = self.bot.connectors.get(exchange.lower())
            if not connector:
                embed = discord.Embed(
                    title="❌ Exchange Not Supported",
                    description=f"{exchange} is not supported yet.",
                    color=0xff0000
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Get balance
            logger.info(f"Getting balance for {exchange} using connector")
            balance = await connector.get_balance(api_key_data)
            logger.info(f"Balance response: {balance}")
            
            embed = discord.Embed(
                title=f"💰 {exchange.capitalize()} Balance",
                color=0x0099ff if balance.get('total', 0) > 0 else 0xff6b35
            )
            embed.add_field(name="💵 Total Balance", value=f"${balance.get('total', 0):.2f}", inline=True)
            embed.add_field(name="✅ Available", value=f"${balance.get('available', 0):.2f}", inline=True)
            
            if balance.get('withdrawable'):
                embed.add_field(name="💳 Withdrawable", value=f"${balance.get('withdrawable', 0):.2f}", inline=True)
            if balance.get('margin_used'):
                embed.add_field(name="📊 Margin Used", value=f"${balance.get('margin_used', 0):.2f}", inline=True)
            
            # Add account breakdown if available
            if balance.get('perps_balance') is not None or balance.get('spot_balance') is not None:
                perps_bal = balance.get('perps_balance', 0)
                spot_bal = balance.get('spot_balance', 0)
                embed.add_field(name="📈 Perps Account", value=f"${perps_bal:.2f}", inline=True)
                embed.add_field(name="💱 Spot Account", value=f"${spot_bal:.2f}", inline=True)
            
            # Add debugging info if balance is 0
            if balance.get('total', 0) == 0:
                embed.add_field(
                    name="🔍 Troubleshooting", 
                    value="• Check if funds are deposited to Hyperliquid\n• Verify correct wallet address\n• Try testnet:false for mainnet\n• Check both Perps and Spot accounts", 
                    inline=False
                )
            elif balance.get('perps_balance', 0) == 0 and balance.get('spot_balance', 0) > 0:
                embed.add_field(
                    name="⚠️ Account Notice",
                    value="Funds found in Spot account but none in Perps.\nTransfer to Perps account to enable trading.",
                    inline=False
                )
            
            account_type = f"{'🧪 Testnet' if api_key_data.get('testnet') else '🔴 Live'} Account"
            embed.set_footer(text=f"{account_type} • Address: {api_key_data.get('api_key', 'Unknown')[-6:]}")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error getting balance: {e}")
            embed = discord.Embed(
                title="❌ Error",
                description="Failed to get balance. Please check your API key.",
                color=0xff0000
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    # ---------------- Wallet Management ----------------
    @app_commands.command(name="set_wallet", description="Set or update your wallet address (e.g. for Hyperliquid)")
    @app_commands.describe(exchange="Exchange name (e.g., hyperliquid)", wallet_address="Your public wallet address (0x... or hlx...)")
    @require_api_key
    async def set_wallet(self, interaction: discord.Interaction, exchange: str, wallet_address: str):
        await interaction.response.defer(ephemeral=True)
        exchange = exchange.lower()
        try:
            if not (wallet_address.startswith('0x') or wallet_address.lower().startswith('hlx')):
                await interaction.followup.send(
                    "⚠️ Wallet address format doesn't look standard (expected 0x... or hlx...). Please double check.",
                    ephemeral=True
                )
                return
            success = self.bot.db.update_wallet(str(interaction.user.id), exchange, wallet_address)
            if not success:
                await interaction.followup.send(
                    "❌ Could not store wallet. Make sure you added your API key first using /add_api_key.",
                    ephemeral=True
                )
                return
            await interaction.followup.send(
                f"✅ Wallet updated for {exchange}. Now re-run /balance {exchange} to verify.",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error setting wallet: {e}")
            await interaction.followup.send(
                "❌ Failed to set wallet due to an internal error.",
                ephemeral=True
            )

    @app_commands.command(name="show_wallet", description="Show the stored wallet / identifier used for balance queries")
    @app_commands.describe(exchange="Exchange name (e.g., hyperliquid)")
    @require_api_key
    async def show_wallet(self, interaction: discord.Interaction, exchange: str):
        await interaction.response.defer(ephemeral=True)
        exchange = exchange.lower()
        try:
            creds = self.bot.db.get_user_api_key(str(interaction.user.id), exchange)
            if not creds:
                await interaction.followup.send("❌ No API key row found. Add one first.", ephemeral=True)
                return
            wallet = creds.get('api_passphrase') or '(not set)'
            embed = discord.Embed(title="🔑 Wallet / Identifier", color=0x0099ff)
            embed.add_field(name="Exchange", value=exchange, inline=True)
            embed.add_field(name="Wallet", value=wallet, inline=False)
            embed.add_field(name="Testnet", value=str(creds.get('testnet')), inline=True)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Error showing wallet: {e}")
            await interaction.followup.send("❌ Failed to fetch wallet.", ephemeral=True)

    @app_commands.command(name="switch_network", description="Switch between testnet and mainnet for an exchange")
    @app_commands.describe(exchange="Exchange name", testnet="true = testnet, false = mainnet")
    @require_api_key
    async def switch_network(self, interaction: discord.Interaction, exchange: str, testnet: bool):
        await interaction.response.defer(ephemeral=True)
        exchange = exchange.lower()
        try:
            updated = self.bot.db.update_exchange_network(str(interaction.user.id), exchange, testnet)
            if not updated:
                await interaction.followup.send("❌ Could not update network (missing API key row?)", ephemeral=True)
                return
            await interaction.followup.send(
                f"✅ Network switched for {exchange}. Now using {'testnet' if testnet else 'mainnet'}. Re-run /balance {exchange}.",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error switching network: {e}")
            await interaction.followup.send("❌ Failed to switch network.", ephemeral=True)
    
    @app_commands.command(name="positions", description="Check your open positions")
    @app_commands.describe(exchange="Exchange to check positions for")
    @require_api_key
    async def positions(self, interaction: discord.Interaction, exchange: str):
        try:
            # Get user API key
            api_key_data = self.bot.db.get_user_api_key(str(interaction.user.id), exchange.lower())
            if not api_key_data:
                embed = discord.Embed(
                    title="❌ No API Key",
                    description=f"Please add your API key for {exchange} first.",
                    color=0xff0000
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Get connector
            connector = self.bot.connectors.get(exchange.lower())
            if not connector:
                embed = discord.Embed(
                    title="❌ Exchange Not Supported",
                    description=f"{exchange} is not supported yet.",
                    color=0xff0000
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Get positions
            positions = await connector.get_positions(api_key_data)
            
            embed = discord.Embed(
                title=f"📊 {exchange.capitalize()} Positions",
                color=0x0099ff
            )
            
            if not positions:
                embed.description = "No open positions"
            else:
                for pos in positions[:10]:  # Limit to 10 positions
                    pnl_emoji = "🟢" if pos.get('unrealized_pnl', 0) >= 0 else "🔴"
                    embed.add_field(
                        name=f"{pnl_emoji} {pos['symbol']}",
                        value=f"Size: {pos['size']}\nEntry: ${pos.get('entry_price', 0):.4f}\nPnL: ${pos.get('unrealized_pnl', 0):.2f}",
                        inline=True
                    )
            
            embed.set_footer(text=f"{'Testnet' if api_key_data.get('testnet') else 'Live'} Account")
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            embed = discord.Embed(
                title="❌ Error",
                description="Failed to get positions. Please check your API key.",
                color=0xff0000
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="trades", description="View your recent trades")
    @require_api_key
    async def trades(self, interaction: discord.Interaction):
        try:
            trades = self.bot.db.get_user_trades(str(interaction.user.id), limit=10)
            
            embed = discord.Embed(
                title="📈 Recent Trades",
                color=0x0099ff
            )
            
            if not trades:
                embed.description = "No trades found"
            else:
                trade_text = ""
                for trade in trades:
                    side_emoji = "🟢" if trade['side'] == 'buy' else "🔴"
                    trade_text += f"{side_emoji} {trade['symbol']} - {trade['side'].upper()} {trade['size']}\n"
                    trade_text += f"   Exchange: {trade['exchange']} | Status: {trade['status']}\n"
                    if trade['price']:
                        trade_text += f"   Price: ${trade['price']:.4f}\n"
                    trade_text += f"   Time: {trade['created_at']}\n\n"
                
                embed.description = trade_text[:4000]  # Discord limit
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error getting trades: {e}")
            embed = discord.Embed(
                title="❌ Error",
                description="Failed to get trades.",
                color=0xff0000
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="test_signal", description="Test signal parsing")
    @app_commands.describe(message="Test message to parse")
    @require_api_key
    async def test_signal(self, interaction: discord.Interaction, message: str):
        try:
            signal = self.bot.signal_parser.parse_signal(message)
            
            if signal:
                embed = discord.Embed(
                    title="✅ Signal Parsed",
                    description="Successfully parsed the following signal:",
                    color=0x00ff00
                )
                
                for key, value in signal.items():
                    embed.add_field(name=key.replace('_', ' ').title(), value=str(value), inline=True)
            else:
                embed = discord.Embed(
                    title="❌ No Signal Found",
                    description="Could not parse a valid signal from the message.",
                    color=0xff0000
                )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error testing signal: {e}")
            embed = discord.Embed(
                title="❌ Error",
                description="Failed to test signal.",
                color=0xff0000
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @commands.command(name="bothelp")
    async def help_command(self, ctx):
        """Show help message"""
        embed = discord.Embed(
            title="🤖 Trading Bot Commands",
            description="Available commands for the trading bot:",
            color=0x0099ff
        )
        
        embed.add_field(
            name="Setup Commands",
            value="`/add_api_key` - Add your exchange API key\n`/subscribe` - Subscribe to signal channel\n`/unsubscribe` - Unsubscribe from channel",
            inline=False
        )
        
        embed.add_field(
            name="Trading Commands",
            value="`/balance` - Check exchange balance\n`/positions` - View open positions\n`/trades` - View recent trades",
            inline=False
        )
        
        embed.add_field(
            name="Utility Commands",
            value="`/test_signal` - Test signal parsing\n`!bothelp` - Show this help message",
            inline=False
        )
        
        embed.set_footer(text="Use slash commands (/) for most commands")
        
        await ctx.send(embed=embed)
    
    @app_commands.command(name="quick_subscribe", description="Quick subscribe to current channel with smart defaults")
    @require_api_key
    async def quick_subscribe(self, interaction: discord.Interaction):
        """Quick command to subscribe to the current channel with recommended defaults"""
        try:
            # Add user to database
            self.bot.db.add_user(str(interaction.user.id), interaction.user.name)
            
            # Add channel to database 
            self.bot.db.add_channel(str(interaction.channel.id), interaction.channel.name)
            
            # Subscribe user to channel with smart defaults:
            # - Percentage mode (10% of balance)
            # - Max risk 2%
            self.bot.db.subscribe_to_channel(
                str(interaction.user.id),
                str(interaction.channel.id),
                exchange='hyperliquid',
                position_size=1.0,  # Legacy (ignored)
                max_risk=2.0,
                position_mode='percentage',
                fixed_amount=100.0,
                percentage_of_balance=10.0
            )
            
            embed = discord.Embed(
                title="✅ Quick Subscription Complete!",
                description=f"You're now subscribed to **{interaction.channel.name}** with smart defaults.",
                color=0x00ff00
            )
            embed.add_field(name="📊 Exchange", value="Hyperliquid", inline=True)
            embed.add_field(name="💰 Mode", value="Percentage", inline=True)
            embed.add_field(name="�️ Max Risk", value="2%", inline=True)
            embed.add_field(name="📈 Amount", value="10% of balance per trade", inline=False)
            embed.add_field(
                name="💡 Example with $1,000 balance:",
                value="• Each trade uses $100 (10%)\n• If signal has 20x leverage → $2,000 position\n• Max loss capped at $20 (2% risk)",
                inline=False
            )
            embed.add_field(
                name="⚙️ Want different settings?",
                value="Use `/subscribe` command for full customization:\n• Fixed dollar amount per trade\n• Custom percentage\n• Different max risk",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Quick subscribe error: {e}")
            error_text = f"""❌ **SUBSCRIPTION FAILED**

Error: {str(e)}

Please try again or contact support."""
            await interaction.response.send_message(error_text, ephemeral=True)
    
    @app_commands.command(name="setup_dashboard", description="Setup permanent dashboard in this channel (Admin only)")
    async def setup_dashboard(self, interaction: discord.Interaction):
        """Setup permanent dashboard with buttons in the current channel - Admin only"""
        
        # Check if user is admin
        if not interaction.user.guild_permissions.administrator:
            error_text = """❌ **ACCESS DENIED**

Only server administrators can setup the permanent dashboard.
Contact your server admin to set this up."""
            await interaction.response.send_message(error_text, ephemeral=True)
            return
        
        try:
            # Create the permanent dashboard message
            dashboard_text = f"""🤖 **DISCORD TRADING BOT DASHBOARD**

**Professional automated trading with real-time monitoring**

Welcome to your trading command center! Use the buttons below to:
• Configure your trading settings
• Monitor active trades in real-time  
• View performance analytics
• Get help and support

🔥 **Features:**
✅ Real-time signal processing
✅ Live price monitoring & alerts
✅ Multi-exchange support
✅ Advanced risk management
✅ Professional UI & analytics

🚀 **Get Started:** Click a button below to begin!

───────────────────────────
📊 **Channel**: #{interaction.channel.name}
⚙️ **Setup by**: {interaction.user.mention}
🕐 **Created**: <t:{int(interaction.created_at.timestamp())}:F>"""
            
            # Create persistent view for the dashboard
            view = PermanentDashboardView(self.bot)
            
            # Send the permanent dashboard message
            dashboard_msg = await interaction.response.send_message(
                content=dashboard_text, 
                view=view
            )
            
            # Get the message object to pin it
            message = await interaction.original_response()
            
            # Pin the message
            try:
                await message.pin()
                pin_status = "✅ Message pinned successfully"
            except discord.Forbidden:
                pin_status = "⚠️ Could not pin message (missing permissions)"
            except Exception:
                pin_status = "⚠️ Could not pin message"
            
            # Lock the channel - only bot can send messages
            lock_status = ""
            try:
                # Prevent @everyone from sending messages
                await interaction.channel.set_permissions(
                    interaction.guild.default_role,
                    send_messages=False,
                    add_reactions=False,
                    create_public_threads=False,
                    create_private_threads=False,
                    send_messages_in_threads=False,
                    reason="Dashboard channel - bot only"
                )
                
                # Allow bot to send messages
                await interaction.channel.set_permissions(
                    interaction.guild.me,
                    send_messages=True,
                    add_reactions=True,
                    reason="Allow bot to update dashboard"
                )
                
                lock_status = "🔒 Channel locked successfully (bot-only)"
            except discord.Forbidden:
                lock_status = "⚠️ Could not lock channel (missing Manage Channel permissions)"
            except Exception as e:
                lock_status = f"⚠️ Could not lock channel: {str(e)}"
            
            # Send confirmation to admin
            confirmation_text = f"""✅ **DASHBOARD SETUP COMPLETE**

🎯 **Status**: Permanent dashboard created successfully
📍 **Location**: #{interaction.channel.name}
📌 **Pin Status**: {pin_status}
🔒 **Lock Status**: {lock_status}
🔒 **Persistent**: Buttons will work even after bot restart

📋 **Dashboard Features:**
• ⚙️ Setup - User configuration
• 💰 Trading - Balance & testing
• 📊 Analytics - Performance tracking
• 🔍 Monitor - Real-time trade monitoring
• ❓ Help - Support & information

🎮 **Usage**: Users can now click the buttons in #{interaction.channel.name} to access all bot features!

⚠️ **Note**: Only the bot can send messages in this channel. Users interact via buttons only."""
            
            await interaction.followup.send(confirmation_text, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error setting up dashboard: {e}")
            error_text = f"""❌ **SETUP FAILED**

Failed to create the permanent dashboard.
Error: {str(e)}

Please check bot permissions and try again."""
            await interaction.followup.send(error_text, ephemeral=True)
    
    @app_commands.command(name="symbols", description="List available trading symbols on Hyperliquid")
    @app_commands.describe(search="Search for specific symbols (optional)")
    async def symbols(self, interaction: discord.Interaction, search: str = None):
        """List available trading symbols"""
        try:
            # Check if user is banned
            user_id = str(interaction.user.id)
            self.bot.db.add_user(user_id, interaction.user.name)
            
            if self.bot.db.is_user_banned(user_id):
                banned_text = """🚫 **ACCESS DENIED**

❌ **Your account has been banned**

You cannot use this bot. If you believe this is a mistake, please contact the administrator."""
                await interaction.response.send_message(banned_text, ephemeral=True)
                return
            
            await interaction.response.defer()
            
            # Get Hyperliquid connector
            connector = self.bot.connectors.get('hyperliquid')
            if not connector:
                await interaction.followup.send("❌ Hyperliquid connector not available", ephemeral=True)
                return
            
            # Get available symbols
            symbols = await connector.get_available_symbols(testnet=True)
            
            if not symbols:
                await interaction.followup.send("❌ Could not fetch symbols from Hyperliquid", ephemeral=True)
                return
            
            # Filter symbols if search provided
            if search:
                search_upper = search.upper()
                filtered_symbols = [s for s in symbols if search_upper in s.upper()]
                title = f"🔍 Search Results for '{search}'"
                symbols_to_show = filtered_symbols
            else:
                title = "📈 Available Trading Symbols on Hyperliquid"
                symbols_to_show = symbols
            
            if not symbols_to_show:
                await interaction.followup.send(f"❌ No symbols found matching '{search}'", ephemeral=True)
                return
            
            # Create response text
            response_text = f"""**{title}**

💰 **Total Available**: {len(symbols)} symbols
🎯 **Showing**: {len(symbols_to_show)} symbols

**Popular Symbols:**
{', '.join(symbols_to_show[:20])}

**All Symbols:**
{', '.join(symbols_to_show[:50])}{'...' if len(symbols_to_show) > 50 else ''}

💡 **Usage**: Use these exact symbols in your trading signals
📊 **Example**: `LONG BTCUSDT` instead of `LONG BTC`
🔍 **Search**: Use `/symbols search:BTC` to find specific symbols"""
            
            # Split message if too long
            if len(response_text) > 2000:
                # Send shorter version
                response_text = f"""**{title}**

💰 **Total Available**: {len(symbols)} symbols
🎯 **Top 30 Symbols**: {', '.join(symbols_to_show[:30])}

💡 **Get full list**: Use `/symbols search:keyword` to search
📊 **Popular**: BTC, ETH, SOL, AVAX, MATIC, BNB, ATOM, DOGE"""
            
            await interaction.followup.send(response_text)
            
        except Exception as e:
            logger.error(f"Error getting symbols: {e}")
            await interaction.followup.send("❌ Error fetching symbols. Please try again later.", ephemeral=True)
    
    @app_commands.command(name="auto_register_channel", description="Auto-register channel for trading signals (Admin only)")
    async def auto_register_channel(self, interaction: discord.Interaction):
        """Auto-register current channel for signal trading"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            # Check if user has admin permissions
            if not interaction.user.guild_permissions.administrator:
                await interaction.followup.send("❌ This command requires Administrator permissions", ephemeral=True)
                return
            
            channel_id = str(interaction.channel.id)
            channel_name = interaction.channel.name
            
            # Register the channel
            self.bot.db.add_channel(channel_id, channel_name)
            
            # Create welcome message for the channel
            welcome_text = f"""🤖 **TRADING BOT ACTIVATED**

📍 **Channel**: #{channel_name}
🎯 **Status**: Ready for automated trading signals
🔗 **Bot**: Auto Trade Bot active

📋 **How to Get Started**:
1️⃣ Add your API key: `/add_api_key`
2️⃣ Subscribe to signals: `/subscribe`
3️⃣ Post trading signals - bot will execute automatically!

🛡️ **Features**:
• Automatic trade execution for subscribers
• Real-time monitoring & alerts
• Private error notifications
• Balance & risk management

⚙️ **Commands**: Use `/help` to see all available commands
📊 **Dashboard**: Use `/setup_dashboard` for permanent controls

✅ Users can now post trading signals and the bot will automatically execute trades for all subscribers!"""
            
            await interaction.followup.send(welcome_text, ephemeral=True)
            
            # Also send a public message in the channel
            public_msg = f"""🚀 **AUTOMATED TRADING ACTIVATED**

This channel is now ready for trading signals! 
📊 Use `/subscribe` to enable auto-trading on your account
💡 Use `/help` for all commands"""
            
            await interaction.channel.send(public_msg)
            
            logger.info(f"Channel {channel_name} ({channel_id}) registered for auto-trading by {interaction.user.name}")
            
        except Exception as e:
            logger.error(f"Error auto-registering channel: {e}")
            await interaction.followup.send(f"❌ Error setting up channel: {str(e)}", ephemeral=True)
    
    @app_commands.command(name="channel_stats", description="Show channel subscription statistics")
    async def channel_stats(self, interaction: discord.Interaction):
        """Show channel subscription stats"""
        try:
            # Check if user is banned
            user_id = str(interaction.user.id)
            self.bot.db.add_user(user_id, interaction.user.name)
            
            if self.bot.db.is_user_banned(user_id):
                banned_text = """🚫 **ACCESS DENIED**

❌ **Your account has been banned**

You cannot use this bot. If you believe this is a mistake, please contact the administrator."""
                await interaction.response.send_message(banned_text, ephemeral=True)
                return
            
            await interaction.response.defer()
            
            channel_id = str(interaction.channel.id)
            users = self.bot.db.get_channel_users(channel_id)
            
            if not users:
                stats_text = f"""📊 **CHANNEL STATISTICS**

📍 **Channel**: #{interaction.channel.name}
👥 **Subscribers**: 0
🔗 **Status**: No active subscribers

💡 **Get Started**:
• Use `/add_api_key` to add your trading account
• Use `/subscribe` to enable auto-trading
• Post trading signals to test the system!"""
            else:
                exchange_counts = {}
                for user in users:
                    exchange = user['exchange']
                    exchange_counts[exchange] = exchange_counts.get(exchange, 0) + 1
                
                exchange_list = '\n'.join([f"• {exchange}: {count} users" for exchange, count in exchange_counts.items()])
                
                stats_text = f"""📊 **CHANNEL STATISTICS**

📍 **Channel**: #{interaction.channel.name}
👥 **Total Subscribers**: {len(users)}
🔗 **Active Connections**: {len(users)} API accounts

📈 **Exchanges**:
{exchange_list}

✅ **Status**: Ready for automated trading
🎯 **Next**: Post a trading signal to test execution!"""
            
            await interaction.followup.send(stats_text)
            
        except Exception as e:
            logger.error(f"Error getting channel stats: {e}")
            await interaction.followup.send("❌ Error fetching channel statistics", ephemeral=True)
    
    @app_commands.command(name="monitor_stats", description="Show trade monitoring optimization stats")
    async def monitor_stats(self, interaction: discord.Interaction):
        """Show trade monitoring optimization statistics"""
        try:
            # Check if user is banned
            user_id = str(interaction.user.id)
            self.bot.db.add_user(user_id, interaction.user.name)
            
            if self.bot.db.is_user_banned(user_id):
                banned_text = """🚫 **ACCESS DENIED**

❌ **Your account has been banned**

You cannot use this bot. If you believe this is a mistake, please contact the administrator."""
                await interaction.response.send_message(banned_text, ephemeral=True)
                return
            
            await interaction.response.defer()
            
            stats = self.bot.trade_monitor.get_monitoring_stats()
            
            active_signals = stats.get('active_signals', 0)
            total_users = stats.get('total_users_affected', 0)
            total_trades = stats.get('total_db_trades', 0)
            is_running = stats.get('is_running', False)
            
            # Calculate optimization metrics
            if active_signals > 0 and total_users > 0:
                api_calls_saved = total_users - active_signals
                reduction_pct = (api_calls_saved / total_users * 100) if total_users > 0 else 0
                efficiency_ratio = f"{total_users}:{active_signals}"
            else:
                api_calls_saved = 0
                reduction_pct = 0
                efficiency_ratio = "N/A"
            
            status_emoji = "🟢" if is_running else "🔴"
            status_text = "Active" if is_running else "Stopped"
            
            stats_text = f"""📊 **SIGNAL-BASED MONITORING STATS**

{status_emoji} **Status**: {status_text}

🎯 **Active Signals**: {active_signals}
👥 **Total Users**: {total_users}
📊 **Database Trades**: {total_trades}

💰 **OPTIMIZATION METRICS**:
• **Efficiency Ratio**: {efficiency_ratio}
• **API Calls Saved**: {api_calls_saved} per cycle
• **Reduction**: {reduction_pct:.1f}%

🚀 **How It Works**:
• Old System: {total_users} API calls (one per user)
• New System: {active_signals} API calls (one per signal)
• **Result**: {api_calls_saved} fewer API calls every 30 seconds!

💡 **Example**:
If 50 users trade BTC/USDT, we check the price ONCE and notify all 50 users. That's 49 saved API calls per check! ✨"""
            
            await interaction.followup.send(stats_text)
            
        except Exception as e:
            logger.error(f"Error getting monitor stats: {e}")
            await interaction.followup.send(f"❌ Error fetching monitoring statistics: {e}", ephemeral=True)

    @app_commands.command(name="sync_commands", description="Sync bot commands (Admin only - makes commands appear in autocomplete)")
    async def sync_commands(self, interaction: discord.Interaction):
        """Sync commands to make them appear in autocomplete - Admin only"""
        try:
            # Check if user has admin permissions
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ This command requires Administrator permissions", ephemeral=True)
                return
            
            await interaction.response.defer(ephemeral=True)
            
            await self.bot.sync_commands()
            
            success_text = f"""✅ **COMMANDS SYNCED**

📋 **Result**: All bot commands are now visible in autocomplete
💡 **Effect**: When users type `/`, they will see all available commands
⏱️ **Note**: May take a few minutes to appear globally

🔧 **Available Commands**:
• `/dashboard` - Main bot interface
• `/add_api_key` - Add trading credentials  
• `/subscribe` - Subscribe to channels
• `/balance` - Check account balance
• And many more...

ℹ️ **To hide commands again**: Use `/clear_commands` """
            
            await interaction.followup.send(success_text, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error syncing commands: {e}")
            await interaction.followup.send(f"❌ Error syncing commands: {e}", ephemeral=True)

    @app_commands.command(name="clear_commands", description="Clear bot commands (Admin only - hides commands from autocomplete)")
    async def clear_commands(self, interaction: discord.Interaction):
        """Clear commands to hide them from autocomplete - Admin only"""
        try:
            # Check if user has admin permissions
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ This command requires Administrator permissions", ephemeral=True)
                return
            
            await interaction.response.defer(ephemeral=True)
            
            await self.bot.clear_commands()
            
            success_text = f"""✅ **COMMANDS HIDDEN**

🚫 **Result**: User commands are now hidden from autocomplete
💡 **Effect**: When users type `/`, they won't see bot commands
📋 **Note**: Commands still work if users know the exact names
🔧 **Admin commands remain visible**: `/sync_commands` and `/clear_commands`

🔧 **Commands Still Available** (just hidden):
• `/dashboard` - Main bot interface
• `/add_api_key` - Add trading credentials
• `/subscribe` - Subscribe to channels
• `/balance` - Check account balance
• And many more...

ℹ️ **To show commands again**: Use `/sync_commands` """
            
            await interaction.followup.send(success_text, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error clearing commands: {e}")
            await interaction.followup.send(f"❌ Error clearing commands: {e}", ephemeral=True)