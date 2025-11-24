import aiohttp
import asyncio
import hmac
import hashlib
import json
import time
from typing import Dict, Any, List, Optional
from .base_connector import BaseConnector
from config import Config
import logging

# Import utilities (same as Hyperliquid/Bybit)
from utils import (
    RiskManager,
    SlippageProtection,
    with_retry,
    with_rate_limit,
    bybit_limiter  # Reuse rate limiter
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class BinanceConnector(BaseConnector):
    """Connector for Binance Futures exchange"""
    def __init__(self):
        self.base_url = "https://fapi.binance.com"
        self.testnet_url = "https://testnet.binancefuture.com"
        self._recv_window = 5000
        self.active_orders: Dict[str, Dict[str, Any]] = {}
        
    def _get_base_url(self, testnet: bool = False) -> str:
        return self.testnet_url if testnet else self.base_url
    
    def _generate_signature(self, query_string: str, api_secret: str) -> str:
        """Generate HMAC SHA256 signature for Binance API"""
        return hmac.new(
            api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def _get_headers(self, api_key: str) -> Dict[str, str]:
        """Generate headers for Binance API requests"""
        return {
            "X-MBX-APIKEY": api_key,
            "Content-Type": "application/json"
        }
    
    async def connect(self, credentials: Dict[str, str]) -> bool:
        """Test connection to Binance"""
        try:
            api_key = credentials.get('api_key')
            api_secret = credentials.get('api_secret')
            testnet = credentials.get('testnet', False)
            
            if not api_key or not api_secret:
                return False
            
            # Test connection by getting account info
            timestamp = int(time.time() * 1000)
            query_string = f"timestamp={timestamp}&recvWindow={self._recv_window}"
            signature = self._generate_signature(query_string, api_secret)
            
            url = f"{self._get_base_url(testnet)}/fapi/v2/account?{query_string}&signature={signature}"
            headers = self._get_headers(api_key)
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        logger.info("✅ Connected to Binance successfully")
                        return True
                    else:
                        text = await response.text()
                        logger.error(f"❌ Binance connection failed (HTTP {response.status}): {text}")
                        return False
            
        except Exception as e:
            logger.error(f"❌ Binance connection error: {e}")
            return False
    
    def validate_credentials(self, credentials: Dict[str, str]) -> bool:
        """Validate Binance API credentials format"""
        api_key = credentials.get('api_key')
        api_secret = credentials.get('api_secret')
        
        if not api_key or not api_secret:
            return False
        
        if len(api_key) < 10 or len(api_secret) < 10:
            return False
        
        return True
    
    @with_rate_limit(bybit_limiter)
    async def get_balance(self, credentials: Dict[str, str]) -> Dict[str, float]:
        """Get Binance Futures account balance"""
        try:
            api_key = credentials.get('api_key')
            api_secret = credentials.get('api_secret')
            testnet = credentials.get('testnet', False)
            
            if not api_key or not api_secret:
                logger.error("Missing API key or secret")
                return {'USDT': 0.0}
            
            timestamp = int(time.time() * 1000)
            query_string = f"timestamp={timestamp}&recvWindow={self._recv_window}"
            signature = self._generate_signature(query_string, api_secret)
            
            url = f"{self._get_base_url(testnet)}/fapi/v2/account?{query_string}&signature={signature}"
            headers = self._get_headers(api_key)
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        total_balance = float(data.get('totalWalletBalance', 0))
                        available_balance = float(data.get('availableBalance', 0))
                        
                        logger.info(f"📊 Binance Account - Total: ${total_balance:.2f}, Available: ${available_balance:.2f}")
                        
                        coins_detail = {}
                        for asset in data.get('assets', []):
                            asset_name = asset.get('asset')
                            wallet_balance = float(asset.get('walletBalance', 0))
                            available = float(asset.get('availableBalance', 0))
                            
                            if asset_name == 'USDT' or wallet_balance > 0:
                                coins_detail[asset_name] = {
                                    'equity': wallet_balance,
                                    'wallet_balance': wallet_balance,
                                    'available': available
                                }
                        
                        return {
                            'total': total_balance,
                            'available': available_balance,
                            'coins': coins_detail
                        }
                    else:
                        error_data = await response.text()
                        logger.error(f"❌ Binance balance check failed (HTTP {response.status}): {error_data}")
                        return {}
            
        except Exception as e:
            logger.error(f"❌ Error getting Binance balance: {e}")
            return {}
    
    @with_rate_limit(bybit_limiter)
    async def get_positions(self, credentials: Dict[str, str]) -> List[Dict[str, Any]]:
        """Get open positions on Binance"""
        try:
            api_key = credentials.get('api_key')
            api_secret = credentials.get('api_secret')
            testnet = credentials.get('testnet', False)
            
            timestamp = int(time.time() * 1000)
            query_string = f"timestamp={timestamp}&recvWindow={self._recv_window}"
            signature = self._generate_signature(query_string, api_secret)
            
            url = f"{self._get_base_url(testnet)}/fapi/v2/positionRisk?{query_string}&signature={signature}"
            headers = self._get_headers(api_key)
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        positions = []
                        for pos in data:
                            position_amt = float(pos.get('positionAmt', 0))
                            if position_amt != 0:
                                positions.append({
                                    'symbol': pos.get('symbol'),
                                    'side': 'long' if position_amt > 0 else 'short',
                                    'size': abs(position_amt),
                                    'entry_price': float(pos.get('entryPrice', 0)),
                                    'leverage': int(pos.get('leverage', 1)),
                                    'unrealized_pnl': float(pos.get('unRealizedProfit', 0))
                                })
                        return positions
            
            return []
        except Exception as e:
            logger.error(f"❌ Error getting Binance positions: {e}")
            return []
    
    async def execute_trade(self, user_data: Dict, signal: Dict) -> Dict[str, Any]:
        """Execute trade on Binance based on signal - SAME SYSTEM AS HYPERLIQUID/BYBIT"""
        try:
            api_key = user_data.get('api_key')
            api_secret = user_data.get('api_secret')
            testnet = user_data.get('testnet', False)
            
            if not api_key or not api_secret:
                return {'success': False, 'error': 'Missing API credentials'}
            
            # Get balance for position sizing
            balance = await self.get_balance(user_data)
            
            if 'coins' in balance:
                usdt_info = balance.get('coins', {}).get('USDT', {})
                total_balance = usdt_info.get('equity', 0) if isinstance(usdt_info, dict) else 0
            else:
                total_balance = balance.get('USDT', 0)
            
            if total_balance <= 0:
                testnet_hint = ""
                if testnet:
                    testnet_hint = "\n\n💡 **Testnet Tip**: Visit Binance testnet to get test USDT"
                return {
                    "success": False,
                    "error": f"❌ Insufficient Balance: Account balance is $0.00{testnet_hint}",
                    "balance_check": {
                        "total": total_balance,
                        "required": "Minimum $10",
                        "status": "NO_BALANCE"
                    }
                }
            
            min_balance = 1.0
            if total_balance < min_balance:
                return {
                    "success": False,
                    "error": f"❌ Insufficient Balance: ${total_balance:.2f} available, minimum ${min_balance} required",
                    "balance_check": {
                        "total": total_balance,
                        "required": min_balance,
                        "status": "BELOW_MINIMUM"
                    }
                }
            
            # Prepare symbol (Binance format)
            symbol = signal.get('symbol', '').upper()
            if not symbol.endswith('USDT'):
                symbol = f"{symbol}USDT"
            
            # Validate symbol
            symbol_valid = await self._validate_symbol(symbol, testnet)
            if not symbol_valid:
                return {
                    "success": False,
                    "error": f"❌ Symbol Not Available: {symbol} is not tradeable on Binance",
                    "symbol_check": {
                        "requested": signal.get('symbol'),
                        "cleaned": symbol,
                        "status": "NOT_AVAILABLE"
                    }
                }
            
            # Position sizing (same as Bybit/Hyperliquid)
            entry_price = float(signal.get('entry', [0])[0] if signal.get('entry') else 0)
            stop_loss = float(signal.get('stop_loss', [0])[0] if signal.get('stop_loss') else 0)
            leverage = signal.get('leverage', Config.DEFAULT_LEVERAGE)
            
            if entry_price <= 0:
                return {
                    "success": False,
                    "error": "❌ Missing entry price for order placement"
                }
            
            fixed_amount = user_data.get('fixed_amount', 100.0)
            max_risk_percent = user_data.get('max_risk', 2.0)
            leveraged_amount = fixed_amount * leverage
            
            # Risk check
            if stop_loss > 0:
                price_distance = abs(entry_price - stop_loss)
                risk_distance = price_distance / entry_price
                expected_loss = fixed_amount * risk_distance * leverage
                max_allowed_loss = total_balance * (max_risk_percent / 100)
                
                logger.info(
                    f"🛡️ Risk Check:\n"
                    f"   Entry: ${entry_price:.2f}\n"
                    f"   Stop Loss: ${stop_loss:.2f}\n"
                    f"   Distance: {risk_distance*100:.2f}%\n"
                    f"   Expected Loss: ${expected_loss:.2f}\n"
                    f"   Max Allowed Loss ({max_risk_percent}%): ${max_allowed_loss:.2f}"
                )
                
                if expected_loss > max_allowed_loss:
                    scaling_factor = max_allowed_loss / expected_loss
                    fixed_amount = fixed_amount * scaling_factor
                    leveraged_amount = fixed_amount * leverage
                    logger.warning(
                        f"⚠️ Position reduced to respect {max_risk_percent}% max risk:\n"
                        f"   Adjusted Amount: ${fixed_amount:.2f}\n"
                        f"   Adjusted Position: ${leveraged_amount:.2f}"
                    )
            
            position_size = leveraged_amount
            logger.info(
                f"💰 Fixed amount position sizing:\n"
                f"   Fixed Amount: ${fixed_amount:.2f}\n"
                f"   Leverage: {leverage}x\n"
                f"   Position Size: ${position_size:.2f}\n"
                f"   Entry Price: ${entry_price:.2f}"
            )
            
            quantity = position_size / entry_price
            quantity = await self._round_quantity(symbol, quantity, testnet)
            
            # Check minimum order value
            min_order_value = 5.0
            order_value = quantity * entry_price
            
            if order_value < min_order_value:
                min_quantity = (min_order_value * 1.01) / entry_price
                min_quantity = await self._round_quantity(symbol, min_quantity, testnet)
                min_required_balance = (min_order_value * 1.01) / leverage
                
                if total_balance < min_required_balance:
                    return {
                        "success": False,
                        "error": f"❌ Insufficient Balance: ${total_balance:.2f} available. Need minimum ${min_required_balance:.2f} to place $5 order with {leverage}x leverage",
                        "balance_check": {
                            "total": total_balance,
                            "required": min_required_balance,
                            "min_order_value": min_order_value,
                            "status": "BELOW_MINIMUM_ORDER"
                        }
                    }
                
                quantity = min_quantity
                logger.warning(f"⚠️ Order value ${order_value:.2f} below minimum ${min_order_value}. Adjusted to {quantity} coins (${quantity * entry_price:.2f})")
            
            side = "BUY" if signal['side'] == 'buy' else "SELL"
            
            logger.info(f"📊 Binance Trade: {symbol} {side} {quantity} @ ${entry_price} (Leverage: {leverage}x, Value: ${quantity * entry_price:.2f})")
            
            # Set leverage
            await self._set_leverage(symbol, leverage, api_key, api_secret, testnet)
            
            # Place market order
            order_result = await self._place_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=entry_price,
                api_key=api_key,
                api_secret=api_secret,
                testnet=testnet,
                order_type="MARKET"
            )
            
            if not order_result.get('success'):
                return order_result
            
            order_id = order_result.get('order_id')
            logger.info(f"✅ Main order placed successfully: {order_id}")
            
            result = {
                'success': True,
                'order_id': order_id,
                'symbol': symbol,
                'side': side,
                'quantity': quantity,
                'price': entry_price
            }
            
            await asyncio.sleep(2)
            
            # Set stop loss
            if signal.get('stop_loss'):
                stop_prices = signal['stop_loss'] if isinstance(signal['stop_loss'], list) else [signal['stop_loss']]
                stop_price = float(stop_prices[0])
                
                sl_result = await self._place_stop_loss(
                    symbol=symbol,
                    side="SELL" if side == "BUY" else "BUY",
                    quantity=quantity,
                    stop_price=stop_price,
                    api_key=api_key,
                    api_secret=api_secret,
                    testnet=testnet
                )
                result['stop_loss'] = sl_result
            
            # Place take profit orders
            tp_results = []
            if signal.get('take_profit'):
                tp_prices = signal['take_profit'] if isinstance(signal['take_profit'], list) else [signal['take_profit']]
                num_tps = len(tp_prices)
                logger.info(f"Placing {num_tps} take profit orders...")
                
                for i, tp_price in enumerate(tp_prices, start=1):
                    if num_tps == 1:
                        tp_size = quantity
                    else:
                        if i < num_tps:
                            tp_size = quantity / num_tps
                        else:
                            tp_size = quantity - (quantity / num_tps * (num_tps - 1))
                    
                    tp_size = await self._round_quantity(symbol, tp_size, testnet)
                    logger.info(f"TP{i}: {tp_size:.6f} coins (out of {quantity:.6f} total)")
                    
                    tp_result = await self._place_take_profit(
                        symbol=symbol,
                        side="SELL" if side == "BUY" else "BUY",
                        quantity=tp_size,
                        tp_price=float(tp_price),
                        api_key=api_key,
                        api_secret=api_secret,
                        testnet=testnet,
                        tp_number=i
                    )
                    
                    tp_results.append({
                        "level": i,
                        "price": tp_price,
                        "size": tp_size,
                        "result": tp_result
                    })
                    
                    if tp_result.get('success'):
                        logger.info(f"✅ Take Profit {i} placed at ${tp_price} (size: {tp_size:.6f})")
                    else:
                        logger.error(f"❌ Take Profit {i} failed: {tp_result.get('error')}")
            
            result['take_profits'] = tp_results
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Binance trade execution error: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _round_quantity(self, symbol: str, quantity: float, testnet: bool = False) -> float:
        """Round quantity to appropriate decimal places"""
        try:
            url = f"{self._get_base_url(testnet)}/fapi/v1/exchangeInfo?symbol={symbol}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        for symbol_info in data.get('symbols', []):
                            if symbol_info.get('symbol') == symbol:
                                for filter_info in symbol_info.get('filters', []):
                                    if filter_info.get('filterType') == 'LOT_SIZE':
                                        step_size = float(filter_info.get('stepSize', 0.001))
                                        rounded = round(quantity / step_size) * step_size
                                        return round(rounded, 8)
            
            return round(quantity, 3)
        except Exception as e:
            logger.warning(f"⚠️ Error rounding quantity, using default: {e}")
            return round(quantity, 3)
    
    async def _validate_symbol(self, symbol: str, testnet: bool = False) -> bool:
        """Validate if symbol is available for trading"""
        try:
            url = f"{self._get_base_url(testnet)}/fapi/v1/exchangeInfo?symbol={symbol}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        for symbol_info in data.get('symbols', []):
                            if symbol_info.get('symbol') == symbol:
                                status = symbol_info.get('status', '')
                                if status == 'TRADING':
                                    return True
                                else:
                                    logger.warning(f"Symbol {symbol} exists but status is: {status}")
                                    return False
            
            logger.warning(f"Symbol {symbol} not found on Binance")
            return False
        except Exception as e:
            logger.error(f"Error validating symbol {symbol}: {e}")
            return False
    
    async def _set_leverage(self, symbol: str, leverage: int, api_key: str, api_secret: str, testnet: bool = False):
        """Set leverage for a symbol"""
        try:
            timestamp = int(time.time() * 1000)
            query_string = f"symbol={symbol}&leverage={leverage}&timestamp={timestamp}&recvWindow={self._recv_window}"
            signature = self._generate_signature(query_string, api_secret)
            
            url = f"{self._get_base_url(testnet)}/fapi/v1/leverage?{query_string}&signature={signature}"
            headers = self._get_headers(api_key)
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers) as response:
                    if response.status == 200:
                        logger.info(f"✅ Leverage set to {leverage}x for {symbol}")
                    else:
                        data = await response.text()
                        logger.warning(f"⚠️ Failed to set leverage: {data}")
        except Exception as e:
            logger.error(f"❌ Error setting leverage: {e}")
    
    @with_rate_limit(bybit_limiter)
    async def _place_order(self, symbol: str, side: str, quantity: float, price: float,
                          api_key: str, api_secret: str, testnet: bool = False,
                          order_type: str = "LIMIT") -> Dict[str, Any]:
        """Place an order on Binance"""
        try:
            timestamp = int(time.time() * 1000)
            
            params = {
                "symbol": symbol,
                "side": side,
                "type": order_type,
                "quantity": quantity,
                "timestamp": timestamp,
                "recvWindow": self._recv_window
            }
            
            if order_type == "LIMIT":
                params["price"] = price
                params["timeInForce"] = "GTC"
            
            query_string = "&".join([f"{k}={v}" for k, v in params.items()])
            signature = self._generate_signature(query_string, api_secret)
            
            url = f"{self._get_base_url(testnet)}/fapi/v1/order?{query_string}&signature={signature}"
            headers = self._get_headers(api_key)
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers) as response:
                    data = await response.json()
                    
                    if response.status == 200:
                        return {
                            'success': True,
                            'order_id': data.get('orderId'),
                            'client_order_id': data.get('clientOrderId')
                        }
                    else:
                        error_msg = data.get('msg', 'Unknown error')
                        logger.error(f"❌ Order placement failed: {error_msg}")
                        return {'success': False, 'error': error_msg}
        except Exception as e:
            logger.error(f"❌ Error placing order: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _place_stop_loss(self, symbol: str, side: str, quantity: float, stop_price: float,
                              api_key: str, api_secret: str, testnet: bool = False):
        """Place stop loss order"""
        try:
            timestamp = int(time.time() * 1000)
            
            params = {
                "symbol": symbol,
                "side": side,
                "type": "STOP_MARKET",
                "stopPrice": stop_price,
                "quantity": quantity,
                "timestamp": timestamp,
                "recvWindow": self._recv_window,
                "closePosition": "false"
            }
            
            query_string = "&".join([f"{k}={v}" for k, v in params.items()])
            signature = self._generate_signature(query_string, api_secret)
            
            url = f"{self._get_base_url(testnet)}/fapi/v1/order?{query_string}&signature={signature}"
            headers = self._get_headers(api_key)
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers) as response:
                    data = await response.json()
                    if response.status == 200:
                        logger.info(f"✅ Stop Loss placed at ${stop_price}")
                        return {'success': True, 'order_id': data.get('orderId')}
                    else:
                        error_msg = data.get('msg', 'Unknown error')
                        logger.warning(f"⚠️ Stop Loss placement failed: {error_msg}")
                        return {'success': False, 'error': error_msg}
        except Exception as e:
            logger.error(f"❌ Error placing stop loss: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _place_take_profit(self, symbol: str, side: str, quantity: float, tp_price: float,
                                api_key: str, api_secret: str, testnet: bool = False, tp_number: int = 1) -> Dict[str, Any]:
        """Place take profit order"""
        try:
            timestamp = int(time.time() * 1000)
            quantity = await self._round_quantity(symbol, quantity, testnet)
            
            params = {
                "symbol": symbol,
                "side": side,
                "type": "TAKE_PROFIT_MARKET",
                "stopPrice": tp_price,
                "quantity": quantity,
                "timestamp": timestamp,
                "recvWindow": self._recv_window,
                "closePosition": "false"
            }
            
            query_string = "&".join([f"{k}={v}" for k, v in params.items()])
            signature = self._generate_signature(query_string, api_secret)
            
            url = f"{self._get_base_url(testnet)}/fapi/v1/order?{query_string}&signature={signature}"
            headers = self._get_headers(api_key)
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers) as response:
                    data = await response.json()
                    if response.status == 200:
                        logger.info(f"✅ Take Profit {tp_number} placed at ${tp_price}")
                        return {
                            'success': True,
                            'order_id': data.get('orderId'),
                            'price': tp_price,
                            'quantity': quantity
                        }
                    else:
                        error_msg = data.get('msg', 'Unknown error')
                        logger.warning(f"⚠️ Take Profit {tp_number} placement failed: {error_msg}")
                        return {'success': False, 'error': error_msg}
        except Exception as e:
            logger.error(f"❌ Error placing take profit: {e}")
            return {'success': False, 'error': str(e)}
    
    async def update_stop_loss_to_breakeven(self, symbol: str, entry_price: float, side: str,
                                           api_key: str, api_secret: str, testnet: bool = False) -> Dict[str, Any]:
        """Update stop loss to breakeven (entry price) after TP1 hit"""
        try:
            logger.info(f"🔄 Moving stop loss to breakeven for {symbol} at ${entry_price}")
            
            # Cancel existing stop loss orders
            open_orders = await self._get_open_orders(symbol, api_key, api_secret, testnet)
            sl_orders = [order for order in open_orders if order.get('type') == 'STOP_MARKET']
            
            for order in sl_orders:
                await self._cancel_order(symbol, order.get('orderId'), api_key, api_secret, testnet)
            
            # Get current position size
            positions = await self.get_positions({'api_key': api_key, 'api_secret': api_secret, 'testnet': testnet})
            position_size = 0
            for pos in positions:
                if pos.get('symbol') == symbol:
                    position_size = pos.get('size', 0)
                    break
            
            if position_size == 0:
                return {"success": False, "error": "No open position found"}
            
            # Place new stop loss at entry price
            sl_side = "SELL" if side.lower() == "buy" else "BUY"
            result = await self._place_stop_loss(
                symbol=symbol,
                side=sl_side,
                quantity=position_size,
                stop_price=entry_price,
                api_key=api_key,
                api_secret=api_secret,
                testnet=testnet
            )
            
            if result.get('success'):
                logger.info(f"✅ Stop loss moved to breakeven at ${entry_price}")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Error moving stop loss to breakeven: {e}")
            return {"success": False, "error": str(e)}
    
    async def _get_open_orders(self, symbol: str, api_key: str, api_secret: str, testnet: bool = False) -> List[Dict]:
        """Get open orders for symbol"""
        try:
            timestamp = int(time.time() * 1000)
            query_string = f"symbol={symbol}&timestamp={timestamp}&recvWindow={self._recv_window}"
            signature = self._generate_signature(query_string, api_secret)
            
            url = f"{self._get_base_url(testnet)}/fapi/v1/openOrders?{query_string}&signature={signature}"
            headers = self._get_headers(api_key)
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        return await response.json()
            return []
        except Exception as e:
            logger.error(f"❌ Error getting open orders: {e}")
            return []
    
    async def _cancel_order(self, symbol: str, order_id: str, api_key: str, api_secret: str, testnet: bool = False) -> bool:
        """Cancel an order"""
        try:
            timestamp = int(time.time() * 1000)
            query_string = f"symbol={symbol}&orderId={order_id}&timestamp={timestamp}&recvWindow={self._recv_window}"
            signature = self._generate_signature(query_string, api_secret)
            
            url = f"{self._get_base_url(testnet)}/fapi/v1/order?{query_string}&signature={signature}"
            headers = self._get_headers(api_key)
            
            async with aiohttp.ClientSession() as session:
                async with session.delete(url, headers=headers) as response:
                    return response.status == 200
        except Exception as e:
            logger.error(f"❌ Error cancelling order: {e}")
            return False
