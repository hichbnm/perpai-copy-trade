import aiohttp
import asyncio
import hmac
import hashlib
import json
import time
import base64
from datetime import datetime, timezone
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

class OKXConnector(BaseConnector):
    """Connector for OKX exchange"""
    def __init__(self):
        self.base_url = "https://www.okx.com"
        self.testnet_url = "https://www.okx.com"  # OKX uses demo trading mode
        self.active_orders: Dict[str, Dict[str, Any]] = {}
        
    def _get_base_url(self, testnet: bool = False) -> str:
        return self.base_url  # OKX uses same URL for demo/live
    
    def _generate_signature(self, timestamp: str, method: str, request_path: str, body: str, api_secret: str) -> str:
        """Generate signature for OKX API"""
        message = timestamp + method + request_path + body
        mac = hmac.new(
            api_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        )
        return base64.b64encode(mac.digest()).decode()
    
    def _get_headers(self, api_key: str, passphrase: str, timestamp: str, signature: str, testnet: bool = False) -> Dict[str, str]:
        """Generate headers for OKX API requests"""
        headers = {
            "OK-ACCESS-KEY": api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": passphrase,
            "Content-Type": "application/json"
        }
        if testnet:
            headers["x-simulated-trading"] = "1"
        return headers
    
    async def connect(self, credentials: Dict[str, str]) -> bool:
        """Test connection to OKX"""
        try:
            api_key = credentials.get('api_key')
            api_secret = credentials.get('api_secret')
            passphrase = credentials.get('passphrase')
            testnet = credentials.get('testnet', False)
            
            if not api_key or not api_secret or not passphrase:
                return False
            
            # Test connection by getting account info
            timestamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
            method = "GET"
            request_path = "/api/v5/account/balance"
            body = ""
            
            signature = self._generate_signature(timestamp, method, request_path, body, api_secret)
            
            url = f"{self._get_base_url(testnet)}{request_path}"
            headers = self._get_headers(api_key, passphrase, timestamp, signature, testnet)
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('code') == '0':
                            logger.info("✅ Connected to OKX successfully")
                            return True
                        else:
                            logger.error(f"❌ OKX connection failed: {data.get('msg')}")
                            return False
                    else:
                        text = await response.text()
                        logger.error(f"❌ OKX connection failed (HTTP {response.status}): {text}")
                        return False
            
        except Exception as e:
            logger.error(f"❌ OKX connection error: {e}")
            return False
    
    def validate_credentials(self, credentials: Dict[str, str]) -> bool:
        """Validate OKX API credentials format"""
        api_key = credentials.get('api_key')
        api_secret = credentials.get('api_secret')
        passphrase = credentials.get('passphrase')
        
        if not api_key or not api_secret or not passphrase:
            return False
        
        if len(api_key) < 10 or len(api_secret) < 10:
            return False
        
        return True
    
    @with_rate_limit(bybit_limiter)
    async def get_balance(self, credentials: Dict[str, str]) -> Dict[str, float]:
        """Get OKX account balance"""
        try:
            api_key = credentials.get('api_key')
            api_secret = credentials.get('api_secret')
            passphrase = credentials.get('passphrase')
            testnet = credentials.get('testnet', False)
            
            if not api_key or not api_secret or not passphrase:
                logger.error("Missing API credentials")
                return {'USDT': 0.0}
            
            timestamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
            method = "GET"
            request_path = "/api/v5/account/balance"
            body = ""
            
            signature = self._generate_signature(timestamp, method, request_path, body, api_secret)
            
            url = f"{self._get_base_url(testnet)}{request_path}"
            headers = self._get_headers(api_key, passphrase, timestamp, signature, testnet)
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('code') == '0':
                            balance_data = data.get('data', [])
                            if balance_data:
                                total_eq = float(balance_data[0].get('totalEq', 0))
                                
                                coins_detail = {}
                                for detail in balance_data[0].get('details', []):
                                    ccy = detail.get('ccy')
                                    eq = float(detail.get('eq', 0))
                                    avail_bal = float(detail.get('availBal', 0))
                                    
                                    if ccy == 'USDT' or eq > 0:
                                        coins_detail[ccy] = {
                                            'equity': eq,
                                            'wallet_balance': eq,
                                            'available': avail_bal
                                        }
                                
                                logger.info(f"📊 OKX Account - Total Equity: ${total_eq:.2f}")
                                
                                return {
                                    'total': total_eq,
                                    'available': total_eq,
                                    'coins': coins_detail
                                }
                        else:
                            logger.error(f"❌ OKX balance check failed: {data.get('msg')}")
                            return {}
                    else:
                        error_data = await response.text()
                        logger.error(f"❌ OKX balance check failed (HTTP {response.status}): {error_data}")
                        return {}
            
        except Exception as e:
            logger.error(f"❌ Error getting OKX balance: {e}")
            return {}
    
    @with_rate_limit(bybit_limiter)
    async def get_positions(self, credentials: Dict[str, str]) -> List[Dict[str, Any]]:
        """Get open positions on OKX"""
        try:
            api_key = credentials.get('api_key')
            api_secret = credentials.get('api_secret')
            passphrase = credentials.get('passphrase')
            testnet = credentials.get('testnet', False)
            
            timestamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
            method = "GET"
            request_path = "/api/v5/account/positions"
            body = ""
            
            signature = self._generate_signature(timestamp, method, request_path, body, api_secret)
            
            url = f"{self._get_base_url(testnet)}{request_path}"
            headers = self._get_headers(api_key, passphrase, timestamp, signature, testnet)
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('code') == '0':
                            positions = []
                            for pos in data.get('data', []):
                                pos_amt = float(pos.get('pos', 0))
                                if pos_amt != 0:
                                    positions.append({
                                        'symbol': pos.get('instId'),
                                        'side': 'long' if pos.get('posSide') == 'long' else 'short',
                                        'size': abs(pos_amt),
                                        'entry_price': float(pos.get('avgPx', 0)),
                                        'leverage': float(pos.get('lever', 1)),
                                        'unrealized_pnl': float(pos.get('upl', 0))
                                    })
                            return positions
            
            return []
        except Exception as e:
            logger.error(f"❌ Error getting OKX positions: {e}")
            return []
    
    async def execute_trade(self, user_data: Dict, signal: Dict) -> Dict[str, Any]:
        """Execute trade on OKX based on signal - SAME SYSTEM AS HYPERLIQUID/BYBIT"""
        try:
            api_key = user_data.get('api_key')
            api_secret = user_data.get('api_secret')
            passphrase = user_data.get('passphrase')
            testnet = user_data.get('testnet', False)
            
            if not api_key or not api_secret or not passphrase:
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
                    testnet_hint = "\n\n💡 **Testnet Tip**: Use OKX demo trading mode"
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
            
            # Prepare symbol (OKX format: BTC-USDT-SWAP)
            symbol = signal.get('symbol', '').upper()
            if not '-USDT-SWAP' in symbol:
                symbol = f"{symbol}-USDT-SWAP"
            
            # Validate symbol
            symbol_valid = await self._validate_symbol(symbol, testnet)
            if not symbol_valid:
                return {
                    "success": False,
                    "error": f"❌ Symbol Not Available: {symbol} is not tradeable on OKX",
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
            
            # OKX uses contracts, need to get contract value
            contract_val = await self._get_contract_value(symbol, testnet)
            quantity = (position_size / entry_price) / contract_val if contract_val > 0 else position_size / entry_price
            quantity = round(quantity)  # OKX uses whole contracts
            
            # Check minimum order value
            min_order_value = 5.0
            order_value = quantity * contract_val * entry_price
            
            if order_value < min_order_value:
                quantity = max(1, round(min_order_value / (contract_val * entry_price)))
                logger.warning(f"⚠️ Adjusted quantity to minimum: {quantity} contracts")
            
            side = "buy" if signal['side'] == 'buy' else "sell"
            
            logger.info(f"📊 OKX Trade: {symbol} {side} {quantity} contracts @ ${entry_price} (Leverage: {leverage}x)")
            
            # Set leverage
            await self._set_leverage(symbol, leverage, api_key, api_secret, passphrase, testnet)
            
            # Place market order
            order_result = await self._place_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=entry_price,
                api_key=api_key,
                api_secret=api_secret,
                passphrase=passphrase,
                testnet=testnet,
                order_type="market"
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
                    side="sell" if side == "buy" else "buy",
                    quantity=quantity,
                    stop_price=stop_price,
                    api_key=api_key,
                    api_secret=api_secret,
                    passphrase=passphrase,
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
                            tp_size = round(quantity / num_tps)
                        else:
                            tp_size = quantity - (round(quantity / num_tps) * (num_tps - 1))
                    
                    logger.info(f"TP{i}: {tp_size} contracts (out of {quantity} total)")
                    
                    tp_result = await self._place_take_profit(
                        symbol=symbol,
                        side="sell" if side == "buy" else "buy",
                        quantity=tp_size,
                        tp_price=float(tp_price),
                        api_key=api_key,
                        api_secret=api_secret,
                        passphrase=passphrase,
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
                        logger.info(f"✅ Take Profit {i} placed at ${tp_price} (size: {tp_size} contracts)")
                    else:
                        logger.error(f"❌ Take Profit {i} failed: {tp_result.get('error')}")
            
            result['take_profits'] = tp_results
            
            return result
            
        except Exception as e:
            logger.error(f"❌ OKX trade execution error: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _get_contract_value(self, symbol: str, testnet: bool = False) -> float:
        """Get contract value for symbol"""
        try:
            url = f"{self._get_base_url(testnet)}/api/v5/public/instruments?instType=SWAP&instId={symbol}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('code') == '0':
                            instruments = data.get('data', [])
                            if instruments:
                                return float(instruments[0].get('ctVal', 1))
            return 1.0
        except Exception as e:
            logger.warning(f"⚠️ Error getting contract value: {e}")
            return 1.0
    
    async def _validate_symbol(self, symbol: str, testnet: bool = False) -> bool:
        """Validate if symbol is available for trading"""
        try:
            url = f"{self._get_base_url(testnet)}/api/v5/public/instruments?instType=SWAP&instId={symbol}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('code') == '0':
                            instruments = data.get('data', [])
                            if instruments and len(instruments) > 0:
                                state = instruments[0].get('state', '')
                                if state == 'live':
                                    return True
                                else:
                                    logger.warning(f"Symbol {symbol} exists but state is: {state}")
                                    return False
            
            logger.warning(f"Symbol {symbol} not found on OKX")
            return False
        except Exception as e:
            logger.error(f"Error validating symbol {symbol}: {e}")
            return False
    
    async def _set_leverage(self, symbol: str, leverage: int, api_key: str, api_secret: str, passphrase: str, testnet: bool = False):
        """Set leverage for a symbol"""
        try:
            timestamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
            method = "POST"
            request_path = "/api/v5/account/set-leverage"
            
            body_data = {
                "instId": symbol,
                "lever": str(leverage),
                "mgnMode": "cross"
            }
            body = json.dumps(body_data)
            
            signature = self._generate_signature(timestamp, method, request_path, body, api_secret)
            
            url = f"{self._get_base_url(testnet)}{request_path}"
            headers = self._get_headers(api_key, passphrase, timestamp, signature, testnet)
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=body, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('code') == '0':
                            logger.info(f"✅ Leverage set to {leverage}x for {symbol}")
                        else:
                            logger.warning(f"⚠️ Failed to set leverage: {data.get('msg')}")
        except Exception as e:
            logger.error(f"❌ Error setting leverage: {e}")
    
    @with_rate_limit(bybit_limiter)
    async def _place_order(self, symbol: str, side: str, quantity: float, price: float,
                          api_key: str, api_secret: str, passphrase: str, testnet: bool = False,
                          order_type: str = "limit") -> Dict[str, Any]:
        """Place an order on OKX"""
        try:
            timestamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
            method = "POST"
            request_path = "/api/v5/trade/order"
            
            order_data = {
                "instId": symbol,
                "tdMode": "cross",
                "side": side,
                "ordType": order_type,
                "sz": str(int(quantity))
            }
            
            if order_type == "limit":
                order_data["px"] = str(price)
            
            body = json.dumps(order_data)
            signature = self._generate_signature(timestamp, method, request_path, body, api_secret)
            
            url = f"{self._get_base_url(testnet)}{request_path}"
            headers = self._get_headers(api_key, passphrase, timestamp, signature, testnet)
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=body, headers=headers) as response:
                    data = await response.json()
                    
                    if response.status == 200 and data.get('code') == '0':
                        result = data.get('data', [{}])[0]
                        return {
                            'success': True,
                            'order_id': result.get('ordId'),
                            'client_order_id': result.get('clOrdId')
                        }
                    else:
                        error_msg = data.get('msg', 'Unknown error')
                        logger.error(f"❌ Order placement failed: {error_msg}")
                        return {'success': False, 'error': error_msg}
        except Exception as e:
            logger.error(f"❌ Error placing order: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _place_stop_loss(self, symbol: str, side: str, quantity: float, stop_price: float,
                              api_key: str, api_secret: str, passphrase: str, testnet: bool = False):
        """Place stop loss order"""
        try:
            timestamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
            method = "POST"
            request_path = "/api/v5/trade/order-algo"
            
            order_data = {
                "instId": symbol,
                "tdMode": "cross",
                "side": side,
                "ordType": "conditional",
                "sz": str(int(quantity)),
                "slTriggerPx": str(stop_price),
                "slOrdPx": "-1"  # Market price
            }
            
            body = json.dumps(order_data)
            signature = self._generate_signature(timestamp, method, request_path, body, api_secret)
            
            url = f"{self._get_base_url(testnet)}{request_path}"
            headers = self._get_headers(api_key, passphrase, timestamp, signature, testnet)
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=body, headers=headers) as response:
                    data = await response.json()
                    if response.status == 200 and data.get('code') == '0':
                        logger.info(f"✅ Stop Loss placed at ${stop_price}")
                        return {'success': True, 'order_id': data.get('data', [{}])[0].get('algoId')}
                    else:
                        error_msg = data.get('msg', 'Unknown error')
                        logger.warning(f"⚠️ Stop Loss placement failed: {error_msg}")
                        return {'success': False, 'error': error_msg}
        except Exception as e:
            logger.error(f"❌ Error placing stop loss: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _place_take_profit(self, symbol: str, side: str, quantity: float, tp_price: float,
                                api_key: str, api_secret: str, passphrase: str, testnet: bool = False, tp_number: int = 1) -> Dict[str, Any]:
        """Place take profit order"""
        try:
            timestamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
            method = "POST"
            request_path = "/api/v5/trade/order"
            
            order_data = {
                "instId": symbol,
                "tdMode": "cross",
                "side": side,
                "ordType": "limit",
                "sz": str(int(quantity)),
                "px": str(tp_price),
                "reduceOnly": True
            }
            
            body = json.dumps(order_data)
            signature = self._generate_signature(timestamp, method, request_path, body, api_secret)
            
            url = f"{self._get_base_url(testnet)}{request_path}"
            headers = self._get_headers(api_key, passphrase, timestamp, signature, testnet)
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=body, headers=headers) as response:
                    data = await response.json()
                    if response.status == 200 and data.get('code') == '0':
                        logger.info(f"✅ Take Profit {tp_number} placed at ${tp_price}")
                        return {
                            'success': True,
                            'order_id': data.get('data', [{}])[0].get('ordId'),
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
                                           api_key: str, api_secret: str, passphrase: str, testnet: bool = False) -> Dict[str, Any]:
        """Update stop loss to breakeven (entry price) after TP1 hit"""
        try:
            logger.info(f"🔄 Moving stop loss to breakeven for {symbol} at ${entry_price}")
            
            # Cancel existing stop loss orders (algo orders)
            timestamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
            method = "POST"
            request_path = "/api/v5/trade/cancel-algos"
            
            # Get and cancel all algo orders for this symbol
            # Note: In production, you'd query open algo orders first
            
            # Get current position size
            positions = await self.get_positions({'api_key': api_key, 'api_secret': api_secret, 'passphrase': passphrase, 'testnet': testnet})
            position_size = 0
            for pos in positions:
                if pos.get('symbol') == symbol:
                    position_size = pos.get('size', 0)
                    break
            
            if position_size == 0:
                return {"success": False, "error": "No open position found"}
            
            # Place new stop loss at entry price
            sl_side = "sell" if side.lower() == "buy" else "buy"
            result = await self._place_stop_loss(
                symbol=symbol,
                side=sl_side,
                quantity=position_size,
                stop_price=entry_price,
                api_key=api_key,
                api_secret=api_secret,
                passphrase=passphrase,
                testnet=testnet
            )
            
            if result.get('success'):
                logger.info(f"✅ Stop loss moved to breakeven at ${entry_price}")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Error moving stop loss to breakeven: {e}")
            return {"success": False, "error": str(e)}
