import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from imports import *
from economics import *

#
#$ Portifolio Allocation
#
Portfolio = [
    {'TICKER': 'ITUB3', 'WEIGHT': 90},
    {'TICKER': 'PETR3', 'WEIGHT': 88},
    {'TICKER': 'WEGE3', 'WEIGHT': 87},
    {'TICKER': 'BBAS3', 'WEIGHT': 85},
    {'TICKER': 'TOTS3', 'WEIGHT': 85},
    {'TICKER': 'EGIE3', 'WEIGHT': 80},
    {'TICKER': 'EQTL3', 'WEIGHT': 80},
    {'TICKER': 'FRAS3', 'WEIGHT': 77},
    {'TICKER': 'PSSA3', 'WEIGHT': 76},
    {'TICKER': 'RADL3', 'WEIGHT': 75},
    {'TICKER': 'LEVE3', 'WEIGHT': 70},
    {'TICKER': 'LREN3', 'WEIGHT': 65},
]

#$ Selenium
def setupSelenium():
    options = webdriver.ChromeOptions()

    options.add_argument('user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.8191.896 Safari/537.36')
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-images')
    options.add_argument('--blink-settings=imagesEnabled=false')

    driver = webdriver.Chrome(
        options=options,
        service=Service(log_output=os.devnull),
    )
    driver.implicitly_wait(3)
    return driver

#
#$ Data Loading
#
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=3))
def getPriceData(TICKER):
    stock = yf.Ticker(f'{TICKER}.SA')
    df=stock.history(period='max')
    df = df.reset_index()
    df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
    df['Date'] = pd.to_datetime(df['Date'])

    return df

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=3))
def getLPAdata(TICKER):
    """Backtesting LPA Data"""

    driver = setupSelenium()
    driver.get(f'https://statusinvest.com.br/acoes/{TICKER}')
    
    script = f"""
    var callback = arguments[arguments.length - 1];
    fetch('/acao/indicatorhistoricallist', {{
        method: 'POST',
        headers: {{
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest'
        }},
        body: 'codes%5B%5D={TICKER.lower()}&time=5&byQuarter=false&futureData=false'
    }})
    .then(response => response.json())
    .then(data => callback(data))
    .catch(error => callback(null));
    """

    histDataJSON = driver.execute_async_script(script)
    
    tickerData = histDataJSON['data'].get(TICKER.lower(), [])

    lpa_ranks = []
    for indicator in tickerData:
        if indicator.get('key') == 'lpa':
            lpa_ranks = indicator.get('ranks', [])

    lpa_df = pd.json_normalize(lpa_ranks)
    lpa_df = lpa_df.drop(columns=[
        'rankN',
        'rank_F',
        'timeType',
        'value_F',
    ])
    lpa_df = lpa_df.rename(columns={
        'rank': 'year',
    })

    driver.quit()
    return lpa_df

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=3))
def getProfitData(TICKER):
    """Get historical LUCRO LIQUIDO data for CAGR calculations"""
    try:
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
                    lucro = value
                    rows.append({'TICKER': ticker, 'NOME': nome, 'ANO': ano, 'LUCRO LIQUIDO': lucro})

            df = pd.DataFrame(rows)
            df = df.sort_values('ANO').reset_index(drop=True)
            return df
    except:
        pass
    
    return pd.DataFrame(columns=['TICKER', 'NOME', 'ANO', 'LUCRO LIQUIDO'])

def calculateIntrinsicValue_backtesting(TICKER, date, profitData, lpaData):
    """
    V = (LPA x (8.5 + 2x) x z) / y
    
    Where:
    - x = 10-year Liquid Profit CAGR (%)
    - y = Current SELIC Rate (%)
    - z = Average SELIC Rate over 10 years (%)
    - LPA = Earnings Per Share (R$)
    """
    try:
        # 1. Check profit data
        if TICKER not in profitData:
            print(f"    [ERROR] {TICKER} not in profitData")
            return None
        
        df = profitData[TICKER]
        
        if df is None or len(df) == 0:
            print(f"    [ERROR] {TICKER} profitData is empty")
            return None
        
        # 2. Filter for 10 years of data
        df_10y = df[df['ANO'] <= date.year - 1].tail(10)
        
        if len(df_10y) < 10:
            print(f"    [ERROR] {TICKER} only has {len(df_10y)} years of data (need 10)")
            return None
        
        # 3. Check for valid profit data
        if df_10y['LUCRO LIQUIDO'].isnull().any():
            print(f"    [ERROR] {TICKER} has null LUCRO LIQUIDO values")
            return None
        
        if (df_10y['LUCRO LIQUIDO'] <= 0).any():
            print(f"    [ERROR] {TICKER} has negative/zero LUCRO LIQUIDO values")
            return None
        
        # 4. Calculate CAGR
        lucro_inicial = df_10y.iloc[0]['LUCRO LIQUIDO']
        lucro_final = df_10y.iloc[-1]['LUCRO LIQUIDO']
        n = len(df_10y) - 1
        
        x = ((lucro_final / lucro_inicial) ** (1 / n) - 1) * 100
        
        print(f"    [CAGR] {TICKER}: {x:.2f}% (from {lucro_inicial} to {lucro_final})")
        
        # 5. Get interest rates
        y, z = getInterestRates(date)
        
        if y is None or z is None:
            print(f"    [ERROR] {TICKER} interest rates failed (y={y}, z={z})")
            return None
        
        print(f"    [SELIC] y={y*100:.2f}%, z={z*100:.2f}%")
        
        # 6. Get LPA
        if TICKER not in lpaData:
            print(f"    [ERROR] {TICKER} not in lpaData")
            return None
        
        lpa_df = lpaData[TICKER]
        
        if lpa_df is None or len(lpa_df) == 0:
            print(f"    [ERROR] {TICKER} lpaData is empty")
            return None
        
        lpa_values = lpa_df[lpa_df['year'] == date.year]['value']
        
        if len(lpa_values) == 0:
            print(f"    [ERROR] {TICKER} no LPA data for year {date.year}")
            print(f"           Available years: {lpa_df['year'].unique().tolist()}")
            return None
        
        lpa = lpa_values.values[0]
        
        if lpa is None or lpa <= 0:
            print(f"    [ERROR] {TICKER} invalid LPA: {lpa}")
            return None
        
        print(f"    [LPA] {TICKER}: {lpa}")
        
        # 7. Calculate intrinsic value
        intrinsicValue = lpa * (8.5 + 2*x) * z / y
        
        print(f"    [RESULT] {TICKER}: IV = {lpa} * (8.5 + 2*{x:.2f}) * {z*100:.2f}% / {y*100:.2f}% = {intrinsicValue:.2f}")
        
        return round(intrinsicValue, 2)
    except Exception as e:
        import traceback
        print(f"    [EXCEPTION] {TICKER}: {str(e)}")
        print(f"    {traceback.format_exc()}")
        return None

#
#$ Backtester
#
class Backtester:
    def __init__(self, config, portfolio, priceData, lpaData, profitData):
        self.config = config
        self.portfolio = portfolio
    
        self.priceData = priceData
        self.lpaData = lpaData
        self.profitData = profitData

        self.cash = config['INITIAL_CAPITAL']
        self.positions = {}
        self.trades = []
        self.equity_log = []
        self.dividends_log = []
        self.stock_splits_log = []
        self.iv_cache = {}

        self.setupPortfolio()

    def get_iv_cached(self, ticker, date):
        """Get IV from cache, calculate per year to account for changing SELIC rates"""
        year = date.year
        
        if ticker not in self.iv_cache:
            self.iv_cache[ticker] = {}
        
        if year not in self.iv_cache[ticker]:
            try:
                iv = calculateIntrinsicValue_backtesting(ticker, date, self.profitData, self.lpaData)
                self.iv_cache[ticker][year] = iv
                
                # Debug output - ALWAYS print first calculation per year
                print(f"\n[IV CALC] {ticker} {date.year}: {iv}")
            except Exception as e:
                print(f"\n[ERROR] {ticker} caching failed: {str(e)}")
                self.iv_cache[ticker][year] = None
        
        return self.iv_cache[ticker][year]

    def setupPortfolio(self):
        """
        Allocate initial capital based on weights.
        
        Allocation = (Weight / Total Weights) x Initial Capital
        
        Example:
            Total Weight = 1,000
            WEGE3 Weight = 87
            WEGE3 Allocation = (87 / 1000) x R$10,000 = R$870
        """
        totalWeight = self.portfolio['WEIGHT'].sum()

        print("\n" + "="*60)
        print("Initial PORTFOLIO setup".center(60))
        print("="*60)
        for _, row in self.portfolio.iterrows():
            ticker = row['TICKER']
            weight = row['WEIGHT']

            allocationPct = weight / totalWeight
            allocationAmount = self.config['INITIAL_CAPITAL'] * allocationPct

            price = self.priceData[f'{ticker}']
            initialPrice = price[price['Date'] >= self.config['START_DATE']]['Close'].iloc[0]

            shares = int(allocationAmount / initialPrice)

            if shares > 0:
                cost = shares * initialPrice
                self.positions[ticker] = shares
                self.cash -= cost

            print(f'{ticker} {weight} | R${cost:.2f} in {shares} shares')
        print(f'\nRemaining Cash: R${self.cash:.2f}')

    def process_corporate_events(self, ticker, date, price_row):
        """Process dividends for the given date"""
        
        # Process DIVIDENDS only (stock splits already adjusted in Yahoo data)
        if price_row.get('Dividends', 0) > 0 and ticker in self.positions:
            dividend_per_share = price_row['Dividends']
            shares_held = self.positions[ticker]
            dividend_amount = shares_held * dividend_per_share
            
            self.cash += dividend_amount
            
            self.dividends_log.append({
                'Date': date,
                'Ticker': ticker,
                'Shares': shares_held,
                'Dividend_Per_Share': round(dividend_per_share, 4),
                'Total_Dividend': round(dividend_amount, 2)
            })

    def backtest(self):
        mergedDF = None
        
        for _, row in self.portfolio.iterrows():
            ticker = row['TICKER']
            df = self.priceData[ticker][['Date', 'Close', 'Dividends']].copy()
            df.columns = ['Date', ticker, f'{ticker}_Div']
            
            if mergedDF is None:
                mergedDF = df
            else:
                mergedDF = mergedDF.merge(df, on='Date', how='outer')
        
        mergedDF = mergedDF.sort_values('Date').reset_index(drop=True)
        startDate = pd.to_datetime(self.config['START_DATE'])
        endDate = pd.to_datetime(self.config['END_DATE'])
        mergedDF = mergedDF[(mergedDF['Date'] >= startDate) & (mergedDF['Date'] <= endDate)]
        
        print("\n" + "="*60)
        print("Running BACKTEST simulation".center(60))
        print("="*60)
        print(f"Period: {startDate.date()} to {endDate.date()}")
        print(f"Total Trading Days: {len(mergedDF)}\n")

        signal_count = {'BUY': 0, 'SELL': 0, 'HOLD': 0}

        # Each day
        for day_idx, (_, row) in enumerate(mergedDF.iterrows()):
            date = row['Date']
            buySignals = {}

            # Progress bar
            progress = (day_idx + 1) / len(mergedDF) * 100
            bar_length = 40
            filled = int(bar_length * (day_idx + 1) / len(mergedDF))
            bar = '█' * filled + '░' * (bar_length - filled)
            
            # Calculate current equity
            portfolio_value = sum(self.positions.get(t, 0) * row.get(t, 0) for t in self.portfolio['TICKER'] if not pd.isna(row.get(t)))
            current_equity = self.cash + portfolio_value
            
            print(f'\r[{bar}] {progress:.1f}% | Day {day_idx + 1}/{len(mergedDF)} | Equity: R${current_equity:.2f}', end='', flush=True)

            # Process corporate events FIRST (dividends only)
            for _, portfolio_row in self.portfolio.iterrows():
                ticker = portfolio_row['TICKER']
                
                if pd.isna(row[ticker]):
                    continue
                
                price_row = self.priceData[ticker][self.priceData[ticker]['Date'] == date]
                if len(price_row) > 0:
                    self.process_corporate_events(ticker, date, price_row.iloc[0])

            # Process trading signals
            for _, portfolio_row in self.portfolio.iterrows():
                ticker = portfolio_row['TICKER']
                strategicWeight = portfolio_row['WEIGHT']

                if pd.isna(row[ticker]):
                    continue

                currentPrice = row[ticker]

                # DEBUG: Check IV on first day
                if day_idx == 0:
                    print(f"\n[DEBUG DAY 0] {ticker}: Price={currentPrice:.2f}")

                try:
                    # Use cached IV calculation
                    IV = self.get_iv_cached(ticker, date)

                    if IV is None:
                        if day_idx == 0:
                            print(f"  -> IV is None")
                        signal_count['HOLD'] += 1
                        continue
                    
                    if IV <= 0:
                        if day_idx == 0:
                            print(f"  -> IV <= 0: {IV}")
                        signal_count['HOLD'] += 1
                        continue
                    
                    if day_idx == 0:
                        print(f"  -> IV={IV:.2f}")
                    
                    buyPrice = calculateBuyPrice(IV, self.config['SAFETY_MARGIN'])
                    sellPrice = calculateSellPrice(IV, self.config['SAFETY_MARGIN'])

                    if buyPrice is None or sellPrice is None or buyPrice <= 0 or sellPrice <= 0:
                        if day_idx == 0:
                            print(f"  -> Invalid prices: buy={buyPrice}, sell={sellPrice}")
                        signal_count['HOLD'] += 1
                        continue
                    
                    if day_idx == 0:
                        print(f"  -> BuyPrice={buyPrice:.2f}, SellPrice={sellPrice:.2f}")
                        
                except Exception as e:
                    if day_idx == 0:
                        print(f"  -> Exception: {str(e)}")
                    signal_count['HOLD'] += 1
                    continue
                
                # Generate signal
                try:
                    signal = generateTradingSignal(currentPrice, IV, self.config['SAFETY_MARGIN'])
                    if day_idx == 0:
                        print(f"  -> Signal={signal}")
                except Exception as e:
                    print(f"\n[SIGNAL ERROR] {ticker} on {date.date()}: {str(e)}")
                    signal = None
                
                if signal is None:
                    signal_count['HOLD'] += 1
                    continue
                
                signal_count[signal] = signal_count.get(signal, 0) + 1

                # SELL signal
                if signal == 'SELL' and ticker in self.positions and self.positions[ticker] > 0:
                    shares = self.positions[ticker]
                    profitMargin = (IV / currentPrice) if currentPrice > 0 else 0

                    try:
                        sellLevels = calculatePartialSellLevels()
                    except Exception as e:
                        print(f"\n[SELL LEVELS ERROR] {ticker}: {str(e)}")
                        sellLevels = []

                    sharesToSell = shares
                    levelExecuted = None
                    
                    for level in sellLevels:
                        triggerMargin = level['price_mult']
                        
                        if profitMargin >= triggerMargin:
                            sharesToSell = int(shares * level['sell_pct'])
                            levelExecuted = level['level']
                            
                            if sharesToSell > 0:
                                proceeds = sharesToSell * currentPrice
                                self.cash += proceeds
                                self.positions[ticker] -= sharesToSell
                                
                                if self.positions[ticker] <= 0:
                                    del self.positions[ticker]
                                
                                self.trades.append({
                                    'Date': date,
                                    'Ticker': ticker,
                                    'Action': 'SELL',
                                    'Shares': sharesToSell,
                                    'Price': currentPrice,
                                    'IV': IV,
                                    'Sell_Price': sellPrice,
                                    'Profit_Margin': round(profitMargin, 4),
                                    'Sell_Level': levelExecuted
                                })
                                
                                print(f"\n[TRADE] SELL {ticker}: {sharesToSell} @ R${currentPrice:.2f}")
                            break
                    
                    if ticker in self.positions and self.positions[ticker] > 0:
                        shares = self.positions[ticker]
                        proceeds = shares * currentPrice
                        self.cash += proceeds
                        
                        self.trades.append({
                            'Date': date,
                            'Ticker': ticker,
                            'Action': 'SELL',
                            'Shares': shares,
                            'Price': currentPrice,
                            'IV': IV,
                            'Sell_Price': sellPrice,
                            'Profit_Margin': round(profitMargin, 4),
                            'Sell_Level': 'FULL_EXIT'
                        })
                        
                        print(f"\n[TRADE] SELL {ticker} (FULL): {shares} @ R${currentPrice:.2f}")
                        
                        del self.positions[ticker]

                elif signal == 'BUY':
                    try:
                        wpp = calculateWPP(IV, currentPrice, strategicWeight)
                    except Exception as e:
                        print(f"\n[WPP ERROR] {ticker}: {str(e)}")
                        wpp = 0
                    
                    if wpp is not None and wpp > 0:
                        buySignals[ticker] = {
                            'IV': IV,
                            'Price': currentPrice,
                            'WPP': wpp,
                            'Weight': strategicWeight,
                            'BuyPrice': buyPrice
                        }
                        
                        print(f"\n[TRADE] BUY signal for {ticker} (WPP={wpp:.4f})")
            
            # Execute BUY signals
            if len(buySignals) > 0 and self.cash > 0:
                print(f"\n[BUY] Executing {len(buySignals)} buy signals with R${self.cash:.2f} cash")
                try:
                    allocations = allocateCapitalByWPP(buySignals, self.cash)
                except Exception as e:
                    print(f"\n[ALLOCATION ERROR]: {str(e)}")
                    allocations = {}
                
                for ticker, allocationAmount in allocations.items():
                    if allocationAmount <= 0:
                        continue
                    
                    currentPrice = buySignals[ticker]['Price']
                    IV = buySignals[ticker]['IV']
                    buyPrice = buySignals[ticker]['BuyPrice']
                    
                    shares = int(allocationAmount / currentPrice)
                    
                    if shares > 0:
                        cost = shares * currentPrice
                        self.positions[ticker] = self.positions.get(ticker, 0) + shares
                        self.cash -= cost
                        
                        discountMargin = (IV / currentPrice) if currentPrice > 0 else 0
                        
                        self.trades.append({
                            'Date': date,
                            'Ticker': ticker,
                            'Action': 'BUY',
                            'Shares': shares,
                            'Price': currentPrice,
                            'IV': IV,
                            'Buy_Price': buyPrice,
                            'WPP': buySignals[ticker]['WPP'],
                            'Discount_Margin': round(discountMargin, 4),
                            'Allocation': round(allocationAmount, 2)
                        })
                        
                        print(f"\n[TRADE] BUY {ticker}: {shares} @ R${currentPrice:.2f}")

            # Log equity at end of day
            portfolio_value = 0
            for _, portfolio_row in self.portfolio.iterrows():
                ticker = portfolio_row['TICKER']
                if ticker in self.positions and not pd.isna(row[ticker]):
                    portfolio_value += self.positions[ticker] * row[ticker]
            
            total_equity = self.cash + portfolio_value
            self.equity_log.append({
                'Date': date,
                'Cash': self.cash,
                'Portfolio_Value': portfolio_value,
                'Total_Equity': total_equity
            })

        print("\n" + "="*60)
        print(f"Signal Summary: BUY={signal_count['BUY']}, SELL={signal_count['SELL']}, HOLD={signal_count['HOLD']}")
        print("="*60 + "\n")

    def get_results(self):
        """Return backtest results"""
        equity_df = pd.DataFrame(self.equity_log)
        trades_df = pd.DataFrame(self.trades) if len(self.trades) > 0 else pd.DataFrame()
        dividends_df = pd.DataFrame(self.dividends_log) if len(self.dividends_log) > 0 else pd.DataFrame()
        
        if len(equity_df) == 0:
            print("No backtest data available")
            return None
        
        final_equity = equity_df['Total_Equity'].iloc[-1]
        total_return = ((final_equity - self.config['INITIAL_CAPITAL']) / self.config['INITIAL_CAPITAL']) * 100
        total_dividends = dividends_df['Total_Dividend'].sum() if len(dividends_df) > 0 else 0
        
        return {
            'equity_curve': equity_df,
            'trades': trades_df,
            'dividends': dividends_df,
            'final_equity': final_equity,
            'total_return': total_return,
            'total_dividends': total_dividends,
            'num_trades': len(trades_df),
        }

if __name__ == "__main__":
    BACKTEST_CONFIG = {
        'SAFETY_MARGIN': 0.50,
        'MIN_CAGR': 0.05,
        'PROFIT_MARGIN_SPIKE': 0.175,
        'SELL_PERCENTAGE': 0.50,
        'INITIAL_CAPITAL': 10000,
        'START_DATE': '2016-01-01',
        'END_DATE': '2024-12-31',
    }
    
    portfolio = pd.DataFrame(Portfolio)
    priceData = {}
    lpaData = {}
    profitData = {}

    print("\n" + "="*60)
    print("Loading FUNDAMENTALIST data".center(60))
    print("="*60)

    for TICKER in portfolio['TICKER'].tolist():
        print(f"Loading {TICKER}")
        priceData[f'{TICKER}'] = getPriceData(f'{TICKER}')
        lpaData[f'{TICKER}'] = getLPAdata(f'{TICKER}')
        profitData[f'{TICKER}'] = getProfitData(f'{TICKER}')

    print("="*60 + "\n")

    bt = Backtester(
        config=BACKTEST_CONFIG,
        portfolio=portfolio,
        priceData=priceData,
        lpaData=lpaData,
        profitData=profitData
    )
    
    bt.backtest()
    results = bt.get_results()
    
    if results:
        print("\n" + "="*60)
        print("BACKTEST RESULTS".center(60))
        print("="*60)
        print(f"Final Equity: R$ {results['final_equity']:.2f}")
        print(f"Total Return: {results['total_return']:.2f}%")
        print(f"Total Dividends: R$ {results['total_dividends']:.2f}")
        print(f"Number of Trades: {results['num_trades']}")
        print("="*60)

        # Export results to CSV
        from datetime import datetime
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        results['equity_curve'].to_csv(f'equity_curve_{timestamp}.csv', index=False)
        print(f"\n✓ Equity curve exported to: equity_curve_{timestamp}.csv")
        
        if len(results['trades']) > 0:
            results['trades'].to_csv(f'trades_{timestamp}.csv', index=False)
            print(f"✓ Trades exported to: trades_{timestamp}.csv")
        
        if len(results['dividends']) > 0:
            results['dividends'].to_csv(f'dividends_{timestamp}.csv', index=False)
            print(f"✓ Dividends exported to: dividends_{timestamp}.csv")