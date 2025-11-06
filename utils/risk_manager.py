"""
Risk Management Module
Handles position sizing, risk calculations, and trade validation
"""
import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

class RiskManager:
    """
    Manages risk and position sizing for trades
    
    Features:
    - Dynamic position sizing based on account balance
    - Risk-based calculations (% of account per trade)
    - Stop-loss distance validation
    - Leverage adjustment
    - Maximum position limits
    """
    
    # Default risk parameters
    DEFAULT_RISK_PERCENT = 2.0  # Risk 2% of account per trade
    MAX_RISK_PERCENT = 5.0  # Maximum 5% risk allowed
    MIN_RISK_REWARD_RATIO = 1.5  # Minimum 1.5:1 R/R ratio
    MAX_POSITION_PERCENT = 50.0  # Max 50% of account in single position
    
    @staticmethod
    def calculate_position_size(
        balance: float,
        entry_price: float,
        stop_loss: float,
        risk_percent: float = None,
        leverage: int = 1,
        side: str = 'buy'
    ) -> Dict:
        """
        Calculate optimal position size based on risk management
        
        Formula:
        1. Risk Amount = Balance × Risk%
        2. Price Distance = |Entry - StopLoss|
        3. Risk Per Unit = Price Distance / Entry Price
        4. Position Value = Risk Amount / Risk Per Unit
        5. Position Size = Position Value / Entry Price
        
        Args:
            balance: Account balance in USD
            entry_price: Entry price
            stop_loss: Stop loss price
            risk_percent: Percentage of balance to risk (default: 2%)
            leverage: Leverage multiplier (default: 1x)
            side: 'buy' or 'sell'
        
        Returns:
            Dict with position details
        """
        try:
            if risk_percent is None:
                risk_percent = RiskManager.DEFAULT_RISK_PERCENT
            
            # Validate inputs
            if balance <= 0:
                return {
                    'success': False,
                    'error': 'Invalid balance',
                    'position_size': 0
                }
            
            if entry_price <= 0 or stop_loss <= 0:
                return {
                    'success': False,
                    'error': 'Invalid prices',
                    'position_size': 0
                }
            
            # Cap risk at maximum
            if risk_percent > RiskManager.MAX_RISK_PERCENT:
                logger.warning(f"Risk {risk_percent}% exceeds maximum, capping at {RiskManager.MAX_RISK_PERCENT}%")
                risk_percent = RiskManager.MAX_RISK_PERCENT
            
            # Calculate risk amount in USD
            risk_amount = balance * (risk_percent / 100)
            
            # Calculate price distance to stop loss
            price_distance = abs(entry_price - stop_loss)
            
            if price_distance == 0:
                return {
                    'success': False,
                    'error': 'Entry and stop loss cannot be the same',
                    'position_size': 0
                }
            
            # Calculate risk per unit (as percentage)
            risk_per_unit = price_distance / entry_price
            
            # Calculate position value needed
            position_value = risk_amount / risk_per_unit
            
            # Apply leverage (increases position size)
            leveraged_position_value = position_value * leverage
            
            # Log position size for user awareness (no longer enforcing maximum)
            position_percent = (leveraged_position_value / balance) * 100
            if position_percent > 100:
                logger.warning(
                    f"⚠️ Position {position_percent:.1f}% of balance - High risk position"
                )
            
            # Calculate position size in coins
            position_size = leveraged_position_value / entry_price
            
            # Calculate actual risk with final position size
            actual_risk = position_size * price_distance
            actual_risk_percent = (actual_risk / balance) * 100
            
            logger.info(
                f"📊 Position Sizing:\n"
                f"   Balance: ${balance:.2f}\n"
                f"   Risk: {risk_percent}% = ${risk_amount:.2f}\n"
                f"   Entry: ${entry_price:.2f}\n"
                f"   Stop Loss: ${stop_loss:.2f}\n"
                f"   Distance: ${price_distance:.2f} ({risk_per_unit*100:.2f}%)\n"
                f"   Leverage: {leverage}x\n"
                f"   Position Value: ${leveraged_position_value:.2f}\n"
                f"   Position Size: {position_size:.6f} coins\n"
                f"   Actual Risk: ${actual_risk:.2f} ({actual_risk_percent:.2f}%)"
            )
            
            return {
                'success': True,
                'position_size': round(position_size, 6),
                'position_value': round(leveraged_position_value, 2),
                'risk_amount': round(risk_amount, 2),
                'risk_percent': round(actual_risk_percent, 2),
                'price_distance': round(price_distance, 2),
                'risk_per_unit': round(risk_per_unit * 100, 2),  # As percentage
                'position_percent': round(position_percent, 2)
            }
            
        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            return {
                'success': False,
                'error': str(e),
                'position_size': 0
            }
    
    @staticmethod
    def validate_risk_reward(
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        side: str = 'buy'
    ) -> Dict:
        """
        Validate risk/reward ratio
        
        Args:
            entry_price: Entry price
            stop_loss: Stop loss price
            take_profit: Take profit price (can be single or list)
            side: 'buy' or 'sell'
        
        Returns:
            Dict with R/R analysis
        """
        try:
            # Handle multiple TPs (use first one)
            if isinstance(take_profit, list):
                take_profit = take_profit[0] if take_profit else entry_price
            
            # Calculate risk and reward distances
            risk_distance = abs(entry_price - stop_loss)
            reward_distance = abs(take_profit - entry_price)
            
            if risk_distance == 0:
                return {
                    'valid': False,
                    'error': 'Stop loss equals entry price',
                    'ratio': 0
                }
            
            # Calculate R/R ratio
            rr_ratio = reward_distance / risk_distance
            
            # Check if it meets minimum requirements
            meets_minimum = rr_ratio >= RiskManager.MIN_RISK_REWARD_RATIO
            
            logger.info(
                f"📈 Risk/Reward Analysis:\n"
                f"   Entry: ${entry_price:.2f}\n"
                f"   Stop Loss: ${stop_loss:.2f} (Risk: ${risk_distance:.2f})\n"
                f"   Take Profit: ${take_profit:.2f} (Reward: ${reward_distance:.2f})\n"
                f"   R/R Ratio: 1:{rr_ratio:.2f}\n"
                f"   Status: {'✅ GOOD' if meets_minimum else '⚠️ LOW R/R'}"
            )
            
            return {
                'valid': meets_minimum,
                'ratio': round(rr_ratio, 2),
                'risk_distance': round(risk_distance, 2),
                'reward_distance': round(reward_distance, 2),
                'recommendation': 'TAKE' if meets_minimum else 'SKIP (Low R/R)'
            }
            
        except Exception as e:
            logger.error(f"Error validating R/R: {e}")
            return {
                'valid': False,
                'error': str(e),
                'ratio': 0
            }
    
    @staticmethod
    def calculate_max_leverage(
        balance: float,
        position_value: float,
        risk_percent: float = None
    ) -> int:
        """
        Calculate maximum safe leverage
        
        Args:
            balance: Account balance
            position_value: Desired position value
            risk_percent: Risk percentage
        
        Returns:
            Maximum safe leverage (as integer)
        """
        if risk_percent is None:
            risk_percent = RiskManager.DEFAULT_RISK_PERCENT
        
        # Allow any leverage - no position size limit
        # Users can choose their own risk level
        
        # Cap at exchange limits only
        max_leverage = 125  # Hyperliquid/Bybit maximum
        
        return max_leverage
    
    @staticmethod
    def validate_trade(
        balance: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        leverage: int,
        risk_percent: float = None,
        side: str = 'buy'
    ) -> Dict:
        """
        Complete trade validation
        
        Args:
            balance: Account balance
            entry_price: Entry price
            stop_loss: Stop loss price
            take_profit: Take profit price
            leverage: Leverage
            risk_percent: Risk percentage
            side: Trade side
        
        Returns:
            Dict with validation results and position sizing
        """
        try:
            # Validate R/R ratio
            rr_check = RiskManager.validate_risk_reward(
                entry_price, stop_loss, take_profit, side
            )
            
            # Calculate position size
            position = RiskManager.calculate_position_size(
                balance, entry_price, stop_loss, risk_percent, leverage, side
            )
            
            # Overall validation
            is_valid = rr_check['valid'] and position['success']
            
            warnings = []
            if not rr_check['valid']:
                warnings.append(f"Low R/R ratio: {rr_check['ratio']:.2f}")
            
            if position.get('position_percent', 0) > 30:
                warnings.append(f"Large position: {position['position_percent']:.1f}% of balance")
            
            if leverage > 10:
                warnings.append(f"High leverage: {leverage}x")
            
            return {
                'valid': is_valid,
                'position_size': position.get('position_size', 0),
                'position_details': position,
                'risk_reward': rr_check,
                'warnings': warnings,
                'recommendation': 'EXECUTE' if is_valid and not warnings else 'REVIEW'
            }
            
        except Exception as e:
            logger.error(f"Trade validation error: {e}")
            return {
                'valid': False,
                'error': str(e),
                'position_size': 0
            }
