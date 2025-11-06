import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
    
    # PostgreSQL Database Configuration
    DATABASE_URL = os.getenv('DATABASE_URL', 
                             f"postgresql://{os.getenv('POSTGRES_USER', 'trader')}:"
                             f"{os.getenv('POSTGRES_PASSWORD', 'secure_password_change_me')}@"
                             f"{os.getenv('POSTGRES_HOST', 'localhost')}:"
                             f"{os.getenv('POSTGRES_PORT', '5432')}/"
                             f"{os.getenv('POSTGRES_DB', 'trading_bot')}")
    
    POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')
    POSTGRES_PORT = int(os.getenv('POSTGRES_PORT', 5432))
    POSTGRES_DB = os.getenv('POSTGRES_DB', 'trading_bot')
    POSTGRES_USER = os.getenv('POSTGRES_USER', 'trader')
    POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'secure_password_change_me')
    
    COMMAND_PREFIX = os.getenv('COMMAND_PREFIX', '!')
    
    # Hyperliquid URLs
    HYPERLIQUID_BASE_URL = os.getenv('HYPERLIQUID_BASE_URL', 'https://api.hyperliquid.xyz')
    HYPERLIQUID_TESTNET_URL = os.getenv('HYPERLIQUID_TESTNET_URL', 'https://api.hyperliquid-testnet.xyz')
    
    # Bybit URLs
    BYBIT_BASE_URL = os.getenv('BYBIT_BASE_URL', 'https://api.bybit.com')
    BYBIT_TESTNET_URL = os.getenv('BYBIT_TESTNET_URL', 'https://api-testnet.bybit.com')
    
    # Trading settings
    DEFAULT_POSITION_SIZE = float(os.getenv('DEFAULT_POSITION_SIZE', 1.0))
    DEFAULT_MAX_RISK = float(os.getenv('DEFAULT_MAX_RISK', 2.0))
    DEFAULT_LEVERAGE = int(os.getenv('DEFAULT_LEVERAGE', 20))
    LIVE_TRADING = os.getenv('LIVE_TRADING', 'false').lower() == 'true'
    
    # Signal patterns
    SIGNAL_PATTERNS = {
        'entry': r'(?:ENTRY|ENTRIES)[\s:]+(.*?)(?=\s*(?:TAKE\s?PROFIT|TP|STOP\s?LOSS|SL|STOP|LEVERAGE|LEV|SYMBOL|PAIR|$))',
        'stop_loss': r'(?:SL|STOP\s?LOSS|STOP)[\s:]*([^\n]+?)(?=\s*(?:TAKE\s?PROFIT|TP|ENTRY|LEVERAGE|LEV|SYMBOL|PAIR|$))',
        'take_profit': r'(?:TP|TAKE\s?PROFIT|TARGET)[\s:]*([^\n]+?)(?=\s*(?:ENTRY|STOP\s?LOSS|SL|STOP|LEVERAGE|LEV|SYMBOL|PAIR|$))',
        'leverage': r'(?:LEVERAGE|LEV)[\s:]*(\d+)x?',
        'symbol': r'(?:SYMBOL|PAIR)[\s:]*([A-Z0-9\/\-]+)',
        'side': r'\b(LONG|SHORT|BUY|SELL)\b'
    }