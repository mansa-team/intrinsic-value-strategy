import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from imports import *

#
#$ SELIC dataframe retireval
#
selic_df = requests.get('https://api.bcb.gov.br/dados/serie/bcdata.sgs.4189/dados?formato=json')
selic_df = pd.DataFrame(selic_df.json())
selic_df = selic_df.astype({'data': 'datetime64[ns]', 'valor': 'float64'})

#
#$ Fundamentalist Economic Analysis
#
def getInterestRates(date):
    global selic_df

    if selic_df is None:
        return None, None

    # Filter data up to target date
    selic_filtered = selic_df[selic_df['data'] <= date]
    
    if len(selic_filtered) == 0:
        return None, None
    
    # Current SELIC rate (latest available on or before target date)
    selic_atual = selic_filtered.iloc[-1]['valor']

    # Average SELIC over 10 years
    selic_yearly = selic_filtered.set_index('data')
    selic_yearly = selic_yearly.groupby(pd.Grouper(freq='YE'))['valor'].mean()
    
    selic_yearly = selic_yearly.reset_index()
    selic_yearly['ano'] = selic_yearly['data'].dt.year
    selic_yearly = selic_yearly[['ano', 'valor']]

    target_year = date.year
    selic_10y = selic_yearly[selic_yearly['ano'] >= target_year - 10]['valor'].mean()

    return selic_atual, selic_10y

def calculateProfitCAGR(TICKER, date):
    response = requests.get(f'http://{Config.STOCKS_API["HOST"]}:{Config.STOCKS_API["PORT"]}/api/historical?search={TICKER}&fields=LUCRO%20LIQUIDO')

    if response.status_code == 200:
        data = response.json()
        data = data['data'][0]
        
        ticker = data['TICKER']
        nome = data['NOME']

        rows = []
        for key, value in data.items():
            if key.startswith('LUCRO LIQUIDO'):
                ano = int(key.split()[-1])
                if ano <= date.year - 1:
                    lucro = value
                    rows.append({'TICKER': ticker, 'NOME': nome, 'ANO': ano, 'LUCRO LIQUIDO': lucro})

        df = pd.DataFrame(rows)
        df = df.sort_values('ANO').reset_index(drop=True)
        
        df_10y = df.tail(10)
        
        if len(df_10y) < 10:
            return None
        
        if df_10y['LUCRO LIQUIDO'].isnull().any() or (df_10y['LUCRO LIQUIDO'] <= 0).any():
            return None
        
        lucro_inicial = df_10y.iloc[0]['LUCRO LIQUIDO']
        lucro_final = df_10y.iloc[-1]['LUCRO LIQUIDO']
        n = len(df_10y) - 1
        
        cagr = ((lucro_final / lucro_inicial) ** (1 / n) - 1) * 100
        
        return round(cagr, 2)
    
    return None

def getCurrentLPA(TICKER):
    response = requests.get(f'http://{Config.STOCKS_API["HOST"]}:{Config.STOCKS_API["PORT"]}/api/fundamental?search={TICKER}&fields=LPA')
            
    if response.status_code == 200:
        api_data = response.json()

        if len(api_data['data']) > 0:
            lpa = api_data['data'][0]['LPA']
            return lpa
        else:
            return None

def calculateIntrinsicValue(TICKER, date):
    """
    V = (LPA * (8.5 + 2 * (x / 100)) * z) / y
    
    Where:
    - x = 10-year Liquid Profit CAGR (%)
    - y = Current SELIC Rate (%)
    - z = Average SELIC Rate over 10 years (%)
    - LPA = Earnings Per Share (R$)
    """

    x = calculateProfitCAGR(TICKER, date)
    y, z = getInterestRates(date)
    lpa = getCurrentLPA(TICKER)

    if x is None or y is None or z is None or lpa is None:
        return None
    
    intrinsicValue = lpa * (8.5 + 2*(x / 100)) * z / y

    return round(intrinsicValue, 2)

#
#$ Trade signals
#
def calculateBuyPrice(intrinsic_value, safety_margin):
    """
    Calculate Buy Price with Safety Margin
    
    Buy Price = V x (1 - m)
    
    Where:
    - V = Intrinsic Value
    - m = Safety Margin (default: 50%)
    
    Example:
        V = R$ 96.84
        m = 0.50
        Buy Price = 96.84 x 0.50 = R$ 48.42
    """
    if intrinsic_value is None:
        return None
    
    return round(intrinsic_value * (1 - safety_margin), 2)

def calculateSellPrice(intrinsic_value, safety_margin):
    """
    Calculate Sell Price with Safety Margin
    
    Sell Price = V x (1 + m)
    
    Example:
        V = R$ 96.84
        m = 0.50
        Sell Price = 96.84 x 1.50 = R$ 145.26
    """
    if intrinsic_value is None:
        return None
    
    return round(intrinsic_value * (1 + safety_margin), 2)

def generateTradingSignal(current_price, intrinsic_value, safety_margin):
    """
    Generate Trading Signal based on Price and Intrinsic Value

    Sell Price  ├─────────────────────────────────
                │  SELL ZONE (Full Exit)
                │
    IV          ├─────────────────────────────────
                │  INTRINSIC VALUE
                │
    Buy Price   ├─────────────────────────────────
                │  BUY ZONE (Accumulate)
    
    Rules:
    - If Current_Price <= Buy_Price: Signal = BUY
    - If Buy_Price < Current_Price < Sell_Price: Signal = KEEP
    - If Current_Price >= Sell_Price: Signal = SELL
    
    Returns: 'BUY', 'KEEP', 'SELL', or 'SKIP'
    """
    if intrinsic_value is None or intrinsic_value <= 0:
        return 'SKIP'
    
    buy_price = calculateBuyPrice(intrinsic_value, safety_margin)
    sell_price = calculateSellPrice(intrinsic_value, safety_margin)
    
    if current_price <= buy_price:
        return 'BUY'
    elif current_price >= sell_price:
        return 'SELL'
    else:
        return 'KEEP'

def calculatePartialSellLevels():
    """
    Get Partial Sell Strategy Levels
    
    For every 17.5% increase above the 50% safety margin, sell 50% of position, logarithmically.
    
    Sell Levels:
    | Level | Trigger Price | Profit Margin | Action |
    |-------|---------------|---------------|--------|
    | 1     | V x 1.50      | +50%          | Sell 50% |
    | 2     | V x 1.675     | +67.5%        | Sell 50% of remaining |
    | 3     | V x 1.85      | +85%          | Sell 50% of remaining |
    | 4     | V x 2.025     | +102.5%       | Sell 50% of remaining |
    | 5     | V x 2.20      | +120%         | Sell remaining |
    
    Example:
        V = R$ 96.84
        Initial position: 1,000 shares
        
        Level 1: Price = R$ 145.26 → Sell 500 shares
        Level 2: Price = R$ 171.31 → Sell 250 shares
    
    Returns: list of dicts with level configuration
    """
    return [
        {'level': 1, 'profit': 0.50, 'price_mult': 1.50, 'sell_pct': 0.50},
        {'level': 2, 'profit': 0.675, 'price_mult': 1.675, 'sell_pct': 0.50},
        {'level': 3, 'profit': 0.85, 'price_mult': 1.85, 'sell_pct': 0.50},
        {'level': 4, 'profit': 1.025, 'price_mult': 2.025, 'sell_pct': 0.50},
        {'level': 5, 'profit': 1.20, 'price_mult': 2.20, 'sell_pct': 1.00},
    ]

#
#$ Portifolio Management
#
def calculateWPP(intrinsic_value, current_price, strategic_weight):
    """
    Calculate Weighted Purchase Price (WPP)
    
    WPP = (IV / Price) x SW
    
    Allocate capital based on how undervalued each stock is, weighted by Strategic Weight.
    
    Where:
    - IV = Intrinsic Value
    - Price = Current Market Price
    - SW = Strategic Weight (1-100)
    
    Example:
        Stock A: IV = 100, Price = 40, SW = 90
        Discount Factor = 100/40 = 2.5x
        WPP_A = 2.5 x 90 = 225
        
        Stock B: IV = 50, Price = 20, SW = 50
        Discount Factor = 50/20 = 2.5x
        WPP_B = 2.5 x 50 = 125
    """
    if current_price <= 0:
        return 0
    
    discount_factor = intrinsic_value / current_price
    return round(discount_factor * strategic_weight, 2)

def allocateCapitalByWPP(wpp_dict, total_capital):
    """
    Proportional Capital Distribution (PCD)
    
    Determine what % of total capital each stock gets:
    
    PCD_i = (WPP_i / Σ WPP) x 100%
    Capital_Allocated_i = PCD_i x Total_Capital
    
    Example (R$ 10,000 total):
        Stock A WPP = 225: PCD = 55.56%, Capital = R$ 5,556
        Stock B WPP = 125: PCD = 44.44%, Capital = R$ 4,444
    
    Returns: dict with ticker -> allocated capital
    """
    total_wpp = sum(wpp_dict.values())
    if total_wpp == 0:
        return {ticker: 0 for ticker in wpp_dict.keys()}
    
    allocation = {}
    for ticker, wpp in wpp_dict.items():
        pcd = (wpp / total_wpp) * 100
        allocation[ticker] = (pcd / 100) * total_capital
    
    return allocation