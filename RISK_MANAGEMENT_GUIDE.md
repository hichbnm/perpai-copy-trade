# Risk Management & Position Sizing Guide

This document explains the formulas and logic used by the trading bot to calculate positions, manage risk, and protect your capital.

---

## 📐 Formulas

### **1. Position Sizing (Fixed Amount System)**

```
leveraged_amount = fixed_amount × leverage
```

- **fixed_amount**: Your base trade amount (e.g., $10)
- **leverage**: Multiplier (e.g., 20x)
- **leveraged_amount**: Total position value (e.g., $10 × 20 = $200)

### **2. Quantity Calculation**

**Bybit (USD-based):**
```
position_size = leveraged_amount
quantity = position_size / entry_price
```

**Hyperliquid (Coin-based):**
```
position_size = leveraged_amount / entry_price (in coins)
```

### **3. Risk Distance (Stop Loss Percentage)**

```
price_distance = |entry_price - stop_loss|
risk_distance = price_distance / entry_price
```

**Example:**
- Entry: $100, Stop Loss: $95
- price_distance = |100 - 95| = $5
- risk_distance = 5 / 100 = 0.05 (5%)

### **4. Expected Loss Calculation**

```
expected_loss = fixed_amount × risk_distance × leverage
```

**Example:**
- fixed_amount = $10
- risk_distance = 5% (0.05)
- leverage = 20x
- expected_loss = $10 × 0.05 × 20 = **$10**

### **5. Maximum Allowed Loss**

```
max_allowed_loss = total_balance × (max_risk_percent / 100)
```

**Example:**
- total_balance = $100
- max_risk_percent = 2%
- max_allowed_loss = $100 × 0.02 = **$2**

### **6. Safety Cap (Position Reduction)**

```
IF expected_loss > max_allowed_loss THEN:
    scaling_factor = max_allowed_loss / expected_loss
    fixed_amount = fixed_amount × scaling_factor
    leveraged_amount = fixed_amount × leverage
```

**Example:**
- expected_loss = $10
- max_allowed_loss = $2
- scaling_factor = 2 / 10 = 0.2
- **new fixed_amount = $10 × 0.2 = $2**
- **new leveraged_amount = $2 × 20 = $40**

### **7. Margin Requirement**

```
margin_required = leveraged_amount / leverage = fixed_amount
```

**Example:**
- leveraged_amount = $200
- leverage = 20x
- margin_required = $200 / 20 = **$10**

---

## 💡 Complete Example

**Settings:**
- Balance: $50
- Fixed Amount: $10
- Leverage: 20x
- Max Risk: 2%
- Entry: $100
- Stop Loss: $95

**Calculations:**
1. `leveraged_amount = $10 × 20 = $200`
2. `risk_distance = |100 - 95| / 100 = 5%`
3. `expected_loss = $10 × 0.05 × 20 = $10`
4. `max_allowed_loss = $50 × 0.02 = $1`
5. `expected_loss ($10) > max_allowed_loss ($1)` → **REDUCE POSITION**
6. `scaling_factor = $1 / $10 = 0.1`
7. `adjusted_fixed_amount = $10 × 0.1 = $1`
8. `adjusted_leveraged_amount = $1 × 20 = $20`
9. `quantity = $20 / $100 = 0.2 coins`
10. `margin_required = $1`

**Result:** Position reduced from $200 to $20 to respect 2% max risk!

---

## 🎯 Real Trading Scenario

### **📊 Scenario Setup**

**Your Account:**
- Exchange: Bybit
- Balance: $100
- Risk Management Settings: 5% max risk
- Fixed Trade Amount: $15

**Signal Received:**
```
Symbol: ETHUSDT
Side: LONG
Entry: $2,650
Stop Loss: $2,570
Take Profit 1: $2,730
Take Profit 2: $2,810
Leverage: 25x
```

---

### **🔢 Step-by-Step Calculations**

#### **Step 1: Initial Position Size**
```
leveraged_amount = fixed_amount × leverage
leveraged_amount = $15 × 25 = $375
```
**Initial position value: $375**

---

#### **Step 2: Risk Distance Calculation**
```
price_distance = |entry_price - stop_loss|
price_distance = |$2,650 - $2,570| = $80

risk_distance = price_distance / entry_price
risk_distance = $80 / $2,650 = 0.0302 = 3.02%
```
**If stop loss hits, you lose 3.02% of your position**

---

#### **Step 3: Expected Loss Calculation**
```
expected_loss = fixed_amount × risk_distance × leverage
expected_loss = $15 × 0.0302 × 25
expected_loss = $11.32
```
**If stop loss triggers, you would lose $11.32**

---

#### **Step 4: Maximum Allowed Loss**
```
max_allowed_loss = total_balance × (max_risk_percent / 100)
max_allowed_loss = $100 × (5 / 100)
max_allowed_loss = $5.00
```
**With 5% max risk, you can only afford to lose $5**

---

#### **Step 5: Safety Cap Check**
```
Is expected_loss > max_allowed_loss?
Is $11.32 > $5.00?  ✅ YES - POSITION MUST BE REDUCED
```

---

#### **Step 6: Position Reduction (Safety Cap)**
```
scaling_factor = max_allowed_loss / expected_loss
scaling_factor = $5.00 / $11.32 = 0.4417

adjusted_fixed_amount = fixed_amount × scaling_factor
adjusted_fixed_amount = $15 × 0.4417 = $6.63

adjusted_leveraged_amount = adjusted_fixed_amount × leverage
adjusted_leveraged_amount = $6.63 × 25 = $165.75
```
**Position reduced from $375 to $165.75**

---

#### **Step 7: Quantity Calculation**
```
quantity = adjusted_leveraged_amount / entry_price
quantity = $165.75 / $2,650
quantity = 0.0625 ETH
```

---

#### **Step 8: Margin Required**
```
margin_required = adjusted_fixed_amount
margin_required = $6.63
```
**Your account needs $6.63 available to open this trade**

---

#### **Step 9: Verify Final Risk**
```
final_expected_loss = adjusted_fixed_amount × risk_distance × leverage
final_expected_loss = $6.63 × 0.0302 × 25
final_expected_loss = $5.00 ✅

This equals exactly your max_allowed_loss of $5.00
```

---

### **📋 Order Placement**

**Main Order (Market):**
- Symbol: ETHUSDT
- Side: BUY
- Quantity: 0.0625 ETH
- Entry Price: ~$2,650 (market)
- Position Value: $165.75
- Margin Used: $6.63

**Stop Loss:**
- Trigger: $2,570
- Loss if hit: $5.00 (5% of balance)

**Take Profit Orders:**
- TP1: 0.03125 ETH @ $2,730 (50% of position)
  - Profit: $2.50
- TP2: 0.03125 ETH @ $2,810 (remaining 50%)
  - Profit: $5.00

---

### **💰 Potential Outcomes**

**Worst Case (Stop Loss Hit):**
```
Loss = $5.00
New Balance = $100 - $5 = $95.00 (-5%)
```

**Best Case (Both TPs Hit):**
```
TP1 Profit = ($2,730 - $2,650) × 0.03125 = $2.50
TP2 Profit = ($2,810 - $2,650) × 0.03125 = $5.00
Total Profit = $7.50
New Balance = $100 + $7.50 = $107.50 (+7.5%)
```

**Risk-to-Reward Ratio:**
```
Risk: $5.00
Reward: $7.50
R:R = 1:1.5
```

---

### **🎯 What the Bot Does Automatically**

1. ✅ Reads your settings: $15 trade, 5% max risk, 25x leverage
2. ✅ Calculates initial position: $375
3. ✅ Detects this would risk $11.32 (exceeds $5 limit)
4. ⚠️ **Reduces position to $165.75** to keep risk at exactly $5
5. ✅ Places market order for 0.0625 ETH
6. ✅ Sets stop loss at $2,570
7. ✅ Places 2 take profit orders (splits position 50/50)

---

### **📊 Example Logs**

When the bot executes this trade, you would see logs like:

```
🛡️ Risk Check:
   Entry: $2650.00
   Stop Loss: $2570.00
   Distance: 3.02%
   Expected Loss: $11.32
   Max Allowed Loss (5%): $5.00

⚠️ Position reduced to respect 5% max risk:
   Adjusted Amount: $6.63
   Adjusted Position: $165.75

💰 Fixed amount position sizing:
   Fixed Amount: $6.63
   Leverage: 25x
   Position Size: $165.75
   Entry Price: $2650.00

📊 Bybit Trade: ETHUSDT Buy 0.0625 @ $2650.00 (Leverage: 25x, Value: $165.75)

✅ Main order placed successfully: [order_id]
✅ Stop Loss set at $2570.00
✅ Take Profit 1 placed at $2730.00 (size: 0.03125)
✅ Take Profit 2 placed at $2810.00 (size: 0.03125)
```

---

## 🛡️ Safety Features

### **1. Balance Protection**
The bot never risks more than your configured max risk percentage per trade.

### **2. Minimum Order Size**
- Bybit: $5 minimum order value
- Hyperliquid: Varies by asset

If your position is reduced below minimum, the bot will either:
- Use the minimum required amount
- Skip the trade if balance is too low

### **3. Leverage Limits**
The bot respects exchange leverage limits and will not exceed maximum allowed leverage for each symbol.

### **4. Real-time Balance Check**
Before placing any order, the bot verifies you have sufficient available balance.

---

## ⚙️ Configuring Your Settings

### **Via Discord Bot**

Use the `/riskmanagement` command to update:
- **Fixed Amount**: Base trade size (e.g., $10, $50, $100)
- **Max Risk %**: Maximum percentage of balance to risk per trade (e.g., 1%, 2%, 5%)

### **Via Admin Panel**

Navigate to `Subscriptions` → Edit channel subscription → Update:
- Position Mode: `fixed`
- Fixed Amount: Your desired trade amount
- Max Risk: Your risk tolerance percentage

---

## 📈 Best Practices

1. **Start Small**: Begin with a low fixed amount ($5-$10) to test the system
2. **Conservative Risk**: Keep max risk at 1-2% for consistent capital preservation
3. **Monitor Balance**: Ensure you have at least 10x your fixed amount in available balance
4. **Understand Leverage**: Higher leverage amplifies both profits and losses
5. **Use Stop Losses**: Always enable stop loss in signals for protection
6. **Regular Review**: Check your trade history and adjust settings based on performance

---

## 🔍 Troubleshooting

### "ab not enough for new order"
**Cause:** Insufficient available balance on exchange

**Solution:**
- Check your exchange balance
- Reduce fixed amount
- Reduce leverage
- Increase max risk % (with caution)

### Position is too small
**Cause:** Safety cap reduced position below minimum order size

**Solution:**
- Increase fixed amount
- Increase max risk %
- Reduce leverage
- Choose signals with tighter stop losses

### Trade not executing
**Cause:** Multiple possible reasons

**Check:**
1. Exchange API keys are valid
2. Sufficient balance available
3. Symbol is available on exchange
4. Leverage settings are correct

---

## 📞 Support

For questions or issues:
1. Check `/dashboard` for trade history
2. Review logs in `logs/trading_bot.log`
3. Contact admin panel for configuration help

---

**Last Updated:** November 10, 2025
