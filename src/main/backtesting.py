import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from imports import *
from economics import *

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
    def __init__(self, config, portfolio, price_data, lpa_data, profit_data, use_strategy=True):
        self.config = config
        self.portfolio = portfolio
        self.use_strategy = use_strategy
        self.price_data = price_data
        self.lpa_data = lpa_data
        self.profit_data = profit_data
        
        self.cash = config['INITIAL_CAPITAL']
        self.positions = {}
        self.trades = []
        self.equity_log = []
        self.dividends_log = []
        self.iv_cache = {}
        
        self._setup_portfolio()
    
    def _setup_portfolio(self):
        """Initial equal weight allocation"""
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
            
            if shares > 0:
                cost = shares * start_price
                self.positions[ticker] = shares
                self.cash -= cost
                print(f'{ticker:6} | W:{row["WEIGHT"]:3} | {shares:5} shares @ R${start_price:8.2f} = R${cost:10.2f}')
        
        print(f'\nInitial cash: R${self.cash:.2f}\n')
    
    def _get_iv(self, ticker, date):
        """Get cached IV or calculate it - cache by date to account for interest rate changes"""
        date_str = date.strftime('%Y-%m-%d')
        
        if ticker not in self.iv_cache:
            self.iv_cache[ticker] = {}
        
        if date_str not in self.iv_cache[ticker]:
            try:
                iv = calculateIntrinsicValue(ticker, date, self.profit_data, self.lpa_data)
                self.iv_cache[ticker][date_str] = iv
            except:
                self.iv_cache[ticker][date_str] = None
        
        return self.iv_cache[ticker][date_str]
    
    def _process_dividends(self, ticker, date, price_row):
        """Reinvest dividends immediately"""
        dividend = price_row.get('Dividends', 0)
        if dividend > 0 and ticker in self.positions:
            amount = self.positions[ticker] * dividend
            
            current_price = price_row['Close']
            shares_to_buy = int(amount / current_price)
            
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
                'Total_Dividend': round(amount, 2)
            })
    
    def _execute_sell(self, ticker, date, current_price, iv):
        """Execute sell signal with partial sell levels"""
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
                    
                    profit_margin = level['profit_margin']
                    self.trades.append({
                        'Date': date,
                        'Ticker': ticker,
                        'Action': 'SELL',
                        'Shares': shares,
                        'Price': round(current_price, 2),
                        'IV': round(iv, 2),
                        'Profit_Margin': profit_margin,
                        'Level': level['level']
                    })
                break
    
    def _execute_buys(self, buy_signals, date):
        """Execute buy signals using WPP allocation"""
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
    
    def backtest(self):
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
            progress = (day_idx + 1) / len(merged) * 100
            
            filled = int(40 * (day_idx + 1) / len(merged))
            bar = '█' * filled + '░' * (40 - filled)
            
            portfolio_value = sum(self.positions.get(t, 0) * row.get(t, 0) for t in self.portfolio['TICKER'] if not pd.isna(row.get(t)))
            equity = self.cash + portfolio_value
            
            print(f'\r[{bar}] {progress:.0f}% | R${equity:10.2f} | Cash: R${self.cash:8.2f}', end='', flush=True)
            
            # Process dividends
            for _, p_row in self.portfolio.iterrows():
                ticker = p_row['TICKER']
                if not pd.isna(row.get(ticker)):
                    price_row = self.price_data[ticker][self.price_data[ticker]['Date'] == date]
                    if len(price_row) > 0:
                        self._process_dividends(ticker, date, price_row.iloc[0])
            
            # Apply Graham's Strategy
            if self.use_strategy:
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
                    elif current_price <= buy_price and self.cash > current_price * 10:
                        wpp = calculateWPP(iv, current_price, p_row['WEIGHT'])
                        
                        if wpp > 0:
                            buy_signals[ticker] = {
                                'iv': iv,
                                'price': current_price,
                                'wpp': wpp,
                                'buy_price': buy_price,
                            }
                
                if buy_signals:
                    self._execute_buys(buy_signals, date)
            
            # Log daily equity
            portfolio_value = sum(self.positions.get(t, 0) * row.get(t, 0) for t in self.portfolio['TICKER'] if not pd.isna(row.get(t)))
            self.equity_log.append({
                'Date': date,
                'Cash': round(self.cash, 2),
                'Portfolio_Value': round(portfolio_value, 2),
                'Total_Equity': round(self.cash + portfolio_value, 2)
            })
        
        print("\n" + "="*70 + "\n")
    
    def get_results(self):
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

if __name__ == "__main__":
    config = {
        'SAFETY_MARGIN': 0.50,
        'INITIAL_CAPITAL': 10000,
        'START_DATE': '2016-01-01',
        'END_DATE': '2024-12-31',
    }
    
    portfolio = pd.DataFrame(Portfolio)
    
    print("="*70)
    print("LOADING DATA".center(70))
    print("="*70)
    
    price_data = {t: getPriceData(t) for t in portfolio['TICKER']}
    lpa_data = {t: getLPAData(t) for t in portfolio['TICKER']}
    profit_data = {t: getProfitData(t) for t in portfolio['TICKER']}
    
    # Strategy Backtest
    print("\n" + "█"*70)
    print("GRAHAM'S VALUE STRATEGY BACKTEST".center(70))
    print("█"*70)
    bt_strat = Backtester(config, portfolio, price_data, lpa_data, profit_data, use_strategy=True)
    bt_strat.backtest()
    results_strat = bt_strat.get_results()
    
    # Buy & Hold Backtest
    print("\n" + "█"*70)
    print("BUY & HOLD BACKTEST".center(70))
    print("█"*70)
    bt_hold = Backtester(config, portfolio, price_data, lpa_data, profit_data, use_strategy=False)
    bt_hold.backtest()
    results_hold = bt_hold.get_results()
    
    # Results Comparison
    if results_strat and results_hold:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        print("\n" + "█"*70)
        print("BACKTEST COMPARISON".center(70))
        print("█"*70)
        
        print(f"\n{'METRIC':<30} | {'STRATEGY':<15} | {'BUY & HOLD':<15} | {'DIFFERENCE':<15}")
        print("-" * 80)
        print(f"{'Final Equity':<30} | R${results_strat['final_equity']:>13.2f} | R${results_hold['final_equity']:>13.2f} | R${results_strat['final_equity'] - results_hold['final_equity']:>13.2f}")
        print(f"{'Total Return':<30} | {results_strat['total_return']:>14.2f}% | {results_hold['total_return']:>14.2f}% | {results_strat['total_return'] - results_hold['total_return']:>14.2f}%")
        print(f"{'Number of Trades':<30} | {results_strat['num_trades']:>15} | {results_hold['num_trades']:>15} | {results_strat['num_trades'] - results_hold['num_trades']:>15}")
        print(f"{'Total Dividends':<30} | R${results_strat['total_dividends']:>13.2f} | R${results_hold['total_dividends']:>13.2f} |")
        print("█"*70)
        
        # Export results
        results_strat['equity_curve'].to_csv(f'equity_STRATEGY_{ts}.csv', index=False)
        results_hold['equity_curve'].to_csv(f'equity_BUYHOLD_{ts}.csv', index=False)
        
        if not results_strat['trades'].empty:
            results_strat['trades'].to_csv(f'trades_STRATEGY_{ts}.csv', index=False)
        
        if not results_hold['dividends'].empty:
            results_hold['dividends'].to_csv(f'dividends_{ts}.csv', index=False)
        
        print(f"\n✓ Results exported to CSV files")