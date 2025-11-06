import asyncio
import json
import logging
import websockets
from typing import Dict, Callable, Optional

logger = logging.getLogger(__name__)

class WebSocketPriceFeed:
    def __init__(self):
        self.websocket: Optional[websockets.WebSocketServerProtocol] = None
        self.subscriptions = set()  # {symbol}
        self.price_callbacks = []  # List of callback functions
        self.reconnect_interval = 5
        self.max_reconnect_attempts = 10
        self.running = False
        
    async def start(self):
        """Start WebSocket connection"""
        self.running = True
        await self._connect_hyperliquid()
        
    async def stop(self):
        """Stop WebSocket connection"""
        self.running = False
        if self.websocket and not self.websocket.closed:
            await self.websocket.close()
        
    def add_price_callback(self, callback: Callable):
        """Add callback function for price updates"""
        self.price_callbacks.append(callback)
        
    def subscribe_symbol(self, symbol: str):
        """Subscribe to price updates for a symbol"""
        self.subscriptions.add(symbol.upper())
        
    def unsubscribe_symbol(self, symbol: str):
        """Unsubscribe from price updates for a symbol"""
        self.subscriptions.discard(symbol.upper())
        
    async def _connect_hyperliquid(self):
        """Connect to Hyperliquid WebSocket stream"""
        asyncio.create_task(self._hyperliquid_connection_handler())
        
    async def _hyperliquid_connection_handler(self):
        """Handle Hyperliquid WebSocket connection with reconnection"""
        attempts = 0
        
        while self.running and attempts < self.max_reconnect_attempts:
            try:
                await self._maintain_hyperliquid_connection()
                attempts = 0  # Reset on successful connection
            except Exception as e:
                attempts += 1
                logger.error(f"Hyperliquid WebSocket error (attempt {attempts}): {e}")
                if attempts < self.max_reconnect_attempts:
                    await asyncio.sleep(self.reconnect_interval)
                else:
                    logger.error("Max reconnection attempts reached for Hyperliquid")
                    
    async def _maintain_hyperliquid_connection(self):
        """Maintain Hyperliquid WebSocket connection"""
        # Hyperliquid WebSocket URL
        url = "wss://api.hyperliquid.xyz/ws"
        
        async with websockets.connect(url) as websocket:
            self.websocket = websocket
            logger.info("Connected to Hyperliquid WebSocket")
            
            # Subscribe to all price updates
            subscription_message = {
                "method": "subscribe",
                "subscription": {
                    "type": "allMids"
                }
            }
            await websocket.send(json.dumps(subscription_message))
            logger.info("Subscribed to all Hyperliquid price updates")
            
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self._handle_hyperliquid_message(data)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to decode Hyperliquid message: {e}")
                except Exception as e:
                    logger.error(f"Error handling Hyperliquid message: {e}")
                    
    async def _handle_hyperliquid_message(self, data):
        """Handle incoming Hyperliquid price data"""
        try:
            # Hyperliquid sends price updates in format: {"data": {"SYMBOL": "PRICE"}}
            if "data" in data and isinstance(data["data"], dict):
                prices = data["data"]
                for symbol, price_str in prices.items():
                    # Convert Hyperliquid symbol to standard format
                    # Hyperliquid uses base symbols (e.g., "BTC", "ETH") 
                    # We need to convert to our format (e.g., "BTC/USDC")
                    standard_symbol = f"{symbol}/USDC"
                    
                    # Only process if we're subscribed to this symbol
                    if standard_symbol in self.subscriptions:
                        try:
                            price = float(price_str)
                            # Notify all callbacks
                            for callback in self.price_callbacks:
                                try:
                                    await callback(standard_symbol, price)
                                except Exception as e:
                                    logger.error(f"Error in price callback: {e}")
                        except ValueError as e:
                            logger.error(f"Invalid price format for {symbol}: {price_str}")
                            
        except Exception as e:
            logger.error(f"Error processing Hyperliquid price data: {e}")


class HybridPriceFeed:
    """Hybrid price feed that combines WebSocket and REST API"""
    
    def __init__(self):
        self.websocket_feed = WebSocketPriceFeed()
        self.rest_prices = {}  # Fallback price cache
        self.callbacks = []
        
    async def start(self):
        """Start the hybrid price feed"""
        # Add our callback to WebSocket feed
        self.websocket_feed.add_price_callback(self._on_websocket_price)
        await self.websocket_feed.start()
        
    async def stop(self):
        """Stop the hybrid price feed"""
        await self.websocket_feed.stop()
        
    def add_callback(self, callback: Callable):
        """Add price update callback"""
        self.callbacks.append(callback)
        
    def subscribe(self, symbol: str):
        """Subscribe to symbol price updates"""
        self.websocket_feed.subscribe_symbol(symbol)
        
    def unsubscribe(self, symbol: str):
        """Unsubscribe from symbol price updates"""
        self.websocket_feed.unsubscribe_symbol(symbol)
        
    async def _on_websocket_price(self, symbol: str, price: float):
        """Handle WebSocket price updates"""
        # Update our cache
        self.rest_prices[symbol] = price
        
        # Notify all callbacks
        for callback in self.callbacks:
            try:
                await callback(symbol, price)
            except Exception as e:
                logger.error(f"Error in hybrid price callback: {e}")
                
    async def get_price(self, symbol: str) -> Optional[float]:
        """Get current price for symbol (with REST fallback)"""
        # Try WebSocket cache first
        if symbol in self.rest_prices:
            return self.rest_prices[symbol]
            
        # Fallback to Hyperliquid REST API
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Convert symbol format (e.g., "BTC/USDC" -> "BTC")
                base_symbol = symbol.split('/')[0]
                url = f"https://api.hyperliquid.xyz/info"
                
                payload = {
                    "type": "allMids"
                }
                
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        if isinstance(data, dict) and base_symbol in data:
                            price = float(data[base_symbol])
                            self.rest_prices[symbol] = price
                            return price
        except Exception as e:
            logger.error(f"Failed to get REST price for {symbol}: {e}")
            
        return None