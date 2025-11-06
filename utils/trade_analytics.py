"""
Trade Analytics Module
Tracks and analyzes trading performance
"""
import logging
from typing import Dict, List, Optional, Union
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)

class TradeAnalytics:
    """
    Comprehensive trade analytics and performance tracking
    
    Features:
    - Win rate calculation
    - Profit factor
    - Average win/loss
    - Drawdown tracking
    - Sharpe ratio
    - Performance by symbol, time period, etc.
    """
    
    def __init__(self, db_manager):
        """
        Initialize TradeAnalytics with DatabaseManager
        
        Args:
            db_manager: DatabaseManager instance (PostgreSQL or SQLite)
        """
        self.db = db_manager
    
    def calculate_metrics(
        self,
        user_id: Optional[int] = None,
        days: int = 30,
        symbol: Optional[str] = None,
        exchange: Optional[str] = None
    ) -> Dict:
        """
        Calculate comprehensive trading metrics
        
        Args:
            user_id: Filter by user ID (None = all users)
            days: Number of days to analyze
            symbol: Filter by symbol
            exchange: Filter by exchange
        
        Returns:
            Dict with all metrics
        """
        try:
            trades = self._get_closed_trades(user_id, days, symbol, exchange)
            
            if not trades:
                return {
                    'total_trades': 0,
                    'message': 'No completed trades in this period'
                }
            
            # Separate wins and losses
            wins = [t for t in trades if t['pnl'] > 0]
            losses = [t for t in trades if t['pnl'] < 0]
            breakeven = [t for t in trades if t['pnl'] == 0]
            
            # Calculate basic metrics
            total_profit = sum(t['pnl'] for t in wins)
            total_loss = abs(sum(t['pnl'] for t in losses))
            net_pnl = total_profit - total_loss
            
            # Win rate
            win_rate = (len(wins) / len(trades)) * 100 if trades else 0
            
            # Profit factor (total profit / total loss)
            profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')
            
            # Average metrics
            avg_win = total_profit / len(wins) if wins else 0
            avg_loss = total_loss / len(losses) if losses else 0
            avg_pnl = net_pnl / len(trades) if trades else 0
            
            # Best and worst trades
            largest_win = max((t['pnl'] for t in wins), default=0)
            largest_loss = min((t['pnl'] for t in losses), default=0)
            
            # Expectancy (average expected return per trade)
            expectancy = (win_rate / 100 * avg_win) - ((100 - win_rate) / 100 * avg_loss)
            
            # Calculate drawdown
            drawdown_info = self._calculate_drawdown(trades)
            
            # Calculate consecutive stats
            consecutive_stats = self._calculate_consecutive_stats(trades)
            
            # Performance by period
            daily_pnl = self._calculate_daily_pnl(trades)
            
            # Removed verbose logging for production
            
            return {
                'period_days': days,
                'total_trades': len(trades),
                'winning_trades': len(wins),
                'losing_trades': len(losses),
                'breakeven_trades': len(breakeven),
                
                # Performance metrics
                'win_rate': round(win_rate, 2),
                'profit_factor': round(profit_factor, 2),
                'expectancy': round(expectancy, 2),
                
                # P&L metrics
                'total_profit': round(total_profit, 2),
                'total_loss': round(total_loss, 2),
                'net_pnl': round(net_pnl, 2),
                
                # Average metrics
                'avg_win': round(avg_win, 2),
                'avg_loss': round(avg_loss, 2),
                'avg_pnl': round(avg_pnl, 2),
                
                # Best/Worst
                'largest_win': round(largest_win, 2),
                'largest_loss': round(largest_loss, 2),
                
                # Risk metrics
                'max_drawdown': drawdown_info,
                'consecutive_stats': consecutive_stats,
                
                # Time-based
                'daily_pnl': daily_pnl,
                
                # Filters applied
                'filtered_by': {
                    'user_id': user_id,
                    'symbol': symbol,
                    'exchange': exchange
                }
            }
            
        except Exception as e:
            logger.error(f"Error calculating metrics: {e}")
            return {
                'error': str(e),
                'total_trades': 0
            }
    
    def _get_closed_trades(
        self,
        user_id: Optional[int],
        days: int,
        symbol: Optional[str],
        exchange: Optional[str]
    ) -> List[Dict]:
        """Fetch closed trades from database"""
        try:
            # Use DatabaseManager's connection management
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Build query with filters (PostgreSQL syntax)
                query = """
                    SELECT 
                        id, user_id, exchange, symbol, side,
                        position_size, entry_price, exit_price,
                        pnl, status, created_at, closed_at
                    FROM trades
                    WHERE (status = 'closed' OR status = 'completed')
                    AND closed_at >= CURRENT_TIMESTAMP - INTERVAL '%s days'
                """
                params = [days]
                
                if user_id:
                    query += " AND user_id = %s"
                    params.append(str(user_id))
                
                if symbol:
                    query += " AND symbol = %s"
                    params.append(symbol)
                
                if exchange:
                    query += " AND exchange = %s"
                    params.append(exchange)
                
                query += " ORDER BY closed_at ASC"
                
                cursor.execute(query, params)
                rows = cursor.fetchall()
                
                trades = []
                for row in rows:
                    # Handle dictionary-like row access
                    if isinstance(row, dict):
                        row_dict = row
                    else:
                        # Convert tuple to dict using column names
                        columns = [desc[0] for desc in cursor.description]
                        row_dict = dict(zip(columns, row))
                    
                    # Calculate PNL if it's missing or zero
                    pnl = row_dict.get('pnl', 0)
                    if pnl == 0 and row_dict.get('entry_price') and row_dict.get('exit_price'):
                        entry = float(row_dict['entry_price'])
                        exit_price = float(row_dict['exit_price'])
                        position_size = float(row_dict.get('position_size', 0) or 0)
                        
                        if row_dict['side'] == 'long':
                            pnl = (exit_price - entry) * position_size
                        else:  # short
                            pnl = (entry - exit_price) * position_size
                    
                    trades.append({
                        'id': row_dict['id'],
                        'user_id': row_dict['user_id'],
                        'exchange': row_dict['exchange'],
                        'symbol': row_dict['symbol'],
                        'side': row_dict['side'],
                        'position_size': row_dict.get('position_size', 0),
                        'entry_price': row_dict.get('entry_price'),
                        'exit_price': row_dict.get('exit_price'),
                        'pnl': pnl or 0,
                        'created_at': row_dict.get('created_at'),
                        'closed_at': row_dict.get('closed_at')
                    })
                
                return trades
        except Exception as e:
            logger.error(f"Error fetching trades: {e}")
            return []
    
    def _calculate_drawdown(self, trades: List[Dict]) -> Dict:
        """Calculate maximum drawdown"""
        if not trades:
            return {'max_drawdown': 0, 'max_drawdown_percent': 0}
        
        # Calculate cumulative P&L
        cumulative_pnl = 0
        peak = 0
        max_drawdown = 0
        
        for trade in trades:
            cumulative_pnl += trade['pnl']
            if cumulative_pnl > peak:
                peak = cumulative_pnl
            
            drawdown = peak - cumulative_pnl
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        max_drawdown_percent = (max_drawdown / peak * 100) if peak > 0 else 0
        
        return {
            'max_drawdown': round(max_drawdown, 2),
            'max_drawdown_percent': round(max_drawdown_percent, 2)
        }
    
    def _calculate_consecutive_stats(self, trades: List[Dict]) -> Dict:
        """Calculate consecutive wins/losses"""
        if not trades:
            return {
                'max_consecutive_wins': 0,
                'max_consecutive_losses': 0,
                'current_streak': 0
            }
        
        max_wins = 0
        max_losses = 0
        current_wins = 0
        current_losses = 0
        
        for trade in trades:
            if trade['pnl'] > 0:
                current_wins += 1
                current_losses = 0
                max_wins = max(max_wins, current_wins)
            elif trade['pnl'] < 0:
                current_losses += 1
                current_wins = 0
                max_losses = max(max_losses, current_losses)
            else:
                current_wins = 0
                current_losses = 0
        
        # Determine current streak
        last_trade = trades[-1]
        if last_trade['pnl'] > 0:
            current_streak = current_wins
        elif last_trade['pnl'] < 0:
            current_streak = -current_losses
        else:
            current_streak = 0
        
        return {
            'max_consecutive_wins': max_wins,
            'max_consecutive_losses': max_losses,
            'current_streak': current_streak
        }
    
    def _calculate_daily_pnl(self, trades: List[Dict]) -> Dict:
        """Calculate P&L by day"""
        daily_pnl = defaultdict(float)
        
        for trade in trades:
            try:
                date = datetime.fromisoformat(trade['closed_at']).date()
                daily_pnl[str(date)] += trade['pnl']
            except:
                pass
        
        return dict(daily_pnl)
    
    def get_performance_by_symbol(
        self,
        user_id: Optional[int] = None,
        days: int = 30
    ) -> Dict[str, Dict]:
        """Get performance breakdown by symbol"""
        try:
            trades = self._get_closed_trades(user_id, days, None, None)
            
            if not trades:
                return {}
            
            # Group by symbol
            by_symbol = defaultdict(list)
            for trade in trades:
                by_symbol[trade['symbol']].append(trade)
            
            # Calculate metrics for each symbol
            results = {}
            for symbol, symbol_trades in by_symbol.items():
                wins = [t for t in symbol_trades if t['pnl'] > 0]
                losses = [t for t in symbol_trades if t['pnl'] < 0]
                
                total_pnl = sum(t['pnl'] for t in symbol_trades)
                win_rate = len(wins) / len(symbol_trades) * 100 if symbol_trades else 0
                
                results[symbol] = {
                    'total_trades': len(symbol_trades),
                    'wins': len(wins),
                    'losses': len(losses),
                    'win_rate': round(win_rate, 2),
                    'total_pnl': round(total_pnl, 2),
                    'avg_pnl': round(total_pnl / len(symbol_trades), 2)
                }
            
            # Sort by total P&L
            results = dict(sorted(
                results.items(),
                key=lambda x: x[1]['total_pnl'],
                reverse=True
            ))
            
            return results
            
        except Exception as e:
            logger.error(f"Error calculating symbol performance: {e}")
            return {}
    
    def create_performance_report(
        self,
        user_id: Optional[int] = None,
        days: int = 30
    ) -> str:
        """
        Create a formatted performance report
        
        Returns:
            Formatted text report
        """
        metrics = self.calculate_metrics(user_id, days)
        
        if metrics.get('total_trades', 0) == 0:
            return "📊 **Performance Report**\n\nNo completed trades in this period."
        
        report = f"""
📊 **PERFORMANCE REPORT** ({days} days)

**📈 Overview:**
• Total Trades: {metrics['total_trades']}
• Wins: {metrics['winning_trades']} | Losses: {metrics['losing_trades']}
• Win Rate: **{metrics['win_rate']:.1f}%**
• Profit Factor: **{metrics['profit_factor']:.2f}**

**💰 Profit & Loss:**
• Total Profit: ${metrics['total_profit']:.2f}
• Total Loss: -${metrics['total_loss']:.2f}
• **Net P&L: ${metrics['net_pnl']:.2f}**
• Expectancy: ${metrics['expectancy']:.2f} per trade

**📊 Average Performance:**
• Avg Win: ${metrics['avg_win']:.2f}
• Avg Loss: -${metrics['avg_loss']:.2f}
• Avg Trade: ${metrics['avg_pnl']:.2f}

**🎯 Best & Worst:**
• Largest Win: ${metrics['largest_win']:.2f}
• Largest Loss: ${metrics['largest_loss']:.2f}

**📉 Risk Metrics:**
• Max Drawdown: -${metrics['max_drawdown']['max_drawdown']:.2f} ({metrics['max_drawdown']['max_drawdown_percent']:.1f}%)
• Max Consecutive Wins: {metrics['consecutive_stats']['max_consecutive_wins']}
• Max Consecutive Losses: {metrics['consecutive_stats']['max_consecutive_losses']}
• Current Streak: {metrics['consecutive_stats']['current_streak']}

**💡 Performance Rating:**
"""
        
        # Add rating
        if metrics['profit_factor'] >= 2.0 and metrics['win_rate'] >= 60:
            report += "⭐⭐⭐⭐⭐ EXCELLENT"
        elif metrics['profit_factor'] >= 1.5 and metrics['win_rate'] >= 50:
            report += "⭐⭐⭐⭐ VERY GOOD"
        elif metrics['profit_factor'] >= 1.0 and metrics['win_rate'] >= 45:
            report += "⭐⭐⭐ GOOD"
        elif metrics['net_pnl'] > 0:
            report += "⭐⭐ PROFITABLE"
        else:
            report += "⭐ NEEDS IMPROVEMENT"
        
        return report.strip()
