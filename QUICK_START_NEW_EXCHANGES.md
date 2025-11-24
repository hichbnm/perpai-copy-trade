# 🚀 Quick Start: Using New Exchanges

## Binance Futures Setup

### 1. Create API Key on Binance
1. Go to https://www.binance.com/en/my/settings/api-management
2. Create a new API key
3. Enable **Futures Trading** permission
4. Save your API Key and Secret Key

### 2. Add to Bot
```
/add_api_key exchange:binance api_key:YOUR_API_KEY api_secret:YOUR_SECRET
```

### 3. Subscribe to Channel
```
/subscribe channel_id:CHANNEL_ID
```

### 4. Start Trading!
The bot will automatically execute trades when signals are posted in the subscribed channel.

---

## OKX Perpetuals Setup

### 1. Create API Key on OKX
1. Go to https://www.okx.com/account/my-api
2. Create a new API key
3. Set permissions: **Trade** (required)
4. Set a **passphrase** (remember this!)
5. Save your API Key, Secret Key, and Passphrase

### 2. Add to Bot
```
/add_api_key exchange:okx api_key:YOUR_API_KEY api_secret:YOUR_SECRET passphrase:YOUR_PASSPHRASE
```

### 3. Subscribe to Channel
```
/subscribe channel_id:CHANNEL_ID
```

### 4. Start Trading!
Trades will execute automatically on OKX.

---

## Testnet/Demo Trading

### Binance Testnet
1. Go to https://testnet.binancefuture.com
2. Login with your Binance account
3. Get test USDT from the faucet
4. Create API keys on testnet
5. Use with bot (bot auto-detects testnet API keys)

### OKX Demo Trading
1. Use regular OKX API keys
2. Enable demo trading in your OKX account settings
3. The bot will execute trades in demo mode

---

## Switching Exchanges

To switch from one exchange to another:

1. **Remove old API key** (automatic when adding new one for same user)
2. **Add new exchange API key**
```
/add_api_key exchange:NEW_EXCHANGE api_key:... api_secret:...
```

Your subscriptions remain active - only the execution exchange changes!

---

## Comparing Exchanges

### Hyperliquid
- ✅ Lowest fees (maker rebates)
- ✅ Direct blockchain interaction
- ✅ No KYC required
- ⚠️ Lower liquidity than CEX
- 🎯 Best for: DeFi traders, MEV, advanced users

### Bybit
- ✅ High leverage (up to 100x)
- ✅ Good liquidity
- ✅ Beginner-friendly
- ⚠️ KYC required
- 🎯 Best for: High leverage trading, futures

### Binance
- ✅ Highest liquidity
- ✅ Most trading pairs
- ✅ Lowest spreads
- ⚠️ Strict KYC
- 🎯 Best for: Large positions, popular pairs

### OKX
- ✅ Advanced features
- ✅ Global access
- ✅ Demo trading mode
- ⚠️ 3 credentials needed
- 🎯 Best for: Advanced traders, international users

---

## Example Signal Execution

When a signal like this is posted:
```
🔵 LONG BTC
ENTRY: 50000
SL: 49000
TP1: 51000
TP2: 52000
TP3: 53000
LEVERAGE: 10x
```

**What happens on each exchange:**

### Hyperliquid
- Symbol: `BTC`
- Order: Native blockchain transaction
- SL/TP: On-chain orders

### Bybit
- Symbol: `BTCUSDT`
- Order: Market order via API
- SL: Trading-stop position-level SL
- TP: Multiple limit orders

### Binance
- Symbol: `BTCUSDT`
- Order: MARKET order
- SL: STOP_MARKET order
- TP: Multiple TAKE_PROFIT_MARKET orders

### OKX
- Symbol: `BTC-USDT-SWAP`
- Order: Market order in contracts
- SL: Conditional algo order
- TP: Multiple limit orders with reduceOnly

**All exchanges:**
- ✅ Use your fixed amount from subscription
- ✅ Apply risk management (max 2% loss)
- ✅ Split position across TPs
- ✅ Move SL to breakeven after TP1 hit

---

## Troubleshooting

### Binance: "Invalid API key"
- Ensure Futures Trading is enabled on your API key
- Check if using testnet vs mainnet keys
- Verify API key hasn't expired

### OKX: "Invalid passphrase"
- Passphrase is case-sensitive
- Must match exactly what you set on OKX website
- Cannot be recovered - must create new API key if forgotten

### "Symbol not available"
- Binance: Check if futures contract exists (not all coins have USDT perpetuals)
- OKX: Check if SWAP contract exists
- Try different symbol or exchange

### "Insufficient balance"
- Minimum $5 order value required
- With 10x leverage, need minimum $0.50 balance
- Check if funds are in Futures wallet (not Spot)

---

## Pro Tips

1. **Start with Testnet/Demo**
   - Test the bot with fake money first
   - Verify signals execute correctly
   - Check TP/SL placement

2. **Use Multiple Exchanges**
   - Different users can use different exchanges
   - Bot handles all exchanges simultaneously
   - Compare execution quality

3. **Monitor Notifications**
   - Bot sends private DMs for each trade
   - Channel notifications for all users
   - Check for "LIVE" vs "SIMULATED" mode

4. **Risk Management**
   - Bot automatically limits risk to 2% per trade
   - Position size scales down if SL too wide
   - Never risks more than max_risk setting

5. **Leverage Settings**
   - Use leverage specified in signal
   - Higher leverage = smaller required balance
   - But also higher liquidation risk!

---

## Support Commands

Check your setup:
```
/balance - View exchange balance
/positions - See open positions
/profile - View your settings
/help - Get command list
```

Happy trading! 🚀
