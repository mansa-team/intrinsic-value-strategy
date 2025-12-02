import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from economics import *
from imports import *

from typing import Dict, Optional, List

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
            lpa_data = next((ind.get('ranks', []) for ind in data['data'][ticker.lower()] if ind.get('key') == 'lpa'), [])
            df = pd.json_normalize(lpa_data)
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
        price_data: Dict[str, pd.DataFrame],
        lpa_data: Dict[str, pd.DataFrame],
        profit_data: Dict[str, pd.DataFrame],
        use_strategy: bool = True
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
            price_data: Dict mapping ticker -> price DataFrame
            lpa_data: Dict mapping ticker -> LPA DataFrame
            profit_data: Dict mapping ticker -> profit DataFrame
            use_strategy: If True, apply Graham's strategy; else Buy & Hold
        """
        self.config = config
        self.portfolio = portfolio
        self.use_strategy = use_strategy
        self.price_data = price_data
        self.lpa_data = lpa_data
        self.profit_data = profit_data
        
        self.cash = config['INITIAL_CAPITAL']
        self.positions: Dict[str, int] = {}
        self.trades: List[Dict] = []
        self.equity_log: List[Dict] = []
        self.dividends_log: List[Dict] = []
        self.iv_cache: Dict[str, Dict[str, Optional[float]]] = {}
        
        self._setup_portfolio()
    
    def _setup_portfolio(self) -> None:
        """Perform initial equal weight allocation across portfolio"""
        total_weight = self.portfolio['WEIGHT'].sum()
        print("\n" + "="*70)
        print("PORTFOLIO SETUP".center(70))
        print("="*70)
        
        for _, row in self.portfolio.iterrows():
            ticker = row['TICKER']
            allocation = self.config['INITIAL_CAPITAL'] * (row['WEIGHT'] / total_weight)
            price_df = self.price_data[ticker]
            start_price = price_df[price_df['Date'] >= self.config['START_DATE']]['Close'].iloc[0]
            shares = int(allocation / start_price)
            
            if shares > MIN_SHARES:
                cost = shares * start_price
                self.positions[ticker] = shares
                self.cash -= cost
                print(f'{ticker:6} | W:{row["WEIGHT"]:3} | {shares:5} shares @ R${start_price:8.2f} = R${cost:10.2f}')
        
        print(f'\nInitial cash: R${self.cash:.2f}\n')
    
    def _get_iv(self, ticker: str, date: pd.Timestamp) -> Optional[float]:
        """
        Get cached IV or calculate it
        
        Cache by date to account for interest rate changes
        
        Args:
            ticker: Stock ticker
            date: Target date
        
        Returns:
            Intrinsic value or None if calculation fails
        """
        date_str = date.strftime('%Y-%m-%d')
        
        if ticker not in self.iv_cache:
            self.iv_cache[ticker] = {}
        
        if date_str not in self.iv_cache[ticker]:
            try:
                iv = calculateIntrinsicValue(ticker, date, self.profit_data, self.lpa_data)
                self.iv_cache[ticker][date_str] = iv
            except Exception:
                self.iv_cache[ticker][date_str] = None
        
        return self.iv_cache[ticker][date_str]
    
    def _process_dividends(self, ticker: str, date: pd.Timestamp, price_row: pd.Series) -> None:
        """
        Process dividend payment and reinvest immediately
        
        Args:
            ticker: Stock ticker
            date: Dividend date
            price_row: Price data row for this date
        """
        dividend = price_row.get('Dividends', 0)
        if dividend <= 0 or ticker not in self.positions:
            return
        
        dividend_amount = self.positions[ticker] * dividend
        current_price = price_row['Close']
        shares_to_buy = int(dividend_amount / current_price)
        
        if shares_to_buy > 0:
            cost = shares_to_buy * current_price
            if self.cash >= cost:
                self.positions[ticker] += shares_to_buy
                self.cash -= cost
                
                self.trades.append({
                    'Date': date,
                    'Ticker': ticker,
                    'Action': 'DIVIDEND_REINVEST',
                    'Shares': shares_to_buy,
                    'Price': round(current_price, 2),
                    'Amount': round(cost, 2),
                })
        
        self.dividends_log.append({
            'Date': date,
            'Ticker': ticker,
            'Shares_Held': self.positions[ticker],
            'Dividend_Per_Share': round(dividend, 4),
            'Total_Dividend': round(dividend_amount, 2)
        })
    
    def _execute_sell(
        self,
        ticker: str,
        date: pd.Timestamp,
        current_price: float,
        iv: float
    ) -> None:
        """
        Execute sell signal with partial sell levels
        
        Args:
            ticker: Stock to sell
            date: Transaction date
            current_price: Current market price
            iv: Intrinsic value
        """
        if ticker not in self.positions or self.positions[ticker] <= 0:
            return
        
        # Get dynamic sell levels based on this stock's IV
        sell_levels = calculatePartialSellLevels(iv, self.config['SAFETY_MARGIN'])
        
        for level in sell_levels:
            if current_price >= level['trigger_price']:
                shares = int(self.positions[ticker] * level['sell_pct'])
                
                if shares > 0:
                    proceeds = shares * current_price
                    self.cash += proceeds
                    self.positions[ticker] -= shares
                    
                    if self.positions[ticker] <= 0:
                        del self.positions[ticker]
                    
                    self.trades.append({
                        'Date': date,
                        'Ticker': ticker,
                        'Action': 'SELL',
                        'Shares': shares,
                        'Price': round(current_price, 2),
                        'IV': round(iv, 2),
                        'Profit_Margin': level['profit_margin'],
                        'Level': level['level']
                    })
                break
    
    def _execute_buys(
        self,
        buy_signals: Dict[str, Dict],
        date: pd.Timestamp
    ) -> None:
        """
        Execute buy signals using WPP allocation
        
        Args:
            buy_signals: Dict of {ticker: signal_data}
            date: Transaction date
        """
        if not buy_signals or self.cash <= 0:
            return
        
        allocations = allocateCapitalByWPP(buy_signals, self.cash)
        
        for ticker, allocation_amount in allocations.items():
            if allocation_amount <= 0:
                continue
            
            signal = buy_signals[ticker]
            current_price = signal['price']
            shares = int(allocation_amount / current_price)
            
            if shares > 0:
                cost = shares * current_price
                if self.cash >= cost:
                    self.positions[ticker] = self.positions.get(ticker, 0) + shares
                    self.cash -= cost
                    
                    self.trades.append({
                        'Date': date,
                        'Ticker': ticker,
                        'Action': 'BUY',
                        'Shares': shares,
                        'Price': round(current_price, 2),
                        'IV': round(signal['iv'], 2),
                        'WPP': round(signal['wpp'], 4),
                        'Discount': round(signal['iv'] / current_price, 4),
                        'Allocation': round(allocation_amount, 2)
                    })
    
    def _print_progress(self, day_idx: int, total_days: int, equity: float) -> None:
        """Print progress bar with current equity"""
        progress = (day_idx + 1) / total_days * 100
        filled = int(PROGRESS_BAR_WIDTH * (day_idx + 1) / total_days)
        bar = '█' * filled + '░' * (PROGRESS_BAR_WIDTH - filled)
        print(
            f'\r[{bar}] {progress:.0f}% | R${equity:10.2f} | Cash: R${self.cash:8.2f}',
            end='', flush=True
        )
    
    def _calculate_portfolio_value(self, row: pd.Series) -> float:
        """Calculate current portfolio market value"""
        return sum(
            self.positions.get(t, 0) * row.get(t, 0)
            for t in self.portfolio['TICKER']
            if not pd.isna(row.get(t))
        )
    
    def _evaluate_trading_signals(self, row: pd.Series, date: pd.Timestamp) -> Dict[str, Dict]:
        """
        Evaluate buy/sell signals for all portfolio tickers
        
        Returns dict of buy signals for execution
        """
        buy_signals = {}
        
        for _, p_row in self.portfolio.iterrows():
            ticker = p_row['TICKER']
            if pd.isna(row.get(ticker)):
                continue
            
            current_price = row[ticker]
            iv = self._get_iv(ticker, date)
            
            if iv is None or iv <= 0:
                continue
            
            buy_price = calculateBuyPrice(iv, self.config['SAFETY_MARGIN'])
            sell_price = calculateSellPrice(iv, self.config['SAFETY_MARGIN'])
            
            if not buy_price or not sell_price:
                continue
            
            # SELL signal
            if current_price >= sell_price:
                self._execute_sell(ticker, date, current_price, iv)
            
            # BUY signal
            elif current_price <= buy_price and self.cash > current_price * MIN_CASH_FOR_BUY:
                wpp = calculateWPP(iv, current_price, p_row['WEIGHT'])
                
                if wpp > 0:
                    buy_signals[ticker] = {
                        'iv': iv,
                        'price': current_price,
                        'wpp': wpp,
                        'buy_price': buy_price,
                    }
        
        return buy_signals
    
    def backtest(self) -> None:
        """Execute backtest over entire date range"""
        # Merge price data
        merged = None
        for _, row in self.portfolio.iterrows():
            ticker = row['TICKER']
            df = self.price_data[ticker][['Date', 'Close', 'Dividends']].copy()
            df.columns = ['Date', ticker, f'{ticker}_Div']
            merged = df if merged is None else merged.merge(df, on='Date', how='outer')
        
        merged = merged.sort_values('Date').reset_index(drop=True)
        start_date = pd.to_datetime(self.config['START_DATE'])
        end_date = pd.to_datetime(self.config['END_DATE'])
        merged = merged[(merged['Date'] >= start_date) & (merged['Date'] <= end_date)]
        
        strategy_name = "GRAHAM'S STRATEGY" if self.use_strategy else "BUY & HOLD"
        print("\n" + "="*70)
        print(f"BACKTEST: {strategy_name}".center(70))
        print(f"Period: {start_date.date()} to {end_date.date()}".center(70))
        print("="*70 + "\n")
        
        for day_idx, (_, row) in enumerate(merged.iterrows()):
            date = row['Date']
            
            portfolio_value = self._calculate_portfolio_value(row)
            equity = self.cash + portfolio_value
            self._print_progress(day_idx, len(merged), equity)
            
            # Process dividends
            for _, p_row in self.portfolio.iterrows():
                ticker = p_row['TICKER']
                if not pd.isna(row.get(ticker)):
                    price_row = self.price_data[ticker][self.price_data[ticker]['Date'] == date]
                    if len(price_row) > 0:
                        self._process_dividends(ticker, date, price_row.iloc[0])
            
            # Apply Graham's Strategy
            if self.use_strategy:
                buy_signals = self._evaluate_trading_signals(row, date)
                if buy_signals:
                    self._execute_buys(buy_signals, date)
            
            # Log daily equity
            portfolio_value = self._calculate_portfolio_value(row)
            self.equity_log.append({
                'Date': date,
                'Cash': round(self.cash, 2),
                'Portfolio_Value': round(portfolio_value, 2),
                'Total_Equity': round(self.cash + portfolio_value, 2)
            })
        
        print("\n" + "="*70 + "\n")
    
    def get_results(self) -> Optional[Dict]:
        """
        Compile backtest results
        
        Returns:
            Dict with keys: equity_curve, trades, dividends, final_equity,
                          total_return, total_dividends, num_trades
        """
        equity_df = pd.DataFrame(self.equity_log)
        trades_df = pd.DataFrame(self.trades) if self.trades else pd.DataFrame()
        dividends_df = pd.DataFrame(self.dividends_log) if self.dividends_log else pd.DataFrame()
        
        if equity_df.empty:
            return None
        
        final_equity = equity_df['Total_Equity'].iloc[-1]
        total_return = ((final_equity - self.config['INITIAL_CAPITAL']) / self.config['INITIAL_CAPITAL']) * 100
        total_dividends = dividends_df['Total_Dividend'].sum() if not dividends_df.empty else 0
        
        return {
            'equity_curve': equity_df,
            'trades': trades_df,
            'dividends': dividends_df,
            'final_equity': final_equity,
            'total_return': total_return,
            'total_dividends': total_dividends,
            'num_trades': len(trades_df),
        }