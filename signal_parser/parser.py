import re
from typing import Dict, Optional, List
from config import Config
import logging

logger = logging.getLogger(__name__)

class SignalParser:
    SECTION_KEYWORDS = {
        'entry': [
            'entry', 'entries', 'entry zone', 'entry zones', 'entry price', 'entry prices',
            'buy zone', 'buy zones', 'buy area', 'entry range', 'entry ranges',
            'cmp', 'current market price', 'dca', 'dca2', 'dca3', 'dca4', 'dca5'
        ],
        'take_profit': [
            'take profit', 'take profits', 'tp', 'targets', 'target', 'profit targets'
        ],
        'stop_loss': [
            'stop loss', 'stop losses', 'stop', 'sl', 'stop price'
        ]
    }

    SECTION_BOUNDARY_KEYWORDS = [
        'entry', 'entries', 'entry zone', 'entry zones', 'entry price', 'entry prices',
        'entry range', 'entry ranges', 'take profit', 'take profits', 'tp', 'targets',
        'target', 'profit targets', 'stop loss', 'stop losses', 'stop', 'sl',
        'leverage', 'lev', 'risk', 'notes', 'comment', 'analysis'
    ]

    def __init__(self):
        self.patterns = Config.SIGNAL_PATTERNS
    
    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        """
        Normalize symbol for Hyperliquid compatibility.
        Converts BTC/USD, BTC/USDT, BTCUSDT, etc. to just BTC
        """
        if not symbol:
            return symbol
        
        # Remove common separators and quote currencies
        symbol = symbol.upper().strip()
        
        # Remove /USD, /USDT, -USD, -USDT suffixes
        symbol = re.sub(r'[/\-](USD[T]?|PERP)$', '', symbol, flags=re.IGNORECASE)
        
        # Remove USDT, USD suffix if directly attached (e.g., BTCUSDT -> BTC)
        symbol = re.sub(r'(USDT|USD|PERP)$', '', symbol, flags=re.IGNORECASE)
        
        return symbol.upper()
    
    def parse_signal(self, message_content: str) -> List[Dict]:
        """Parse trading signals from message content, supporting multiple signals separated by '/'"""
        signals = []
        
        # First try to parse the entire message as one signal
        signal = self._parse_single_signal(message_content)
        if signal:
            signals.append(signal)
            return signals
        
        # If that fails, look for multiple signals separated by " / " (with spaces)
        # This avoids splitting on symbol names like BTC/USDT
        if " / " in message_content:
            signal_parts = [part.strip() for part in message_content.split(" / ") if part.strip()]
            
            for part in signal_parts:
                signal = self._parse_single_signal(part)
                if signal:
                    signals.append(signal)
        elif "/" in message_content and len(message_content.split("/")) > 2:
            # Fallback: if there are multiple '/', try splitting but be careful
            # Only split if we have clear signal boundaries
            parts = message_content.split("/")
            if len(parts) >= 2:
                # Try to reconstruct signals by looking for LONG/SHORT keywords
                current_signal = ""
                for part in parts:
                    part = part.strip()
                    if not part:
                        continue
                    current_signal += part + " "
                    
                    # Check if this looks like a complete signal
                    if re.search(r'\b(LONG|SHORT|BUY|SELL)\b', part, re.IGNORECASE):
                        signal = self._parse_single_signal(current_signal.strip())
                        if signal:
                            signals.append(signal)
                            current_signal = ""
                
                # Handle remaining part
                if current_signal.strip():
                    signal = self._parse_single_signal(current_signal.strip())
                    if signal:
                        signals.append(signal)
        
        return signals
    
    def _parse_price_levels(self, text: str) -> List[float]:
        """Parse price levels from text, handling numbered lists, ranges, CMP, DCA formats, and plain numbers"""
        if not text:
            return []

        # Handle special cases first
        if 'CMP' in text.upper():
            # CMP means Current Market Price - we'll mark this for special handling
            # For now, we'll extract any numbers that appear with CMP
            text = re.sub(r'\bCMP\b', '', text, flags=re.IGNORECASE)

        # Clean up the text and remove prefixes
        cleaned_segments: List[str] = []
        for line in text.splitlines():
            cleaned_line = line.strip()
            if not cleaned_line:
                continue
            
            # Remove numbered prefixes like "1)", "2:", etc.
            cleaned_line = re.sub(r'^\d+\s*(?:\)|:)\s*', '', cleaned_line)
            cleaned_line = re.sub(r'^\d+\s*\.(?!\d)\s*', '', cleaned_line)
            
            # Remove DCA prefixes (including DCA2, DCA3, etc.)
            cleaned_line = re.sub(r'DCA\d*\s*:\s*', '', cleaned_line, flags=re.IGNORECASE)
            
            # Remove Entry: prefixes that appear multiple times
            cleaned_line = re.sub(r'^Entry\s*:\s*', '', cleaned_line, flags=re.IGNORECASE)
            
            # Remove other section prefixes
            cleaned_line = re.sub(
                r'^(?:tp|take\s*profit|target|targets|entries|sl|stop\s*loss|stop)\s*\d*\s*[:\-]\s*',
                '',
                cleaned_line,
                flags=re.IGNORECASE
            )
            
            if cleaned_line.strip():
                cleaned_segments.append(cleaned_line)

        cleaned_text = ' '.join(cleaned_segments)
        
        # Remove thousand separators (commas) from numbers like 111,999 -> 111999
        cleaned_text = re.sub(r'(\d+),(\d{3})', r'\1\2', cleaned_text)
        # Handle multiple commas (e.g., 1,111,999 -> 1111999)
        while re.search(r'(\d+),(\d{3})', cleaned_text):
            cleaned_text = re.sub(r'(\d+),(\d{3})', r'\1\2', cleaned_text)
        
        # Replace dashes between numbers with spaces to handle ranges
        cleaned_text = re.sub(r'(?<=\d)[-–](?=\d)', ' ', cleaned_text)
        
        # Extract all price numbers (including decimals like 0.00662)
        prices = []
        price_matches = re.finditer(r'\d+(?:\.\d+)?', cleaned_text)

        for match in price_matches:
            value_str = match.group(0)
            start, end = match.span()
            before = cleaned_text[start - 1] if start > 0 else ''
            after = cleaned_text[end] if end < len(cleaned_text) else ''

            # Skip if the number is part of a word or date
            if before and before.isalpha():
                continue
            if after and after.isalpha():
                continue

            try:
                value = float(value_str)
                if value > 0:
                    prices.append(value)
            except ValueError:
                continue

        # Remove duplicates while preserving order
        unique_prices = []
        for price in prices:
            if price not in unique_prices:
                unique_prices.append(price)

        return unique_prices
    
    def _parse_single_signal(self, message_content: str) -> Optional[Dict]:
        """Parse a single trading signal from message content"""
        signal = {}
        
        # Clean up the message
        message_content = message_content.strip()
        
        # Extract symbol first as it's critical
        symbol_match = re.search(self.patterns['symbol'], message_content, re.IGNORECASE)
        if symbol_match:
            raw_symbol = symbol_match.group(1).strip().upper()
            signal['symbol'] = self.normalize_symbol(raw_symbol)
        else:
            # Try to find symbol in common formats (support 1+ characters for symbols like Q, X, etc.)
            symbol_patterns = [
                r'\b([A-Z0-9]{1,10}\/USD[T]?)\b',  # Q/USDT, BTC/USDT, 0G/USDT, BROCCOLI/USDT
                r'\b([A-Z0-9]{1,10}-USD[T]?)\b',  # Q-USDT, BTC-USDT, 0G-USDT, BROCCOLI-USDT
                r'\b([A-Z0-9]{2,10}USDT?)\b',  # BTCUSDT, ETHUSDT, 0GUSDT, BROCCOLIUSDT (min 2 chars to avoid false positives)
            ]
            for pattern in symbol_patterns:
                match = re.search(pattern, message_content, re.IGNORECASE)
                if match:
                    raw_symbol = match.group(1).strip().upper()
                    signal['symbol'] = self.normalize_symbol(raw_symbol)
                    break
        
        # Extract side (LONG/SHORT/BUY/SELL)
        side_match = re.search(self.patterns['side'], message_content, re.IGNORECASE)
        if side_match:
            side = side_match.group(1).upper()
            if side in ['LONG', 'BUY']:
                signal['side'] = 'buy'
            elif side in ['SHORT', 'SELL']:
                signal['side'] = 'sell'
        
        # Extract entry prices - handle multiple "Entry:" lines and DCA entries
        entry_text = self._extract_section(
            message_content,
            self.SECTION_KEYWORDS.get('entry', [])
        )
        
        # Also look for individual "Entry:" lines and DCA entries
        entry_lines = []
        for line in message_content.splitlines():
            line = line.strip()
            if re.match(r'^(?:Entry|DCA\d*)\s*:', line, re.IGNORECASE):
                entry_lines.append(line)
        
        if entry_lines:
            entry_text = '\n'.join(entry_lines) + '\n' + (entry_text or '')
        elif not entry_text:
            entry_match = re.search(self.patterns['entry'], message_content, re.IGNORECASE)
            if entry_match:
                entry_text = entry_match.group(1).strip()
                
        if entry_text:
            entry_prices = self._parse_price_levels(entry_text)
            if entry_prices:
                signal['entry'] = entry_prices

        # Extract stop loss
        sl_text = self._extract_section(
            message_content,
            self.SECTION_KEYWORDS.get('stop_loss', [])
        )
        if not sl_text:
            sl_match = re.search(self.patterns['stop_loss'], message_content, re.IGNORECASE)
            if sl_match:
                sl_text = sl_match.group(1).strip()
        if sl_text:
            sl_prices = self._parse_price_levels(sl_text)
            if sl_prices:
                signal['stop_loss'] = sl_prices

        # Extract take profit
        tp_text = self._extract_section(
            message_content,
            self.SECTION_KEYWORDS.get('take_profit', [])
        )
        if not tp_text:
            tp_match = re.search(self.patterns['take_profit'], message_content, re.IGNORECASE)
            if tp_match:
                tp_text = tp_match.group(1).strip()
        if tp_text:
            tp_prices = self._parse_price_levels(tp_text)
            if tp_prices:
                signal['take_profit'] = tp_prices
        
        # Extract leverage - handle formats like "20x", "Leverage: 20x", "20x Cross"
        lev_match = re.search(self.patterns['leverage'], message_content, re.IGNORECASE)
        if not lev_match:
            # Try alternative leverage patterns
            lev_match = re.search(r'(?:leverage\s*:?\s*)?(\d+)x(?:\s+cross|\s+isolated)?', message_content, re.IGNORECASE)
        
        if lev_match:
            try:
                signal['leverage'] = int(lev_match.group(1))
            except (ValueError, IndexError):
                pass
        
        # Additional parsing for common signal formats
        signal = self._parse_common_formats(message_content, signal)
        
        # Only return signal if we have minimum required fields
        if 'symbol' in signal and 'side' in signal:
            logger.info(f"Parsed signal: {signal}")
            return signal
        
        logger.debug(f"Could not parse signal from: {message_content[:100]}...")
        return None

    def _extract_section(self, message: str, keywords: List[str], stop_keywords: Optional[List[str]] = None) -> Optional[str]:
        if not message or not keywords:
            return None

        keyword_set = [kw for kw in keywords if kw]
        if not keyword_set:
            return None

        if stop_keywords is None:
            stop_keywords = self.SECTION_BOUNDARY_KEYWORDS

        normalized_keywords = {kw.lower() for kw in keyword_set}
        boundary_keywords = [
            kw for kw in stop_keywords
            if kw and kw.lower() not in normalized_keywords
        ]

        keyword_pattern = '|'.join(re.escape(kw) for kw in keyword_set)
        boundary_pattern = '|'.join(re.escape(kw) for kw in boundary_keywords) if boundary_keywords else ''

        if boundary_pattern:
            pattern = rf'(?:^|\n)\s*(?:{keyword_pattern})\s*(?:[:\-]\s*)?(.*?)(?=\n\s*(?:{boundary_pattern})(?:\s*[:\-]|$)|\Z)'
        else:
            pattern = rf'(?:^|\n)\s*(?:{keyword_pattern})\s*(?:[:\-]\s*)?(.*)'

        match = re.search(pattern, message, re.IGNORECASE | re.DOTALL)
        if match:
            extracted = match.group(1).strip()
            return extracted if extracted else None
        return None
    
    def _parse_common_formats(self, message: str, signal: Dict) -> Dict:
        """Parse common signal formats"""
        
        # Format: "LONG BTCUSDT @ 45000"
        long_short_pattern = r'(LONG|SHORT)\s+([A-Z0-9\/\-]+)\s*[@]\s*([\d.]+)'
        match = re.search(long_short_pattern, message, re.IGNORECASE)
        if match:
            side = 'buy' if match.group(1).upper() == 'LONG' else 'sell'
            raw_symbol = match.group(2).upper()
            symbol = self.normalize_symbol(raw_symbol)
            entry_price = float(match.group(3))
            
            signal.update({
                'side': side,
                'symbol': symbol,
                'entry': [entry_price]
            })
        
        # Format: "BUY ETHUSDT 3000-3050"
        range_pattern = r'(BUY|SELL)\s+([A-Z0-9\/\-]+)\s+([\d.]+)-([\d.]+)'
        match = re.search(range_pattern, message, re.IGNORECASE)
        if match:
            side = 'buy' if match.group(1).upper() == 'BUY' else 'sell'
            raw_symbol = match.group(2).upper()
            symbol = self.normalize_symbol(raw_symbol)
            entry_low = float(match.group(3))
            entry_high = float(match.group(4))
            
            signal.update({
                'side': side,
                'symbol': symbol,
                'entry': [entry_low, entry_high]
            })
        
        return signal
    
    def validate_signal(self, signal: Dict) -> bool:
        """Validate if signal has required fields"""
        required_fields = ['symbol', 'side']
        return all(field in signal for field in required_fields)
    
    def format_signal_summary(self, signal: Dict) -> str:
        """Format signal for display"""
        summary = f"**{signal['symbol']}** - {signal['side'].upper()}"
        
        if signal.get('entry'):
            entry_str = ', '.join([str(p) for p in signal['entry']])
            summary += f"\n📍 Entry: {entry_str}"
        
        if signal.get('stop_loss'):
            sl_str = ', '.join([str(p) for p in signal['stop_loss']])
            summary += f"\n🛑 Stop Loss: {sl_str}"
        
        if signal.get('take_profit'):
            tp_str = ', '.join([str(p) for p in signal['take_profit']])
            summary += f"\n🎯 Take Profit: {tp_str}"
        
        if signal.get('leverage'):
            summary += f"\n⚡ Leverage: {signal['leverage']}x"
        
        return summary