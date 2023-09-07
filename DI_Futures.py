import pandas as pd
import numpy as np
import datetime as dt
from urllib import request
from datetime import datetime, timedelta
import holidays

## Function that returns the prices of futures from B3 (Brazilian Mercantile and Futures Exchange):
def GetFutureB3Data(Date=None, Object=None, Expiry=None, Type='Price'):
    if isinstance(Date, str):
        Date = dt.datetime.strptime(Date, '%Y-%m-%d').strftime('%d/%m/%Y')
    elif isinstance(Date, dt.date):
        Date = Date.strftime('%d/%m/%Y')
    else:
        raise ValueError('The date must follow the type str yyyy-mm-dd or the type dt.date')
    
    source = request.urlopen(request.Request(f'https://www2.bmf.com.br/pages/portal/bmfbovespa/boletim1/Ajustes1.asp?txtData={Date}')).read()
    df = pd.read_html(source, thousands='.', decimal=',')[5].ffill()
    df = df.rename(columns=df.iloc[0]).drop(df.index[0])
    df['Mercadoria'] = df['Mercadoria'].apply(lambda x: x.split('-')[0][:-1])

    if Object is None:
        print('Object must be filled')
    else:
        pass

    if Expiry is None:
        pass
    else:
        df = df.loc[df['Vct'] == Expiry]
        
    if Type == 'Adjustment':
        df = df.loc[:,['Mercadoria','Vct','Valor do Ajuste por Contrato (R$)']]
    elif Type == 'Price':
        df = df.loc[:,['Mercadoria','Vct','Preço de Ajuste Atual']]
    else:
        raise ValueError('Type must be price or adjustment')
        
    df = df.loc[df['Mercadoria'] == Object]
    df = df.set_index('Mercadoria')
        
    return df

#print(GetFutureB3Data('2023-09-01','DI1','F24'))

## Support function to get the brazilian holidays for the next X years:
def GetBrazilianHolidays(start_date, end_date):
    if isinstance(start_date, str):
        pass
    elif isinstance(start_date, dt.date):
        start_date = start_date.strftime('%Y-%m-%d')
        end_date = end_date.strftime('%Y-%m-%d')
    else:
        raise ValueError('The date must follow the type str yyyy-mm-dd or the type dt.date')
    
    start_date = pd.to_datetime(start_date)
    end_date = pd.to_datetime(end_date)
    br_holidays = holidays.Brazil(years=range(start_date.year, end_date.year + 1))

    holidays_list = []
    for date in pd.date_range(start_date, end_date):
        if date in br_holidays:
            holidays_list.append(date)

    return holidays_list

#print(GetBrazilianHolidays('2023-09-01','2037-12-31'))

##Function that returns the expiration of a DI contract, given its ticker. Needs to have a list of holidays so we can skip the holidays in the beggining of the month:
def TickerToExpiration(ticker,holidays):
    if isinstance(ticker, str):
        pass
    else:
        raise ValueError('Ticker must be type str')
    
    Expiration = {'F': '01', 'G': '02', 'H': '03', 'J': '04',
                  'K': '05', 'M': '06', 'N': '07', 'Q': '08',
                  'U': '09', 'V': '10', 'X': '11', 'Z': '12'}
    year = str(20) + ticker[1:]
    month = Expiration[ticker[:1]]
    auxdate = year + '-' + month + '-' + '01'
    date = pd.bdate_range(auxdate,periods=1,freq='C',holidays=holidays)[0]
    return date

#print(TickerToExpiration('M24',GetBrazilianHolidays('2023-09-01','2037-12-31')))

##Function that calculates the forward rate between two other rates:
def ForwardRate(Rate,PrevRate,BusinessDays,PreviousBusinessDays,ForwardBusinessDays):
  ForwardRate = (((1+Rate)**(BusinessDays/252)) / ((1+PrevRate)**(PreviousBusinessDays/252)))**(252/ForwardBusinessDays) - 1
  return ForwardRate

#Function that returns a price given a price:
def PriceToYield(RefDate,Price,Contract):
    Date = datetime.strptime(RefDate, '%Y-%m-%d')
    Holidays = GetBrazilianHolidays(RefDate,pd.to_datetime(RefDate) + timedelta(days=10000))
    Expiration = TickerToExpiration(Contract,Holidays)
    BusinessDays = len(pd.bdate_range(Date,Expiration,freq='C',holidays=Holidays))
    Yield = ((100000/Price)**(252/BusinessDays)) - 1
    return(Yield)

##Function that creates a table with the forward rates:
def ForwardTable(RefDate,EndDate):
    Holidays = pd.DataFrame({'Date':GetBrazilianHolidays(RefDate,EndDate)})['Date']
    RefDate = datetime.strptime(RefDate, '%Y-%m-%d')
    EndDate = datetime.strptime(EndDate, '%Y-%m-%d')
    Futures = GetFutureB3Data(RefDate,'DI1')
    Futures.index = Futures['Vct']
    
    Contracts = pd.DataFrame(index=Futures['Vct'])
    Contracts.loc[:,'Price'] = Futures.loc[:,'Preço de Ajuste Atual']
    Contracts.loc[:,'Expiration'] = Contracts.index.to_series().apply(lambda x: TickerToExpiration(x,Holidays))

    if pd.to_datetime(Contracts.iloc[0,:].loc['Expiration']) > EndDate:
        raise ValueError('EndDate must be after the next DI expiry date')
    else:
        pass

    Contracts = Contracts.loc[pd.to_datetime(Contracts['Expiration']) < EndDate].loc[pd.to_datetime(Contracts['Expiration']) > RefDate]
    Contracts.loc[:,'BusinessDays'] = Contracts.apply(lambda row: len(pd.bdate_range(RefDate, row['Expiration'], freq='C', holidays=Holidays.to_list())), axis=1) - 1 
    Contracts.loc[Contracts.index[0],'Forward BusinessDays'] = Contracts.loc[Contracts.index[0],'BusinessDays']

    for Expiry, PreviousExpiry in zip(Contracts.index[1:],Contracts.index):
        Contracts.loc[Expiry,'Forward BusinessDays'] = Contracts.loc[Expiry,'BusinessDays'] - Contracts.loc[PreviousExpiry,'BusinessDays']

    for Expiry in Contracts.index:
        Price = float(Contracts.loc[Expiry,'Price'])
        BusinessDays = Contracts.loc[Expiry,'BusinessDays']
        Contracts.loc[Expiry,'Yield'] = ((100000/Price)**(252/BusinessDays)) - 1   

    Contracts.loc[Contracts.index[0],'Forward Rate'] = Contracts.loc[Contracts.index[0],'Yield'] #Primeiro contrato NDU = NDU termo
    Contracts.loc[:,'Present Value'] = Contracts.loc[:,'Price']

    for Expiry, PreviousExpiry in zip(Contracts.index[1:], Contracts.index):
        Contracts.loc[Expiry,'Forward Rate'] = ForwardRate(Contracts.loc[Expiry,'Yield'], Contracts.loc[PreviousExpiry,'Yield'], Contracts.loc[Expiry,'BusinessDays'], Contracts.loc[PreviousExpiry,'BusinessDays'], Contracts.loc[Expiry,'Forward BusinessDays'])

    Contracts.insert(0, 'Vertice', [x + 1 for x in range(len(Contracts))])
    Contracts = Contracts.reset_index()
    Contracts = Contracts.set_index('Vertice')

    return Contracts

#print(ForwardTable('2023-09-01','2037-12-31'))    

## Function that calculates the exposition in each contract after an impulse on the rate:
def ExpositionImpulse(RefDate,EndDate,Impulse):
    df = ForwardTable(RefDate,EndDate)
    Impulse = 0.01

    for Expiry in df.index:
        df.loc[Expiry,'Exp Forward'] = (100000/(1 + df.loc[Expiry,'Yield'] + Impulse)**(df.loc[Expiry,'BusinessDays']/252)) - float(df.loc[Expiry,'Present Value'])
        df.loc[Expiry, 'Exp Spot'] = (-df.loc[Expiry,'BusinessDays']/252) * (float(df.loc[Expiry, 'Present Value'])/(1+df.loc[Expiry, 'Yield'])/100)

    return(df)

#print(ExpositionImpulse('2023-09-01','2037-12-31',0.01))

## Function that calculates the exposition that each contract holds in each vertice after an impulse in the spot rate:
def ForwardExpositionImpulse(RefDate,EndDate,Impulse):
    df = ExpositionImpulse(RefDate,EndDate,Impulse)
    ForwardExposition = pd.DataFrame(index = df.index, columns = df.index)

    for j in ForwardExposition.columns:
        for i in ForwardExposition.index:
            if int(i) >= int(j):
                ForwardExposition.loc[i,j] = (- df.loc[j,'Forward BusinessDays'] / 252) * (float(df.loc[i,'Present Value']) / (1 + df.loc[j,'Forward Rate']) / 100)
            else:
                pass
            
    ForwardExposition.insert(0, 'Expo Termos', ForwardExposition.sum(axis=1))
    ForwardExposition = ForwardExposition.fillna('')
    return(ForwardExposition)

#print(ForwardExpositionImpulse('2023-09-01','2037-12-31',0.01))

## Support interpolation function:
def Interpolation(PreviousRate,SubsequentRate,PreviousBusinessDays,SubsequentBusinessDays,BusinessDays,Type="Linear"):
    if Type == "FlatForward":
        ForwardCarry = ((1+SubsequentRate)**(SubsequentBusinessDays/252))
        PreviousCarry = ((1+PreviousRate)**(PreviousBusinessDays/252))
        BusinessDaysFactor = ((BusinessDays - PreviousBusinessDays)/(SubsequentBusinessDays - PreviousBusinessDays))
        Rate = ((PreviousCarry * ((ForwardCarry / PreviousCarry)**BusinessDaysFactor))**(252/BusinessDays)) - 1
    elif Type == "FlatForwardLinearConvention":
        ForwardCarry = ((1+SubsequentRate*SubsequentBusinessDays/360))
        PreviousCarry = ((1+PreviousRate*PreviousBusinessDays/360))
        BusinessDaysFactor = ((BusinessDays - PreviousBusinessDays)/(SubsequentBusinessDays - PreviousBusinessDays))
        Rate = ((PreviousCarry * ((ForwardCarry / PreviousCarry)**BusinessDaysFactor))**(360/BusinessDays)) - 1
    elif Type == "Interpolation360":
        ForwardCarry = ((1+SubsequentRate)**(SubsequentBusinessDays/360))
        PreviousCarry = ((1+PreviousRate)**(PreviousBusinessDays/360))
        BusinessDaysFactor = ((BusinessDays - PreviousBusinessDays)/(SubsequentBusinessDays - PreviousBusinessDays))
        Rate = ((PreviousCarry * ((ForwardCarry / PreviousCarry)**BusinessDaysFactor))**(360/BusinessDays)) - 1
    elif Type == "Linear":
        PreviousCarry = ((1+PreviousRate)**(SubsequentBusinessDays/252))
        ForwardCarry = ((1+SubsequentRate)**(PreviousBusinessDays/252))
        Rate = ((PreviousCarry * ForwardCarry)**(252/BusinessDays))-1
    else:
        pass
    
    return(Rate)

##Function to return data from the Brazilian Central Bank API:
def GetBacenData(Titulos, codigos_bcb, Start, End):
    main_df = pd.DataFrame()

    for i, codigo in enumerate(codigos_bcb):
        url = f'http://api.bcb.gov.br/dados/serie/bcdata.sgs.{str(codigo)}/dados?formato=json&dataInicial={Start}&dataFinal={End}'
        df = pd.read_json(url)

        df['DATE'] = pd.to_datetime(df['data'], dayfirst=True)
        df.drop('data', axis=1, inplace=True)
        df.set_index('DATE', inplace=True)
        df.columns = [str(Titulos[i])]

        if main_df.empty:
            main_df = df
        else:
            main_df = main_df.merge(df, how='outer', left_index=True, right_index=True)

    main_df.fillna(method='ffill', inplace=True)

    return main_df

## Function that creates the yield curve from the DI contracts:
def YieldCurve(RefDate,EndDate,Type="Forward"):
    
    if Type == 'Spot':
        Tbl = (ExpositionImpulse(RefDate,EndDate,0)).loc[:,['Expiration','Yield']].set_index('Expiration')
    elif Type == 'Forward':
        Tbl = (ExpositionImpulse(RefDate,EndDate,0)).loc[:,['Expiration','Forward Rate']].set_index('Expiration')
    else:
        raise ValueError('The type must be spot or forward')
    
    AuxDates = pd.bdate_range(RefDate,EndDate,freq='C',holidays=GetBrazilianHolidays(RefDate,EndDate))

    Curve = pd.DataFrame(index=AuxDates,columns=['Rate', 'PreviousRate', 'SubsequentRate'])

    for Date in AuxDates:
        try:
            if Type == 'Spot':
                Curve.loc[Date,'Rate'] = Tbl.loc[Date,'Yield']
            elif Type == 'Forward':
                Curve.loc[Date,'Rate'] = Tbl.loc[Date,'Forward Rate']
            else:
                raise ValueError('The type must be spot or forward')
        except:
            pass

    SelicDaily = GetBacenData(['CDI'], [12], RefDate, RefDate).loc[RefDate,'CDI']/100
    Selic = ((1+SelicDaily)**(252))-1
    Curve.loc[RefDate,'Rate'] = Selic

    Curve = Curve.reset_index()
    Curve['PreviousDay'] = Curve['index'].where(Curve['Rate'].notnull()).ffill()
    Curve['SubsequentDay'] = Curve['index'].where(Curve['Rate'].notnull()).bfill()
    Curve = Curve.set_index('index')

    for Date in AuxDates:
        PreviousDay = Curve.loc[Date,'PreviousDay']
        SubsequentDay = Curve.loc[Date,'SubsequentDay']
        if (PreviousDay < Date and Date < SubsequentDay) == True:
            try:
                Curve.loc[Date,'PreviousRate'] = Curve.loc[PreviousDay,'Rate']
                Curve.loc[Date,'SubsequentRate'] = Curve.loc[SubsequentDay,'Rate']
                Curve.loc[Date,'PreviousBusinessDays'] = len(pd.bdate_range(PreviousDay,Date,freq='C',holidays=GetBrazilianHolidays(RefDate,EndDate)))-1
                Curve.loc[Date,'SubsequentBusinessDays'] = len(pd.bdate_range(Date,SubsequentDay,freq='C',holidays=GetBrazilianHolidays(RefDate,EndDate)))-1
                Curve.loc[Date,'BusinessDays'] = Curve.loc[Date,'PreviousBusinessDays'] + Curve.loc[Date,'SubsequentBusinessDays']
                Curve.loc[Date,'CalculatedRate'] = Interpolation(Curve.loc[Date,'PreviousRate'], Curve.loc[Date,'SubsequentRate'], Curve.loc[Date,'PreviousBusinessDays'],Curve.loc[Date,'SubsequentBusinessDays'],Curve.loc[Date,'BusinessDays'])
            except:
                pass
        else:
            pass

    Curve['ProjectedRate'] = np.where(pd.isnull(Curve['Rate']), Curve['CalculatedRate'], Curve['Rate'])       
    Curve['ProjectedRate'] = Curve['ProjectedRate'].ffill()
    
    Curve = Curve.loc[:,'ProjectedRate']

    return(Curve)

#print(YieldCurve('2023-09-01','2037-12-31',Type='Forward'))

##Function that returns the projection of the interest rate given a future date:
def YieldDay(RefDate, YieldDay,Type="Forward"):
    EndDate = (pd.to_datetime(YieldDay) + timedelta(days=365)).strftime("%Y-%m-%d")
    Curve = YieldCurve(RefDate, EndDate, Type)
    if YieldDay in Curve.index:
        Yield = Curve.loc[YieldDay]
        return(Yield)
    else:
        raise ValueError('YieldDay cannot be a holiday or a weekend')
    
#print(YieldDay('2023-09-01','2037-09-01'))

##Function that returns the exposition of a DI contract considering its duration:
def ExpositionDI(RefDate, Object):
    try:
        Contract = Object.partition('-')[0]
        Expiry = Object.partition('-')[2]
    except:
        raise ValueError('The object must follow the format ABC-X99')
    
    Price = float(GetFutureB3Data(RefDate,Contract,Expiry)['Preço de Ajuste Atual'])
 
    PU = (Price)
    Yield = PriceToYield(RefDate,Price,Expiry)
    Holidays = GetBrazilianHolidays(RefDate,pd.to_datetime(RefDate) + timedelta(days=10000))
    Expiration = TickerToExpiration(Expiry, Holidays)
    BusinessDays = len(pd.bdate_range(RefDate,Expiration,freq='C',holidays=Holidays))
    Duration = BusinessDays/252
    Exp = -Duration * PU * (1+Yield)

    return(Exp)

#print(ExpositionDI('2023-09-01','DI1-F24'))
