import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from imports import *

# Load SELIC data
selic_df = requests.get('https://api.bcb.gov.br/dados/serie/bcdata.sgs.4189/dados?formato=json')
selic_df = pd.DataFrame(selic_df.json())
selic_df['data'] = pd.to_datetime(selic_df['data'], format='%d/%m/%Y')
selic_df['valor'] = selic_df['valor'].astype('float64')
selic_df = selic_df.sort_values('data').reset_index(drop=True)

def getInterestRates(date):
    """
    Get current SELIC rate (y) and 10-year average SELIC rate (z)
    
    Args:
        date: datetime object for the target date
    
    Returns: 
        (y, z) as decimals (0.105 = 10.5%)
        y = Current SELIC rate on or before target date
        z = Average SELIC rate over the 10 years preceding target date
    """
    global selic_df
    
    if selic_df is None or len(selic_df) == 0:
        return None, None
    
    # Ensure date is datetime
    if not isinstance(date, pd.Timestamp):
        date = pd.Timestamp(date)
    
    # Current SELIC rate on or before target date
    selic_filtered = selic_df[selic_df['data'] <= date]
    if len(selic_filtered) == 0:
        return None, None
    
    y = selic_filtered.iloc[-1]['valor'] / 100  # Convert to decimal
    
    # 10-year average SELIC (from 10 years before target date to target date)
    ten_years_ago = pd.Timestamp(date.year - 10, date.month, date.day)
    selic_10y = selic_df[(selic_df['data'] >= ten_years_ago) & (selic_df['data'] <= date)]
    
    if len(selic_10y) == 0:
        return y, y
    
    z = selic_10y['valor'].mean() / 100
    
    return y, z

def calculateCAGR(profit_list, year_list):
    """
    Calculate Compound Annual Growth Rate
    
    CAGR = (Profit_Final / Profit_Initial)^(1/n) - 1
    
    Args:
        profit_list: list of profit values in chronological order
        year_list: corresponding list of years
    
    Returns:
        CAGR as decimal (0.10 = 10%)
    """
    if len(profit_list) < 2 or any(p <= 0 for p in profit_list):
        return None
    
    initial_profit = profit_list[0]
    final_profit = profit_list[-1]
    
    # Calculate actual years elapsed
    years_elapsed = year_list[-1] - year_list[0]
    
    if years_elapsed <= 0:
        return None
    
    cagr = (final_profit / initial_profit) ** (1 / years_elapsed) - 1
    return cagr

def calculateIntrinsicValue(ticker, date, profit_data, lpa_data):
    """
    Calculate Graham's Intrinsic Value
    
    V = (LPA × (8.5 + 2x) × z) / y
    
    Where:
    - LPA = Earnings Per Share (R$) for the target year
    - x = 10-year Liquid Profits CAGR (as decimal)
    - y = Current SELIC Rate (as decimal) on the target date
    - z = Average SELIC Rate over 10 years (as decimal)
    
    Args:
        ticker: stock ticker
        date: target date (datetime)
        profit_data: dict {ticker: DataFrame with 'ANO' and 'LUCRO LIQUIDO' columns}
        lpa_data: dict {ticker: DataFrame with 'year' and 'value' columns}
    
    Returns:
        Intrinsic Value (R$) or None if calculation fails
    """
    try:
        # Validate profit data exists
        if ticker not in profit_data or profit_data[ticker].empty:
            return None
        
        df_profit = profit_data[ticker].copy()
        df_profit = df_profit[df_profit['ANO'] < date.year].sort_values('ANO')
        
        # Need minimum 2 data points (but ideally 10+ years for reliability)
        if len(df_profit) < 2:
            return None
        
        # Calculate CAGR from available history
        profit_values = df_profit['LUCRO LIQUIDO'].tolist()
        year_values = df_profit['ANO'].tolist()
        x = calculateCAGR(profit_values, year_values)
        
        if x is None:
            return None
        
        # Get SELIC rates for the specific date
        y, z = getInterestRates(date)
        if y is None or z is None or y == 0:
            return None
        
        # Get LPA for target year
        if ticker not in lpa_data or lpa_data[ticker].empty:
            return None
        
        df_lpa = lpa_data[ticker]
        lpa_values = df_lpa[df_lpa['year'] == date.year]['value']
        
        if lpa_values.empty or lpa_values.iloc[0] <= 0:
            return None
        
        lpa = lpa_values.iloc[0]
        
        # Apply Graham's Formula: V = (LPA × (8.5 + 2x) × z) / y
        iv = (lpa * (8.5 + 2 * x) * z) / y
        
        return round(iv, 2) if iv > 0 else None
    
    except Exception as e:
        return None

def calculateBuyPrice(intrinsic_value, safety_margin):
    """
    Calculate Buy Price with Safety Margin
    
    Buy Price = V × (1 - m)
    
    Where:
    - V = Intrinsic Value
    - m = Safety Margin (0.50 = 50%)
    """
    if intrinsic_value is None or intrinsic_value <= 0:
        return None
    
    return round(intrinsic_value * (1 - safety_margin), 2)

def calculateSellPrice(intrinsic_value, safety_margin):
    """
    Calculate Sell Price with Safety Margin
    
    Sell Price = V × (1 + m)
    """
    if intrinsic_value is None or intrinsic_value <= 0:
        return None
    
    return round(intrinsic_value * (1 + safety_margin), 2)

def generateTradingSignal(current_price, intrinsic_value, safety_margin):
    """
    Generate Trading Signal
    
    Returns: 'BUY', 'HOLD', or 'SELL'
    """
    if intrinsic_value is None or intrinsic_value <= 0 or current_price <= 0:
        return 'HOLD'
    
    buy_price = calculateBuyPrice(intrinsic_value, safety_margin)
    sell_price = calculateSellPrice(intrinsic_value, safety_margin)
    
    if buy_price is None or sell_price is None:
        return 'HOLD'
    
    if current_price <= buy_price:
        return 'BUY'
    elif current_price >= sell_price:
        return 'SELL'
    else:
        return 'HOLD'

def calculatePartialSellLevels(intrinsic_value, safety_margin=0.50):
    """
    Generate Partial Sell Strategy Levels dynamically
    
    For every 17.5% increase above the base sell price (V × (1 + m)),
    sell 50% of remaining position, capped at full exit.
    
    Args:
        intrinsic_value: the stock's intrinsic value
        safety_margin: safety margin (default 0.50 = 50%)
    
    Returns: 
        list of dicts with level configuration
    """
    if intrinsic_value is None or intrinsic_value <= 0:
        return []
    
    base_sell_price = intrinsic_value * (1 + safety_margin)
    levels = []
    increment = 0.175  # 17.5% increment
    
    # Level 1: 50% above base (V × 1.50)
    # Level 2: 67.5% above base (V × 1.675)
    # Level 3: 85% above base (V × 1.85)
    # Level 4: 102.5% above base (V × 2.025)
    # Level 5: 120% above base (V × 2.20) - Full exit
    
    profit_margins = [
        (1, 1.50, 0.50),
        (2, 1.675, 0.50),
        (3, 1.85, 0.50),
        (4, 2.025, 0.50),
        (5, 2.20, 1.00),
    ]
    
    for level, multiplier, sell_pct in profit_margins:
        trigger_price = intrinsic_value * multiplier
        levels.append({
            'level': level,
            'trigger_price': round(trigger_price, 2),
            'profit_margin': multiplier,
            'sell_pct': sell_pct
        })
    
    return levels

def calculateWPP(intrinsic_value, current_price, strategic_weight):
    """
    Calculate Weighted Purchase Price (WPP)
    
    WPP = (IV / Price) × SW
    
    Where:
    - IV = Intrinsic Value
    - Price = Current Market Price
    - SW = Strategic Weight (1-100)
    
    Args:
        intrinsic_value: stock's intrinsic value
        current_price: current market price
        strategic_weight: portfolio weight (1-100)
    
    Returns:
        WPP score (higher = more undervalued)
    """
    if intrinsic_value is None or intrinsic_value <= 0 or current_price <= 0:
        return 0
    
    discount_factor = intrinsic_value / current_price
    wpp = round(discount_factor * strategic_weight, 4)
    return wpp

def allocateCapitalByWPP(buy_signals, total_capital):
    """
    Proportional Capital Distribution (PCD)
    
    Allocate capital based on WPP values proportionally
    
    Args:
        buy_signals: dict {ticker: {'iv': ..., 'price': ..., 'wpp': ..., ...}}
        total_capital: float, available cash
    
    Returns:
        dict {ticker: allocated_amount}
    """
    if not buy_signals or total_capital <= 0:
        return {}
    
    # Extract WPP values
    wpp_dict = {ticker: data.get('wpp', 0) for ticker, data in buy_signals.items()}
    total_wpp = sum(wpp_dict.values())
    
    if total_wpp <= 0:
        return {}
    
    # Allocate capital proportionally to WPP
    allocations = {}
    for ticker, wpp in wpp_dict.items():
        allocation_pct = (wpp / total_wpp) * 100
        allocations[ticker] = (allocation_pct / 100) * total_capital
    
    return allocations