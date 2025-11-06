from abc import ABC, abstractmethod
from typing import Dict, Any, List

class BaseConnector(ABC):
    """Base class for exchange connectors"""
    
    @abstractmethod
    async def connect(self, credentials: Dict[str, str]) -> bool:
        """Connect to the exchange"""
        pass
    
    @abstractmethod
    async def execute_trade(self, user_data: Dict, signal: Dict) -> Dict[str, Any]:
        """Execute a trade based on signal"""
        pass
    
    @abstractmethod
    async def get_balance(self, credentials: Dict[str, str]) -> Dict[str, float]:
        """Get account balance"""
        pass
    
    @abstractmethod
    async def get_positions(self, credentials: Dict[str, str]) -> List[Dict[str, Any]]:
        """Get open positions"""
        pass
    
    @abstractmethod
    def validate_credentials(self, credentials: Dict[str, str]) -> bool:
        """Validate API credentials"""
        pass
    
    def calculate_position_size(self, user_data: Dict, signal: Dict, balance: float = None) -> float:
        """Calculate position size based on user settings and risk management"""
        base_size = user_data.get('position_size', 1.0)
        max_risk = user_data.get('max_risk', 2.0)
        
        # If balance is provided, calculate size based on risk percentage
        if balance:
            risk_amount = balance * (max_risk / 100)
            
            # If we have entry and stop loss, calculate size based on risk
            if signal.get('entry') and signal.get('stop_loss'):
                entry_price = signal['entry'][0] if isinstance(signal['entry'], list) else signal['entry']
                stop_price = signal['stop_loss'][0] if isinstance(signal['stop_loss'], list) else signal['stop_loss']
                
                risk_per_unit = abs(entry_price - stop_price)
                if risk_per_unit > 0:
                    calculated_size = risk_amount / risk_per_unit
                    return min(calculated_size, base_size * 2)  # Cap at 2x base size
        
        return base_size