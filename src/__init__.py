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

def loadData(portfolio: pd.DataFrame) -> tuple:
    """
    Load price, LPA, and profit data for all tickers
    
    Args:
        portfolio: DataFrame with tickers to load
    
    Returns:
        (priceData, lpaData, profitData) as dicts
    """
    print("="*70)
    print("LOADING DATA".center(70))
    print("="*70)
    
    priceData = {t: getPriceData(t) for t in portfolio['TICKER']}
    lpaData = {t: getLPAData(t) for t in portfolio['TICKER']}
    profitData = {t: getProfitData(t) for t in portfolio['TICKER']}
    
    return priceData, lpaData, profitData

def runBacktest(
    config: dict,
    portfolio: pd.DataFrame,
    priceData: dict,
    lpaData: dict,
    profitData: dict,
    useStrategy: bool = True
) -> dict:
    """
    Execute single backtest
    
    Args:
        config: Configuration dict
        portfolio: Portfolio DataFrame
        priceData, lpaData, profitData: Market data dicts
        useStrategy: If True, apply Graham's strategy; else Buy & Hold
    
    Returns:
        Results dict from Backtester.getResults()
    """
    bt = Backtester(config, portfolio, priceData, lpaData, profitData, useStrategy)
    bt.backtest()
    return bt.getResults()

def printComparison(resultsStrat: dict, resultsHold: dict) -> None:
    """Print detailed comparison of strategy vs buy & hold"""
    print("\n" + "-"*70)
    print("BACKTEST COMPARISON".center(70))
    print("-"*70)
    
    print(f"\n{'METRIC':<30} | {'STRATEGY':<15} | {'BUY & HOLD':<15} | {'DIFFERENCE':<15}")
    print("-" * 80)
    print(f"{'Final Equity':<30} | R${resultsStrat['final_equity']:>13.2f} | R${resultsHold['final_equity']:>13.2f} | R${resultsStrat['final_equity'] - resultsHold['final_equity']:>13.2f}")
    print(f"{'Total Return':<30} | {resultsStrat['total_return']:>14.2f}% | {resultsHold['total_return']:>14.2f}% | {resultsStrat['total_return'] - resultsHold['total_return']:>14.2f}%")
    print(f"{'Number of Trades':<30} | {resultsStrat['num_trades']:>15} | {resultsHold['num_trades']:>15} | {resultsStrat['num_trades'] - resultsHold['num_trades']:>15}")
    print(f"{'Total Dividends':<30} | R${resultsStrat['total_dividends']:>13.2f} | R${resultsHold['total_dividends']:>13.2f} |")
    print("-" * 80)

def exportResults(resultsStrat: dict, resultsHold: dict) -> None:
    """Export backtest results to CSV files"""
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    resultsStrat['equity_curve'].to_csv(f'equity_STRATEGY_{ts}.csv', index=False)
    resultsHold['equity_curve'].to_csv(f'equity_BUYHOLD_{ts}.csv', index=False)

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
    priceData, lpaData, profitData = loadData(portfolio)
    
    # Run backtests
    resultsStrat = runBacktest(config, portfolio, priceData, lpaData, profitData, useStrategy=True)
    resultsHold = runBacktest(config, portfolio, priceData, lpaData, profitData, useStrategy=False)
    
    # Compare and export
    if resultsStrat and resultsHold:
        exportResults(resultsStrat, resultsHold)
