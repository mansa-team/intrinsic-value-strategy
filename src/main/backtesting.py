import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from economics import *
from imports import *

# Constants
MIN_CASH_FOR_BUY = 10  # Minimum shares worth of cash needed to trigger buy
PROGRESS_BAR_WIDTH = 40
MIN_SHARES = 1

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

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=3))
def getPriceData(ticker):
    df = yf.Ticker(f'{ticker}.SA').history(period='max').reset_index()
    df['Date'] = pd.to_datetime(df['Date'].dt.strftime('%Y-%m-%d'))
    return df

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=3))
def getLPAData(ticker):
    driver = setupSelenium()
    driver.get(f'https://statusinvest.com.br/acoes/{ticker}')
    
    script = f"""
    var callback = arguments[arguments.length - 1];
    fetch('/acao/indicatorhistoricallist', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'X-Requested-With': 'XMLHttpRequest'}},
        body: 'codes%5B%5D={ticker.lower()}&time=5&byQuarter=false&futureData=false'
    }})
    .then(r => r.json())
    .then(data => callback(data))
    .catch(e => callback(null));
    """
    
    try:
        data = driver.execute_async_script(script)
        if data and ticker.lower() in data.get('data', {}):
            lpaData = next((ind.get('ranks', []) for ind in data['data'][ticker.lower()] if ind.get('key') == 'lpa'), [])
            df = pd.json_normalize(lpaData)
            if not df.empty:
                return df[['rank', 'value']].rename(columns={'rank': 'year'})
    except:
        pass
    finally:
        driver.quit()
    
    return pd.DataFrame()

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=3))
def getProfitData(ticker):
    try:
        response = requests.get(f'http://{Config.STOCKS_API["HOST"]}:{Config.STOCKS_API["PORT"]}/api/historical?search={ticker}&fields=LUCRO%20LIQUIDO')
        if response.status_code != 200:
            return pd.DataFrame()
        
        data = response.json()['data'][0]
        rows = []
        for key, value in data.items():
            if key.startswith('LUCRO LIQUIDO') and value:
                try:
                    year = int(key.split()[-1])
                    rows.append({'TICKER': data['TICKER'], 'ANO': year, 'LUCRO LIQUIDO': value})
                except (ValueError, IndexError):
                    continue
        
        return pd.DataFrame(rows).sort_values('ANO') if rows else pd.DataFrame()
    except:
        return pd.DataFrame()

class Backtester:
    def __init__(
        self,
        config: Dict,
        portfolio: pd.DataFrame,
        priceData: Dict[str, pd.DataFrame],
        lpaData: Dict[str, pd.DataFrame],
        profitData: Dict[str, pd.DataFrame],
        useStrategy: bool = True
    ):
        """
        Initialize Backtester instance
        
        Args:
            config: Configuration dict with keys:
                   - 'SAFETY_MARGIN': float (e.g., 0.50)
                   - 'INITIAL_CAPITAL': float (e.g., 10000)
                   - 'START_DATE': str (e.g., '2016-01-01')
                   - 'END_DATE': str (e.g., '2024-12-31')
            portfolio: DataFrame with columns ['TICKER', 'WEIGHT']
            priceData: Dict mapping ticker -> price DataFrame
            lpaData: Dict mapping ticker -> LPA DataFrame
            profitData: Dict mapping ticker -> profit DataFrame
            useStrategy: If True, apply Graham's strategy; else Buy & Hold
        """
        self.config = config
        self.portfolio = portfolio
        self.useStrategy = useStrategy
        self.priceData = priceData
        self.lpaData = lpaData
        self.profitData = profitData
        
        self.cash = config['INITIAL_CAPITAL']
        self.positions: Dict[str, int] = {}
        self.trades: List[Dict] = []
        self.equityLog: List[Dict] = []
        self.dividendsLog: List[Dict] = []
        self.ivCache: Dict[str, Dict[str, Optional[float]]] = {}
        
        self._setupPortfolio()
    
    def _setupPortfolio(self) -> None:
        """Perform initial equal weight allocation across portfolio"""
        totalWeight = self.portfolio['WEIGHT'].sum()
        print("\n" + "="*70)
        print("PORTFOLIO SETUP".center(70))
        print("="*70)
        
        for _, row in self.portfolio.iterrows():
            ticker = row['TICKER']
            allocation = self.config['INITIAL_CAPITAL'] * (row['WEIGHT'] / totalWeight)
            priceDf = self.priceData[ticker]
            startPrice = priceDf[priceDf['Date'] >= self.config['START_DATE']]['Close'].iloc[0]
            shares = int(allocation / startPrice)
            
            if shares > MIN_SHARES:
                cost = shares * startPrice
                self.positions[ticker] = shares
                self.cash -= cost
                print(f'{ticker:6} | W:{row["WEIGHT"]:3} | {shares:5} shares @ R${startPrice:8.2f} = R${cost:10.2f}')
        
        print(f'\nInitial cash: R${self.cash:.2f}\n')
    
    def _getIV(self, ticker: str, date: pd.Timestamp) -> Optional[float]:
        """
        Get cached IV or calculate it
        
        Cache by date to account for interest rate changes
        
        Args:
            ticker: Stock ticker
            date: Target date
        
        Returns:
            Intrinsic value or None if calculation fails
        """
        dateStr = date.strftime('%Y-%m-%d')
        
        if ticker not in self.ivCache:
            self.ivCache[ticker] = {}
        
        if dateStr not in self.ivCache[ticker]:
            try:
                iv = calculateIntrinsicValue(ticker, date, self.profitData, self.lpaData)
                self.ivCache[ticker][dateStr] = iv
            except Exception:
                self.ivCache[ticker][dateStr] = None
        
        return self.ivCache[ticker][dateStr]
    
    def _processDividends(self, ticker: str, date: pd.Timestamp, priceRow: pd.Series) -> None:
        """
        Process dividend payment and reinvest immediately
        
        Args:
            ticker: Stock ticker
            date: Dividend date
            priceRow: Price data row for this date
        """
        dividend = priceRow.get('Dividends', 0)
        if dividend <= 0 or ticker not in self.positions:
            return
        
        dividendAmount = self.positions[ticker] * dividend
        currentPrice = priceRow['Close']
        sharesToBuy = int(dividendAmount / currentPrice)
        
        if sharesToBuy > 0:
            cost = sharesToBuy * currentPrice
            if self.cash >= cost:
                self.positions[ticker] += sharesToBuy
                self.cash -= cost
                
                self.trades.append({
                    'Date': date,
                    'Ticker': ticker,
                    'Action': 'DIVIDEND_REINVEST',
                    'Shares': sharesToBuy,
                    'Price': round(currentPrice, 2),
                    'Amount': round(cost, 2),
                })
        
        self.dividendsLog.append({
            'Date': date,
            'Ticker': ticker,
            'Shares_Held': self.positions[ticker],
            'Dividend_Per_Share': round(dividend, 4),
            'Total_Dividend': round(dividendAmount, 2)
        })
    
    def _executeSell(
        self,
        ticker: str,
        date: pd.Timestamp,
        currentPrice: float,
        iv: float
    ) -> None:
        """
        Execute sell signal with partial sell levels
        
        Args:
            ticker: Stock to sell
            date: Transaction date
            currentPrice: Current market price
            iv: Intrinsic value
        """
        if ticker not in self.positions or self.positions[ticker] <= 0:
            return
        
        # Get dynamic sell levels based on this stock's IV
        sellLevels = calculatePartialSellLevels(iv, self.config['SAFETY_MARGIN'])
        
        for level in sellLevels:
            if currentPrice >= level['trigger_price']:
                shares = int(self.positions[ticker] * level['sell_pct'])
                
                if shares > 0:
                    proceeds = shares * currentPrice
                    self.cash += proceeds
                    self.positions[ticker] -= shares
                    
                    if self.positions[ticker] <= 0:
                        del self.positions[ticker]
                    
                    self.trades.append({
                        'Date': date,
                        'Ticker': ticker,
                        'Action': 'SELL',
                        'Shares': shares,
                        'Price': round(currentPrice, 2),
                        'IV': round(iv, 2),
                        'Profit_Margin': level['profit_margin'],
                        'Level': level['level']
                    })
                break
    
    def _executeBuys(
        self,
        buySignals: Dict[str, Dict],
        date: pd.Timestamp
    ) -> None:
        """
        Execute buy signals using WPP allocation
        
        Args:
            buySignals: Dict of {ticker: signal_data}
            date: Transaction date
        """
        if not buySignals or self.cash <= 0:
            return
        
        allocations = allocateCapitalByWPP(buySignals, self.cash)
        
        for ticker, allocationAmount in allocations.items():
            if allocationAmount <= 0:
                continue
            
            signal = buySignals[ticker]
            currentPrice = signal['price']
            shares = int(allocationAmount / currentPrice)
            
            if shares > 0:
                cost = shares * currentPrice
                if self.cash >= cost:
                    self.positions[ticker] = self.positions.get(ticker, 0) + shares
                    self.cash -= cost
                    
                    self.trades.append({
                        'Date': date,
                        'Ticker': ticker,
                        'Action': 'BUY',
                        'Shares': shares,
                        'Price': round(currentPrice, 2),
                        'IV': round(signal['iv'], 2),
                        'WPP': round(signal['wpp'], 4),
                        'Discount': round(signal['iv'] / currentPrice, 4),
                        'Allocation': round(allocationAmount, 2)
                    })
    
    def _printProgress(self, dayIdx: int, totalDays: int, equity: float) -> None:
        """Print progress bar with current equity"""
        progress = (dayIdx + 1) / totalDays * 100
        filled = int(PROGRESS_BAR_WIDTH * (dayIdx + 1) / totalDays)
        bar = '█' * filled + '░' * (PROGRESS_BAR_WIDTH - filled)
        print(
            f'\r[{bar}] {progress:.0f}% | R${equity:10.2f} | Cash: R${self.cash:8.2f}',
            end='', flush=True
        )
    
    def _calculatePortfolioValue(self, row: pd.Series) -> float:
        """Calculate current portfolio market value"""
        return sum(
            self.positions.get(t, 0) * row.get(t, 0)
            for t in self.portfolio['TICKER']
            if not pd.isna(row.get(t))
        )
    
    def _evaluateTradingSignals(self, row: pd.Series, date: pd.Timestamp) -> Dict[str, Dict]:
        """
        Evaluate buy/sell signals for all portfolio tickers
        
        Returns dict of buy signals for execution
        """
        buySignals = {}
        
        for _, pRow in self.portfolio.iterrows():
            ticker = pRow['TICKER']
            if pd.isna(row.get(ticker)):
                continue
            
            currentPrice = row[ticker]
            iv = self._getIV(ticker, date)
            
            if iv is None or iv <= 0:
                continue
            
            buyPrice = calculateBuyPrice(iv, self.config['SAFETY_MARGIN'])
            sellPrice = calculateSellPrice(iv, self.config['SAFETY_MARGIN'])
            
            if not buyPrice or not sellPrice:
                continue
            
            # SELL signal
            if currentPrice >= sellPrice:
                self._executeSell(ticker, date, currentPrice, iv)
            
            # BUY signal
            elif currentPrice <= buyPrice and self.cash > currentPrice * MIN_CASH_FOR_BUY:
                wpp = calculateWPP(iv, currentPrice, pRow['WEIGHT'])
                
                if wpp > 0:
                    buySignals[ticker] = {
                        'iv': iv,
                        'price': currentPrice,
                        'wpp': wpp,
                        'buy_price': buyPrice,
                    }
        
        return buySignals
    
    def backtest(self) -> None:
        """Execute backtest over entire date range"""
        # Merge price data
        merged = None
        for _, row in self.portfolio.iterrows():
            ticker = row['TICKER']
            df = self.priceData[ticker][['Date', 'Close', 'Dividends']].copy()
            df.columns = ['Date', ticker, f'{ticker}_Div']
            merged = df if merged is None else merged.merge(df, on='Date', how='outer')
        
        merged = merged.sort_values('Date').reset_index(drop=True)
        startDate = pd.to_datetime(self.config['START_DATE'])
        endDate = pd.to_datetime(self.config['END_DATE'])
        merged = merged[(merged['Date'] >= startDate) & (merged['Date'] <= endDate)]
        
        strategyName = "GRAHAM'S STRATEGY" if self.useStrategy else "BUY & HOLD"
        print("\n" + "="*70)
        print(f"BACKTEST: {strategyName}".center(70))
        print(f"Period: {startDate.date()} to {endDate.date()}".center(70))
        print("="*70 + "\n")
        
        for dayIdx, (_, row) in enumerate(merged.iterrows()):
            date = row['Date']
            
            portfolioValue = self._calculatePortfolioValue(row)
            equity = self.cash + portfolioValue
            self._printProgress(dayIdx, len(merged), equity)
            
            # Process dividends
            for _, pRow in self.portfolio.iterrows():
                ticker = pRow['TICKER']
                if not pd.isna(row.get(ticker)):
                    priceRow = self.priceData[ticker][self.priceData[ticker]['Date'] == date]
                    if len(priceRow) > 0:
                        self._processDividends(ticker, date, priceRow.iloc[0])
            
            # Apply Graham's Strategy
            if self.useStrategy:
                buySignals = self._evaluateTradingSignals(row, date)
                if buySignals:
                    self._executeBuys(buySignals, date)
            
            # Log daily equity
            portfolioValue = self._calculatePortfolioValue(row)
            self.equityLog.append({
                'Date': date,
                'Cash': round(self.cash, 2),
                'Portfolio_Value': round(portfolioValue, 2),
                'Total_Equity': round(self.cash + portfolioValue, 2)
            })
        
        print("\n" + "="*70 + "\n")
    
    def getResults(self) -> Optional[Dict]:
        """
        Compile backtest results
        
        Returns:
            Dict with keys: equity_curve, trades, dividends, final_equity,
                          total_return, total_dividends, num_trades
        """
        equityDf = pd.DataFrame(self.equityLog)
        tradesDf = pd.DataFrame(self.trades) if self.trades else pd.DataFrame()
        dividendsDf = pd.DataFrame(self.dividendsLog) if self.dividendsLog else pd.DataFrame()
        
        if equityDf.empty:
            return None
        
        finalEquity = equityDf['Total_Equity'].iloc[-1]
        totalReturn = ((finalEquity - self.config['INITIAL_CAPITAL']) / self.config['INITIAL_CAPITAL']) * 100
        totalDividends = dividendsDf['Total_Dividend'].sum() if not dividendsDf.empty else 0
        
        return {
            'equity_curve': equityDf,
            'trades': tradesDf,
            'dividends': dividendsDf,
            'final_equity': finalEquity,
            'total_return': totalReturn,
            'total_dividends': totalDividends,
            'num_trades': len(tradesDf),
        }