# Intrinsic Value Strategy

A repository dedicated to applying Graham's intrinsic value strategy along with the picking of growing profits stocks (10 years Liquid Profits CAGR) to provide a higher return over the usual Buy & Hold strategies, being one of the key features of this project.

Built for the [Mansa](https://github.com/mansa-team) project and designed for the automated wallet management system that will help the user with Buy & Hold strategies, maximizing their returns.

## Results

![Backtest Results](./assets/results.png)

### Configuration

1. Create `.env` file:
```env
STOCKSAPI_HOST=localhost
STOCKSAPI_PORT=3200

STOCKSAPI_PRIVATE.KEY=your_api_key_here
```

2. Edit portfolio in `src/__init__.py`:
```python
Portfolio = [
    {'TICKER': 'ITUB3', 'WEIGHT': 90},
    {'TICKER': 'PETR3', 'WEIGHT': 88},
    {'TICKER': 'WEGE3', 'WEIGHT': 87},
    # Add more stocks...
]
```

3. Configure backtest:
```python
config = {
    'SAFETY_MARGIN': 0.50,        # 50% margin
    'INITIAL_CAPITAL': 10000,     # R$ 10,000
    'START_DATE': '2016-01-01',
    'END_DATE': '2024-12-31',
}
```

### Run

```bash
python __init__.py
```

## Trading Strategy

### Step 1: Calculate Intrinsic Value

**Graham's Formula (adapted for Brazil):**

$$V = \frac{\text{LPA} \times (8.5 + 2x) \times z}{y}$$

Where:
- **V** = Intrinsic Value (R$)
- **LPA** = Earnings Per Share (R$)
- **x** = 10-year Liquid Profits CAGR (%)
- **y** = Current SELIC Rate (%)
- **z** = Average SELIC Rate over the period of 10 years average (%)

**Why these components?**

| Component | Meaning | Impact on Valuation |
|-----------|---------|-------------------|
| LPA | Current earnings per share | Higher earnings = Higher value |
| 8.5 | Base P/L for 0% growth stocks | Baseline multiplier for earnings |
| 2x | Growth premium (1% growth = +2 P/L points) | Higher growth = Exponentially higher value |
| y | Current interest rate (SELIC) | Higher rates = Lower valuations (inverse relationship) |
| z | Average SELIC rate over 10 years | Historical rate baseline for long-term valuation |

**Example:**
```
LPA = R$ 2.78
x = 15% (CAGR)
y = 10.5% (Current SELIC)
z = 9.5% (10-year Average SELIC)

V = (2.78 × (8.5 + 2×15) × 9.5) / 10.5
V = (2.78 × 38.5 × 9.5) / 10.5
V = 1,016.79 / 10.5
V = R$ 96.84
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
V = R$ 96.84
m = 0.50 (50%)

Buy Price = 96.84 × (1 - 0.50) = R$ 48.42
Sell Price = 96.84 × (1 + 0.50) = R$ 145.26
```

### Signal Zones

```
Price Scale:

R$ 145.26  ├─────────────────────────────────
           │  SELL ZONE (Full Exit)
           │
R$ 96.84   ├─────────────────────────────────
           │  INTRINSIC VALUE
           │
R$ 48.42   ├─────────────────────────────────
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
V = R$ 96.84
Initial position: 1,000 shares

Level 1: Price = R$ 145.26
  Sell 500 shares

Level 2: Price = R$ 171.31
  Sell 250 shares

Result: Locked in profits at each level
```

## Capital Allocation

### Weighted Purchase Price (WPP)

Allocate capital based on how undervalued each stock is, weighted by its Strategic Weight (SW):

$$\text{WPP}_i = \frac{\text{IV}_i}{\text{Price}_i} \times \text{SW}_i$$

Where:
- **IV** = Intrinsic Value
- **Price** = Current Market Price
- **SW** = Strategic Weight (range: 1-100)

The Strategic Weight (SW) represents how important a stock is to your portfolio strategy. Higher SW values indicate stocks you want to prioritize for capital allocation.

**Example (2 stocks, using Strategic Weights):**

```
Stock A: IV = 100, Price = 40, SW = 90 (High Strategic Importance)
  Discount Factor = 100/40 = 2.5x
  WPP_A = 2.5 × 90 = 225

Stock B: IV = 50, Price = 20, SW = 50 (Medium Strategic Importance)
  Discount Factor = 50/20 = 2.5x
  WPP_B = 2.5 × 50 = 125
```

**Key Insight:**
Although both stocks have the same discount factor (2.5x), Stock A receives higher WPP (225 vs 125) due to its greater Strategic Weight (90 vs 50). This allows you to concentrate capital on strategically important positions while still respecting market valuations.

### Proportional Capital Distribution (PCD)

Determine what % of total capital each stock gets:

$$\text{PCD}_i = \frac{\text{WPP}_i}{\sum \text{WPP}} \times 100\%$$

$$\text{Capital Allocated}_i = \text{PCD}_i \times \text{Total Capital}$$

**Example (continuing above, R$ 10,000 total):**
```
Stock A: PCD = (12,500 / 22,500) × 100% = 55.56%
         Capital = R$ 5,556

Stock B: PCD = (10,000 / 22,500) × 100% = 44.44%
         Capital = R$ 4,444

Result: More capital to the more undervalued stock
```

### Shares to Buy

$$\text{Shares} = \left\lfloor \frac{\text{Allocated Capital}}{\text{Current Price}} \right\rfloor$$

**Example (continuing above):**
```
Stock A: floor(5,556 / 40) = 138 shares
Stock B: floor(4,444 / 20) = 222 shares
```

## Capital Liquidation

### Weighted Sell Factor (WSF)

The algorithm calculates a factor to determine liquidation priority. If the whole portfolio is undervalued, it triggers an "emergency" quadratic scaling to protect deep-value assets.

$$\text{WSF}_i = \left(\frac{\text{Price}_i}{V_i}\right)^k \times \frac{100}{\text{SW}_i}$$

Where the exponent $k$ is determined by the portfolio state:

$$k = \begin{cases} 
1, & \text{if } \text{Price}_i \ge V_i \text{ (Standard Overvaluation)} \\ 
2, & \text{if } \text{Price}_i < V_i \text{ (Emergency Protection)} 
\end{cases}$$

**Logic Components:**

| Component | Meaning | Impact |
|-----------|---------|--------|
| $k=1$ | Linear Exit | Standard profit taking proportional to overvaluation. |
| $k=2$ | Quadratic Shield | Squaring a ratio $<1$ makes it much smaller, shielding undervalued stocks. |
| $\frac{100}{\text{SW}}$ | Strategic Inverse | Lower Strategic Weight makes the stock more likely to be sold. |

**Example:**

```
Stock A: Price = 100, V = 80, SW = 90
  Price/V = 100/80 = 1.25 (overvalued)
  k = 1 (Standard Overvaluation)
  WSF_A = (1.25)^1 × (100/90) = 1.25 × 1.11 = 1.389

Stock B: Price = 40, V = 50, SW = 50
  Price/V = 40/50 = 0.80 (undervalued)
  k = 2 (Emergency Protection)
  WSF_B = (0.80)^2 × (100/50) = 0.64 × 2.00 = 1.28

Result: Stock A's higher price/value ratio gives it higher priority for liquidation.
        Stock B's quadratic protection (k=2) shields it from aggressive selling.
```

### Proportional Liquidation Distribution (PLD)

Determine how much of the cash target is requested from each stock:

$$\text{PLD}_i = \frac{\text{WSF}_i}{\sum \text{WSF}} \times 100\%$$

$$\text{Shares to Sell}_i = \left\lceil \frac{\text{PLD}_i \times \text{Target Cash}}{\text{Price}_i} \right\rceil$$

**Example (continuing above, Target Cash: R$ 5,000):**

```
Total WSF = 1.389 + 1.28 = 2.669

Stock A: PLD_A = (1.389 / 2.669) × 100% = 52.04%
         Target Cash = 52.04% × 5,000 = R$ 2,602
         Shares to Sell = ceil(2,602 / 100) = 27 shares

Stock B: PLD_B = (1.28 / 2.669) × 100% = 47.96%
         Target Cash = 47.96% × 5,000 = R$ 2,398
         Shares to Sell = ceil(2,398 / 40) = 60 shares

Result: Stock A (overvalued) prioritized for liquidation.
        Stock B (undervalued) sells fewer shares despite higher quantity,
        because the ceiling function only rounds up when necessary to achieve
        the proportional cash target, not arbitrarily.
```

## TODO
- [ ] Refactor the codebase for a cleaner readability
- [ ] Improve the WPP algorithm to work more as an cap and not as a grade for the stock, preventing "value traps"
- [ ] Make the Partial Sell system prioritize the selling of stocks that are over the SW allocation, rebalancing the portfolio
- [ ] Implement a proper rebalancing system for the portfolio
- [ ] Implement a stock picking algorithm based on the user's profile
- [ ] Implement an API based system for scalability and use in actual production at Mansa

## Visual Overview

![Strategy's Framework](./assets/strategy.png)

## License
Mansa Team's MODIFIED GPL 3.0 License. See LICENSE for details.
