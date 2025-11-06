"""
Partial Fill Handler
Detects and manages partially filled orders
"""
import logging
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class PartialFillHandler:
    """
    Handles detection and management of partially filled orders
    
    A partial fill occurs when only part of your order is executed.
    Example: You place an order for 1 BTC but only 0.6 BTC is filled.
    """
    
    # Thresholds
    PARTIAL_FILL_THRESHOLD = 0.95  # 95% - below this is considered partial
    MINIMUM_FILL_THRESHOLD = 0.10  # 10% - below this is too small
    
    def __init__(self, bot):
        self.bot = bot
        self.tracked_fills = {}  # {order_id: fill_data}
    
    def check_fill_status(
        self,
        expected_size: float,
        actual_size: float,
        order_id: str = None
    ) -> Dict:
        """
        Check if an order was partially filled
        
        Args:
            expected_size: Expected order size
            actual_size: Actual filled size
            order_id: Optional order ID for tracking
        
        Returns:
            Dict with fill status
        """
        try:
            if expected_size <= 0:
                return {
                    'status': 'invalid',
                    'error': 'Invalid expected size',
                    'fill_percent': 0
                }
            
            # Calculate fill percentage
            fill_percent = (actual_size / expected_size) * 100
            
            # Determine fill status
            if fill_percent >= self.PARTIAL_FILL_THRESHOLD * 100:
                status = 'full'
                severity = 'success'
            elif fill_percent >= self.MINIMUM_FILL_THRESHOLD * 100:
                status = 'partial'
                severity = 'warning'
            elif fill_percent > 0:
                status = 'minimal'
                severity = 'error'
            else:
                status = 'unfilled'
                severity = 'error'
            
            result = {
                'status': status,
                'severity': severity,
                'expected_size': round(expected_size, 6),
                'actual_size': round(actual_size, 6),
                'fill_percent': round(fill_percent, 2),
                'unfilled_size': round(expected_size - actual_size, 6),
                'timestamp': datetime.now().isoformat()
            }
            
            # Log appropriately based on severity
            if status == 'full':
                logger.info(f"✅ Order fully filled: {fill_percent:.1f}%")
            elif status == 'partial':
                logger.warning(
                    f"⚠️ PARTIAL FILL detected: {fill_percent:.1f}%\n"
                    f"   Expected: {expected_size:.6f}\n"
                    f"   Filled: {actual_size:.6f}\n"
                    f"   Remaining: {result['unfilled_size']:.6f}"
                )
            elif status == 'minimal':
                logger.error(
                    f"❌ MINIMAL FILL: Only {fill_percent:.1f}% filled\n"
                    f"   This is too small to be useful"
                )
            else:
                logger.error("❌ Order NOT FILLED")
            
            # Track this fill
            if order_id:
                self.tracked_fills[order_id] = result
            
            return result
            
        except Exception as e:
            logger.error(f"Error checking fill status: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'fill_percent': 0
            }
    
    async def handle_partial_fill(
        self,
        signal: Dict,
        position: Dict,
        user_mappings: List[Dict]
    ) -> Dict:
        """
        Handle a partial fill situation
        
        Args:
            signal: Original signal data
            position: Current position data
            user_mappings: List of users affected
        
        Returns:
            Dict with handling results
        """
        try:
            expected_size = signal.get('expected_size', 0)
            actual_size = abs(float(position.get('size', 0)))
            
            fill_status = self.check_fill_status(expected_size, actual_size)
            
            if fill_status['status'] == 'partial':
                # Adjust TP/SL targets for partial position
                adjusted_signal = await self._adjust_targets_for_partial_fill(
                    signal, fill_status
                )
                
                # Notify users about partial fill
                await self._notify_partial_fill(
                    signal, fill_status, user_mappings
                )
                
                logger.info(
                    f"📊 Partial fill handled:\n"
                    f"   Adjusted targets for {fill_status['fill_percent']:.1f}% fill\n"
                    f"   Notified {len(user_mappings)} users"
                )
                
                return {
                    'success': True,
                    'adjusted': True,
                    'fill_status': fill_status,
                    'adjusted_signal': adjusted_signal
                }
            
            return {
                'success': True,
                'adjusted': False,
                'fill_status': fill_status
            }
            
        except Exception as e:
            logger.error(f"Error handling partial fill: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    async def _adjust_targets_for_partial_fill(
        self,
        signal: Dict,
        fill_status: Dict
    ) -> Dict:
        """
        Adjust TP/SL targets proportionally for partial fill
        
        If only 60% of order filled, we might want to:
        - Adjust position size in calculations
        - Keep same TP/SL prices but adjust quantities
        - Update risk calculations
        """
        adjusted_signal = signal.copy()
        fill_percent = fill_status['fill_percent'] / 100
        
        # Adjust expected quantities
        if 'expected_size' in adjusted_signal:
            adjusted_signal['expected_size'] *= fill_percent
        
        # Note the adjustment
        adjusted_signal['partial_fill'] = True
        adjusted_signal['fill_percent'] = fill_status['fill_percent']
        
        logger.info(
            f"🔧 Adjusted signal for {fill_status['fill_percent']:.1f}% fill"
        )
        
        return adjusted_signal
    
    async def _notify_partial_fill(
        self,
        signal: Dict,
        fill_status: Dict,
        user_mappings: List[Dict]
    ):
        """
        Send notifications about partial fill
        """
        try:
            channel_id = signal.get('channel_id')
            if not channel_id:
                return
            
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                return
            
            symbol = signal.get('symbol', 'Unknown')
            side = signal.get('side', 'unknown').upper()
            
            notification = (
                f"⚠️ **PARTIAL FILL DETECTED**\n\n"
                f"📊 **{symbol}** {side}\n"
                f"📈 Fill Status: **{fill_status['fill_percent']:.1f}%**\n"
                f"🎯 Expected: {fill_status['expected_size']:.6f}\n"
                f"✅ Filled: {fill_status['actual_size']:.6f}\n"
                f"⏳ Remaining: {fill_status['unfilled_size']:.6f}\n\n"
                f"💡 **What this means:**\n"
                f"• Only part of your order was executed\n"
                f"• TP/SL targets remain the same\n"
                f"• Position size is smaller than expected\n"
                f"• Monitoring continues for filled portion\n\n"
                f"👥 {len(user_mappings)} users affected"
            )
            
            await channel.send(notification)
            logger.info(f"✅ Partial fill notification sent to channel {channel_id}")
            
        except Exception as e:
            logger.error(f"Error sending partial fill notification: {e}")
    
    def get_fill_statistics(self, user_id: Optional[int] = None) -> Dict:
        """
        Get statistics about fills
        
        Args:
            user_id: Optional user ID to filter by
        
        Returns:
            Dict with fill statistics
        """
        fills = list(self.tracked_fills.values())
        
        if not fills:
            return {
                'total_orders': 0,
                'full_fills': 0,
                'partial_fills': 0,
                'avg_fill_percent': 0
            }
        
        full_fills = [f for f in fills if f['status'] == 'full']
        partial_fills = [f for f in fills if f['status'] == 'partial']
        
        avg_fill = sum(f['fill_percent'] for f in fills) / len(fills)
        
        return {
            'total_orders': len(fills),
            'full_fills': len(full_fills),
            'partial_fills': len(partial_fills),
            'minimal_fills': len([f for f in fills if f['status'] == 'minimal']),
            'unfilled': len([f for f in fills if f['status'] == 'unfilled']),
            'avg_fill_percent': round(avg_fill, 2),
            'partial_fill_rate': round(len(partial_fills) / len(fills) * 100, 2)
        }
    
    def clear_old_fills(self, max_age_hours: int = 24):
        """
        Clear old fill records
        
        Args:
            max_age_hours: Maximum age of records to keep
        """
        cutoff = datetime.now().timestamp() - (max_age_hours * 3600)
        
        to_remove = []
        for order_id, fill_data in self.tracked_fills.items():
            try:
                fill_time = datetime.fromisoformat(fill_data['timestamp']).timestamp()
                if fill_time < cutoff:
                    to_remove.append(order_id)
            except:
                pass
        
        for order_id in to_remove:
            del self.tracked_fills[order_id]
        
        if to_remove:
            logger.info(f"🧹 Cleared {len(to_remove)} old fill records")
