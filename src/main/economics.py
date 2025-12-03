import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from imports import *

# Constants
PROFIT_MARGIN_THRESHOLDS = [
    (1, 1.50, 0.50),
    (2, 1.675, 0.50),
    (3, 1.85, 0.50),
    (4, 2.025, 0.50),
    (5, 2.20, 1.00),
]

# Load SELIC data
selicDf = requests.get('https://api.bcb.gov.br/dados/serie/bcdata.sgs.4189/dados?formato=json')
selicDf = pd.DataFrame(selicDf.json())
selicDf['data'] = pd.to_datetime(selicDf['data'], format='%d/%m/%Y')
selicDf['valor'] = selicDf['valor'].astype('float64')
selicDf = selicDf.sort_values('data').reset_index(drop=True)

def getInterestRates(date: pd.Timestamp) -> Tuple[Optional[float], Optional[float]]:
    """
    Get current SELIC rate (y) and 10-year average SELIC rate (z)
    
    Args:
        date: datetime object for the target date
    
    Returns: 
        (y, z) as decimals (0.105 = 10.5%)
        - y: Current SELIC rate on or before target date
        - z: Average SELIC rate over the 10 years preceding target date
        - (None, None) if data unavailable
    """
    global selicDf
    
    if selicDf is None or len(selicDf) == 0:
        return None, None
    
    # Ensure date is datetime
    if not isinstance(date, pd.Timestamp):
        date = pd.Timestamp(date)
    
    # Current SELIC rate on or before target date
    selicFiltered = selicDf[selicDf['data'] <= date]
    if len(selicFiltered) == 0:
        return None, None
    
    y = selicFiltered.iloc[-1]['valor'] / 100
    
    # 10-year average SELIC (from 10 years before target date to target date)
    tenYearsAgo = pd.Timestamp(date.year - 10, date.month, date.day)
    selic10y = selicDf[(selicDf['data'] >= tenYearsAgo) & (selicDf['data'] <= date)]
    
    if len(selic10y) == 0:
        return y, y
    
    z = selic10y['valor'].mean() / 100
    
    return y, z

def calculateCAGR(profitList: List[float], yearList: List[int]) -> Optional[float]:
    """
    Calculate Compound Annual Growth Rate
    
    CAGR = (Profit_Final / Profit_Initial)^(1/n) - 1
    
    Args:
        profitList: list of profit values in chronological order
        yearList: corresponding list of years
    
    Returns:
        CAGR as decimal (0.10 = 10%), or None if calculation fails
    """
    if len(profitList) < 2 or any(p <= 0 for p in profitList):
        return None
    
    initialProfit = profitList[0]
    finalProfit = profitList[-1]
    
    # Calculate actual years elapsed
    yearsElapsed = yearList[-1] - yearList[0]
    
    if yearsElapsed <= 0:
        return None
    
    cagr = (finalProfit / initialProfit) ** (1 / yearsElapsed) - 1
    return cagr

def calculateIntrinsicValue(
    ticker: str,
    date: pd.Timestamp,
    profitData: Dict[str, pd.DataFrame],
    lpaData: Dict[str, pd.DataFrame]
) -> Optional[float]:
    """
    Calculate Graham's Intrinsic Value using SELIC-adjusted formula
    
    V = (LPA × (8.5 + 2x) × z) / y
    
    Where:
    - LPA = Earnings Per Share (R$) for the target year
    - x = 10-year Liquid Profits CAGR (as decimal)
    - y = Current SELIC Rate (as decimal) on the target date
    - z = Average SELIC Rate over 10 years (as decimal)
    
    Args:
        ticker: stock ticker symbol
        date: target date (datetime)
        profitData: dict {ticker: DataFrame with 'ANO' and 'LUCRO LIQUIDO' columns}
        lpaData: dict {ticker: DataFrame with 'year' and 'value' columns}
    
    Returns:
        Intrinsic Value (R$) or None if calculation fails
    """
    try:
        # Validate profit data exists
        if ticker not in profitData or profitData[ticker].empty:
            return None
        
        dfProfit = profitData[ticker].copy()
        dfProfit = dfProfit[dfProfit['ANO'] < date.year].sort_values('ANO')
        
        if len(dfProfit) < 2:
            return None
        
        # Calculate CAGR from available history
        profitValues = dfProfit['LUCRO LIQUIDO'].tolist()
        yearValues = dfProfit['ANO'].tolist()
        x = calculateCAGR(profitValues, yearValues)
        
        if x is None:
            return None
        
        # Get SELIC rates for the specific date
        y, z = getInterestRates(date)
        if y is None or z is None or y == 0:
            return None
        
        # Get LPA for target year
        if ticker not in lpaData or lpaData[ticker].empty:
            return None
        
        dfLpa = lpaData[ticker]
        lpaValues = dfLpa[dfLpa['year'] == date.year]['value']
        
        if lpaValues.empty or lpaValues.iloc[0] <= 0:
            return None
        
        lpa = lpaValues.iloc[0]
        
        # Apply Graham's Formula: V = (LPA × (8.5 + 2x) × z) / y
        iv = (lpa * (8.5 + 2 * x) * z) / y
        
        return round(iv, 2) if iv > 0 else None
    
    except Exception:
        return None

def calculateBuyPrice(intrinsicValue: Optional[float], safetyMargin: float) -> Optional[float]:
    """
    Calculate Buy Price with Safety Margin
    
    Buy Price = V × (1 - m)
    
    Args:
        intrinsicValue: the stock's intrinsic value
        safetyMargin: safety margin as decimal (0.50 = 50%)
    
    Returns:
        Buy price or None if input invalid
    """
    if intrinsicValue is None or intrinsicValue <= 0:
        return None
    
    return round(intrinsicValue * (1 - safetyMargin), 2)

def calculateSellPrice(intrinsicValue: Optional[float], safetyMargin: float) -> Optional[float]:
    """
    Calculate Sell Price with Safety Margin
    
    Sell Price = V × (1 + m)
    
    Args:
        intrinsicValue: the stock's intrinsic value
        safetyMargin: safety margin as decimal (0.50 = 50%)
    
    Returns:
        Sell price or None if input invalid
    """
    if intrinsicValue is None or intrinsicValue <= 0:
        return None
    
    return round(intrinsicValue * (1 + safetyMargin), 2)

def generateTradingSignal(
    currentPrice: float,
    intrinsicValue: Optional[float],
    safetyMargin: float
) -> str:
    """
    Generate Trading Signal based on price vs intrinsic value
    
    Args:
        currentPrice: current market price
        intrinsicValue: calculated intrinsic value
        safetyMargin: safety margin as decimal
    
    Returns:
        'BUY', 'HOLD', or 'SELL'
    """
    if intrinsicValue is None or intrinsicValue <= 0 or currentPrice <= 0:
        return 'HOLD'
    
    buyPrice = calculateBuyPrice(intrinsicValue, safetyMargin)
    sellPrice = calculateSellPrice(intrinsicValue, safetyMargin)
    
    if buyPrice is None or sellPrice is None:
        return 'HOLD'
    
    if currentPrice <= buyPrice:
        return 'BUY'
    elif currentPrice >= sellPrice:
        return 'SELL'
    else:
        return 'HOLD'

def calculatePartialSellLevels(
    intrinsicValue: Optional[float],
    safetyMargin: float
) -> List[Dict]:
    """
    Generate Partial Sell Strategy Levels dynamically
    
    For every 17.5% increase above the base sell price (V × (1 + m)),
    sell 50% of remaining position, capped at full exit.
    
    Args:
        intrinsicValue: the stock's intrinsic value
        safetyMargin: safety margin as decimal
    
    Returns: 
        List of dicts with level configuration:
        [
            {'level': int, 'trigger_price': float, 'profit_margin': float, 'sell_pct': float},
            ...
        ]
    """
    if intrinsicValue is None or intrinsicValue <= 0:
        return []
    
    levels = []
    
    for level, multiplier, sellPct in PROFIT_MARGIN_THRESHOLDS:
        triggerPrice = intrinsicValue * multiplier
        levels.append({
            'level': level,
            'trigger_price': round(triggerPrice, 2),
            'profit_margin': multiplier,
            'sell_pct': sellPct
        })
    
    return levels

def calculateWPP(
    intrinsicValue: Optional[float],
    currentPrice: float,
    strategicWeight: float
) -> float:
    """
    Calculate Weighted Purchase Price (WPP)
    
    WPP = (IV / Price) × SW
    
    Where:
    - IV = Intrinsic Value
    - Price = Current Market Price
    - SW = Strategic Weight (1-100)
    
    Args:
        intrinsicValue: stock's intrinsic value
        currentPrice: current market price
        strategicWeight: portfolio weight (1-100)
    
    Returns:
        WPP score (higher = more undervalued), or 0 if invalid input
    """
    if intrinsicValue is None or intrinsicValue <= 0 or currentPrice <= 0:
        return 0
    
    discountFactor = intrinsicValue / currentPrice
    wpp = round(discountFactor * strategicWeight, 4)
    return wpp

def allocateCapitalByWPP(
    buySignals: Dict[str, Dict],
    totalCapital: float
) -> Dict[str, float]:
    """
    Proportional Capital Distribution (PCD)
    
    Allocate capital based on WPP values proportionally
    
    Args:
        buySignals: dict mapping ticker to signal data:
                    {ticker: {'iv': float, 'price': float, 'wpp': float, ...}, ...}
        totalCapital: available cash for allocation
    
    Returns:
        Dict mapping ticker to allocated amount: {ticker: float, ...}
    """
    if not buySignals or totalCapital <= 0:
        return {}
    
    # Extract WPP values
    wppDict = {ticker: data.get('wpp', 0) for ticker, data in buySignals.items()}
    totalWpp = sum(wppDict.values())
    
    if totalWpp <= 0:
        return {}
    
    # Allocate capital proportionally to WPP
    allocations = {}
    for ticker, wpp in wppDict.items():
        allocationPct = (wpp / totalWpp) * 100
        allocations[ticker] = (allocationPct / 100) * totalCapital
    
    return allocations