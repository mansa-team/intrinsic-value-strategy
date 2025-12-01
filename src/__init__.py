from imports import *

#
#$ Basic Setup
#
currentYear = pd.Timestamp(datetime.now())

#
#$ Functions
#
def calculateCAGRLucros10anos(TICKER, target_date):
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
                if ano <= target_date.year - 1:
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

def calculateInterestRates(target_date):
    SELIC = requests.get('https://api.bcb.gov.br/dados/serie/bcdata.sgs.4189/dados?formato=json')
    SELIC = pd.DataFrame(SELIC.json())

    #$ The SELIC value based on the target date
    SELIC = SELIC.astype({'data': 'datetime64[ns]', 'valor': 'float64'})
    SELIC = SELIC[SELIC['data'] <= target_date]
    
    if len(SELIC) == 0:
        return None, None
    
    selicAtual = SELIC.iloc[-1]['valor']

    #$ Average SELIC over 10 years
    SELIC = SELIC.set_index('data')
    SELIC = SELIC.groupby(pd.Grouper(freq='YE'))['valor'].mean()
    
    SELIC = SELIC.reset_index()
    SELIC['ano'] = SELIC['data'].dt.year
    SELIC = SELIC[['ano', 'valor']]

    target_year = target_date.year
    selic10y = SELIC[SELIC['ano'] >= target_year - 10]['valor'].mean()

    return selicAtual, selic10y

def calculateIntrinsicValue(TICKER, target_date):
    # x = CAGR LUCROS 10 ANOS
    # z = real interest rate
    # y = current interest rate
    #
    #     LPA * (8.5 + 2x) * z
    # V = --------------------
    #             y

    x = calculateCAGRLucros10anos(TICKER, target_date)
    y, z = calculateInterestRates(target_date)

    response = requests.get(f'http://{Config.STOCKS_API["HOST"]}:{Config.STOCKS_API["PORT"]}/api/fundamental?search={TICKER}&fields=LPA')
        
    if response.status_code == 200:
        api_data = response.json()

        if len(api_data['data']) > 0:
            lpa = api_data['data'][0]['LPA']
        else:
            return None
            
        if lpa is None or x is None or y is None or z is None:
            return None
        
    intrinsicValue = lpa * (8.5 + 2*x) * z / y

    return round(intrinsicValue, 2)

if __name__ == "__main__":
    safetyMargin = 50 # %
    maxHoldTime = 3 # years

    profitMarginSpike = 17.5 # %
    sellWhenPossible = 50 # %
    # (sell another 50% for each 17.5% spike over the 50% profit safetyMargin)

    intrinsicValue = calculateIntrinsicValue('EMBJ3', currentYear)
    print(intrinsicValue)

    # if buyPrice =< price: emitSignal('buy', TICKER)
    # if trimPrice => price: emitSignal('sellPartially', TICKER) # for every 17,5% increase in the currentMargin above the safetyMargin, sell 50%, logarithimically
    # if buyPrice < price < trimPrice: emitSignal('keep', TICKER)

    # weighted purchase price (wpp): distribute the dock capital based of the strategic price and the discount factor (iV/price)
    # wpp($) = pe * iV / price

    # proportional capital distribution (pcd): how much of your dock capital should be allocated to each stock
    # pcd(%) = wpp / Σwpp

    # calculate the final amount of stocks to buy
    # avaliableCapital = currentCapital / pcd
    # floor(avaliableCapital / price) for each stock

    # https://encrypted-tbn3.gstatic.com/licensed-image?q=tbn:ANd9GcQzUKKfhlNERarNN5ZA40UL4iHo2MV6r52GZaYRbeUp1YB0xSggFqskrt6d-fbqDB-iTeA8J9r-zoWiVhJ0_tYvgSia9vnBvpdLtF0LxzzExu5nCLA