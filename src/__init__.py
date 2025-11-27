from imports import *

#
#$ Basic Setup
#
currentYear = datetime.now().year

#
#$ Functions
#
def calculateCAGRLucros10anos(TICKER):
    #$ Calculate the CAGR Lucros 10 Anos
    # CAGR = (Valor Final / Valor Inicial) ^ (1 / n) - 1
    targetStartYear = currentYear - 1

    CAGRLucros10Anos = {}
    response = requests.get(f'http://{Config.STOCKS_API['HOST']}:{Config.STOCKS_API['PORT']}/api/historical?search={TICKER}&fields=LUCRO%20LIQUIDO')

    if response.status_code == 200:
        data = response.json()

        df = pd.DataFrame(data)


    return CAGRLucros10Anos

def calculateInterests():
    SELIC = requests.get('https://api.bcb.gov.br/dados/serie/bcdata.sgs.4189/dados?formato=json')
    SELIC = pd.DataFrame(SELIC.json())

    IPCA = requests.get('https://api.bcb.gov.br/dados/serie/bcdata.sgs.10844/dados?formato=json')
    IPCA = pd.DataFrame(IPCA.json())

    dataframes = {'SELIC': SELIC, 'IPCA': IPCA}
    for name, df in dataframes.items():
        df = df.astype({
            'data': 'datetime64[ns]',
            'valor': 'float64'
        })

        dataframes[name] = df

    SELIC = dataframes['SELIC']
    IPCA = dataframes['IPCA']

    #$ Calculate the real Interest Rate
    jurosRealAtual = round(SELIC.iloc[-1]['valor'] - IPCA.iloc[-1]['valor'], 2)

    #$ Calculate the real Interest Rate over 10 years in average
    for name, df in dataframes.items():
        df = df.set_index('data')
        
        if name == 'IPCA':
            df = df.groupby(pd.Grouper(freq='YE'))['valor'].sum()
        else:
            df = df.groupby(pd.Grouper(freq='YE'))['valor'].mean()
        
        df = df.reset_index()
        df['ano'] = df['data'].dt.year
        df = df[['ano', 'valor']]

        dataframes[name] = df

    SELIC = dataframes['SELIC']
    IPCA = dataframes['IPCA']

    selic_10y = SELIC[SELIC['ano'] >= currentYear - 10]['valor'].mean()
    ipca_10y = IPCA[IPCA['ano'] >= currentYear - 10]['valor'].mean()
    jurosReal10anos = round(selic_10y - ipca_10y, 2)

    return jurosRealAtual, jurosReal10anos


if __name__ == "__main__":
    # x = CAGR LUCROS 10 ANOS
    # z = Juros Real (Selic - IPCA) ao longo de 10 anos
    # y = Juros Real atual
    #
    #     LPA * (8.5 + 2x) * z
    # V = --------------------
    #             y

    x = calculateCAGRLucros10anos("WEGE3")
    y, z = calculateInterests()