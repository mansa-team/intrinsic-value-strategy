"""
Main execution module for Graham's Value Strategy Backtester
"""
from imports import *
from main.backtesting import Backtester, getPriceData, getLPAData, getProfitData

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

def load_data(portfolio: pd.DataFrame) -> tuple:
    """
    Load price, LPA, and profit data for all tickers
    
    Args:
        portfolio: DataFrame with tickers to load
    
    Returns:
        (price_data, lpa_data, profit_data) as dicts
    """
    print("="*70)
    print("LOADING DATA".center(70))
    print("="*70)
    
    price_data = {t: getPriceData(t) for t in portfolio['TICKER']}
    lpa_data = {t: getLPAData(t) for t in portfolio['TICKER']}
    profit_data = {t: getProfitData(t) for t in portfolio['TICKER']}
    
    return price_data, lpa_data, profit_data

def run_backtest(
    config: dict,
    portfolio: pd.DataFrame,
    price_data: dict,
    lpa_data: dict,
    profit_data: dict,
    use_strategy: bool = True
) -> dict:
    """
    Execute single backtest
    
    Args:
        config: Configuration dict
        portfolio: Portfolio DataFrame
        price_data, lpa_data, profit_data: Market data dicts
        use_strategy: If True, apply Graham's strategy; else Buy & Hold
    
    Returns:
        Results dict from Backtester.get_results()
    """
    bt = Backtester(config, portfolio, price_data, lpa_data, profit_data, use_strategy)
    bt.backtest()
    return bt.get_results()

def print_comparison(results_strat: dict, results_hold: dict) -> None:
    """Print detailed comparison of strategy vs buy & hold"""
    print("\n" + "-"*70)
    print("BACKTEST COMPARISON".center(70))
    print("-"*70)
    
    print(f"\n{'METRIC':<30} | {'STRATEGY':<15} | {'BUY & HOLD':<15} | {'DIFFERENCE':<15}")
    print("-" * 80)
    print(f"{'Final Equity':<30} | R${results_strat['final_equity']:>13.2f} | R${results_hold['final_equity']:>13.2f} | R${results_strat['final_equity'] - results_hold['final_equity']:>13.2f}")
    print(f"{'Total Return':<30} | {results_strat['total_return']:>14.2f}% | {results_hold['total_return']:>14.2f}% | {results_strat['total_return'] - results_hold['total_return']:>14.2f}%")
    print(f"{'Number of Trades':<30} | {results_strat['num_trades']:>15} | {results_hold['num_trades']:>15} | {results_strat['num_trades'] - results_hold['num_trades']:>15}")
    print(f"{'Total Dividends':<30} | R${results_strat['total_dividends']:>13.2f} | R${results_hold['total_dividends']:>13.2f} |")
    print("-" * 80)

def export_results(results_strat: dict, results_hold: dict) -> None:
    """Export backtest results to CSV files"""
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    results_strat['equity_curve'].to_csv(f'equity_STRATEGY_{ts}.csv', index=False)
    results_hold['equity_curve'].to_csv(f'equity_BUYHOLD_{ts}.csv', index=False)
    
    #if not results_strat['trades'].empty:
        #results_strat['trades'].to_csv(f'trades_STRATEGY_{ts}.csv', index=False)
    
    #if not results_hold['dividends'].empty:
        #results_hold['dividends'].to_csv(f'dividends_{ts}.csv', index=False)

if __name__ == "__main__":
    """Execute full backtest workflow"""
    config = {
        'SAFETY_MARGIN': 0.50,
        'INITIAL_CAPITAL': 10000,
        'START_DATE': '2016-01-01',
        'END_DATE': '2024-12-31',
    }
    
    portfolio = pd.DataFrame(Portfolio)
    
    # Load data
    price_data, lpa_data, profit_data = load_data(portfolio)
    
    # Run backtests
    results_strat = run_backtest(config, portfolio, price_data, lpa_data, profit_data, use_strategy=True)
    results_hold = run_backtest(config, portfolio, price_data, lpa_data, profit_data, use_strategy=False)
    
    # Compare and export
    if results_strat and results_hold:
        #print_comparison(results_strat, results_hold)
        export_results(results_strat, results_hold)
