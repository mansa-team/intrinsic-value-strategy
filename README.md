# Intrinsic Value Strategy

A repository dedicated to applying Graham's intrinsic value strategy along with the picking of growing profits stocks (10 years Liquid Profits CAGR) to provide a higher return over the usual Buy & Hold strategies, being one of the key features of this project.

Built for the [Mansa](https://github.com/mansa-team) project and designed for the automated wallet management system that will help the user with Buy and Hold strategies, maximizing their returns.

## The Strategy

### Step 1: Calculate Intrinsic Value

**Graham's Formula (adapted for Brazil):**

$$V = \frac{\text{LPA} \times (8.5 + 2x)}{y}$$

Where:
- **V** = Intrinsic Value (R$)
- **LPA** = Earnings Per Share (R$)
- **x** = 10-year Liquid Profits CAGR (%)
- **y** = Current SELIC Rate (%)

**Why these components?**

| Component | Meaning |
|-----------|---------|
| LPA | Current earnings per share |
| 8.5 | Base PE (P/L) for 0% growth stocks |
| 2x | Growth premium (1% growth = +2 PE points) |
| y | Current interest rate (discount rate) |

**Example:**
```
LPA = R$ 2.78
x = 15% (CAGR)
y = 10.5% (SELIC)

V = 2.78 × (8.5 + 2×15) / 10.5
V = 2.78 × 38.5 / 10.5
V = R$ 101.97
```

### Step 2: Validate Growth (10-Year CAGR)

Only stocks with consistent profit growth over 10 years are eligible.

$$\text{CAGR} = \left(\frac{\text{Profit}_{\text{Year 10}}}{\text{Profit}_{\text{Year 1}}}\right)^{\frac{1}{10}} - 1$$

**Requirements:**
- At least 10 years of data
- No negative profit years
- Consistent upward trend

**Example:**
```
Year 1 Profit:  R$ 1,000,000
Year 10 Profit: R$ 2,593,742

CAGR = (2,593,742 / 1,000,000)^(1/10) - 1
CAGR = 10%
```

### Step 3: Generate Trading Signals

Use **Safety Margin** to define entry and exit zones:

$$\text{Buy Price} = V \times (1 - m)$$
$$\text{Sell Price} = V \times (1 + m)$$

Where **m** = Safety Margin (default: 50%)

**Example (continuing above):**
```
V = R$ 101.97
m = 0.50 (50%)

Buy Price = 101.97 × (1 - 0.50) = R$ 50.99
Sell Price = 101.97 × (1 + 0.50) = R$ 152.96
```

### Signal Zones

```
Price Scale:

R$ 152.96  ├─────────────────────────────────
           │  SELL ZONE (Full Exit)
           │
R$ 101.97  ├─────────────────────────────────
           │  INTRINSIC VALUE
           │
R$ 50.99   ├─────────────────────────────────
           │  BUY ZONE (Accumulate)
```

### Signal Rules

```
If Current_Price <= Buy_Price:
    Signal = BUY
    
If Buy_Price < Current_Price < Sell_Price:
    Signal = KEEP
    
If Current_Price >= Sell_Price:
    Signal = SELL
```

### Step 4: Partial Sell Strategy

For every 17.5% increase above the 50% safety margin, sell 50% of position, logarithimically.

**Sell Levels:**

| Level | Trigger Price | Profit Margin | Action |
|-------|---------------|---------------|--------|
| 1 | V × 1.50 | +50% | Sell 50% |
| 2 | V × 1.675 | +67.5% | Sell 50% of remaining |
| 3 | V × 1.85 | +85% | Sell 50% of remaining |
| 4 | V × 2.025 | +102.5% | Sell 50% of remaining |
| 5 | V × 2.20 | +120% | Sell remaining |

**Example:**
```
V = R$ 101.97
Initial position: 1,000 shares

Level 1: Price = R$ 152.96
  Sell 500 shares

Level 2: Price = R$ 171.31
  Sell 250 shares

Result: Locked in profits at each level
```

## Capital Allocation

### Weighted Purchase Price (WPP)

Allocate capital based on how undervalued each stock is, weighted by its Strategic Importance (PE):

$$\text{WPP}_i = \frac{\text{IV}_i}{\text{Price}_i} \times \text{PE}_i$$

Where:
- **IV** = Intrinsic Value
- **Price** = Current Market Price
- **PE** = Strategic Weight (Peso Estratégico, range: 1-100)

The Strategic Weight (PE) represents how important a stock is to your portfolio strategy. Higher PE values indicate stocks you want to prioritize for capital allocation.

**Example (2 stocks, using Strategic Weights):**

```
Stock A: IV = 100, Price = 40, PE = 90 (High Strategic Importance)
  Discount Factor = 100/40 = 2.5x
  WPP_A = 2.5 × 90 = 225

Stock B: IV = 50, Price = 20, PE = 50 (Medium Strategic Importance)
  Discount Factor = 50/20 = 2.5x
  WPP_B = 2.5 × 50 = 125
```

**Key Insight:**
Although both stocks have the same discount factor (2.5x), Stock A receives higher WPP (225 vs 125) due to its greater Strategic Weight (90 vs 50). This allows you to concentrate capital on strategically important positions while still respecting market valuations.

### Proportional Capital Distribution (PCD)

Determine what % of total capital each stock gets:

$$\text{PCD}_i = \frac{\text{WPP}_i}{\sum \text{WPP}} \times 100\%$$

$$\text{Capital\_Allocated}_i = \text{PCD}_i \times \text{Total\_Capital}$$

**Example (continuing above, R$ 10,000 total):**
```
Stock A: PCD = (12,500 / 22,500) × 100% = 55.56%
         Capital = R$ 5,556

Stock B: PCD = (10,000 / 22,500) × 100% = 44.44%
         Capital = R$ 4,444

Result: More capital to the more undervalued stock
```

### Shares to Buy

$$\text{Shares} = \left\lfloor \frac{\text{Allocated\_Capital}}{\text{Current\_Price}} \right\rfloor$$

**Example (continuing above):**
```
Stock A: floor(5,556 / 40) = 138 shares
Stock B: floor(4,444 / 20) = 222 shares
```

## Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| Safety Margin | 50% | Buy discount and sell premium |
| Max Hold Time | 3 years | Maximum time to hold a position |
| Profit Margin Spike | 17.5% | Threshold for partial sells |
| Sell Percentage | 50% | Amount to sell per spike |
| Min CAGR | 5% | Minimum profit growth required |
| Rebalance Frequency | Monthly | Signal check interval |

## Why This Strategy Works

**Graham's Formula Benefits:**
- Objective valuation based on earnings, not emotions
- Growth-adjusted pricing (higher growth = higher value)
- Market-rate adjusted (uses current SELIC, not fixed rates)

**Growth Validation:**
- Filters out stagnant or declining companies
- Focuses on proven track records (10 years)
- Avoids value traps

**Safety Margin:**
- Protects against estimation errors
- Provides buffer for market downturns
- Ensures profitable trades (50% minimum gain target)

**Capital Allocation:**
- Concentrates capital on most undervalued stocks
- Proportional to discount factor
- Maximizes return per dollar deployed

## Visual Overview

![Graham's Framework](https://encrypted-tbn3.gstatic.com/licensed-image?q=tbn:ANd9GcQzUKKfhlNERarNN5ZA40UL4iHo2MV6r52GZaYRbeUp1YB0xSggFqskrt6d-fbqDB-iTeA8J9r-zoWiVhJ0_tYvgSia9vnBvpdLtF0LxzzExu5nCLA)

---

## License

GNU GENERAL PUBLIC LICENSE MODIFIED v1.0 - Mansa Team. See LICENSE for details.