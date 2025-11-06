import aiohttp
import hmac
import hashlib
import json
import time
import string
from typing import Dict, Any, List, Optional
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from .base_connector import BaseConnector
from config import Config
import logging
from eth_account import Account
from hyperliquid.utils.signing import (
    order_request_to_order_wire,
    order_wires_to_order_action,
    sign_l1_action,
)
from hyperliquid.utils.types import Cloid

# Import new utilities
from utils import (
    RiskManager,
    SlippageProtection,
    with_retry,
    with_rate_limit,
    hyperliquid_limiter
)

logger = logging.getLogger(__name__)

# Hyperliquid tick size lookup table (based on observed exchange behavior)
# Format: {symbol: tick_size_as_decimal_string}
TICK_SIZE_LOOKUP = {
    'BTC': '0.5',     # Bitcoin: $0.50 tick
    'ETH': '0.05',    # Ethereum: $0.05 tick
    'SOL': '0.001',   # Solana: $0.001 tick
    'BNB': '0.01',    # BNB: $0.01 tick
    'AVAX': '0.001',  # Avalanche: $0.001 tick
    'DOGE': '0.00001',# Dogecoin: $0.00001 tick
    'ARB': '0.0001',  # Arbitrum: $0.0001 tick
    'OP': '0.0001',   # Optimism: $0.0001 tick
    'SUI': '0.0001',  # Sui: $0.0001 tick
    'MATIC': '0.0001',# Polygon: $0.0001 tick
    'ATOM': '0.001',  # Cosmos: $0.001 tick
    'LTC': '0.01',    # Litecoin: $0.01 tick
    'INJ': '0.001',   # Injective: $0.001 tick
    'DYDX': '0.001',  # dYdX: $0.001 tick
    'APE': '0.001',   # ApeCoin: $0.001 tick
}

class HyperliquidConnector(BaseConnector):
    def __init__(self):
        self.base_url = Config.HYPERLIQUID_BASE_URL
        self.testnet_url = Config.HYPERLIQUID_TESTNET_URL
        self._asset_cache: Dict[str, Dict[str, Any]] = {}
        self._asset_cache_timestamp: Dict[str, float] = {}
        self.active_orders: Dict[str, Dict[str, Any]] = {}  # Track orders by user_id
        self.position_monitors: Dict[str, Any] = {}  # Track monitoring tasks
        self._discovered_ticks: Dict[str, str] = {}  # Cache discovered tick sizes: {symbol: tick_size}
        self._load_tick_cache()
    
    def _load_tick_cache(self):
        """Load previously discovered tick sizes from file"""
        try:
            import os
            tick_file = 'data/discovered_ticks.json'
            if os.path.exists(tick_file):
                with open(tick_file, 'r') as f:
                    self._discovered_ticks = json.load(f)
                logger.info(f"Loaded {len(self._discovered_ticks)} discovered tick sizes from cache")
        except Exception as e:
            logger.warning(f"Could not load tick cache: {e}")
    
    def _save_tick_cache(self):
        """Save discovered tick sizes to file"""
        try:
            import os
            os.makedirs('data', exist_ok=True)
            tick_file = 'data/discovered_ticks.json'
            with open(tick_file, 'w') as f:
                json.dump(self._discovered_ticks, f, indent=2)
            logger.debug(f"Saved {len(self._discovered_ticks)} discovered tick sizes to cache")
        except Exception as e:
            logger.warning(f"Could not save tick cache: {e}")
    
    def _get_base_url(self, testnet: bool = False) -> str:
        return self.testnet_url if testnet else self.base_url

    def _normalize_wallet_address(self, raw: Optional[str]) -> Optional[str]:
        """Return a cleaned Hyperliquid wallet address or None if invalid."""
        if not raw:
            return None

        addr = raw.strip()

        # Remove common formatting artefacts (copy/paste ellipsis, spaces)
        if '...' in addr:
            addr = addr.split('...')[0]
        addr = addr.replace(' ', '')

        # Hyperliquid expects a 0x-prefixed hex address
        if addr.lower().startswith('hlx'):
            logger.debug("Received HLX formatted address – please provide 0x format. Ignoring value.")
            return None

        if addr.startswith('0x'):
            if len(addr) > 42:
                addr = addr[:42]
            if len(addr) != 42:
                logger.warning(f"Hyperliquid wallet appears malformed (length {len(addr)}): {raw}")
                return None
            hex_part = addr[2:]
            if all(ch in string.hexdigits for ch in hex_part):
                return addr.lower()
            logger.warning(f"Hyperliquid wallet contains non-hex characters: {raw}")
            return None

        logger.warning(f"Unsupported wallet format provided: {raw}")
        return None

    async def _resolve_primary_user(self, session: aiohttp.ClientSession, info_url: str, identifier: str, headers: Dict[str, str]) -> str:
        """If the identifier is an agent/sub-account, resolve the master wallet."""
        try:
            payload = {"type": "userRole", "user": identifier}
            async with session.post(info_url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    logger.debug(f"userRole check failed ({resp.status}), using {identifier}")
                    return identifier

                data = await resp.json()
                role = data.get("role")
                role_data = data.get("data") or {}

                logger.debug(f"userRole response for {identifier}: {data}")

                if role == "agent":
                    master = role_data.get("user")
                    if master:
                        logger.info(f"Resolved agent wallet {identifier} to primary user {master}")
                        normalized = self._normalize_wallet_address(master)
                        return normalized or identifier
                elif role == "subAccount":
                    master = role_data.get("master")
                    if master:
                        logger.info(f"Resolved sub-account {identifier} to master {master}")
                        normalized = self._normalize_wallet_address(master)
                        return normalized or identifier
                # For vaults or regular users, just return identifier
        except Exception as err:
            logger.warning(f"Failed to resolve primary user for {identifier}: {err}")
        return identifier
    
    def _sign_request(self, method: str, endpoint: str, params: str, secret: str) -> str:
        """Sign request for Hyperliquid API"""
        message = f"{method}{endpoint}{params}"
        return hmac.new(
            secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    async def connect(self, credentials: Dict[str, str]) -> bool:
        """Test connection to Hyperliquid"""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self._get_base_url(credentials.get('testnet', False))}/info"
                headers = {
                    'Content-Type': 'application/json'
                }
                
                payload = {"type": "meta"}
                
                async with session.post(url, json=payload, headers=headers) as response:
                    if response.status == 200:
                        logger.info("Successfully connected to Hyperliquid")
                        return True
                    else:
                        logger.error(f"Connection failed with status: {response.status}")
                        return False
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False
    
    def validate_credentials(self, credentials: Dict[str, str]) -> bool:
        """Validate API credentials format"""
        has_api_key = bool(credentials.get('api_key'))
        has_secret = bool(credentials.get('api_secret') or credentials.get('private_key'))
        return has_api_key and has_secret
    
    async def get_balance(self, credentials: Dict[str, str]) -> Dict[str, float]:
        """Get account balance from Hyperliquid using authenticated endpoints.

        Uses authenticated /info queries with API key instead of public state queries.
        This should work with API credentials and show actual account balances.
        """
        try:
            async with aiohttp.ClientSession() as session:
                base_url = self._get_base_url(credentials.get('testnet', False))

                headers = {
                    'Content-Type': 'application/json'
                    # Note: Hyperliquid may not require Bearer auth for basic info queries
                }

                # Define URLs early
                perps_url = f"{base_url}/info"
                exchange_url = f"{base_url}/exchange"

                # Resolve a usable wallet identifier
                identifier_candidates = [
                    credentials.get('wallet_address'),
                    credentials.get('api_passphrase'),  # reused in DB for wallet storage
                    credentials.get('wallet'),
                    credentials.get('api_key'),
                ]

                user_identifier: Optional[str] = None
                for candidate in identifier_candidates:
                    user_identifier = self._normalize_wallet_address(candidate)
                    if user_identifier:
                        break

                if not user_identifier:
                    logger.warning("No valid Hyperliquid wallet/identifier found for balance query")
                    return {'total': 0.0, 'available': 0.0, 'withdrawable': 0.0, 'margin_used': 0.0, 'perps_balance': 0.0, 'spot_balance': 0.0}

                # Resolve primary account if this is an agent/sub-account
                user_identifier = await self._resolve_primary_user(session, perps_url, user_identifier, headers)

                logger.info(f"[Hyperliquid] Using identifier for balance: {user_identifier}")

                perps_balance = {'total': 0.0, 'available': 0.0, 'withdrawable': 0.0, 'margin_used': 0.0}
                spot_balance = {'total': 0.0, 'available': 0.0}

                # ---------------------- PUBLIC PERPS BALANCE ----------------------
                perps_payload = {
                    "type": "clearinghouseState",
                    "user": user_identifier
                }

                try:
                    async with session.post(perps_url, json=perps_payload, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            # Use debug level for large responses to avoid blocking
                            logger.debug(f"Authenticated perps response: {data}")

                            balance_info = data.get('marginSummary') or {}
                            withdrawable_top = data.get('withdrawable')

                            account_value = float(balance_info.get('accountValue', 0) or 0)
                            margin_used = float(balance_info.get('totalMarginUsed', 0) or 0)
                            withdrawable = float(balance_info.get('withdrawable', withdrawable_top or 0) or 0)

                            perps_balance.update({
                                'total': account_value,
                                'available': max(0.0, account_value - margin_used),
                                'withdrawable': withdrawable,
                                'margin_used': margin_used
                            })

                            logger.debug(f"Parsed perps balance: ${account_value} total, ${withdrawable} withdrawable")
                        else:
                            txt = await response.text()
                            logger.warning(f"Authenticated perps request failed: {response.status} -> {txt}")
                            logger.warning(f"Perps payload: {perps_payload}")
                except Exception as perps_err:
                    logger.error(f"Error fetching authenticated perps balance: {perps_err}")

                # ---------------------- PUBLIC SPOT BALANCE ----------------------
                spot_payload = {
                    "type": "spotClearinghouseState",
                    "user": user_identifier
                }

                try:
                    async with session.post(perps_url, json=spot_payload, headers=headers) as spot_response:
                        if spot_response.status == 200:
                            spot_data = await spot_response.json()
                            logger.debug(f"Authenticated spot response: {spot_data}")

                            balances = spot_data.get('balances') or []
                            total_spot_usdc = 0.0
                            for bal in balances:
                                try:
                                    coin = bal.get('coin')
                                    if coin == 'USDC':
                                        raw_total = bal.get('total') or bal.get('totalUsd') or 0
                                        total_spot_usdc = float(raw_total)
                                        break
                                except Exception:
                                    continue

                            spot_balance.update({
                                'total': total_spot_usdc,
                                'available': total_spot_usdc
                            })

                            logger.debug(f"Parsed spot balance: ${total_spot_usdc} USDC")
                        else:
                            txt = await spot_response.text()
                            logger.warning(f"Authenticated spot request failed: {spot_response.status} -> {txt}")
                            logger.warning(f"Spot payload: {spot_payload}")
                except Exception as spot_err:
                    logger.error(f"Error fetching authenticated spot balance: {spot_err}")

                # ---------------------- FALLBACK TO PUBLIC IF AUTH FAILS ----------------------
                if perps_balance['total'] == 0 and spot_balance['total'] == 0:
                    logger.info("Authenticated queries returned zero, trying public state queries...")

                    # Try public queries as fallback
                    fallback_identifier = user_identifier

                    if fallback_identifier:
                        logger.info(f"Trying public query with identifier: {fallback_identifier}")

                        # Public perps query
                        public_perps_payload = {"type": "clearinghouseState", "user": fallback_identifier}
                        try:
                            async with session.post(perps_url, json=public_perps_payload, headers={'Content-Type': 'application/json'}) as pub_response:
                                if pub_response.status == 200:
                                    pub_data = await pub_response.json()
                                    logger.debug(f"Public perps response: {pub_data}")

                                    pub_balance_info = pub_data.get('marginSummary') or {}
                                    pub_account_value = float(pub_balance_info.get('accountValue', 0) or 0)
                                    pub_margin_used = float(pub_balance_info.get('totalMarginUsed', 0) or 0)
                                    pub_withdrawable = float(pub_balance_info.get('withdrawable', 0) or 0)

                                    if pub_account_value > 0:
                                        perps_balance.update({
                                            'total': pub_account_value,
                                            'available': max(0.0, pub_account_value - pub_margin_used),
                                            'withdrawable': pub_withdrawable,
                                            'margin_used': pub_margin_used
                                        })
                                        logger.info(f"Found balance via public query: ${pub_account_value}")
                        except Exception as pub_err:
                            logger.warning(f"Public perps query failed: {pub_err}")

                # ---------------------- FINAL RESULT ----------------------
                combined_total = perps_balance['total'] + spot_balance['total']
                combined_available = perps_balance['available'] + spot_balance['available']

                result = {
                    'total': combined_total,
                    'available': combined_available,
                    'withdrawable': perps_balance.get('withdrawable', 0.0),
                    'margin_used': perps_balance.get('margin_used', 0.0),
                    'perps_balance': perps_balance['total'],
                    'spot_balance': spot_balance['total']
                }
                
                # Summary log at INFO level (concise)
                logger.info(f"💰 Balance: ${combined_total:.2f} (Perps: ${perps_balance['total']:.2f}, Spot: ${spot_balance['total']:.2f})")

                logger.info(f"Final balance result: {result}")
                return result

        except Exception as e:
            logger.error(f"Error getting balance: {e}")
            return {'total': 0, 'available': 0}

    async def diagnose_account(self, credentials: Dict[str, str]) -> Dict[str, Any]:
        """Probe multiple Hyperliquid /info query types to help diagnose zero balance issues.

        Returns a dict with raw responses (truncated) and status codes for each attempted type.
        This is purely a diagnostic helper and not used in normal flow.
        """
        results: Dict[str, Any] = {}
        try:
            async with aiohttp.ClientSession() as session:
                base_url = self._get_base_url(credentials.get('testnet', False))
                url = f"{base_url}/info"
                user_identifier = (
                    credentials.get('wallet') or
                    credentials.get('api_passphrase') or
                    credentials.get('api_key')
                )
                probe_types = [
                    "clearinghouseState",      # perps
                    "userState",               # alternative user overview (if supported)
                    "userSpotState",           # spot balances variant
                    "spotClearinghouseState",  # legacy spot variant you attempted earlier
                    "meta"                      # general meta (for universe & possibly symbols)
                ]
                headers = {'Content-Type': 'application/json'}
                for t in probe_types:
                    payload = {"type": t}
                    if t != "meta":
                        payload["user"] = user_identifier
                    try:
                        async with session.post(url, json=payload, headers=headers) as resp:
                            status = resp.status
                            snippet = None
                            try:
                                data = await resp.json(content_type=None)
                                # Store only first 600 chars to avoid log spam
                                snippet = json.dumps(data)[:600]
                            except Exception as parse_err:
                                text_body = await resp.text()
                                snippet = f"<parse_error {parse_err}> raw: {text_body[:300]}"
                            results[t] = {"status": status, "body": snippet}
                    except Exception as single_err:
                        results[t] = {"error": str(single_err)}
        except Exception as e:
            results['fatal_error'] = str(e)
        return results
    
    async def get_positions(self, credentials: Dict[str, str]) -> List[Dict[str, Any]]:
        """Get open positions"""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self._get_base_url(credentials.get('testnet', False))}/info"
                
                payload = {
                    "type": "clearinghouseState",
                    "user": credentials['api_key']
                }
                
                headers = {
                    'Content-Type': 'application/json'
                }
                
                async with session.post(url, json=payload, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        positions = data.get('assetPositions', [])
                        
                        formatted_positions = []
                        for pos in positions:
                            if float(pos.get('position', {}).get('szi', 0)) != 0:
                                formatted_positions.append({
                                    'symbol': pos.get('position', {}).get('coin', ''),
                                    'size': float(pos.get('position', {}).get('szi', 0)),
                                    'entry_price': float(pos.get('position', {}).get('entryPx', 0)),
                                    'unrealized_pnl': float(pos.get('position', {}).get('unrealizedPnl', 0))
                                })
                        
                        return formatted_positions
                    else:
                        logger.error(f"Failed to get positions: {response.status}")
                        return []
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return []
    
    async def get_available_symbols(self, testnet: bool = False) -> List[str]:
        """Get list of available trading symbols on Hyperliquid"""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self._get_base_url(testnet)}/info"
                
                payload = {"type": "meta"}
                headers = {'Content-Type': 'application/json'}
                
                async with session.post(url, json=payload, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        symbols = []
                        
                        # Extract symbols from universe data
                        if 'universe' in data:
                            for asset in data['universe']:
                                if isinstance(asset, dict) and 'name' in asset:
                                    symbols.append(asset['name'])
                        
                        logger.info(f"Found {len(symbols)} available symbols on Hyperliquid")
                        return symbols
                    else:
                        logger.error(f"Failed to get symbols: {response.status}")
                        return []
        except Exception as e:
            logger.error(f"Error getting available symbols: {e}")
            return []
    
    async def validate_symbol(self, symbol: str, testnet: bool = False) -> Dict[str, Any]:
        """Validate if symbol is available for trading on Hyperliquid"""
        try:
            # Clean the symbol (remove USDT, /, etc.)
            clean_symbol = symbol.replace('USDT', '').replace('/', '').upper()
            
            # Get available symbols
            available_symbols = await self.get_available_symbols(testnet)
            
            # Check if symbol exists
            if clean_symbol in available_symbols:
                return {
                    "valid": True,
                    "symbol": clean_symbol,
                    "original": symbol
                }
            else:
                # Try to find similar symbols
                similar = [s for s in available_symbols if clean_symbol in s or s in clean_symbol]
                
                return {
                    "valid": False,
                    "symbol": clean_symbol,
                    "original": symbol,
                    "available_symbols": available_symbols[:20],  # First 20 for reference
                    "similar": similar[:5] if similar else [],  # Up to 5 similar matches
                    "error": f"Symbol '{clean_symbol}' not available on Hyperliquid"
                }
        except Exception as e:
            logger.error(f"Error validating symbol {symbol}: {e}")
            return {
                "valid": False,
                "symbol": symbol,
                "error": f"Symbol validation failed: {str(e)}"
            }
    
    async def execute_trade(self, user_data: Dict, signal: Dict) -> Dict[str, Any]:
        """Execute trade on Hyperliquid"""
        try:
            # Get balance for position sizing
            balance_info = await self.get_balance(user_data)
            total_balance = balance_info.get('total', 0)
            
            # Check if account has sufficient balance
            if total_balance <= 0:
                return {
                    "success": False,
                    "error": "❌ Insufficient Balance: Account balance is $0.00",
                    "balance_check": {
                        "total": total_balance,
                        "required": "Minimum $10",
                        "status": "NO_BALANCE"
                    }
                }
            
            # Check minimum balance requirement
            min_balance = 10.0  # $10 minimum
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
            
            # Validate symbol availability on Hyperliquid
            symbol_validation = await self.validate_symbol(signal['symbol'], user_data.get('testnet', False))
            if not symbol_validation['valid']:
                error_msg = f"❌ Symbol Not Available: {signal['symbol']} is not tradeable on Hyperliquid"
                
                if symbol_validation.get('similar'):
                    similar_symbols = ', '.join(symbol_validation['similar'])
                    error_msg += f"\n\n💡 Similar symbols available: {similar_symbols}"
                
                if symbol_validation.get('available_symbols'):
                    popular_symbols = ', '.join(symbol_validation['available_symbols'][:10])
                    error_msg += f"\n\n📈 Popular symbols: {popular_symbols}"
                
                return {
                    "success": False,
                    "error": error_msg,
                    "symbol_check": {
                        "requested": signal['symbol'],
                        "cleaned": symbol_validation['symbol'],
                        "status": "NOT_AVAILABLE",
                        "similar": symbol_validation.get('similar', []),
                        "available": symbol_validation.get('available_symbols', [])[:10]
                    }
                }
            
            # 🆕 USE RISK MANAGER FOR POSITION SIZING
            entry_price = float(signal.get('entry', [0])[0] if signal.get('entry') else 0)
            stop_loss = float(signal.get('stop_loss', [0])[0] if signal.get('stop_loss') else 0)
            leverage = signal.get('leverage', 1)
            
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
            
            # Calculate position size in coins (divide USD amount by entry price)
            position_size = leveraged_amount / entry_price
            
            logger.info(
                f"💰 Fixed amount position sizing:\n"
                f"   Fixed Amount: ${fixed_amount:.2f}\n"
                f"   Leverage: {leverage}x\n"
                f"   Position Value: ${leveraged_amount:.2f}\n"
                f"   Entry Price: ${entry_price:.2f}\n"
                f"   Position Size: {position_size:.6f} coins"
            )
            
            # Get entry prices
            entry_values = signal.get('entry', [])
            if not entry_values:
                return {
                    "success": False,
                    "error": "❌ Missing entry price for order placement"
                }
            
            limit_price = float(entry_values[0])

            # Fetch asset metadata for tick validation
            testnet = user_data.get('testnet', False)
            async with aiohttp.ClientSession() as session:
                asset_mapping = await self._get_asset_mapping(session, testnet)
            
            asset_info = asset_mapping.get(symbol_validation['symbol'].upper())
            if not asset_info:
                logger.error(f"❌ Asset metadata not found for {symbol_validation['symbol']}")
                return {
                    "success": False,
                    "error": f"Asset metadata not available for {symbol_validation['symbol']}"
                }
            
            px_decimals = asset_info.get('px_decimals')
            
            # Prepare order data - USE GTC LIMIT order that stays on the book
            # For market-like behavior with wide slippage tolerance
            is_buy = signal['side'] == 'buy'
            slippage_pct = 0.01  # 1% slippage buffer for better fill probability
            if is_buy:
                # Buy: add buffer for fill
                limit_px_with_buffer = limit_price * (1.0 + slippage_pct)
            else:
                # Sell: subtract buffer
                limit_px_with_buffer = limit_price * (1.0 - slippage_pct)
            
            # CRITICAL: Snap to tick size using Decimal for exact precision
            limit_px_snapped = self._snap_to_tick(limit_px_with_buffer, symbol_validation['symbol'], px_decimals, is_buy)
            
            order_data = {
                "coin": symbol_validation['symbol'],  # Use validated symbol
                "is_buy": is_buy,
                "sz": float(position_size),
                "limit_px": limit_px_snapped,  # Tick-aligned price
                "order_type": {"limit": {"tif": "Gtc"}},  # GTC = Good-Til-Cancel (stays on book)
                "reduce_only": False
            }
            
            logger.info(f"📊 Placing GTC limit order at ${limit_price} (tick-aligned: ${limit_px_snapped:.10f}, 1% slippage buffer, px_decimals={px_decimals})")

            
            # Set leverage - use signal leverage if specified, otherwise default to configured value
            signal_leverage = signal.get('leverage')
            logger.info(f"📊 Leverage Settings - Signal: {signal_leverage}, Default: {Config.DEFAULT_LEVERAGE}")
            
            if signal_leverage is not None:
                order_data["leverage"] = int(signal_leverage)
                logger.info(f"✅ Using signal leverage: {order_data['leverage']}x")
            else:
                order_data["leverage"] = Config.DEFAULT_LEVERAGE  # Default leverage for signals without specified leverage
                logger.info(f"⚙️ Using default leverage: {order_data['leverage']}x")
            
            # Execute the main trade with automatic tick discovery
            result = await self._place_order_with_tick_fallback(
                user_data, 
                order_data, 
                symbol_validation['symbol'],
                px_decimals,
                is_buy,
                limit_px_with_buffer
            )
            
            if result.get('success'):
                logger.info(f"Main order placed successfully for {user_data['user_id']}")
                user_id = str(user_data['user_id'])
                symbol = symbol_validation['symbol']
                
                # Initialize order tracking for this user/symbol
                if user_id not in self.active_orders:
                    self.active_orders[user_id] = {}
                
                if symbol not in self.active_orders[user_id]:
                    self.active_orders[user_id][symbol] = {
                        'dca_orders': [],
                        'tp_orders': [],
                        'sl_orders': [],
                        'initial_quantity': float(position_size),
                        'remaining_quantity': float(position_size)
                    }
                
                # Place ALL additional entry orders (DCA) and track them
                dca_results = []
                if len(entry_values) > 1:
                    logger.info(f"Placing {len(entry_values) - 1} DCA entry orders...")
                    for i, dca_price in enumerate(entry_values[1:], start=2):
                        # Snap DCA price to tick size
                        dca_price_snapped = self._snap_to_tick(float(dca_price), symbol_validation['symbol'], px_decimals, signal['side'] == 'buy')
                        
                        dca_order = {
                            "coin": symbol_validation['symbol'],
                            "is_buy": signal['side'] == 'buy',
                            "sz": float(position_size),
                            "limit_px": dca_price_snapped,
                            "order_type": {"limit": {"tif": "Gtc"}},
                            "reduce_only": False
                        }
                        
                        # Set leverage for DCA orders - use signal leverage if specified, otherwise default to configured value
                        signal_leverage = signal.get('leverage')
                        if signal_leverage is not None:
                            dca_order["leverage"] = int(signal_leverage)
                        else:
                            dca_order["leverage"] = Config.DEFAULT_LEVERAGE  # Default leverage for signals without specified leverage
                        dca_result = await self._place_order(user_data, dca_order)
                        
                        # Extract order ID and track it
                        if dca_result.get('success') and dca_result.get('response'):
                            try:
                                statuses = dca_result['response'].get('response', {}).get('data', {}).get('statuses', [])
                                if statuses and len(statuses) > 0:
                                    resting = statuses[0].get('resting')
                                    if resting and 'oid' in resting:
                                        order_id = str(resting['oid'])
                                        self.active_orders[user_id][symbol]['dca_orders'].append(order_id)
                                        logger.info(f"✅ DCA Entry {i} placed at ${dca_price} (Order ID: {order_id})")
                            except Exception as track_error:
                                logger.warning(f"Could not extract DCA order ID: {track_error}")
                        
                        dca_results.append({
                            "entry": i,
                            "price": dca_price,
                            "result": dca_result
                        })
                        
                        if not dca_result.get('success'):
                            logger.error(f"❌ DCA Entry {i} failed: {dca_result.get('error')}")
                
                result['dca_entries'] = dca_results
                
                # Set stop loss if provided
                if signal.get('stop_loss'):
                    sl_result = await self._set_stop_loss(user_data, signal, position_size, symbol_validation['symbol'], px_decimals)
                    result['stop_loss'] = sl_result
                
                # Set ALL take profit levels with position splitting
                tp_results = []
                if signal.get('take_profit'):
                    tp_prices = signal['take_profit'] if isinstance(signal['take_profit'], list) else [signal['take_profit']]
                    num_tps = len(tp_prices)
                    logger.info(f"Placing {num_tps} take profit orders...")
                    
                    # Split position size across TPs
                    # Equal distribution with last TP taking any remainder
                    for i, tp_price in enumerate(tp_prices, start=1):
                        if num_tps == 1:
                            # Single TP: use full size
                            tp_size = position_size
                        else:
                            # Multiple TPs: split evenly, last TP gets remainder
                            if i < num_tps:
                                tp_size = position_size / num_tps
                            else:
                                # Last TP: calculate remainder to ensure full position is covered
                                tp_size = position_size - (position_size / num_tps * (num_tps - 1))
                        
                        logger.info(f"TP{i}: {tp_size:.6f} coins (out of {position_size:.6f} total)")
                        
                        tp_result = await self._set_take_profit_level(
                            user_data, 
                            signal, 
                            tp_size,  # Use split size instead of full position_size
                            tp_price, 
                            i,
                            symbol_validation['symbol'],
                            px_decimals
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
                
                # Start position monitoring to auto-cancel DCA orders when position closes
                import asyncio
                if self.active_orders.get(user_id, {}).get(symbol, {}).get('dca_orders'):
                    monitor_key = f"{user_id}_{symbol}"
                    if monitor_key not in self.position_monitors:
                        task = asyncio.create_task(
                            self._monitor_position_closure(user_id, symbol, user_data)
                        )
                        self.position_monitors[monitor_key] = task
                        logger.info(f"🔍 Position monitoring started for {symbol} (User: {user_id})")
            
            return result
            
        except Exception as e:
            logger.error(f"Trade execution failed: {e}")
            return {"success": False, "error": str(e)}
    
    def _normalize_order_type(self, order_type: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Return an order type dict compatible with Hyperliquid's signing schema."""
        if not order_type:
            return {"limit": {"tif": "Gtc"}}

        if "limit" in order_type:
            limit_spec = order_type.get("limit", {}) or {}
            tif = limit_spec.get("tif", "Gtc")
            if isinstance(tif, str):
                tif = tif[:1].upper() + tif[1:].lower()
            return {"limit": {"tif": tif}}

        if "trigger" in order_type:
            trigger_spec = order_type.get("trigger", {}) or {}
            trigger_px = trigger_spec.get("triggerPx", trigger_spec.get("trigger_px"))
            if trigger_px is None:
                raise ValueError("Trigger orders require a trigger price")
            normalized = {
                "trigger": {
                    "isMarket": bool(trigger_spec.get("isMarket", trigger_spec.get("is_market", False))),
                    "triggerPx": float(trigger_px),
                    "tpsl": trigger_spec.get("tpsl"),
                }
            }
            return normalized

        return order_type

    def _snap_to_tick(self, price: float, symbol: str, px_decimals: Optional[int], is_buy: bool) -> float:
        """
        Snap price to Hyperliquid tick size using Decimal for exact precision.
        Uses multi-source tick discovery: lookup table → discovered cache → heuristics.
        
        Args:
            price: Raw price to snap
            symbol: Trading symbol (e.g., 'BTC', 'ETH')
            px_decimals: Price decimals from meta (fallback if symbol not in lookup)
            is_buy: True for buy (round up), False for sell (round down)
        
        Returns:
            Tick-aligned price as float
        """
        symbol_upper = symbol.upper()
        tick_size = None
        
        # 1. Check hardcoded lookup table (highest priority)
        if symbol_upper in TICK_SIZE_LOOKUP:
            tick_size = Decimal(TICK_SIZE_LOOKUP[symbol_upper])
            logger.debug(f"Using lookup table tick for {symbol_upper}: {tick_size}")
        
        # 2. Check discovered ticks cache
        elif symbol_upper in self._discovered_ticks:
            tick_size = Decimal(self._discovered_ticks[symbol_upper])
            logger.debug(f"Using cached discovered tick for {symbol_upper}: {tick_size}")
        
        # 3. Use price-based heuristics as fallback
        else:
            if price >= 10000:
                tick_size = Decimal('0.5')
            elif price >= 1000:
                tick_size = Decimal('0.1')
            elif price >= 100:
                tick_size = Decimal('0.01')
            elif price >= 10:
                tick_size = Decimal('0.001')
            elif price >= 1:
                tick_size = Decimal('0.0001')
            else:
                tick_size = Decimal('0.00001')
            
            logger.warning(f"No tick size for {symbol_upper}, using heuristic: {tick_size} (price={price})")
        
        # Convert to Decimal for exact arithmetic
        price_decimal = Decimal(str(price))
        
        # Snap to tick: round up for buys, down for sells
        rounding = ROUND_UP if is_buy else ROUND_DOWN
        ticks = (price_decimal / tick_size).quantize(Decimal('1'), rounding=rounding)
        snapped = float(ticks * tick_size)
        
        if abs(snapped - price) > 0.000001:
            logger.debug(f"Tick snap {symbol_upper}: {price:.10f} → {snapped:.10f} (tick={tick_size})")
        
        return snapped
    
    def _get_candidate_ticks(self, symbol: str, px_decimals: Optional[int]) -> List[Decimal]:
        """
        Generate candidate tick sizes to try (for automatic discovery).
        Returns list in priority order.
        """
        candidates = []
        symbol_upper = symbol.upper()
        
        # 1. Lookup table tick
        if symbol_upper in TICK_SIZE_LOOKUP:
            candidates.append(Decimal(TICK_SIZE_LOOKUP[symbol_upper]))
        
        # 2. Previously discovered tick
        if symbol_upper in self._discovered_ticks:
            tick = Decimal(self._discovered_ticks[symbol_upper])
            if tick not in candidates:
                candidates.append(tick)
        
        # 3. px_decimals-derived tick
        if px_decimals is not None:
            tick = Decimal(10) ** (-int(px_decimals))
            if tick not in candidates:
                candidates.append(tick)
        
        # 4. Common ticks (most → least common)
        common = [
            Decimal('0.01'),    # Most common for altcoins
            Decimal('0.001'),   # Mid-cap
            Decimal('0.0001'),  # Small-cap
            Decimal('0.5'),     # BTC-like
            Decimal('0.05'),    # ETH-like
            Decimal('0.00001'), # Micro-cap
            Decimal('0.1'),     # High-value
            Decimal('1.0'),     # Very high value
        ]
        
        for tick in common:
            if tick not in candidates:
                candidates.append(tick)
        
        return candidates

    async def _get_asset_mapping(self, session: aiohttp.ClientSession, testnet: bool) -> Dict[str, Dict[str, Any]]:
        """Fetch and cache asset metadata for symbol -> asset id lookups."""
        cache_key = "testnet" if testnet else "mainnet"
        cached = self._asset_cache.get(cache_key)
        timestamp = self._asset_cache_timestamp.get(cache_key)
        if cached and timestamp and time.time() - timestamp < 300:
            return cached

        url = f"{self._get_base_url(testnet)}/info"
        payload = {"type": "meta"}
        headers = {"Content-Type": "application/json"}

        async with session.post(url, json=payload, headers=headers) as response:
            if response.status != 200:
                text = await response.text()
                logger.error(f"Failed to refresh Hyperliquid meta ({response.status}): {text}")
                return cached or {}

            data = await response.json()

        mapping: Dict[str, Dict[str, Any]] = {}
        for idx, asset in enumerate(data.get("universe", [])):
            name = asset.get("name")
            if not name:
                continue
            
            # Log first asset to see structure
            if idx == 0:
                logger.info(f"Sample asset structure: {asset}")
            
            # Extract available precision fields
            # szDecimals = size precision (e.g., 8 for BTC means 0.00000001 size)
            # Look for price-related fields: might be maxLeverage, onlyIsolated, etc.
            sz_decimals = asset.get("szDecimals", 0)
            
            # Try to find price decimals - check various possible field names
            px_decimals = (
                asset.get("pxDecimals") or 
                asset.get("priceDecimals") or
                asset.get("tickDecimals")
            )
            
            # If no explicit price decimals, use a safe default of 2 (0.01 tick)
            # This works for most altcoins; BTC/ETH will be handled by price-based logic in _snap_to_tick
            if px_decimals is None:
                px_decimals = 2  # Default: 0.01 tick for most assets
                logger.debug(f"Using default px_decimals=2 for {name} (szDecimals={sz_decimals})")
            
            mapping[name.upper()] = {
                "asset_id": idx,
                "sz_decimals": sz_decimals,
                "px_decimals": px_decimals,
            }

        self._asset_cache[cache_key] = mapping
        self._asset_cache_timestamp[cache_key] = time.time()
        logger.debug(f"Cached {len(mapping)} Hyperliquid assets for {cache_key}")
        return mapping

    async def _get_asset_info(
        self,
        session: aiohttp.ClientSession,
        symbol: str,
        testnet: bool,
    ) -> Optional[Dict[str, Any]]:
        mapping = await self._get_asset_mapping(session, testnet)
        return mapping.get(symbol.upper())

    def _build_order_request(self, order_data: Dict[str, Any], asset_info: Dict[str, Any]) -> Dict[str, Any]:
        if order_data.get("limit_px") is None:
            raise ValueError("limit_px must be provided for Hyperliquid orders")

        size = float(order_data.get("sz", 0))
        if size <= 0:
            raise ValueError("Order size must be greater than zero")

        limit_px = float(order_data.get("limit_px"))
        sz_decimals = int(asset_info.get("sz_decimals", 0))
        size = round(size, sz_decimals)
        limit_px = round(limit_px, 6)

        order_request: Dict[str, Any] = {
            "coin": order_data["coin"],
            "is_buy": bool(order_data.get("is_buy")),
            "sz": size,
            "limit_px": limit_px,
            "order_type": self._normalize_order_type(order_data.get("order_type")),
            "reduce_only": bool(order_data.get("reduce_only", False)),
        }

        # Add leverage if specified
        if "leverage" in order_data:
            order_request["leverage"] = int(order_data["leverage"])

        cloid = order_data.get("cloid")
        if cloid:
            if isinstance(cloid, Cloid):
                order_request["cloid"] = cloid
            else:
                raw = str(cloid)
                if not raw.startswith("0x"):
                    raw = f"0x{raw}"
                order_request["cloid"] = Cloid.from_str(raw)

        return order_request

    def _generate_client_order_id(self) -> str:
        """Generate a 16-byte client order id (Cloid) for Hyperliquid orders."""
        import secrets

        return Cloid.from_int(secrets.randbits(128)).to_raw()

    async def _place_order_with_tick_fallback(self, user_data: Dict, order_data: Dict, 
                                               symbol: str, px_decimals: Optional[int],
                                               is_buy: bool, base_price: float) -> Dict[str, Any]:
        """
        Place order with automatic tick size discovery.
        Tries multiple tick candidates until one succeeds.
        """
        symbol_upper = symbol.upper()
        candidates = self._get_candidate_ticks(symbol, px_decimals)
        last_error = None
        
        # Try each candidate tick
        for attempt, tick_size in enumerate(candidates[:8], 1):  # Limit to 8 attempts
            # Snap price to this tick
            price_decimal = Decimal(str(base_price))
            rounding = ROUND_UP if is_buy else ROUND_DOWN
            ticks = (price_decimal / tick_size).quantize(Decimal('1'), rounding=rounding)
            snapped_price = float(ticks * tick_size)
            
            # Update order with snapped price
            order_data['limit_px'] = snapped_price
            
            logger.info(f"🔄 Attempt {attempt}/{len(candidates[:8])}: Trying {symbol_upper} with tick={tick_size}, price={snapped_price:.10f}")
            
            # Try to place order
            result = await self._place_order(user_data, order_data)
            
            if result.get('success'):
                # Success! Cache this tick for future use
                if symbol_upper not in TICK_SIZE_LOOKUP and symbol_upper not in self._discovered_ticks:
                    self._discovered_ticks[symbol_upper] = str(tick_size)
                    self._save_tick_cache()
                    logger.info(f"✅ Discovered tick size for {symbol_upper}: {tick_size} (cached for future)")
                return result
            
            # Check if error is tick-related
            error_msg = result.get('error', '')
            if 'tick' in error_msg.lower() or 'divisible' in error_msg.lower():
                logger.warning(f"⚠️ Tick {tick_size} failed for {symbol_upper}: {error_msg}")
                last_error = error_msg
                continue  # Try next tick
            else:
                # Non-tick error, don't retry
                logger.error(f"❌ Non-tick error for {symbol_upper}: {error_msg}")
                return result
        
        # All attempts failed
        return {
            "success": False,
            "error": f"All {len(candidates[:8])} tick attempts failed for {symbol_upper}. Last error: {last_error}"
        }

    @with_retry(max_attempts=3, backoff_base=2)
    @with_rate_limit(hyperliquid_limiter)
    async def _place_order(self, user_data: Dict, order_data: Dict) -> Dict[str, Any]:
        """Place order on Hyperliquid with retry and rate limiting"""
        try:
            async with aiohttp.ClientSession() as session:
                testnet = user_data.get('testnet', False)
                base_url = self._get_base_url(testnet)
                symbol = order_data.get("coin")
                if not symbol:
                    return {"success": False, "error": "Order is missing symbol"}

                asset_info = await self._get_asset_info(session, symbol, testnet)
                if not asset_info:
                    return {
                        "success": False,
                        "error": f"Unable to resolve Hyperliquid asset id for {symbol}",
                    }

                if "cloid" not in order_data:
                    order_data["cloid"] = self._generate_client_order_id()

                try:
                    order_request = self._build_order_request(order_data, asset_info)
                except ValueError as build_err:
                    logger.error(f"Order build failed: {build_err}")
                    return {"success": False, "error": str(build_err)}

                try:
                    order_wire = order_request_to_order_wire(order_request, asset_info["asset_id"])
                except Exception as wire_err:
                    logger.error(f"Failed to convert order to wire format: {wire_err}")
                    return {"success": False, "error": f"Failed to serialize order: {wire_err}"}

                action = order_wires_to_order_action([order_wire])
                nonce = int(time.time() * 1000)

                if not Config.LIVE_TRADING:
                    logger.info(f"🔵 Simulating order placement: {order_request}")
                    return {
                        "success": True,
                        "simulated": True,
                        "message": "Order simulated (wallet integration required for live trading)",
                        "order": {**order_request, "cloid": order_request.get("cloid").to_raw() if order_request.get("cloid") else None},
                        "action": action,
                    }

                logger.warning("🔴 LIVE TRADING ENABLED - Attempting to place real order on Hyperliquid!")
                private_key = user_data.get('private_key') or user_data.get('api_secret', '')
                if not private_key:
                    return {"success": False, "error": "No private key found for wallet signing"}

                account = Account.from_key(private_key)
                is_mainnet = base_url == self.base_url

                signature = sign_l1_action(
                    account,
                    action,
                    None,
                    nonce,
                    None,
                    is_mainnet,
                )

                payload = {
                    "action": action,
                    "nonce": nonce,
                    "signature": signature,
                    "vaultAddress": None,
                    "expiresAfter": None,
                }

                headers = {'Content-Type': 'application/json'}
                logger.info(f"Submitting Hyperliquid order with cloid {order_data['cloid']}")

                async with session.post(f"{base_url}/exchange", json=payload, headers=headers) as response:
                    response_text = await response.text()

                    if response.status == 200:
                        try:
                            response_data = json.loads(response_text)
                        except json.JSONDecodeError:
                            logger.error(f"Invalid JSON response from Hyperliquid: {response_text}")
                            return {"success": False, "error": f"Invalid response from Hyperliquid: {response_text}"}

                        # Inspect statuses for errors even when HTTP 200
                        resp_ok = True
                        err_msg = None
                        try:
                            if isinstance(response_data, dict):
                                r = response_data.get('response') or {}
                                if isinstance(r, dict) and r.get('type') == 'order':
                                    statuses = (r.get('data') or {}).get('statuses') or []
                                    for st in statuses:
                                        if isinstance(st, dict) and st.get('error'):
                                            resp_ok = False
                                            err_msg = st.get('error')
                                            break
                        except Exception:
                            pass

                        if not resp_ok:
                            logger.error(f"Hyperliquid order rejected: {err_msg}")
                            return {"success": False, "error": err_msg or "Order rejected"}

                        logger.info(f"✅ Live order accepted: {response_data}")
                        return {
                            "success": True,
                            "simulated": False,
                            "live": True,
                            "message": "Order accepted on Hyperliquid",
                            "order": {**order_request, "cloid": order_request.get("cloid").to_raw() if order_request.get("cloid") else None},
                            "action": action,
                            "response": response_data,
                        }

                    logger.error(f"Hyperliquid API error: HTTP {response.status} - {response_text}")
                    return {
                        "success": False,
                        "error": f"Hyperliquid API error: HTTP {response.status} - {response_text}",
                    }

        except Exception as e:
            logger.error(f"Order placement failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def _set_stop_loss(self, user_data: Dict, signal: Dict, size: float, validated_symbol: str = None, px_decimals: int = None):
        """Set stop loss order"""
        try:
            stop_price = signal['stop_loss'][0] if isinstance(signal['stop_loss'], list) else signal['stop_loss']
            
            # Use validated symbol if provided, otherwise clean the symbol
            clean_symbol = validated_symbol or signal['symbol'].replace('USDT', '').replace('/', '')
            
            # Snap trigger price to tick size
            stop_price_snapped = self._snap_to_tick(float(stop_price), clean_symbol, px_decimals, signal['side'] == 'sell')
            
            order_data = {
                "coin": clean_symbol,
                "is_buy": signal['side'] == 'sell',  # Opposite of entry
                "sz": float(size),
                "limit_px": stop_price_snapped,
                "order_type": {"trigger": {"triggerPx": stop_price_snapped, "isMarket": True, "tpsl": "sl"}},
                "reduce_only": True
            }
            
            result = await self._place_order(user_data, order_data)
            logger.info(f"Stop loss set at {stop_price_snapped} (tick-aligned from {stop_price})")
            return result
            
        except Exception as e:
            logger.error(f"Failed to set stop loss: {e}")
            return {"success": False, "error": str(e)}
    
    async def _set_take_profit(self, user_data: Dict, signal: Dict, size: float, validated_symbol: str = None):
        """Set take profit order (legacy - for single TP)"""
        try:
            tp_price = signal['take_profit'][0] if isinstance(signal['take_profit'], list) else signal['take_profit']
            
            # Use validated symbol if provided, otherwise clean the symbol
            clean_symbol = validated_symbol or signal['symbol'].replace('USDT', '').replace('/', '')
            
            order_data = {
                "coin": clean_symbol,
                "is_buy": signal['side'] == 'sell',  # Opposite of entry
                "sz": float(size),
                "limit_px": float(tp_price),
                "order_type": {"trigger": {"triggerPx": float(tp_price), "isMarket": True, "tpsl": "tp"}},
                "reduce_only": True
            }
            
            result = await self._place_order(user_data, order_data)
            logger.info(f"Take profit set at {tp_price}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to set take profit: {e}")
            return {"success": False, "error": str(e)}
    
    async def _set_take_profit_level(self, user_data: Dict, signal: Dict, size: float, tp_price: float, 
                                     level: int, validated_symbol: str = None, px_decimals: int = None):
        """Set a specific take profit level"""
        try:
            # Use validated symbol if provided, otherwise clean the symbol
            clean_symbol = validated_symbol or signal['symbol'].replace('USDT', '').replace('/', '')
            
            # Snap trigger price to tick size
            tp_price_snapped = self._snap_to_tick(float(tp_price), clean_symbol, px_decimals, signal['side'] == 'sell')
            
            order_data = {
                "coin": clean_symbol,
                "is_buy": signal['side'] == 'sell',  # Opposite of entry
                "sz": float(size),
                "limit_px": tp_price_snapped,
                "order_type": {"trigger": {"triggerPx": tp_price_snapped, "isMarket": True, "tpsl": "tp"}},
                "reduce_only": True
            }
            
            result = await self._place_order(user_data, order_data)
            logger.info(f"Take profit level {level} set at {tp_price_snapped} (tick-aligned from {tp_price})")
            return result
            
        except Exception as e:
            logger.error(f"Failed to set take profit level {level}: {e}")
            return {"success": False, "error": str(e)}
    
    def _calculate_position_size(self, user_data: Dict, signal: Dict, balance: float) -> float:
        """
        Calculate position size with SIMPLIFIED settings:
        - Option 1: Fixed dollar amount per trade ($100, $500, $1000)
        - Option 2: Percentage of balance (5%, 10%, 20%)
        - Max Risk % acts as safety cap
        """
        try:
            # Get user's position sizing preferences
            position_mode = user_data.get('position_mode', 'percentage')  # 'fixed' or 'percentage'
            fixed_amount = user_data.get('fixed_amount', 100.0)  # Default $100
            percentage_of_balance = user_data.get('percentage_of_balance', 10.0)  # Default 10%
            max_risk_percent = user_data.get('max_risk', 2.0)  # Safety cap (default 2%)
            
            # Get signal leverage (use signal value if present, otherwise default)
            signal_leverage = signal.get('leverage')
            leverage = signal_leverage if signal_leverage is not None else 20
            logger.info(f"📊 Leverage from signal: {signal_leverage} → Using: {leverage}x")
            
            # Step 1: Calculate DESIRED MARGIN based on user's mode
            if position_mode == 'fixed':
                desired_margin = fixed_amount
                logger.info(f"💰 Position Mode: FIXED AMOUNT = ${desired_margin:.2f}")
            else:  # percentage mode
                desired_margin = balance * (percentage_of_balance / 100)
                logger.info(f"💰 Position Mode: {percentage_of_balance}% of ${balance:.2f} = ${desired_margin:.2f}")
            
            # Get entry and stop loss prices
            if not signal.get('entry'):
                logger.error("No entry price in signal")
                return 0.001  # Minimum fallback
            
            entry_price = float(signal['entry'][0] if isinstance(signal['entry'], list) else signal['entry'])
            
            # Step 2: Calculate position VALUE with leverage
            position_value_with_leverage = desired_margin * leverage
            
            logger.info(f"📊 Leverage: {leverage}x → Position Value: ${position_value_with_leverage:.2f}")
            
            # Step 3: SAFETY CHECK - Respect max risk %
            if signal.get('stop_loss'):
                stop_prices = signal['stop_loss'] if isinstance(signal['stop_loss'], list) else [signal['stop_loss']]
                sl_price = float(stop_prices[0])
                
                # Calculate distance to SL as percentage
                risk_distance = abs(entry_price - sl_price) / entry_price
                
                # Calculate expected loss if SL hits
                # Loss = position_value × risk_distance (simplified for spot-like)
                expected_loss = desired_margin * risk_distance * leverage
                
                # Calculate max allowed loss based on account balance
                max_allowed_loss = balance * (max_risk_percent / 100)
                
                logger.info(
                    f"🛡️ Risk Check:\n"
                    f"  Entry: ${entry_price:g}\n"
                    f"  Stop Loss: ${sl_price:g}\n"
                    f"  Distance to SL: {risk_distance*100:.2f}%\n"
                    f"  Expected Loss if SL hits: ${expected_loss:.2f}\n"
                    f"  Max Allowed Loss ({max_risk_percent}%): ${max_allowed_loss:.2f}"
                )
                
                # If expected loss exceeds max risk, scale down the position
                if expected_loss > max_allowed_loss:
                    scaling_factor = max_allowed_loss / expected_loss
                    desired_margin = desired_margin * scaling_factor
                    position_value_with_leverage = desired_margin * leverage
                    
                    logger.warning(
                        f"⚠️ POSITION REDUCED to respect Max Risk {max_risk_percent}%:\n"
                        f"  New Margin: ${desired_margin:.2f}\n"
                        f"  New Position Value: ${position_value_with_leverage:.2f}\n"
                        f"  Max Loss if SL hits: ${max_allowed_loss:.2f}"
                    )
            
            # Step 4: Convert position VALUE to SIZE (in base currency)
            calculated_size = position_value_with_leverage / entry_price
            
            # Ensure minimum size (exchange requirement)
            min_size = 0.001
            calculated_size = max(min_size, calculated_size)
            
            # Cap at 95% of total balance (safety check)
            max_position_value = balance * 0.95
            if position_value_with_leverage > max_position_value:
                calculated_size = max_position_value / entry_price
                logger.warning(f"⚠️ Position capped at 95% of balance: ${max_position_value:.2f}")
            
            logger.info(
                f"✅ FINAL POSITION:\n"
                f"  Mode: {position_mode.upper()}\n"
                f"  Margin Used: ${desired_margin:.2f}\n"
                f"  Leverage: {leverage}x\n"
                f"  Position Value: ${position_value_with_leverage:.2f}\n"
                f"  Size: {calculated_size:.6f} units\n"
                f"  Max Risk: {max_risk_percent}%"
            )
            
            return round(calculated_size, 6)
            
        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            # Emergency fallback: $50 worth at assumed $50k price
            return round(50 / 50000, 6)
    
    async def validate_credentials(self, wallet_address: str, private_key: str, testnet: bool = False) -> Dict[str, Any]:
        """
        Validate Hyperliquid credentials by attempting to fetch account info.
        
        Args:
            wallet_address: The wallet address (0x...)
            private_key: The private key (without 0x prefix)
            testnet: Whether to use testnet
            
        Returns:
            Dict with 'valid' (bool), 'message' (str), and 'balance' (float if valid)
        """
        try:
            # Normalize inputs
            wallet = self._normalize_wallet_address(wallet_address)
            if not wallet:
                return {
                    'valid': False,
                    'message': 'Invalid wallet address format'
                }
            
            # Validate private key format
            if private_key.startswith('0x'):
                private_key = private_key[2:]
            
            if len(private_key) != 64 or not all(c in string.hexdigits for c in private_key):
                return {
                    'valid': False,
                    'message': 'Invalid private key format (must be 64 hex characters)'
                }
            
            # Try to create account object to verify key matches wallet
            try:
                account = Account.from_key(f"0x{private_key}")
                derived_address = account.address.lower()
                
                if derived_address != wallet.lower():
                    return {
                        'valid': False,
                        'message': f'Private key does not match wallet address\nDerived: {derived_address[:10]}...\nProvided: {wallet[:10]}...'
                    }
            except Exception as key_err:
                logger.error(f"Error verifying private key: {key_err}")
                return {
                    'valid': False,
                    'message': f'Invalid private key: {str(key_err)}'
                }
            
            # Test connection by fetching balance
            credentials = {
                'wallet_address': wallet,
                'api_passphrase': wallet,
                'private_key': private_key,
                'testnet': testnet
            }
            
            balance_info = await self.get_balance(credentials)
            
            # Check if we got valid data
            if balance_info is None or (
                balance_info.get('total', 0) == 0 and 
                balance_info.get('spot_balance', 0) == 0 and
                balance_info.get('perps_balance', 0) == 0
            ):
                # Even $0 balance is valid if API responds
                # Check if we at least got a response structure
                if isinstance(balance_info, dict) and 'total' in balance_info:
                    return {
                        'valid': True,
                        'message': 'Credentials validated successfully (Balance: $0.00)',
                        'balance': 0.0
                    }
                else:
                    return {
                        'valid': False,
                        'message': 'Unable to fetch account data. Please verify your credentials.'
                    }
            
            total_balance = balance_info.get('total', 0) + balance_info.get('spot_balance', 0)
            
            return {
                'valid': True,
                'message': f'Credentials validated successfully (Balance: ${total_balance:.2f})',
                'balance': total_balance
            }
            
        except Exception as e:
            logger.error(f"Credential validation error: {e}")
            return {
                'valid': False,
                'message': f'Validation failed: {str(e)}'
            }
    
    async def _monitor_position_closure(self, user_id: str, symbol: str, user_data: Dict):
        """Monitor position and cancel DCA orders when position is fully closed"""
        import asyncio
        
        logger.info(f"🔍 Started position monitor for {symbol} (User: {user_id})")
        
        try:
            while True:
                await asyncio.sleep(15)  # Check every 15 seconds
                
                # Check if we're still tracking this position
                if user_id not in self.active_orders or symbol not in self.active_orders[user_id]:
                    logger.info(f"⏹️ Position monitor stopped for {symbol} - No active tracking")
                    break
                
                position_data = self.active_orders[user_id][symbol]
                
                # Get current position size
                current_position = await self._get_position_size(symbol, user_data)
                
                # If position is fully closed (or very small due to rounding)
                if abs(current_position) < 0.001:
                    logger.warning(f"⚠️ Position fully closed for {symbol} (User: {user_id}) - Cancelling all pending orders")
                    
                    # Cancel all DCA orders
                    dca_order_ids = position_data.get('dca_orders', [])
                    if dca_order_ids:
                        cancelled = await self._cancel_orders(symbol, dca_order_ids, user_data)
                        logger.info(f"✅ Cancelled {cancelled}/{len(dca_order_ids)} DCA orders for {symbol}")
                    
                    # Optionally cancel remaining TP orders
                    tp_order_ids = position_data.get('tp_orders', [])
                    if tp_order_ids:
                        cancelled_tp = await self._cancel_orders(symbol, tp_order_ids, user_data)
                        logger.info(f"✅ Cancelled {cancelled_tp}/{len(tp_order_ids)} remaining TP orders for {symbol}")
                    
                    # Remove from tracking
                    del self.active_orders[user_id][symbol]
                    logger.info(f"🧹 Cleaned up tracking for {symbol} (User: {user_id})")
                    break
                
                # Update remaining quantity
                position_data['remaining_quantity'] = abs(current_position)
                
        except Exception as e:
            logger.error(f"❌ Error in position monitor for {symbol}: {e}")
            
    async def _get_position_size(self, symbol: str, user_data: Dict) -> float:
        """Get current position size for symbol"""
        try:
            positions = await self.get_positions(user_data)
            
            if not positions:
                return 0.0
            
            for position in positions:
                if position.get('coin') == symbol or position.get('symbol') == symbol:
                    # 'szi' is the signed size (positive for long, negative for short)
                    size = position.get('szi', position.get('size', 0))
                    return float(size)
            
            return 0.0
            
        except Exception as e:
            logger.error(f"❌ Error getting position size for {symbol}: {e}")
            return 0.0
    
    async def _cancel_orders(self, symbol: str, order_ids: List[str], user_data: Dict) -> int:
        """Cancel multiple orders and return count of successful cancellations"""
        cancelled_count = 0
        already_gone_count = 0
        
        for order_id in order_ids:
            try:
                success = await self._cancel_single_order(symbol, order_id, user_data)
                if success:
                    cancelled_count += 1
                    logger.info(f"✅ Cancelled order {order_id} for {symbol}")
                else:
                    # Order might already be filled/cancelled - this is expected
                    already_gone_count += 1
                    logger.debug(f"Order {order_id} for {symbol} already filled/cancelled")
                    
            except Exception as e:
                logger.error(f"❌ Error cancelling order {order_id}: {e}")
        
        if already_gone_count > 0:
            logger.info(f"ℹ️ {already_gone_count} order(s) for {symbol} already filled/cancelled")
        
        return cancelled_count
    
    async def _cancel_single_order(self, symbol: str, order_id: str, user_data: Dict) -> bool:
        """Cancel a single order on Hyperliquid"""
        try:
            wallet_address = self._normalize_wallet_address(
                user_data.get('wallet') or 
                user_data.get('api_passphrase') or 
                user_data.get('api_key')
            )
            private_key = user_data.get('private_key') or user_data.get('api_secret', '')
            testnet = user_data.get('testnet', False)
            
            if not wallet_address or not private_key:
                logger.error("Missing wallet address or private key for order cancellation")
                return False
            
            # Build cancel request
            cancel_action = {
                "type": "cancel",
                "cancels": [{
                    "a": wallet_address,
                    "o": int(order_id)
                }]
            }
            
            # Sign the action with correct parameters for newer SDK
            timestamp = int(time.time() * 1000)
            try:
                # Try new SDK signature (with active_pool and expires_after)
                signed_action = sign_l1_action(
                    wallet=Account.from_key(private_key),
                    action=cancel_action,
                    active_pool=None,  # For spot/perps, use None
                    nonce=timestamp,
                    is_mainnet=not testnet,
                    expires_after=None  # No expiration
                )
            except TypeError:
                # Fallback to old SDK signature
                signed_action = sign_l1_action(
                    wallet=Account.from_key(private_key),
                    action=cancel_action,
                    nonce=timestamp,
                    is_mainnet=not testnet
                )
            
            # Send cancel request
            url = f"{self._get_base_url(testnet)}/exchange"
            headers = {"Content-Type": "application/json"}
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=signed_action, headers=headers) as response:
                    if response.status == 200:
                        result = await response.json()
                        if result.get("status") == "ok":
                            return True
                        else:
                            logger.error(f"Cancel order failed: {result}")
                            return False
                    elif response.status == 422:
                        # 422 = Unprocessable Entity - order likely already filled/cancelled
                        response_text = await response.text()
                        logger.debug(f"Order {order_id} already filled/cancelled (422): {response_text}")
                        return False
                    else:
                        response_text = await response.text()
                        logger.error(f"Cancel order HTTP error {response.status}: {response_text}")
                        return False
                        
        except Exception as e:
            logger.error(f"❌ Cancel order exception: {e}")
            return False
    
    def _track_orders(self, user_id: str, symbol: str, order_data: Dict):
        """Track placed orders for a user's position"""
        if user_id not in self.active_orders:
            self.active_orders[user_id] = {}
        
        if symbol not in self.active_orders[user_id]:
            self.active_orders[user_id][symbol] = {
                'dca_orders': [],
                'tp_orders': [],
                'sl_orders': [],
                'initial_quantity': 0,
                'remaining_quantity': 0
            }
        
        # Update tracked orders based on order_data
        if 'dca_order_id' in order_data:
            self.active_orders[user_id][symbol]['dca_orders'].append(order_data['dca_order_id'])
        
        if 'tp_order_id' in order_data:
            self.active_orders[user_id][symbol]['tp_orders'].append(order_data['tp_order_id'])
        
        if 'sl_order_id' in order_data:
            self.active_orders[user_id][symbol]['sl_orders'].append(order_data['sl_order_id'])
