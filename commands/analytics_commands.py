"""
Analytics Commands
Discord commands for viewing trading analytics
"""
import discord
from discord import app_commands
import logging
from utils import TradeAnalytics

logger = logging.getLogger(__name__)

async def setup_analytics_commands(bot):
    """Setup analytics commands"""
    
    @bot.tree.command(name="analytics", description="View your trading performance analytics")
    @app_commands.describe(
        days="Number of days to analyze (default: 30)",
        symbol="Filter by specific symbol (optional)"
    )
    async def analytics(
        interaction: discord.Interaction,
        days: int = 30,
        symbol: str = None
    ):
        """Show comprehensive trading analytics"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            user_id = interaction.user.id
            
            # Initialize analytics
            analytics_engine = TradeAnalytics(bot.db)
            
            # Generate report
            report = analytics_engine.create_performance_report(
                user_id=user_id,
                days=days
            )
            
            # Get symbol performance if available
            symbol_perf = analytics_engine.get_performance_by_symbol(
                user_id=user_id,
                days=days
            )
            
            # Create embed
            embed = discord.Embed(
                title=f"📊 Trading Analytics ({days} days)",
                description=report,
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            
            # Add symbol breakdown if available
            if symbol_perf:
                symbol_text = "\n".join([
                    f"**{sym}**: {data['total_trades']} trades | "
                    f"{data['win_rate']:.1f}% WR | "
                    f"${data['total_pnl']:+.2f}"
                    for sym, data in list(symbol_perf.items())[:5]  # Top 5
                ])
                embed.add_field(
                    name="📈 Top Symbols",
                    value=symbol_text or "No data",
                    inline=False
                )
            
            embed.set_footer(text=f"User ID: {user_id}")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            logger.info(f"Analytics displayed for user {user_id}")
            
        except Exception as e:
            logger.error(f"Error showing analytics: {e}")
            await interaction.followup.send(
                "❌ Error generating analytics. Please try again later.",
                ephemeral=True
            )
    
    @bot.tree.command(name="stats", description="Quick performance stats")
    async def stats(interaction: discord.Interaction):
        """Show quick performance stats"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            user_id = interaction.user.id
            analytics_engine = TradeAnalytics(bot.db)
            
            # Get metrics for different periods
            week = analytics_engine.calculate_metrics(user_id, 7)
            month = analytics_engine.calculate_metrics(user_id, 30)
            
            embed = discord.Embed(
                title="⚡ Quick Stats",
                color=discord.Color.gold(),
                timestamp=discord.utils.utcnow()
            )
            
            # Last 7 days
            if week.get('total_trades', 0) > 0:
                embed.add_field(
                    name="📅 Last 7 Days",
                    value=(
                        f"Trades: {week['total_trades']}\n"
                        f"Win Rate: {week['win_rate']:.1f}%\n"
                        f"P&L: ${week['net_pnl']:+.2f}"
                    ),
                    inline=True
                )
            
            # Last 30 days
            if month.get('total_trades', 0) > 0:
                embed.add_field(
                    name="📅 Last 30 Days",
                    value=(
                        f"Trades: {month['total_trades']}\n"
                        f"Win Rate: {month['win_rate']:.1f}%\n"
                        f"P&L: ${month['net_pnl']:+.2f}"
                    ),
                    inline=True
                )
            
            if week.get('total_trades', 0) == 0 and month.get('total_trades', 0) == 0:
                embed.description = "No completed trades found."
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error showing stats: {e}")
            await interaction.followup.send(
                "❌ Error generating stats. Please try again later.",
                ephemeral=True
            )
    
    logger.info("✅ Analytics commands registered")
