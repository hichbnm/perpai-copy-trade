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

# Import new utilities (same as Hyperliquid)
from utils import (
    RiskManager,
    SlippageProtection,
    with_retry,
    with_rate_limit,
    bybit_limiter  # Use dedicated Bybit rate limiter
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class BybitConnector(BaseConnector):
    def __init__(self):
        self.base_url = "https://api.bybit.com"
        self.testnet_url = "https://api-testnet.bybit.com"
        self._recv_window = 5000
        
    def _get_base_url(self, testnet: bool = False) -> str:
        return self.testnet_url if testnet else self.base_url
    
    def _generate_signature(self, params: str, api_secret: str) -> str:
        """Generate HMAC SHA256 signature for Bybit API"""
        return hmac.new(
            api_secret.encode('utf-8'),
            params.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def _get_headers(self, api_key: str, timestamp: str, signature: str, recv_window: str = None) -> Dict[str, str]:
        """Generate headers for Bybit API requests"""
        headers = {
            "X-BAPI-API-KEY": api_key,
            "X-BAPI-SIGN": signature,
            "X-BAPI-TIMESTAMP": timestamp,
            "Content-Type": "application/json"
        }
        if recv_window:
            headers["X-BAPI-RECV-WINDOW"] = recv_window
        else:
            headers["X-BAPI-RECV-WINDOW"] = str(self._recv_window)
        return headers
    
    async def connect(self, credentials: Dict[str, str]) -> bool:
        """Test connection to Bybit"""
        try:
            api_key = credentials.get('api_key')
            api_secret = credentials.get('api_secret')
            testnet = credentials.get('testnet', False)
            
            if not api_key or not api_secret:
                return False
            
            # Test connection by getting account info
            timestamp = str(int(time.time() * 1000))
            recv_window = str(self._recv_window)
            
            # Bybit v5 signature: timestamp + api_key + recv_window + queryString
            param_str = f"accountType=UNIFIED"
            signature_payload = f"{timestamp}{api_key}{recv_window}{param_str}"
            signature = self._generate_signature(signature_payload, api_secret)
            
            url = f"{self._get_base_url(testnet)}/v5/account/wallet-balance?accountType=UNIFIED"
            headers = self._get_headers(api_key, timestamp, signature, recv_window)
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        ret_code = data.get('retCode', -1)
                        ret_msg = data.get('retMsg', 'Unknown error')
                        
                        if ret_code == 0:
                            logger.info("✅ Connected to Bybit successfully")
                            return True
                        elif ret_code == 10003:
                            logger.error(f"❌ Bybit API key is invalid (retCode 10003). Please check your API key on Bybit {'testnet' if testnet else 'mainnet'} and ensure it has correct permissions (Read-Write, Derivatives Trading enabled)")
                            return False
                        else:
                            logger.error(f"❌ Bybit connection failed (retCode: {ret_code}): {ret_msg}")
                            return False
                    else:
                        text = await response.text()
                        logger.error(f"❌ Bybit connection failed (HTTP {response.status}): {text}")
                        return False
            
            return False
        except Exception as e:
            logger.error(f"❌ Bybit connection error: {e}")
            return False
    
    def validate_credentials(self, credentials: Dict[str, str]) -> bool:
        """Validate Bybit API credentials format"""
        api_key = credentials.get('api_key')
        api_secret = credentials.get('api_secret')
        
        if not api_key or not api_secret:
            return False
        
        # Basic validation - Bybit API keys are typically alphanumeric
        if len(api_key) < 10 or len(api_secret) < 10:
            return False
        
        return True
    
    @with_rate_limit(bybit_limiter)
    async def get_balance(self, credentials: Dict[str, str]) -> Dict[str, float]:
        """Get Bybit account balance"""
        try:
            api_key = credentials.get('api_key')
            api_secret = credentials.get('api_secret')
            testnet = credentials.get('testnet', False)
            
            if not api_key or not api_secret:
                logger.error("Missing API key or secret")
                return {'USDT': 0.0}
            
            timestamp = str(int(time.time() * 1000))
            recv_window = str(self._recv_window)
            
            # Bybit v5 signature: timestamp + api_key + recv_window + queryString
            param_str = f"accountType=UNIFIED"
            signature_payload = f"{timestamp}{api_key}{recv_window}{param_str}"
            signature = self._generate_signature(signature_payload, api_secret)
            
            logger.debug(f"🔐 Bybit Auth Debug:")
            logger.debug(f"  Timestamp: {timestamp}")
            logger.debug(f"  Recv Window: {recv_window}")
            logger.debug(f"  API Key: {api_key[:8]}...")
            logger.debug(f"  Signature Payload: {signature_payload}")
            logger.debug(f"  Signature: {signature}")
            
            url = f"{self._get_base_url(testnet)}/v5/account/wallet-balance?accountType=UNIFIED"
            headers = self._get_headers(api_key, timestamp, signature, recv_window)
            
            logger.debug(f"  URL: {url}")
            logger.debug(f"  Headers: {headers}")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        ret_code = data.get('retCode', -1)
                        ret_msg = data.get('retMsg', 'Unknown error')
                        
                        if ret_code == 0:
                            result = data.get('result', {})
                            
                            # Parse unified account balance
                            total_balance_usd = 0.0
                            available_balance_usd = 0.0
                            coins_detail = {}
                            
                            for account in result.get('list', []):
                                # Safely convert values, handling empty strings
                                total_equity = float(account.get('totalEquity') or 0)
                                total_wallet_balance = float(account.get('totalWalletBalance') or 0)
                                available_balance_raw = account.get('totalAvailableBalance', '0')
                                available_balance = float(available_balance_raw) if available_balance_raw and available_balance_raw != '' else 0.0
                                
                                logger.info(f"📊 Bybit Account - Total Equity: ${total_equity:.2f}, Wallet Balance: ${total_wallet_balance:.2f}")
                                
                                # Use total equity as the main balance in USD
                                total_balance_usd = total_equity
                                available_balance_usd = available_balance if available_balance > 0 else total_wallet_balance
                                
                                for coin in account.get('coin', []):
                                    symbol = coin.get('coin')
                                    # Safely convert all float values
                                    equity = float(coin.get('equity') or 0)
                                    wallet_balance = float(coin.get('walletBalance') or 0)
                                    available_to_withdraw = float(coin.get('availableToWithdraw') or 0)
                                    
                                    # Store coin details
                                    if symbol == 'USDT' or equity > 0:
                                        coins_detail[symbol] = {
                                            'equity': equity,
                                            'wallet_balance': wallet_balance,
                                            'available': available_to_withdraw
                                        }
                                        logger.debug(f"  {symbol}: Equity=${equity:.2f}, Wallet=${wallet_balance:.2f}, Available=${available_to_withdraw:.2f}")
                                
                                # Ensure USDT is always included
                                if 'USDT' not in coins_detail:
                                    coins_detail['USDT'] = {'equity': 0.0, 'wallet_balance': 0.0, 'available': 0.0}
                                    logger.warning("⚠️ No USDT balance found in account")
                            
                            # Return balance in the format expected by UI
                            return {
                                'total': total_balance_usd,
                                'available': available_balance_usd,
                                'coins': coins_detail
                            }
                        elif ret_code == 10003:
                            logger.error(f"❌ Bybit API key is invalid (retCode 10003).")
                            logger.error(f"   Please check your API key on Bybit {'testnet' if testnet else 'mainnet'}:")
                            logger.error(f"   1. Verify the API key exists and hasn't been deleted")
                            logger.error(f"   2. Ensure it has Read-Write permissions (not Read-Only)")
                            logger.error(f"   3. Ensure 'Derivatives Trading' permission is enabled")
                            logger.error(f"   4. If the key is invalid, create a new one with /add_api_key")
                            return {}
                        else:
                            logger.error(f"❌ Bybit balance check failed (retCode: {ret_code}): {ret_msg}")
                            return {}
                    else:
                        try:
                            error_data = await response.json()
                            error_msg = error_data.get('retMsg', 'Unknown error')
                            ret_code = error_data.get('retCode', 'N/A')
                            logger.error(f"❌ Bybit balance check failed (HTTP {response.status})")
                            logger.error(f"   retCode: {ret_code}, retMsg: {error_msg}")
                            logger.error(f"   Full response: {error_data}")
                        except:
                            error_text = await response.text()
                            logger.error(f"❌ Bybit balance check failed (HTTP {response.status}): {error_text}")
            
            return {'USDT': 0.0}
        except Exception as e:
            logger.error(f"❌ Error getting Bybit balance: {e}")
            return {}
    
    @with_rate_limit(bybit_limiter)
    async def get_positions(self, credentials: Dict[str, str]) -> List[Dict[str, Any]]:
        """Get open positions on Bybit"""
        try:
            api_key = credentials.get('api_key')
            api_secret = credentials.get('api_secret')
            testnet = credentials.get('testnet', False)
            
            timestamp = str(int(time.time() * 1000))
            recv_window = str(self._recv_window)
            
            # For GET requests: timestamp + api_key + recv_window + queryString
            param_str = f"category=linear&settleCoin=USDT"
            signature_payload = f"{timestamp}{api_key}{recv_window}{param_str}"
            signature = self._generate_signature(signature_payload, api_secret)
            
            url = f"{self._get_base_url(testnet)}/v5/position/list?category=linear&settleCoin=USDT"
            headers = self._get_headers(api_key, timestamp, signature, recv_window)
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('retCode') == 0:
                            positions = []
                            for pos in data.get('result', {}).get('list', []):
                                size = float(pos.get('size', 0))
                                if size > 0:
                                    positions.append({
                                        'symbol': pos.get('symbol'),
                                        'side': pos.get('side'),
                                        'size': size,
                                        'entry_price': float(pos.get('avgPrice', 0)),
                                        'leverage': float(pos.get('leverage', 1)),
                                        'unrealized_pnl': float(pos.get('unrealisedPnl', 0))
                                    })
                            return positions
            
            return []
        except Exception as e:
            logger.error(f"❌ Error getting Bybit positions: {e}")
            return []
    
    async def execute_trade(self, user_data: Dict, signal: Dict) -> Dict[str, Any]:
        """Execute trade on Bybit based on signal - SAME SYSTEM AS HYPERLIQUID"""
        try:
            api_key = user_data.get('api_key')
            api_secret = user_data.get('api_secret')
            testnet = user_data.get('testnet', False)
            
            if not api_key or not api_secret:
                return {'success': False, 'error': 'Missing API credentials'}
            
            # Get balance for position sizing
            balance = await self.get_balance(user_data)
            
            # Extract USDT balance - check if it's the new format with 'coins' or old format
            if 'coins' in balance:
                usdt_info = balance.get('coins', {}).get('USDT', {})
                total_balance = usdt_info.get('equity', 0) if isinstance(usdt_info, dict) else 0
            else:
                total_balance = balance.get('USDT', 0)
            
            # Check if account has sufficient balance
            if total_balance <= 0:
                testnet_hint = ""
                if testnet:
                    testnet_hint = "\n\n💡 **Testnet Tip**: Visit https://testnet.bybit.com and use the faucet to get test USDT"
                return {
                    "success": False,
                    "error": f"❌ Insufficient Balance: Account balance is $0.00{testnet_hint}",
                    "balance_check": {
                        "total": total_balance,
                        "required": "Minimum $10",
                        "status": "NO_BALANCE"
                    }
                }
            
            # Check minimum balance requirement (need at least enough for $5 order at max leverage)
            # With 20x leverage, $5 order requires $0.25 balance minimum
            # But we set a safer minimum of $1 to account for fees and price movements
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
            
            # Prepare symbol (Bybit format)
            symbol = signal.get('symbol', '').upper()
            if not symbol.endswith('USDT'):
                symbol = f"{symbol}USDT"
            
            # Validate symbol availability on Bybit
            symbol_valid = await self._validate_symbol(symbol, testnet)
            if not symbol_valid:
                return {
                    "success": False,
                    "error": f"❌ Symbol Not Available: {symbol} is not tradeable on Bybit",
                    "symbol_check": {
                        "requested": signal.get('symbol'),
                        "cleaned": symbol,
                        "status": "NOT_AVAILABLE"
                    }
                }
            
            # 🆕 USE RISK MANAGER FOR POSITION SIZING (same as Hyperliquid)
            entry_price = float(signal.get('entry', [0])[0] if signal.get('entry') else 0)
            stop_loss = float(signal.get('stop_loss', [0])[0] if signal.get('stop_loss') else 0)
            leverage = signal.get('leverage', Config.DEFAULT_LEVERAGE)
            
            if entry_price <= 0:
                return {
                    "success": False,
                    "error": "❌ Missing entry price for order placement"
                }
            
            # Use fixed amount from subscription settings
            fixed_amount = user_data.get('fixed_amount', 100.0)
            max_risk_percent = user_data.get('max_risk', 2.0)
            
            # Apply leverage to the fixed amount
            leveraged_amount = fixed_amount * leverage
            
            # Safety check: if stop loss exists, ensure loss doesn't exceed max_risk
            if stop_loss > 0:
                # Calculate distance to stop loss
                price_distance = abs(entry_price - stop_loss)
                risk_distance = price_distance / entry_price
                
                # Calculate expected loss if SL hits
                expected_loss = fixed_amount * risk_distance * leverage
                
                # Calculate max allowed loss based on balance
                max_allowed_loss = total_balance * (max_risk_percent / 100)
                
                logger.info(
                    f"🛡️ Risk Check:\n"
                    f"   Entry: ${entry_price:.2f}\n"
                    f"   Stop Loss: ${stop_loss:.2f}\n"
                    f"   Distance: {risk_distance*100:.2f}%\n"
                    f"   Expected Loss: ${expected_loss:.2f}\n"
                    f"   Max Allowed Loss ({max_risk_percent}%): ${max_allowed_loss:.2f}"
                )
                
                # If expected loss exceeds max risk, scale down position
                if expected_loss > max_allowed_loss:
                    scaling_factor = max_allowed_loss / expected_loss
                    fixed_amount = fixed_amount * scaling_factor
                    leveraged_amount = fixed_amount * leverage
                    logger.warning(
                        f"⚠️ Position reduced to respect {max_risk_percent}% max risk:\n"
                        f"   Adjusted Amount: ${fixed_amount:.2f}\n"
                        f"   Adjusted Position: ${leveraged_amount:.2f}"
                    )
            
            # Calculate position size in USD (this is what we'll trade with)
            position_size = leveraged_amount
            
            logger.info(
                f"💰 Fixed amount position sizing:\n"
                f"   Fixed Amount: ${fixed_amount:.2f}\n"
                f"   Leverage: {leverage}x\n"
                f"   Position Size: ${position_size:.2f}\n"
                f"   Entry Price: ${entry_price:.2f}"
            )
            
            # Calculate quantity based on entry price
            quantity = position_size / entry_price
            quantity = await self._round_quantity(symbol, quantity, testnet)
            
            # Check minimum order value (Bybit requires $5 USDT minimum)
            min_order_value = 5.0
            order_value = quantity * entry_price
            
            if order_value < min_order_value:
                # Calculate minimum quantity needed with 1% buffer to account for rounding
                min_quantity = (min_order_value * 1.01) / entry_price
                min_quantity = await self._round_quantity(symbol, min_quantity, testnet)
                
                # Check if user has enough balance for minimum order
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
                
                # Use minimum quantity
                quantity = min_quantity
                logger.warning(f"⚠️ Order value ${order_value:.2f} below minimum ${min_order_value}. Adjusted to {quantity} coins (${quantity * entry_price:.2f})")
            
            side = "Buy" if signal['side'] == 'buy' else "Sell"
            
            logger.info(f"📊 Bybit Trade: {symbol} {side} {quantity} @ ${entry_price} (Leverage: {leverage}x, Value: ${quantity * entry_price:.2f})")
            
            # Set leverage first
            await self._set_leverage(symbol, leverage, api_key, api_secret, testnet)
            
            # Place main order as MARKET order for immediate fill
            order_result = await self._place_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=entry_price,
                api_key=api_key,
                api_secret=api_secret,
                testnet=testnet,
                order_type="Market"  # Execute at market price for instant fill
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
            
            # Wait a moment for order to fill and position to open
            await asyncio.sleep(2)
            
            # Set stop loss via trading-stop endpoint if specified
            if signal.get('stop_loss'):
                stop_prices = signal['stop_loss'] if isinstance(signal['stop_loss'], list) else [signal['stop_loss']]
                stop_price = float(stop_prices[0])
                
                sl_result = await self._set_trading_stop(
                    symbol=symbol,
                    side=side,
                    stop_loss=stop_price,
                    api_key=api_key,
                    api_secret=api_secret,
                    testnet=testnet
                )
                result['stop_loss'] = sl_result
            
            # Place take profit orders with position splitting (SAME AS HYPERLIQUID)
            tp_results = []
            if signal.get('take_profit'):
                tp_prices = signal['take_profit'] if isinstance(signal['take_profit'], list) else [signal['take_profit']]
                num_tps = len(tp_prices)
                logger.info(f"Placing {num_tps} take profit orders...")
                
                # Split position size across TPs
                for i, tp_price in enumerate(tp_prices, start=1):
                    if num_tps == 1:
                        # Single TP: use full size
                        tp_size = quantity
                    else:
                        # Multiple TPs: split evenly, last TP gets remainder
                        if i < num_tps:
                            tp_size = quantity / num_tps
                        else:
                            # Last TP: calculate remainder to ensure full position is covered
                            tp_size = quantity - (quantity / num_tps * (num_tps - 1))
                    
                    tp_size = await self._round_quantity(symbol, tp_size, testnet)
                    logger.info(f"TP{i}: {tp_size:.6f} coins (out of {quantity:.6f} total)")
                    
                    tp_result = await self._place_take_profit(
                        symbol=symbol,
                        side='Sell' if side == 'Buy' else 'Buy',
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
            logger.error(f"❌ Bybit trade execution error: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _round_quantity(self, symbol: str, quantity: float, testnet: bool = False) -> float:
        """Round quantity to appropriate decimal places based on symbol info"""
        try:
            url = f"{self._get_base_url(testnet)}/v5/market/instruments-info?category=linear&symbol={symbol}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('retCode') == 0:
                            instruments = data.get('result', {}).get('list', [])
                            if instruments:
                                lot_size_filter = instruments[0].get('lotSizeFilter', {})
                                qty_step = float(lot_size_filter.get('qtyStep', 0.001))
                                
                                # Round to the nearest step
                                rounded = round(quantity / qty_step) * qty_step
                                return round(rounded, 8)  # Max 8 decimals
            
            # Default rounding
            return round(quantity, 3)
        except Exception as e:
            logger.warning(f"⚠️ Error rounding quantity, using default: {e}")
            return round(quantity, 3)
    
    async def _validate_symbol(self, symbol: str, testnet: bool = False) -> bool:
        """Validate if symbol is available for trading on Bybit"""
        try:
            url = f"{self._get_base_url(testnet)}/v5/market/instruments-info?category=linear&symbol={symbol}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('retCode') == 0:
                            instruments = data.get('result', {}).get('list', [])
                            if instruments and len(instruments) > 0:
                                # Check if trading is enabled
                                status = instruments[0].get('status', '')
                                if status == 'Trading':
                                    return True
                                else:
                                    logger.warning(f"Symbol {symbol} exists but status is: {status}")
                                    return False
            
            logger.warning(f"Symbol {symbol} not found on Bybit")
            return False
        except Exception as e:
            logger.error(f"Error validating symbol {symbol}: {e}")
            return False
    
    async def _set_leverage(self, symbol: str, leverage: int, api_key: str, api_secret: str, testnet: bool = False):
        """Set leverage for a symbol"""
        try:
            timestamp = str(int(time.time() * 1000))
            recv_window = str(self._recv_window)
            
            params = {
                "category": "linear",
                "symbol": symbol,
                "buyLeverage": str(leverage),
                "sellLeverage": str(leverage)
            }
            
            body_str = json.dumps(params)
            signature_payload = f"{timestamp}{api_key}{recv_window}{body_str}"
            signature = self._generate_signature(signature_payload, api_secret)
            
            url = f"{self._get_base_url(testnet)}/v5/position/set-leverage"
            headers = self._get_headers(api_key, timestamp, signature, recv_window)
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=params, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('retCode') == 0:
                            logger.info(f"✅ Leverage set to {leverage}x for {symbol}")
                        else:
                            logger.warning(f"⚠️ Failed to set leverage: {data.get('retMsg')}")
        except Exception as e:
            logger.error(f"❌ Error setting leverage: {e}")
    
    @with_rate_limit(bybit_limiter)
    async def _place_order(self, symbol: str, side: str, quantity: float, price: float,
                          api_key: str, api_secret: str, testnet: bool = False,
                          order_type: str = "Limit") -> Dict[str, Any]:
        """Place an order on Bybit"""
        try:
            timestamp = str(int(time.time() * 1000))
            recv_window = str(self._recv_window)
            
            order_params = {
                "category": "linear",
                "symbol": symbol,
                "side": side,
                "orderType": order_type,
                "qty": str(quantity)
            }
            
            # Only add price for limit orders
            if order_type == "Limit":
                order_params["price"] = str(price)
                order_params["timeInForce"] = "GTC"  # Good Till Cancel
            
            # For POST requests: timestamp + api_key + recv_window + json_body
            body_str = json.dumps(order_params)
            signature_payload = f"{timestamp}{api_key}{recv_window}{body_str}"
            signature = self._generate_signature(signature_payload, api_secret)
            
            url = f"{self._get_base_url(testnet)}/v5/order/create"
            headers = self._get_headers(api_key, timestamp, signature, recv_window)
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=order_params, headers=headers) as response:
                    data = await response.json()
                    
                    if response.status == 200 and data.get('retCode') == 0:
                        result = data.get('result', {})
                        return {
                            'success': True,
                            'order_id': result.get('orderId'),
                            'order_link_id': result.get('orderLinkId')
                        }
                    else:
                        error_msg = data.get('retMsg', 'Unknown error')
                        logger.error(f"❌ Order placement failed: {error_msg}")
                        return {'success': False, 'error': error_msg}
        except Exception as e:
            logger.error(f"❌ Error placing order: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _set_trading_stop(self, symbol: str, side: str, stop_loss: float,
                              api_key: str, api_secret: str, testnet: bool = False):
        """Set stop loss via trading-stop endpoint (for existing positions)"""
        try:
            timestamp = str(int(time.time() * 1000))
            recv_window = str(self._recv_window)
            
            params = {
                "category": "linear",
                "symbol": symbol,
                "stopLoss": str(stop_loss),
                "slTriggerBy": "LastPrice",
                "positionIdx": 0  # One-way mode
            }
            
            body_str = json.dumps(params)
            signature_payload = f"{timestamp}{api_key}{recv_window}{body_str}"
            signature = self._generate_signature(signature_payload, api_secret)
            
            url = f"{self._get_base_url(testnet)}/v5/position/trading-stop"
            headers = self._get_headers(api_key, timestamp, signature, recv_window)
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=params, headers=headers) as response:
                    data = await response.json()
                    if data.get('retCode') == 0:
                        logger.info(f"✅ Stop Loss set at ${stop_loss}")
                        return {'success': True}
                    else:
                        logger.warning(f"⚠️ Stop Loss failed: {data.get('retMsg')}")
                        return {'success': False, 'error': data.get('retMsg')}
        except Exception as e:
            logger.error(f"❌ Error setting stop loss: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _place_stop_loss(self, symbol: str, side: str, quantity: float, stop_price: float,
                              api_key: str, api_secret: str, testnet: bool = False):
        """Place stop loss order (DEPRECATED - use _set_trading_stop instead)"""
        try:
            timestamp = str(int(time.time() * 1000))
            
            order_params = {
                "category": "linear",
                "symbol": symbol,
                "side": side,
                "orderType": "Market",
                "qty": str(quantity),
                "stopLoss": str(stop_price),
                "slTriggerBy": "LastPrice",
                "timeInForce": "GTC"
            }
            
            recv_window = str(self._recv_window)
            body_str = json.dumps(order_params)
            signature_payload = f"{timestamp}{api_key}{recv_window}{body_str}"
            signature = self._generate_signature(signature_payload, api_secret)
            
            url = f"{self._get_base_url(testnet)}/v5/order/create"
            headers = self._get_headers(api_key, timestamp, signature, recv_window)
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=order_params, headers=headers) as response:
                    data = await response.json()
                    if data.get('retCode') == 0:
                        logger.info(f"✅ Stop Loss placed at ${stop_price}")
                    else:
                        logger.warning(f"⚠️ Stop Loss placement failed: {data.get('retMsg')}")
        except Exception as e:
            logger.error(f"❌ Error placing stop loss: {e}")
    
    async def _place_take_profit(self, symbol: str, side: str, quantity: float, tp_price: float,
                                api_key: str, api_secret: str, testnet: bool = False, tp_number: int = 1) -> Dict[str, Any]:
        """Place take profit order"""
        try:
            timestamp = str(int(time.time() * 1000))
            recv_window = str(self._recv_window)
            
            # Round quantity for TP order
            quantity = await self._round_quantity(symbol, quantity, testnet)
            
            order_params = {
                "category": "linear",
                "symbol": symbol,
                "side": side,
                "orderType": "Limit",
                "qty": str(quantity),
                "price": str(tp_price),
                "timeInForce": "GTC",
                "reduceOnly": True  # Important for TP orders
            }
            
            body_str = json.dumps(order_params)
            signature_payload = f"{timestamp}{api_key}{recv_window}{body_str}"
            signature = self._generate_signature(signature_payload, api_secret)
            
            url = f"{self._get_base_url(testnet)}/v5/order/create"
            headers = self._get_headers(api_key, timestamp, signature, recv_window)
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=order_params, headers=headers) as response:
                    data = await response.json()
                    if data.get('retCode') == 0:
                        result = data.get('result', {})
                        logger.info(f"✅ Take Profit {tp_number} placed at ${tp_price}")
                        return {
                            'success': True,
                            'order_id': result.get('orderId'),
                            'price': tp_price,
                            'quantity': quantity
                        }
                    else:
                        error_msg = data.get('retMsg', 'Unknown error')
                        logger.warning(f"⚠️ Take Profit {tp_number} placement failed: {error_msg}")
                        return {
                            'success': False,
                            'error': error_msg
                        }
        except Exception as e:
            logger.error(f"❌ Error placing take profit: {e}")
            return {
                'success': False,
                'error': str(e)
            }
