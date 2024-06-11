import pandas as pd

from decimal import Decimal, getcontext
import math
import sys, datetime, csv, json
from io import StringIO
import io, os, re
getcontext().prec = 1000
import configparser

config = configparser.ConfigParser()
config.read('config.ini')

#App1 imports
import csv
from copy import copy
import os

#App1 Variables
ASSETS_TRACKER = {}

#App2 Variables
assets_state2 = {}
line_counter2 = 0

#Main App Variales
assets_state = {}
asset_state = {}
line_counter = 1
averagePriceFromOtherAccount = Decimal('0')

CURRENCIES = json.loads(config.get('settings', 'CURRENCIES'))
#CAD/USD
EXCHANGE_RATES = json.loads(config.get('settings', 'EXCHANGE_RATES'))

#for app2 user input
DF_COPY = None
NOT_VAILD_FX_RATES = False
EXCHANGE_RATES_CSV = None
EXCHANGE_RATES_CSV_HEADER = None

#both will be used to find when BASE_QC is None and we need to priorties which QC to use. #ref101
USD_PAIRS_FOR_CSV_RATES = []
USD_AVILABLE_FOR_CURRENCIES = []
stablecoins = ["BUSD", "USDT", "UST", "USDC", "TUSD", "PUSD"] 

BASE_QC = None

def remove_missing_time(date_str): #Remove HH:MM From Date 
    date_str = str(date_str).strip()
    if len(date_str) != 10:
        return date_str.split(' ')[0]
    return date_str

####################################### UTILS
def get_guote_currency(row, asset, app2=False): #Get Quote Currnency 
    global Default_Quote_Currency, AdjustRates2

    try:
        quote_currency = row['Quote Currency'] #Try to get the Inputted Quote Currency 
    except KeyError: #If error 
        quote_currency = None #Then it wil be none 
    if (not quote_currency or str(quote_currency).lower() == 'nan') and not check_data_in_currencies(asset): #If quote currency is None or NaN and Asset is not in dictionary
        quote_currency = Default_Quote_Currency #Quote Currency is Default Currency
    elif (not quote_currency or str(quote_currency).lower() == 'nan') and check_data_in_currencies(asset): #If quote currency is None or NaN and Asset is in dictionary 
        if (AdjustRates2 or AdjustRatesFromCSV) and app2: #If App2 is On, and one of AdjustRates is turned on 
            quote_currency = 'nan' #Quote Currency is Nothing 
        else:
            quote_currency = asset #Quote Currency is asset (probably never trigger) 
    elif quote_currency and check_data_in_currencies(asset): #If there is quote currency and asset is in dictionary 
        if (AdjustRates2 or AdjustRatesFromCSV) and app2:
            quote_currency = row['Quote Currency'] #Same as the first try 
        else:
            quote_currency = asset #Quote currency is asset (probably will never trigger) 
    return quote_currency

def get_modification_qc(row, asset):  #Get Quote Currnency 
    global Default_Quote_Currency

    try:
        quote_currency = row['Quote Currency'] #Try to get Inputted Quote Currency 
    except KeyError: #If error 
        quote_currency = None #Then its none 
    if (not quote_currency or str(quote_currency).lower() == 'nan') and not check_data_in_currencies(asset): #If Quote currenc is None or NaN and Asset not in dictionary
        quote_currency = Default_Quote_Currency #Quote Currency is Default Quote Currency 
    elif (not quote_currency or str(quote_currency).lower() == 'nan') and check_data_in_currencies(asset): #If Quote currenc is None or NaN and Asset  in dictionary
        quote_currency = 'no_qc' #There will be no data 
    return quote_currency

def check_nan_make_0(data): #Treat NaN as 0 
    if str(data) == 'nan' or not data: #If string Data is NaN or error 
        data = 0
    return data

#Util to find date object.
def detect_date_from_string(date_string): #Convert the string input date to object 
    try:
        datetime_obj = datetime.datetime.strptime(date_string, '%Y-%m-%d') #First attempt try to YYYY-MM-DD 
    except:
        try:
            datetime_obj = datetime.datetime.strptime(date_string, '%Y-%m-%d %H:%M') #If failed try YYYY-MM-DD HH:MM (Dont know if skipping trying YYYY-MM-DD HH can caused bug) 
        except:
            try:
                datetime_obj = datetime.datetime.strptime(date_string, '%Y-%m-%d %H:%M:%S') #If failed try YYYY-DD HH:MM:SS 
            except:
                return None
    return datetime_obj

def detect_date_info(data_list):
    mim_check_dates = 5 #so this will find header if minimum this amount of date is present. #Minimum amount to be 5 dates in a row to be consider header in FX Rates 

    founded_dates = []
    date_position = None
    date_value = None
    index_of_date = None
    for index, row in enumerate(data_list):
        tmp_row = [r for r in row if r.strip()] #select non empty lines/lines that has values 
        if not tmp_row: #Continue if empty 
            continue
        date_data = tmp_row[0] #? 

        datetime_obj = detect_date_from_string(date_data) #Turn date_data into date_object
        if datetime_obj: #If date object is valid add it to founded_date list 
            founded_dates.append(datetime_obj) 
            if not date_position:  
                date_position = index - 1 #?

                if not date_value: 
                    prev_row = data_list[index - 1] #Previous row is the previous index 
                    tmp_row2 = [r for r in prev_row if r.strip()] #select non empty lines/lines that has values 
                    if tmp_row2: #If empty row 
                        date_value = tmp_row2[0] #? 
                        for i, r in enumerate(prev_row):
                            if r == date_value:
                                index_of_date = i
        else:
            founded_dates = []
            date_position = None
            date_value = None
            index_of_date = None
        if len(founded_dates) == mim_check_dates: #If the length of the list is = to the mininimum amount of date in a row 
            break #Then break 
    if len(founded_dates) < mim_check_dates: #If the length of the list of founded date is less than minimum amount of date in  a row 
        date_position, date_value, index_of_date = None, None, None
    return date_position, date_value, index_of_date

def update_exchange_rate_data(csv_path): #Take in FX Rates.csv path 
    global EXCHANGE_RATES_CSV, EXCHANGE_RATES_CSV_HEADER, CURRENCIES, BASE_QC, USD_PAIRS_FOR_CSV_RATES, USD_AVILABLE_FOR_CURRENCIES, NOT_VAILD_FX_RATES

    USE_UPDATED_TRIGGER_KEY = True #True|False both will work | False will search through index, True will search throw word

    extracted_rows = []
    found_header = False
    first_test_pass = False
    index_of_date = None

    if not os.path.exists(csv_path):
        NOT_VAILD_FX_RATES = True
        return

    with open(csv_path, 'r', encoding='utf-8-sig') as csv_f:
        csv_reader = csv.reader(csv_f)
        data_list = list(csv_reader)

    #V0
    #where it's depended on keyword date.
    find_trigger_key = 'date'
    USE_OLD_LOGIC = False #If this is True, it will find based on header date 
    date_position, date_col_value, date_col_index = detect_date_info(data_list)
    if not (date_position and date_col_value and date_col_index):
        USE_OLD_LOGIC = True
    elif USE_UPDATED_TRIGGER_KEY:
        find_trigger_key = date_col_value

    index_of_date = None

    for index, row in enumerate(data_list):
        row_t = [r.lower().strip() for r in row]
        if not index_of_date and find_trigger_key in row_t and USE_UPDATED_TRIGGER_KEY:
            index_of_date = row_t.index(find_trigger_key)
        elif not index_of_date and not USE_UPDATED_TRIGGER_KEY and str(index) == str(date_position):
            index_of_date = date_col_index
        #it was (find_trigger_key in row_t) before

        if USE_OLD_LOGIC and find_trigger_key in row_t:
            index_of_date = row_t.index(find_trigger_key)
        
        if index_of_date is not None and not found_header:
            #index_of_date = row_t.index(find_trigger_key)
            #check if row[1] is currency thing.
            for c in CURRENCIES:
                if c.lower() in row_t[index_of_date+1]:
                    first_test_pass = True
                    break
            if first_test_pass:

                try:
                    next_row = data_list[index + 1]
                except IndexError:
                    continue

                date_data = next_row[index_of_date]
                #currency_data = next_row[index_of_date+1]
                currency_data = [d for d in next_row if d.strip()]
                if currency_data:
                    try:
                        currency_data = currency_data[1] #cause 0 is date
                    except IndexError:
                        currency_data = []

                try:
                    datetime_obj = datetime.datetime.strptime(date_data, '%Y-%m-%d')
                except:
                    try:
                        datetime_obj = datetime.datetime.strptime(date_data, '%Y-%m-%d %H:%M')
                    except:
                        try:
                            datetime_obj = datetime.datetime.strptime(date_data, '%Y-%m-%d %H:%M:%S')
                        except:
                            continue
                try:
                    float(currency_data)
                    found_header = True
                except ValueError:
                    try:
                        int(currency_data)
                        found_header = True
                    except ValueError:
                        continue
        
        if found_header:
            extracted_rows.append(row)

    updated_rows = []
    for row in extracted_rows:
        tmp_row = []
        for index, r in enumerate(row):
            if index < index_of_date:
                pass
            elif (index == index_of_date) and index != 0:
                tmp_row.append(r.split(' ')[0].strip())
            else:
                tmp_row.append(r)
        updated_rows.append(tmp_row)

    if not updated_rows:
        print('FX rates file is not valid! no data found!')
        NOT_VAILD_FX_RATES = True
        return
        sys.exit()

    #update lower case date to data, no matter what
    header_data = updated_rows[0]
    #header_data[index_of_date] = 'date' #won't work when data is after some column empty in left side.
    header_data[0] = 'date'

    EXCHANGE_RATES_CSV = pd.DataFrame(updated_rows[1:], columns=header_data)
    EXCHANGE_RATES_CSV_HEADER = header_data

    EXCHANGE_RATES_CSV['date'] = EXCHANGE_RATES_CSV['date'].apply(remove_missing_time)
    
    tmp_row = EXCHANGE_RATES_CSV_HEADER[1:]
    
    base2 = None
    base1 = get_base_qc(tmp_row[0])
    try:
        base2 = get_base_qc(tmp_row[1])
    except IndexError:
        BASE_QC = base1

    if not base2:
        BASE_QC = base1
    elif base1 == base2:
        BASE_QC = base1

    #update USD currency pairs
    #ref101
    for curreny_string in EXCHANGE_RATES_CSV_HEADER:
        pair = get_first_currency('USD', curreny_string)
        if pair and len(pair) == 2:
            USD_PAIRS_FOR_CSV_RATES.append(pair)
            USD_AVILABLE_FOR_CURRENCIES.append(pair[1][0])
    
    print('[+] CSV Exchange rates loaded successfully!')

def match_col_from_header(currency, qc):
    for col in EXCHANGE_RATES_CSV_HEADER:
        pattern = rf'{currency}.*{qc}'
        match = re.search(pattern, col)
        if match:
            return col
    else:
        return None

def get_exchange_rates_from_csv(currency, date, qc):
    global EXCHANGE_RATES_CSV
    col_name = f'{currency}{qc}'
    date = date.split(' ')[0]

    matched_col = match_col_from_header(currency, qc)
    if not matched_col:
        return None

    row = EXCHANGE_RATES_CSV.loc[EXCHANGE_RATES_CSV['date'] == date]
    if not row.empty:
        value = Decimal(row[matched_col].values[0])
    else:
        value = None
    return value
    
def find_word_index(string, word):
    return string.index(word)

def get_base_qc(check_string):
    base_qc = None
    p_c = []
    for c in CURRENCIES:
        if c in check_string:
            p_c.append((c, find_word_index(check_string, c)))
    if len(p_c) != 2:
        return base_qc
    if p_c[0][1] > p_c[1][1]:
        base_qc = p_c[0][0]
    else:
        base_qc = p_c[1][0]
    return base_qc

def get_first_currency(cur, mixed_string):
    #this will find matching currency if exists
    #ex: for CAD it will look for CAD as first in mixed_string
    p_c = []
    for c in CURRENCIES:
        if c in mixed_string:
            p_c.append((c, find_word_index(mixed_string, c)))
    if not p_c:
        return
    if p_c[0][0] == cur:
        return p_c

################################################################ APP1 Code Starts

def check_for_all_negative_rows(rows):
    global ASSETS_TRACKER

    up_rows = []

    for index, row in enumerate(rows, start=1):
        previous_row = rows[index - 1]
        check_v = row.get(COLUMN_NAME_TO_CHECK)
        if not check_v:
            continue
        
        try:
            val =  int(check_v)
        except ValueError:
            val = Decimal(check_v)
        except ValueError:
            continue

        #update asset
        asset = row[ASSET_NAME_TO_CHECK]
        account = row['Account'].lower().replace(" ", "") #!# Changed by me
        if not ASSETS_TRACKER.get(account):
            ASSETS_TRACKER[account] = {}
        if not ASSETS_TRACKER[account].get(asset):
            ASSETS_TRACKER[account][asset] = {
                'first_negative': False,
                'prev': None,
                'addition_positives': []
            }

        if (val < 0) and not ASSETS_TRACKER[account][asset]['first_negative']:
            #negative
            
            copied_row = copy(row)
            copied_row[BUY_SELL_COL_NAME] = 'buy'
            copied_row[COLUMN_NAME_TO_CHECK] = ''
            if ENABLE_LOG:
                copied_row['log'] = f'margin loan'

            up_rows.append(copied_row)
            ASSETS_TRACKER[account][asset]['cp_row'] = copy(copied_row)

            if ENABLE_LOG:
                row['log'] = f'Sale Short'
            up_rows.append(row)

            ASSETS_TRACKER[account][asset]['first_negative'] = True

            """ new_val = None
            try:
                new_val = int(row[PREV_COL_NAME_TO_CHECK])
            except ValueError:
                new_val = Decimal(row[PREV_COL_NAME_TO_CHECK])
            except ValueError:
                pass """

            ASSETS_TRACKER[account][asset]['prev'] = val
        
        elif (val < 0) and ASSETS_TRACKER[account][asset]['first_negative']:

            if ASSETS_TRACKER[account][asset]['prev'] and val <= ASSETS_TRACKER[account][asset]['prev']:
                copied_row = copy(row)
                copied_row[BUY_SELL_COL_NAME] = 'buy'
                copied_row[COLUMN_NAME_TO_CHECK] = ''
                if ENABLE_LOG:
                    copied_row['log'] = f'margin loan'

                up_rows.append(copied_row)

                if ENABLE_LOG:
                    row['log'] = f'Sale Short'
                up_rows.append(row)

                ASSETS_TRACKER[account][asset]['prev'] = val
                tmp_val = copy(copied_row)
                tmp_val[BUY_SELL_COL_NAME] = 'sell'

                if ENABLE_LOG:
                    tmp_val['log'] = f'loan repayment'
                #date logic
                #tmp_val[DATE_ROW_NAME] = previous_row[DATE_ROW_NAME]
                
                ASSETS_TRACKER[account][asset]['addition_positives'].append(tmp_val)
            else:
                up_rows.append(row)
            
        elif (val >= 0) and ASSETS_TRACKER[account][asset]['first_negative']:
            #positive
            cp_row = ASSETS_TRACKER[account][asset]['cp_row']
            cp_row[BUY_SELL_COL_NAME] = 'sell'

            if ENABLE_LOG:
                cp_row['log'] = f'loan repayment'

            #date logic
            #cp_row[DATE_ROW_NAME] = previous_row[DATE_ROW_NAME]

            up_rows.append(row)
            up_rows.append(cp_row)

            if ASSETS_TRACKER[account][asset]['addition_positives']:
                #print(index+2, ASSETS_TRACKER[account][asset]['addition_positives'])
                up_rows.extend(ASSETS_TRACKER[account][asset]['addition_positives'])

            ASSETS_TRACKER[account][asset]['first_negative'] = False
            ASSETS_TRACKER[account][asset]['cp_row'] = None
            ASSETS_TRACKER[account][asset]['addition_positives'] = []

        else:
            up_rows.append(row)
        
    return up_rows

def write_batches_to_csv(data, batch_size, output_dir):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    num_batches = (len(data) + batch_size - 1) // batch_size
    
    for i in range(num_batches):
        batch = data[i * batch_size: (i + 1) * batch_size]
        filename = os.path.join(output_dir, f'{output_dir}_batch_{i + 1}.csv')
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = data[0].keys()
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(batch)

        #modify the date.
        df = pd.read_csv(filename)
        for index, row in df.iterrows():
            if row['log'] == 'loan repayment':
                if index > 0:
                    df.at[index, 'Date'] = df.at[index - 1, 'Date']
        df.to_csv(filename, index=False)


def check_csv():

    print('[+] CHECK ON {} Started.'.format(CSV_PATH))

    current_rows = []

    with open(CSV_PATH, 'r', encoding='utf-8') as csv_f:
        csv_reader = csv.DictReader(csv_f)
        for index, row in enumerate(csv_reader):
            if ENABLE_LOG:
                row['log'] = ''
            current_rows.append(row)

    up_rows = check_for_all_negative_rows(current_rows)

    if MAKE_NEW_OUTPUT_FILE:
        op_path = OP_CSV_PATH
    else:
        op_path = CSV_PATH

    new_rows = []
    for row in up_rows:
        tmp_d = {}
        for k, v in row.items():
            if '\ufeff' in k:
                k = k.replace('\ufeff', '')
            tmp_d[k] = v
        new_rows.append(tmp_d)

    if not SPLIT_FILE:
        with open(op_path, 'w', newline='', encoding='utf-8') as csv_f:
            field_names = list(new_rows[0].keys())
            csv_writer = csv.DictWriter(csv_f, fieldnames=field_names)
            csv_writer.writeheader()
            csv_writer.writerows(new_rows)
    else:
        write_batches_to_csv(new_rows, SPLIT_ROW_COUNT - 1, OP_CSV_PATH.replace('.csv', ''))

    print('[+] CHECK ON {} Complete.'.format(CSV_PATH))

################################################################ APP1 Code Ends

################################################################ APP2 Code Starts

def get_asset_state2(account, asset):
    if account not in assets_state2:
        assets_state2[account] = {}

    if asset not in assets_state2[account]:
        assets_state2[account][asset] = {
           'ProceedsOfDisposition':Decimal('0'),
            'AdjustedCostBasis':Decimal('0') ,
            'PositionCloseCheck':"none",
            'previousPositionQuantity':Decimal('0'),
            'previousAveragePrice':Decimal('0'),
            'netPNL':Decimal('0'),
            'closeQuantity':Decimal('0'),
            'currentPositionQuantity':Decimal('0'),
            'averagePrice':Decimal('0')
            
           
            
            
    }
        
    return assets_state2[account][asset]


def PoDMinusACB(asset, row, account, price, amount):
   
    global line_counter2
    
    state = get_asset_state2(account, asset)
    original =  get_asset_state(account.lower().replace(" ", ""), asset)
        
  
    podminusacb_output = []
    pod_output = []
    acb_output = []
    disposition_fee = []
    acquistion_fee = []
    capital_gain = []
    income_gain = []
    longproceeds = []
    longacb = []
    
    
    

    state['currentPositionQuantity'] = row['Current Position Quantity']
    state['averagePrice'] = row['Average entry price']
    state['PositionCloseCheck'] = row['Position Close Check']
    state['closeQuantity'] = row['Closed Quantity']
  
    quantity = row['quantity']
    fee = row['Fee']
    side = row['action']
    
    #amount = row['amount']
    #price = row['price']
   

    if(side=="buy" or side=="deposit"):
        acquistion_fee.append(log_print2(f"{fee}"))
    elif(side=="sell" or side == "withdraw"):
        disposition_fee.append(log_print2(f"{fee}"))


    #print(f"previousPositionQuantity: {previousPositionQuantity:.5f}")
    #print(f"currentPositionQuantity: {currentPositionQuantity:.5f}")
  
    
    #If previous is long, and current position is less than last then it means close long || or || if previous is short, and current position is more than previous position then it means close short 
    #if((state['previousPositionQuantity']>0 and state['currentPositionQuantity']<state['previousPositionQuantity']) or (state['previousPositionQuantity']<0 and state['currentPositionQuantity']>state['previousPositionQuantity'])): 
    #if(original['PositionCloseCheck'] == "yes"): ##Potentially can comment out
        #state['PositionCloseCheck'] = "yes"
    #else: 
        #state['PositionCloseCheck'] = "no" #No include buying from the first trade and no transactions. ##Potentially can comment out
    if(state['PositionCloseCheck']=="yes" and state['previousPositionQuantity']>0): #If Close Long  ##Could be wrong
    
        
           
        if(state['PositionCloseCheck']=="yes" and state['previousPositionQuantity']>0 and state['currentPositionQuantity']<0): #This means close long + open short
            state['ProceedsOfDisposition'] = state['closeQuantity']*price 
            state['AdjustedCostBasis'] = state['closeQuantity']*state['previousAveragePrice']
            state['netPNL'] = state['ProceedsOfDisposition'] - state['AdjustedCostBasis']
            if side not in ("withdraw", "deposit", "realized_pnl", "realized_lost", "loan", "loan repayment"):
                podminusacb_output.append(log_print2(f"{state['closeQuantity']:.5f}*{price:.5f} - {state['closeQuantity']:.5f}*{state['previousAveragePrice']:.5f} = {state['netPNL']:.5f} From if close long + open short"))
                pod_output.append(log_print2(f"{state['ProceedsOfDisposition']:.5f}"))
                acb_output.append(log_print2(f"{state['AdjustedCostBasis']:.5f}"))
                capital_gain.append(log_print2(f"{state['netPNL']:.5f}"))
                longproceeds.append(log_print2(f"{state['ProceedsOfDisposition']:.5f}"))
                longacb.append(log_print2(f"{state['AdjustedCostBasis']:.5f}"))
            elif side in ("withdraw", "deposit", "realized_pnl", "realized_lost", "loan", "loan repayment"):
                 state['netPNL'] = 0
                 
         
                
            
        else:
            if(state['averagePrice'] != 0):
                state['AdjustedCostBasis'] = state['closeQuantity']*state['averagePrice']
                state['ProceedsOfDisposition'] = price*state['closeQuantity']
                state['netPNL'] = state['ProceedsOfDisposition'] - state['AdjustedCostBasis']
                #print(f"{quantity:.5f}*{price:.5f}-{quantity:.5f}*{averagePrice:.5f} = {netPNL:.5f} From if close long only") #If Close long 
                if side not in ("withdraw", "deposit", "realized_pnl", "realized_lost", "loan", "loan repayment"):
                    podminusacb_output.append(log_print2(f"{state['closeQuantity']:.5f}*{price:.5f}-{state['closeQuantity']:.5f}*{state['averagePrice']:.5f} = {state['netPNL']:.5f} If Close long"))
                    pod_output.append(log_print2(f"{state['ProceedsOfDisposition']:.5f}"))
                    acb_output.append(log_print2(f"{state['AdjustedCostBasis']:.5f}"))
                    capital_gain.append(log_print2(f"{state['netPNL']:.5f}"))
                    longproceeds.append(log_print2(f"{state['ProceedsOfDisposition']:.5f}"))
                    longacb.append(log_print2(f"{state['AdjustedCostBasis']:.5f}"))
                elif side in ("withdraw", "deposit", "realized_pnl", "realized_lost", "loan", "loan repayment"):
                    state['netPNL'] = 0
             
            else: 
                state['AdjustedCostBasis'] = state['closeQuantity']*state['previousAveragePrice']
                state['ProceedsOfDisposition'] = price*state['closeQuantity']
                state['netPNL'] = state['ProceedsOfDisposition'] - state['AdjustedCostBasis']
                #netPNL =  AdjustedCostBasis - ProceedsOfDisposition
                if side not in ("withdraw", "deposit", "realized_pnl", "realized_lost", "loan", "loan repayment"):
                    podminusacb_output.append(log_print2(f"{state['closeQuantity']:.5f}*{price:.5f}-{state['closeQuantity']:.5f}*{state['previousAveragePrice']:.5f} = {state['netPNL']:.5f} From if close long only")) #If Close long 
                    pod_output.append(log_print2(f"{state['ProceedsOfDisposition']:.5f}"))
                    acb_output.append(log_print2(f"{state['AdjustedCostBasis']:.5f}"))
                    capital_gain.append(log_print2(f"{state['netPNL']:.5f}"))
                    longproceeds.append(log_print2(f"{state['ProceedsOfDisposition']:.5f}"))
                    longacb.append(log_print2(f"{state['AdjustedCostBasis']:.5f}"))
                elif side in ("withdraw", "deposit", "realized_pnl", "realized_lost", "loan", "loan repayment"):
                    state['netPNL'] = 0
           
        
    
  
    
    
       
    if(state['PositionCloseCheck']=="yes" and state['previousPositionQuantity']<0):#If close short ##Could be wrong
    
        if(state['PositionCloseCheck']=="yes" and state['previousPositionQuantity']<0 and state['currentPositionQuantity']>0): #This means close short + open long 
            state['ProceedsOfDisposition'] = state['closeQuantity']*state['previousAveragePrice']
            state['AdjustedCostBasis'] = state['closeQuantity']*price
            state['netPNL'] = state['ProceedsOfDisposition'] - state['AdjustedCostBasis']
            if side not in ("withdraw", "deposit", "realized_pnl", "realized_lost", "loan", "loan repayment"):
                podminusacb_output.append(log_print2(f"{state['closeQuantity']:.5f}*{state['previousAveragePrice']:.5f} - {state['closeQuantity']:.5f}*{price:.5f} = {state['netPNL']:.5f} From if close short + open long"))
                pod_output.append(log_print2(f"{state['ProceedsOfDisposition']:.5f}"))
                acb_output.append(log_print2(f"{state['AdjustedCostBasis']:.5f}"))
                income_gain.append(log_print2(f"{state['netPNL']:.5f}"))
            elif side in ("withdraw", "deposit", "realized_pnl", "realized_lost", "loan", "loan repayment"):
                state['netPNL'] = 0
         
            
            
        else:
            if(state['averagePrice'] != 0):
                #if Log:
                    #sys.__stdout__.write(f"Price after update: {state['averagePrice']}\n") 
                state['ProceedsOfDisposition'] = state['closeQuantity']*state['averagePrice'] #Treating AdjustedCostBasis as selling for shorts
                state['AdjustedCostBasis'] = price*state['closeQuantity']
                state['netPNL'] = state['ProceedsOfDisposition'] - state['AdjustedCostBasis'] 
                
                if side not in ("withdraw", "deposit", "realized_pnl", "realized_lost", "loan", "loan repayment"):
                    podminusacb_output.append(log_print2(f"{state['closeQuantity']:.5f}*{price:.5f}-{state['closeQuantity']:.5f}*{state['averagePrice']:.5f} = {state['netPNL']:.5f} from if close short only 1"))
                    pod_output.append(log_print2(f"{state['ProceedsOfDisposition']:.5f}"))
                    acb_output.append(log_print2(f"{state['AdjustedCostBasis']:.5f}"))
                    income_gain.append(log_print2(f"{state['netPNL']:.5f}"))

                elif side in ("withdraw", "deposit", "realized_pnl", "realized_lost", "loan", "loan repayment"):
                    state['netPNL'] = 0
            
                #If Close Short 
            else: 
                state['ProceedsOfDisposition'] = state['closeQuantity']*state['previousAveragePrice'] #Treating AdjustedCostBasis as selling for shorts
                state['AdjustedCostBasis'] = price*state['closeQuantity']
                #netPNL = ProceedsOfDisposition - AdjustedCostBasis
                state['netPNL'] =  state['ProceedsOfDisposition'] - state['AdjustedCostBasis']
                #print(f"{quantity:.5f}*{price:.5f}-{quantity:.5f}*{previousAveragePrice:.5f} = {netPNL:.5f} from if close short only")
                if side not in ("withdraw", "deposit", "realized_pnl", "realized_lost", "loan", "loan repayment"):
                    podminusacb_output.append(log_print2(f"{state['closeQuantity']:.5f}*{state['previousAveragePrice']:.5f}-{state['closeQuantity']:.5f}*{price:.5f} = {state['netPNL']:.5f} from if close short only 2"))
                    pod_output.append(log_print2(f"{state['ProceedsOfDisposition']:.5f}"))
                    acb_output.append(log_print2(f"{state['AdjustedCostBasis']:.5f}"))
                    income_gain.append(log_print2(f"{state['netPNL']:.5f}"))

                elif side in ("withdraw", "deposit", "realized_pnl", "realized_lost", "loan", "loan repayment"):
                    state['netPNL'] = 0
             

    if(state['PositionCloseCheck']=="no"):
        state['netPNL'] = 0

    #print(f"{ProceedsOfDisposition:.5f} - {AdjustedCostBasis:.5f} = {netPNL:.5f}")
    if(side == "withdraw"):
        if(state['currentPositionQuantity'] == Decimal('0')):
            state['AdjustedCostBasis'] = -abs(state['previousAveragePrice']*state['previousPositionQuantity'])
            acb_output.append(log_print2(f"{state['AdjustedCostBasis']:.5f}"))
        else:
            state['AdjustedCostBasis'] = -abs(state['averagePrice']*quantity)
            acb_output.append(log_print2(f"{state['AdjustedCostBasis']:.5f}"))

    elif(side == "deposit"):
        state['AdjustedCostBasis'] = abs(state['averagePrice']*quantity)
        acb_output.append(log_print2(f"{state['AdjustedCostBasis']:.5f}"))

    

    
    
    if(side=="realized_pnl"):
        income_gain.append(log_print2(f"{Decimal(amount)}"),) 
    elif(side=="realized_lost"):
        income_gain.append(log_print2(f"{Decimal(-amount)}"),) 

    #sys.__stdout__.write(f"PodMinusACB: {line_counter}: {closeQuantity}\n")

   
    #sys.__stdout__.write(f"Previous Average Price after update: {state['previousAveragePrice']}\n")
    state['previousPositionQuantity'] = state['currentPositionQuantity']
    state['previousAveragePrice'] = state['averagePrice']
    state['previousSide'] = side



    # Reset stdout to default to print to the command line
    

    # Print the value you want to show in the command line
    
        #line_counter2 += 1 
        #if 8040 <= line_counter2 <= 8060:
    


    # If you need to continue capturing output, set stdout back to the StringIO object
  

    assets_state2[account, asset] = state
    assets_state[account, asset] = original

    return state['netPNL'], podminusacb_output, pod_output, acb_output, acquistion_fee, disposition_fee, income_gain, capital_gain, longproceeds, longacb
    

def log_print2(message, tag=None):
    # This function just returns the message as is.
    # The tag is used by the calling code to decide which list to append the message to.
    return message

""" def format_decimal(value, max_decimals=7):
    #Format Decimal to string with up to max_decimals places, trimming trailing zeros.
    # Check if the value is None and handle it accordingly
    if value is None:
        return ''  # or '0' or any other placeholder you prefer
    # Convert Decimal to string, rounding to max_decimals
    formatted = f"{value:.{max_decimals}f}"
    # Convert to Decimal and back to string to remove trailing zeros, keeping the Decimal precision
    return str(Decimal(formatted)) """
    
# Format Decimal columns for output
def format_decimal(value, prec):
    return format(value, f'.{prec}f')

def delete_file(i_path):
    print(f'[-] Deleting File : {i_path}')
    os.remove(i_path)

def update_user_input2(row_i, df, state, podminusacb_output, pod_output, acb_output, acquistion_fee, disposition_fee, income_gain, capital_gain, longproceeds, longacb):

    def check_input(col_name):
        return (col_name in df.columns) and not pd.isna(df.iloc[row_i][col_name]) and not df.iloc[row_i][col_name] == ''
    
    #CHECK USER INPUT DATA
    """ if check_input('Average entry price'):
        d = int(df.iloc[row_i]['Average entry price'])
        d = Decimal(d)
        state['averagePrice'] = d
        state['previousAveragePrice'] = d

    if check_input('Current Position Quantity'):
        d = int(df.iloc[row_i]['Current Position Quantity'])
        d = Decimal(d)
        state['currentPositionQuantity'] = d
        state['previousPositionQuantity'] = d """

    if check_input('Console Log: Proceeds - Cost'):
        podminusacb_output = []
        podminusacb_output.append(format(Decimal(df.iloc[row_i]['Console Log: Proceeds - Cost']), '.5f'))
    
    if check_input('Proceeds Of Disposition'):
        pod_output = []
        pod_output.append(format(Decimal(df.iloc[row_i]['Proceeds Of Disposition']), '.5f'))

    if check_input('Adjusted Cost Basis'):
        acb_output = []
        acb_output.append(format(Decimal(df.iloc[row_i]['Adjusted Cost Basis']), '.5f'))

    if check_input('Acquistion Fees'):
        acquistion_fee = []
        acquistion_fee.append(format(Decimal(df.iloc[row_i]['Acquistion Fees']), '.5f'))

    if check_input('Disposition Fees'):
        disposition_fee = []
        disposition_fee.append(format(Decimal(df.iloc[row_i]['Disposition Fees']), '.5f'))

    if check_input('Income Gain (Shorts)'):
        income_gain = []
        income_gain.append(format(Decimal(df.iloc[row_i]['Income Gain (Shorts)']), '.5f'))

    if check_input('Capital Gain (Longs)'):
        capital_gain = []
        capital_gain.append(format(Decimal(df.iloc[row_i]['Capital Gain (Longs)']), '.5f'))

    if check_input('None Liability Goods Sold / POD (Longs)'):
        longproceeds = []
        longproceeds.append(format(Decimal(df.iloc[row_i]['None Liability Goods Sold / POD (Longs)']), '.5f'))

    if check_input('Cost of Good Sold / ACB (Longs)'):
        longacb = []
        longacb.append(format(Decimal(df.iloc[row_i]['Cost of Good Sold / ACB (Longs)']), '.5f'))

    return state, podminusacb_output, pod_output, acb_output, acquistion_fee, disposition_fee, income_gain, capital_gain, longproceeds, longacb

def calculate_pod():

    df = pd.read_csv(INPUT_CSV_PATH_APP2)

    # Convert columns to Decimal
    df['Current Position Quantity'] = df['Current Position Quantity'].apply(Decimal)
    df['price'] = df['price'].apply(Decimal)
    df['Average entry price'] = df['Average entry price'].apply(Decimal)
    df['quantity'] = df['quantity'].apply(Decimal)
    df['Closed Quantity'] = df['Closed Quantity'].apply(Decimal)

    # New column for console output
    try:
        df.insert(13, 'PoD-ACB', '')
    except ValueError:
        pass
    df['Proceeds Of Disposition'] = ''
    df['Adjusted Cost Basis'] = ''
    df['Acquistion Fees'] = ''
    df['Disposition Fees'] = ''
    if Log:
        df['Console Log: Proceeds - Cost'] = ''
    df['Income Gain (Shorts)'] = ''
    df['Capital Gain (Longs)'] = ''

    df['None Liability Goods Sold / POD (Longs)'] = ''
    df['Cost of Good Sold / ACB (Longs)'] = ''
    df['Quote Currency Rates (QC/USD)'] = ''
    df['Default Currency Rates (DC/USD)'] = ''


    # Redirect stdout to capture print statements
    #old_stdout = sys.stdout

    #get default currency rates
    #default_qc_rates = Decimal(get_exchange_rate(Default_Currency))

    # Apply the calculation to each row and create a new column 'Net PNL'
    for index, row in df.iterrows():
        asset = row['asset']
        account = str(row['Account']).lower().replace(' ','')
        state = get_asset_state2(account, asset)

        #NEW CODE AFTER V4
        side = row['action']
        memo1 = row['Memo1']
        memo2 = row['Memo2']
        memo3 = row['Memo3']

        price = row['price']
        amount = row['amount']

        date = row['Date']

        #adjust rates            
        if AdjustRates:
            if row.get('Quote Currency') and str(row['Quote Currency']) != 'nan':
                tmp_qc = row['Quote Currency']
                tmp_qc_rates = Decimal(get_exchange_rate(tmp_qc))
                price = Decimal(price) * tmp_qc_rates
                amount = Decimal(amount) * tmp_qc_rates

        #sys.stdout = io.StringIO()  # Redirect stdout to capture prints

        #trigger user input

        pnl, podminusacb_output, pod_output, acb_output, acquistion_fee, disposition_fee, income_gain, capital_gain, longproceeds, longacb = PoDMinusACB(asset, row, account, price, amount)
        #V0
        state, podminusacb_output, pod_output, acb_output, acquistion_fee, disposition_fee, income_gain, capital_gain, longproceeds, longacb = update_user_input2(index, DF_COPY, state, podminusacb_output, pod_output, acb_output, acquistion_fee, disposition_fee, income_gain, capital_gain, longproceeds, longacb)

        df.at[index, 'PoD-ACB'] = pnl

        #NEW CODE AFTER V4
        if (side == 'deposit' or side == 'withdraw') and any('not a transfer'.lower().replace(' ', '') in str(memo).lower().replace(' ', '') for memo in [memo1, memo2, memo3]):
            state['AdjustedCostBasis'] = 0
            acb_output = []
            acb_output.append(log_print2(f"{state['AdjustedCostBasis']:.5f}"))


        if TrackRealizedPNL:
            pnl = abs(row['Realized PNL'])
            if (side == 'realized_pnl'):
                pod_output = []
                income_gain = []
                pod_output.append(log_print2(f"{pnl:.5f}"))
                income_gain.append(log_print2(f"{pnl:.5f}"))
                state['ProceedsOfDisposition'] = pnl
                
            elif(side == 'realized_lost'):
                acb_output = []
                longacb = []
                acb_output.append(log_print2(f"{pnl:.5f}"))
                longacb.append(log_print2(f"{pnl:.5f}"))
                state['AdjustedCostBasis'] = pnl
            
            if (side == 'realized_pnl' or side == 'realized_lost'):
                pod_data = "".join(pod_output) if pod_output else 0
                acb_data = "".join(acb_output) if acb_output else 0
                pod_data_float = Decimal(pod_data)
                acb_data_float = Decimal(acb_data)
                df.at[index, 'PoD-ACB'] = pod_data_float - acb_data_float

        #adjust rates
        if AdjustRates:
            if row.get('Quote Currency') and str(row['Quote Currency']) != 'nan':
                tmp_qc = row['Quote Currency']
                tmp_qc_rates = Decimal(get_exchange_rate(tmp_qc))
                avg_entryprice = Decimal(row['Average entry price']) / tmp_qc_rates
                df.at[index, 'Average entry price'] = avg_entryprice
        
        
        # Retrieve the output and revert stdout
        #output = sys.stdout.getvalue()
        #sys.stdout = old_stdout  # Reset stdout to original
        
        # Add the captured output to the DataFrame
        if Log:
            #df.at[index, 'Console Log: Proceeds - Cost'] = output.strip()

            df.at[index, 'Console Log: Proceeds - Cost'] = "\n".join(podminusacb_output) if podminusacb_output else ""

        
        # The special output collected within CalculatePNL is added to 'Special Output'
        # Joining the list into a single string separated by newlines
        df.at[index, 'Proceeds Of Disposition'] = "\n".join(pod_output) if pod_output else ""
        
        df.at[index, 'Adjusted Cost Basis'] = "\n".join(acb_output) if acb_output else ""

        df.at[index, 'Acquistion Fees'] = "\n".join(acquistion_fee) if acquistion_fee else ""
        
        df.at[index, 'Disposition Fees'] = "\n".join(disposition_fee) if disposition_fee else ""

        df.at[index, 'Income Gain (Shorts)'] = "\n".join(income_gain) if income_gain else ""
        
        df.at[index, 'Capital Gain (Longs)'] = "\n".join(capital_gain) if capital_gain else ""
        
        df.at[index, 'None Liability Goods Sold / POD (Longs)'] = "\n".join(longproceeds) if longproceeds else ""
        
        df.at[index, 'Cost of Good Sold / ACB (Longs)'] = "\n".join(longacb) if longacb else ""

        #adjust rates 2
        if AdjustRates2 or AdjustRatesFromCSV:
            #print(index+2)
            #print('Default_Currency: ', Default_Currency)
            if row.get('Fee') and str(row['Fee']) != 'nan':
                tmp_qc_rates = Decimal(get_exchange_rate(Default_Currency, date))
                df.at[index, 'Fee'] = Decimal(row.get('Fee')) / tmp_qc_rates

            qc = get_guote_currency(row, row['asset'], app2=True)
            #print(qc)
            qc_rates = Decimal(get_exchange_rate(qc, date))
            t_rel_pnl = check_nan_make_0(df.at[index, 'Realized PNL'])
            t_pod_acb = check_nan_make_0(df.at[index, 'PoD-ACB'])
            t_cost_basis = check_nan_make_0(df.at[index, 'Adjusted Cost Basis'])
            t_pod = check_nan_make_0(df.at[index, 'Proceeds Of Disposition'])

            default_qc_rates = Decimal(get_exchange_rate(Default_Currency, date))

            #print(t_rel_pnl)
            #print(qc_rates)
            #print(default_qc_rates)

            #no quote currency is specified
            #print(t_rel_pnl)
            if qc_rates == 0:
                new_t_rel_pnl = Decimal(t_rel_pnl)
                new_t_pod_acb = Decimal(t_pod_acb)
                new_t_cost_basis = Decimal(t_cost_basis)
                new_t_pod = Decimal(t_pod)
            else:
                new_t_rel_pnl = (Decimal(t_rel_pnl) * qc_rates) / default_qc_rates
                new_t_pod_acb = (Decimal(t_pod_acb) * qc_rates) / default_qc_rates
                new_t_cost_basis = (Decimal(t_cost_basis) * qc_rates) / default_qc_rates
                new_t_pod = (Decimal(t_pod) * qc_rates) / default_qc_rates
            #print(new_t_rel_pnl)

            #print(t_rel_pnl, qc_rates, default_qc_rates, new_t_rel_pnl)

            df.at[index, 'Realized PNL'] = format(new_t_rel_pnl, ".5f")
            df.at[index, 'PoD-ACB'] = new_t_pod_acb
            df.at[index, 'Adjusted Cost Basis'] = format(new_t_cost_basis, ".5f")
            df.at[index, 'Proceeds Of Disposition'] = format(new_t_pod, ".5f")

            df.at[index, 'Quote Currency Rates (QC/USD)'] = f'{qc_rates:.5f}'
            df.at[index, 'Default Currency Rates (DC/USD)'] = f'{default_qc_rates:.5f}'

            #print('\n\n')


    for col in ['Current Position Quantity', 'price', 'Average entry price', 'quantity', 'PoD-ACB']:
        df[col] = df[col].apply(lambda x: format_decimal(x, 7))

    df['Fee'] = df['Fee'].apply(lambda x: format_decimal(x, 10) if pd.notnull(x) else x)

    # Save the modified DataFrame to a new CSV file
    df.to_csv(OUTPUT_CSV_PATH_APP2, index=False)

################################################################ APP2 Code Ends

################################################################ MAIN APP Code Starts

def check_data_in_currencies(val):
    if val != val:
        return False
    check_list = [k.lower() for k in CURRENCIES]
    return val.lower() in check_list

def get_exchange_rate(currency, date=None):
    global AdjustRatesFromCSV, BASE_QC, EXCHANGE_RATES_CSV

    #used when quote currency is blank and asset is in dicitonary, | for AdjustRates2 or AdjustRatesFromCSV is True
    if str(currency) == 'nan':
        return 0

    if not date or not (AdjustRatesFromCSV):
        return EXCHANGE_RATES.get(currency)
    
    if NOT_VAILD_FX_RATES:
        return EXCHANGE_RATES.get(currency)

    date = date.strip().split(' ')[0].replace('/', '-')

    tmp0 = get_exchange_rates_from_csv(currency, date, 'USD')
    if tmp0:
        return tmp0
    
    #do the alog2 here when quote currency is not same for whole file | FX Rates.csv
    if not BASE_QC:
        pairs = []

        for curreny_string in EXCHANGE_RATES_CSV_HEADER:
            pair = get_first_currency(currency, curreny_string)
            if pair and len(pair) == 2:
                pairs.append(pair)

        #first find pair based on Default_currency
        pair = None
        for pair_d in pairs:
            if pair_d[1][1] == Default_Currency:
                pair = pair_d
                break
        
        #if no match found, then use first pair.

        #V0 take any randomly
        #can't take currency randomly
        """ if not pair:
            pair = pairs[0] """
        #V1 find if USD and NEW_BASE_QC is avilable.
        #ref101
        for pair_d in pairs:
            pair_c = pair_d[1][0]
            if pair_c in USD_AVILABLE_FOR_CURRENCIES:
                pair = pair_d

        #Now if still not find anything take first one.
        if not pair:
            pair = pairs[0]

        if not pair:
            return EXCHANGE_RATES.get(currency)
        
        #over write the base qc
        BASE_QC = pair[1][0]

    #CAD/USD case
    if BASE_QC == currency:
        tmp1 = get_exchange_rates_from_csv('USD', date, BASE_QC)
        if tmp1:
            #print(f'GOT: USD/{BASE_QC}', tmp1, f'Return 1/USD/{BASE_QC}', 1/tmp1)
            return 1 / tmp1
        else:
            #default
            #print(f'GOT:  USD/{BASE_QC} | from dictionary', EXCHANGE_RATES.get(currency))
            return EXCHANGE_RATES.get(currency)

    #print(f'[+] Finding {currency}/{BASE_QC}')
    csv_data = get_exchange_rates_from_csv(currency, date, BASE_QC)
    if csv_data and BASE_QC == 'USD':
        #print(f'{currency}/USD', csv_data)
        return csv_data
    """ elif csv_data and currency == 'USD':
        return 1/csv_data """ #this is correct logic, but it's breaking one thing (not sure which one)! but in this case Quote currency and default currency balance will match without this.
    
    #print(f'[+] Finding USD/{BASE_QC}')
    csv_data2 = get_exchange_rates_from_csv('USD', date, BASE_QC)
    #csv_data2 = get_exchange_rates_from_csv(BASE_QC, date, 'USD') #wrong

    if csv_data and csv_data2:
        #print(f'{currency}/{BASE_QC}', csv_data)
        #print(f'USD/{BASE_QC}', csv_data)
        return csv_data / csv_data2 #THIS IS WRONG DATA V0
        #return csv_data * (1 / csv_data2)
    else:
        #default
        #print(f'USD/{BASE_QC} | from dictionary', EXCHANGE_RATES.get(currency))
        return EXCHANGE_RATES.get(currency)

def get_asset_state(account, asset):
    # Initialize state for new assets with Decimal values
  

    if account not in assets_state:
        assets_state[account] = {}

    if asset not in assets_state[account]:
        assets_state[account][asset] = {
            'ProfitAndLost': Decimal('0'),            # total P/L, fees already removed
            'currentPositionQuantity': Decimal('0'), 
            'currentPositionSize': Decimal('0'), 
            'averagePrice': Decimal('0'), 
            'previous_Side': "none", 
            'Realized_PNL': Decimal('0'),  
            'pnl': Decimal('0'), 
            'previousPositionQuantity': Decimal('0'), 
            'direction': "",
            'quantityForPositionSize': Decimal('0'), 
            'PositionCloseCheck': "none",
            'TotalCostBasis': Decimal('0'), 
            'previousTotalCostBasis': Decimal('0'), 
            'previousAveragePrice': Decimal('0'), 
            'signChange': "false",
            'currentPositionLiability': Decimal('0'), 
            'currentFiatBalance': Decimal('0'), 
            'effective_fee': Decimal('0'), 
            'previousFiatBalance': Decimal('0'),
            'Date': '',
            'Fee': Decimal('0')
    }
        
   

    return assets_state[account][asset]


def CalculatePNL(asset, side, quantity, amount, price, fee, feeCurrency, account, date):
    global averagePriceFromOtherAccount, line_counter, PositionQuantityFromOtherAccount, PreviousPositionQuantityFromOtherAccount, TotalCostBasisTransferedFromOtherAccount, closeQuantity, stablecoins 
    state = get_asset_state(account, asset)
    fee_output = []  
    averageprice_output = []
    normal_output = []
    costbasis_output = []
    FiatBalance = []
    CurrentLiability = []
    test = []
    closeQuantityOutput = []
    PositionCloseCheckOutput = []
    line_counter+=1
    closeQuantity = 0 
    

    state['Date'] = date

        

    if side == "buy" or side == "deposit" or side == "realized_pnl" or side == "loan":
        quantity = quantity
    elif side == "sell" or side == "withdraw" or side == "realized_lost" or side == "loan repayment":
        quantity = -quantity


   
        

    if(feeCurrency == asset):
      
        state['Fee'] = Decimal(fee)*Decimal(price)
        state['effective_fee'] = -abs(Decimal(fee))

    elif check_data_in_currencies(feeCurrency):
        rate = get_exchange_rate(feeCurrency)
        state['Fee'] = fee * rate
        state['effective_fee'] = 0
    else:
        state['Fee'] = Decimal(fee)
        state['effective_fee'] = 0

    fee_output.append(log_print(f"{state['Fee']}"),)  
    
  
    
    
#Determine the current direction of position if long or short or no position 
    if state['currentPositionQuantity'] > Decimal('0'): 
        state['direction'] = "long"
    elif state['currentPositionQuantity'] < Decimal('0'): 
        state['direction'] = "short"
    else: 
        state['direction'] = "neutral"
        
    if((state['currentPositionQuantity'] > Decimal('0') and side=="sell") or (state['currentPositionQuantity'] < Decimal('0') and side == "buy")): 
        state['PositionCloseCheck'] = "yes"
    else:
        state['PositionCloseCheck'] = "no" #No include buying from the first trade and no transactions. 

    
    #CurrentLiability.append(log_print(f"{Decimal(quantity)} + {state['currentPositionQuantity']}"))
    state['currentPositionQuantity'] += Decimal(quantity)

    
    state['currentPositionQuantity'] = state['currentPositionQuantity'] + state['effective_fee']
    
    """ if(asset == "USD" or asset == "CAD"):
        state['currentPositionQuantity'] = Decimal('0') """

   


    state['currentPositionSize'] = (price*state['currentPositionQuantity']) 


    if(state['previous_Side']=="none"):
        state['TotalCostBasis'] = (state['currentPositionQuantity'] * price)
       

       
       
        if side not in ("withdraw", "deposit", "realized_pnl", "realized_lost"):
            costbasis_output.append(log_print(f"currentPositionQuantity*price = {state['currentPositionQuantity']:.5f}*{price:.5f} = {state['TotalCostBasis']:.5f}"))
        


    #If Normal Position Close 
    elif(state['PositionCloseCheck']=="yes" and not ((state['currentPositionQuantity']<Decimal('0') and state['previousPositionQuantity']>Decimal('0')) or (state['currentPositionQuantity']>Decimal('0') and state['previousPositionQuantity']<Decimal('0')) or state['currentPositionQuantity']==Decimal('0'))):
        state['TotalCostBasis'] = state['currentPositionQuantity']*state['averagePrice']
        #print(f"currentPositionQuantity*averagePrice = {currentPositionQuantity}*{averagePrice} = TotalCostBasis")
       
     
        if side not in ("withdraw", "deposit", "realized_pnl", "realized_lost"):
            costbasis_output.append(log_print(f"currentPositionQuantity*averageprice = {state['currentPositionQuantity']}*{state['averagePrice']:.5f} = {state['TotalCostBasis']:.5f}"))
        
   
    #If Fully closed
    elif(state['currentPositionQuantity']==Decimal('0')):
        state['TotalCostBasis'] = abs(price*(state['currentPositionQuantity']))
      
        if side not in ("withdraw", "deposit", "realized_pnl", "realized_lost"):
            costbasis_output.append(log_print(f"{state['currentPositionQuantity']}*price = {state['currentPositionQuantity']}*{price:.5f} = {state['TotalCostBasis']:.5f}"))

     #If flip Position
    elif((state['PositionCloseCheck']=="yes") and ((state['currentPositionQuantity']<Decimal('0') and state['previousPositionQuantity']>Decimal('0')) or (state['currentPositionQuantity']>Decimal('0') and state['previousPositionQuantity']<Decimal('0')))):
   
        state['TotalCostBasis'] = abs(price*(state['previousPositionQuantity']+quantity))
        if side not in ("withdraw", "deposit", "realized_pnl", "realized_lost"):
            costbasis_output.append(log_print(f"currentPositionQuantity*price = {state['currentPositionQuantity']}*{price}]:.5f = {state['TotalCostBasis']:.5f}"))
          
      

    elif(state['PositionCloseCheck'] == "no"):
        state['TotalCostBasis'] = abs(state['previousTotalCostBasis']) + abs(quantity*price)
        #print(f"previousTotalCostBasis + TotalCostBasis = {previousTotalCostBasis} + {TotalCostBasis} = TotalCostBasis")
     
       
        if side not in ("withdraw", "deposit", "realized_pnl", "realized_lost"):
            costbasis_output.append(log_print(f"previousTotalCostBasis + TotalCostBasis = {state['previousTotalCostBasis']:.5f} + {quantity}*{price:.5f} = {state['TotalCostBasis']:.5f}"))
           
          
       
            
    #If Position direction changed
    if(((state['previousPositionQuantity']>Decimal('0')) and (state['previousPositionQuantity']+(quantity-abs(state['effective_fee']))<Decimal('0'))) or ((state['previousPositionQuantity']<Decimal('0')) and (state['previousPositionQuantity']+(quantity-abs(state['effective_fee']))>Decimal('0')))):
        signChange = "true"
        #sys.__stdout__.write(f"{line_counter} line 165 of VS Code, Sign Changed, {state['effective_fee']}\n")
    elif(state['previousPositionQuantity']==Decimal('0')):
        state['TotalCostBasis'] = abs(price*quantity)
       
        if side not in ("withdraw", "deposit", "realized_pnl", "realized_lost"):
            costbasis_output.append(log_print(f"prices*quantity = {abs(price):.5f}*{abs(quantity):.5f}"))



    else:
        signChange = "false"
        
    
 
    if((state['currentPositionQuantity'] != Decimal('0'))):

        state['averagePrice'] = abs(state['TotalCostBasis']/state['currentPositionQuantity']) 
        #print(f"Average Price = {TotalCostBasis}/{currentPositionQuantity} = {averagePrice}") # it is calculating the vaerage price of both trades
        

        if side not in ("withdraw", "deposit", "realized_pnl", "realized_lost"):
            averageprice_output.append(log_print(f"Average Price = {state['TotalCostBasis']:.5F}/{state['currentPositionQuantity']:.5F} = {state['averagePrice']:.5F}"))
            #sys.__stdout__.write(f"{line_counter} line 180 of VS Code\n")

     




    if((state['direction'] == "long") and (state['PositionCloseCheck'] == "yes")):
        if(signChange == "true"): #Position partial take close doesn't mean change from long to short or viceversa
            state['Realized_PNL'] = (price - state['previousAveragePrice'])*abs(state['previousPositionQuantity']) #Times it by previous Position Quantity because when sign change, the whole position closed, so the pnl is from the previous position closed and current one just opened. 
        
            #print(f"{price:.5f} - {averagePrice:.5f} x {abs(previousPositionQuantity):.5f}  = {Realized_PNL:.5f} Profit")
            if side not in ("withdraw", "deposit", "realized_pnl", "realized_lost"):
                normal_output.append(log_print(f"({price:.15f} - {state['previousAveragePrice']:.15f}) x {abs(state['previousPositionQuantity']):.15f} = {state['Realized_PNL']:.15f} test1"))
                closeQuantity = abs(state['previousPositionQuantity'])
           

            
            if(state['currentPositionQuantity'] == Decimal('0')):
                state['averagePrice'] = Decimal('0')
                state['TotalCostBasis'] = Decimal('0')
                
              
                
        
            else:
                state['averagePrice'] = price #After sign change, the average price can be considered as the price of executions. 
                #sys.__stdout__.write(f"{line_counter} line 205 of VS Code\n")
             
                
               

                #TotalCostBasis = abs(currentPositionQuantity+previousPositionQuantity)*price #leftoverquantityxprice 
        else:
            state['Realized_PNL'] = (price - state['averagePrice'])*abs(quantity)
       
            #print(f"{price:.5f} - {averagePrice:.5f} x {abs(quantity):.5f}  = {Realized_PNL:.5f} Profit")
            if side not in ("withdraw", "deposit", "realized_pnl", "realized_lost"):
                normal_output.append(log_print(f"({price:.15f} - {state['averagePrice']:.15f}) x {abs(quantity):.15f} = {state['Realized_PNL']:.15f} test2"))
                closeQuantity = abs(quantity)
           
            

            if(state['currentPositionQuantity'] == Decimal('0')):
                state['averagePrice'] = Decimal('0')
                

        
    elif((state['direction'] == "short") and (state['PositionCloseCheck'] == "yes")):
        
        if(signChange == "true"): #Position partial take close doesn't mean change from long to short or viceversa
            state['Realized_PNL'] = (price - state['previousAveragePrice'])*-abs(state['previousPositionQuantity']) #Times it by previous Position Quantity because when sign change, the whole position closed, so the pnl is from the previous position closed and current one just opened.
      
            #print(f"{price:.5f} - {averagePrice:.5f} x {(-abs(previousPositionQuantity)):.5f}  = {Realized_PNL:.5f} Profit") #This one has error
            if side not in ("withdraw", "deposit", "realized_pnl", "realized_lost"):
                normal_output.append(log_print(f"({price:.15f} - {state['previousAveragePrice']:.15f}) x {(-abs(state['previousPositionQuantity'])):.15f} = {state['Realized_PNL']:.15f}test 3"))
                closeQuantity = abs(state['previousPositionQuantity'])

            


            if(state['currentPositionQuantity'] == Decimal('0')):
                state['averagePrice'] = Decimal('0')
                state['TotalCostBasis'] = Decimal('0')
              

               
                    
               
            else:
                #sys.__stdout__.write(f"{line_counter} line 241 of VS Code\n")

                state['averagePrice'] = price ##########################################################################################################
                #TotalCostBasis = abs(currentPositionQuantity+previousPositionQuantity)*price #leftoverquantityxprice
            
        else:
            state['Realized_PNL'] = (price - state['averagePrice'])*-abs(quantity)
         
            #print(f"{price:.5f} - {averagePrice:.5f} x {(-abs(quantity)):.5f}  = {Realized_PNL:.5f} Profit")
            if side not in ("withdraw", "deposit", "realized_pnl", "realized_lost"):
                normal_output.append(log_print(f"({price:.15f} - {state['averagePrice']:.15f}) x {(-abs(quantity)):.15f}  = {state['Realized_PNL']:.5f}test4"),)  
                closeQuantity = abs(quantity)

           
            
            if(state['currentPositionQuantity'] == Decimal('0')):
                state['averagePrice'] = Decimal('0')

           
    
    
    if(state['PositionCloseCheck']=="no"):
        state['Realized_PNL'] = Decimal('0')


    if(side=="buy" or side == "realized_lost"):
       state['currentFiatBalance'] += -abs(Decimal(amount))
    elif(side=="sell" or side == "realized_pnl"):
        state['currentFiatBalance'] += abs(Decimal(amount))
    elif(side=="deposit" and (asset == "USD" or asset == "CAD")):
        state['currentFiatBalance'] += abs(Decimal(quantity))
    elif(side=="withdraw" and (asset == "USD" or asset == "CAD")):
        state['currentFiatBalance'] += -abs(Decimal(quantity))
    if math.isnan(state['currentFiatBalance']):
       state['currentFiatBalance'] = state['previousFiatBalance']


    FiatBalance.append(log_print(f"{state['currentFiatBalance']}"),)   

    

    if(side=="realized_pnl"):
        state['Realized_PNL'] = abs(amount)
        normal_output.append(log_print(f"{Decimal(amount)}"),) 
        state['averagePrice'] = state['previousAveragePrice']
    elif(side=="realized_lost"):
        state['Realized_PNL'] = -abs(amount)
        normal_output.append(log_print(f"{Decimal(amount)}"),) 
        state['averagePrice'] = state['previousAveragePrice']

     


  
    if(side=="realized_pnl"):
        state['Realized_PNL'] = abs(amount)
        normal_output.append(log_print(f"{Decimal(amount)}"),) 

        if math.isnan(price):
            state['averagePrice'] = state['previousAveragePrice']

        else:
            state['averagePrice'] = price

        
    elif(side=="realized_lost"):
        state['Realized_PNL'] = -abs(amount)
        normal_output.append(log_print(f"{Decimal(amount)}"),) 

        if math.isnan(price):
            state['averagePrice'] = state['previousAveragePrice']
        else:
            state['averagePrice'] = price

       

    #After the position changed, the profit should be calculated using the previous position averageprice
    #Then, what should happend after is the remaining quantity would be used to calculate TotalCostBasis (Which is what this code does)
  
    #print(averagePrice)
    #print(TotalCostBasis)

    try:

        if(side == "withdraw"):
            state['averagePrice'] =  state['previousAveragePrice']
            state['TotalCostBasis'] =  state['averagePrice']*state['currentPositionQuantity']

            averagePriceFromOtherAccount =  Decimal(state['averagePrice'])
            PositionQuantityFromOtherAccount = state['currentPositionQuantity']
            PreviousPositionQuantityFromOtherAccount = state['previousPositionQuantity']
            TotalCostBasisTransferedFromOtherAccount = abs(state['averagePrice']*quantity)
        


        if(side=="deposit"):
            if(state['currentPositionQuantity'] != Decimal('0')):
                state['averagePrice'] = (((TotalCostBasisTransferedFromOtherAccount)+(abs(state['previousPositionQuantity'])*abs(state['previousAveragePrice'])))/abs(state['currentPositionQuantity']))
            state['TotalCostBasis'] = state['currentPositionQuantity']*state['averagePrice']
            costbasis_output.append(log_print(f"((TotalCostBasisTransferedFromOtherAccount)+(quantity*previousAveragePrice))/currentPositionQuantity = (({TotalCostBasisTransferedFromOtherAccount:.5f})+({abs(state['previousPositionQuantity']):.5f}*{abs(state['previousAveragePrice']):.5f}))/{abs(state['currentPositionQuantity']):.5f}"))
    
    except NameError:
        state['AdjustedCostBasis'] = 0
        acb_output = []


    if(state['currentPositionQuantity'] == Decimal('0')):
        state['averagePrice'] = Decimal('0')
    

    # Save the original stdout to revert back to later
    closeQuantityOutput.append(log_print(f"{closeQuantity}"))
    PositionCloseCheckOutput.append(log_print(f"{state['PositionCloseCheck']}"))
    
    if(check_data_in_currencies(asset) and side == "deposit" and asset not in stablecoins):
        state['currentPositionQuantity'] -= abs(quantity)
    elif(check_data_in_currencies(asset) and side == "withdraw" and asset not in stablecoins):
        state['currentPositionQuantity'] += abs(quantity)
        

    #sys.__stdout__.write(f"Realized PNL: {line_counter}: {closeQuantity}\n")
   
    #Declaring previous variables to be used next function call 
    state['previous_Side'] = side
    state['previousPositionQuantity'] = state['currentPositionQuantity']
    state['previousTotalCostBasis'] = state['TotalCostBasis']
    state['previousPrice'] = price
    state['previousAveragePrice'] = state['averagePrice']
    state['previousFiatBalance'] =  state['currentFiatBalance']
    
   
    
    #sys.__stdout__.write(f"{line_counter} First VS Code: {state['averagePrice']} \n ")
    #print(averagePrice)
    assets_state[account, asset] = state
    return state['Realized_PNL'], fee_output, averageprice_output, normal_output, costbasis_output, CurrentLiability, FiatBalance, test, closeQuantityOutput, PositionCloseCheckOutput


def get_sum_of_realized_pnl(csv_df, account, asset):
    asset = str(asset).lower()
    
    if str(account) == 'nan':
        tmp_df = csv_df[(csv_df['Account'].isnull()) & (csv_df['asset'].str.lower() == asset)]
    else:
        tmp_df = csv_df[(csv_df['Account'].str.replace(' ', '').str.lower() == account) & (csv_df['asset'].str.lower() == asset)]
    
    r = tmp_df['Realized PNL'].sum()
    qp = 0
    avg_price = 0
    if not tmp_df.empty:
        last_row = tmp_df.iloc[-1]
        qp = last_row['Current Position Quantity']
        avg_price = last_row['Average entry price']
    return r, qp, avg_price

def get_sum_of_fee(csv_df, account, asset):
    asset = str(asset).lower()

    if str(account) == 'nan':
        tmp_df = csv_df[(csv_df['Account'].isnull()) & (csv_df['asset'].str.lower() == asset)]
    else:
        tmp_df = csv_df[(csv_df['Account'].str.replace(' ', '').str.lower() == account) & (csv_df['asset'].str.lower() == asset)]
    
    r = tmp_df['Fee'].sum()
    return r

def get_sum_of_realized_pnl_v2(csv_df, account, asset, oa, txt_op1_assets):
    asset = str(asset).lower()
    match_rows = []
    for ast in oa:
        if ast not in txt_op1_assets:
            match_rows.append(str(ast).lower())

    #V0
    """ if ('Quote Currency' in csv_df.columns):
        if asset == 'usd':
            tmp_df = csv_df[(csv_df['Account'].str.replace(' ', '').str.lower() == account) & ((csv_df['Quote Currency'].isnull()) | (csv_df['asset'].str.lower() == asset))]
        else:
            tmp_df = csv_df[(csv_df['Account'].str.replace(' ', '').str.lower() == account) & ((csv_df['asset'].str.lower() == asset))]
    else:
        tmp_df = csv_df[(csv_df['Account'].str.replace(' ', '').str.lower() == account) & (csv_df['asset'].str.lower() == asset)] """

    #V1
    #tmp_df = csv_df[(csv_df['Account'].str.replace(' ', '').str.lower() == account) & (csv_df['asset'].str.lower() == asset)]
    
    #V3
    if str(account) == 'nan':
        if match_rows:
            tmp_df = csv_df[(csv_df['Account'].isnull()) & (csv_df['asset'].str.lower().isin(match_rows))]
        else:
            tmp_df = csv_df[(csv_df['Account'].isnull()) & (csv_df['asset'].str.lower() == asset)]
    else:
        if match_rows:
            tmp_df = csv_df[(csv_df['Account'].str.replace(' ', '').str.lower() == account) & (csv_df['asset'].str.lower().isin(match_rows))]
        else:
            tmp_df = csv_df[(csv_df['Account'].str.replace(' ', '').str.lower() == account) & (csv_df['asset'].str.lower() == asset)]

    r = tmp_df['Realized PNL'].sum()
    qp = 0
    avg_price = 0
    if not tmp_df.empty:
        last_row = tmp_df.iloc[-1]
        qp = last_row[f'{asset.upper()} Balance']
        avg_price = last_row['Average entry price']
    return r, qp, avg_price

def get_sum_of_fee_v2(csv_df, account, asset, oa, txt_op1_assets):
    asset = str(asset).lower()
    match_rows = []
    for ast in oa:
        if ast not in txt_op1_assets:
            match_rows.append(str(ast).lower())
    
    #V3
    if str(account) == 'nan':
        if match_rows:
            tmp_df = csv_df[(csv_df['Account'].isnull()) & (csv_df['asset'].str.lower().isin(match_rows))]
        else:
            tmp_df = csv_df[(csv_df['Account'].isnull()) & (csv_df['asset'].str.lower() == asset)]
    else:
        if match_rows:
            tmp_df = csv_df[(csv_df['Account'].str.replace(' ', '').str.lower() == account) & (csv_df['asset'].str.lower().isin(match_rows))]
        else:
            tmp_df = csv_df[(csv_df['Account'].str.replace(' ', '').str.lower() == account) & (csv_df['asset'].str.lower() == asset)]

    r = tmp_df['Fee'].sum()
    return r

def normalize_account_name(name):
    normalized_name = str(name).lower().replace(' ', '')
    if normalized_name in ACCOUNT_NAME_MAPPING:
        return ACCOUNT_NAME_MAPPING[normalized_name]
    else:
        return name
    
def normalize_action_name(name):
    normalized_name = str(name).lower().replace(' ', '')
    if normalized_name in ACTION_NAME_MAPPING:
        return ACTION_NAME_MAPPING[normalized_name]
    else:
        return name

def prepare_df(start_date, end_date, csv_path):
    csv_df = pd.read_csv(csv_path, dtype={'action': str, 'quantity': str, 'price': str})
    csv_df['Date'] = pd.to_datetime(csv_df['Date'])

    u_start_date =  pd.to_datetime(start_date.strftime('%Y-%m-%d')).date()
    u_end_date =  pd.to_datetime(end_date.strftime('%Y-%m-%d')).date()
    csv_df = csv_df[(csv_df['Date'].dt.date >= u_start_date) & (csv_df['Date'].dt.date <= u_end_date)]
    return csv_df

def prepare_date_object_check_format(date_string):
    obj = None
    try:
        obj = datetime.datetime.strptime(date_string, "%Y-%m-%d %H:%M")
    except:
        try:
            obj = datetime.datetime.strptime(date_string, "%Y-%m-%d %H:%M:%S")
        except:
            try:
                obj = datetime.datetime.strptime(date_string, "%Y-%m-%d")
            except:
                pass
    return obj

def display_all_assets(csv_path): #test_result 

    op_header_row = ['Account','Asset','Current Postion Quantity','Average Price','PNL', 'Fee', 'from date-end date', 'userinput(date1-date2)']
    tp_keys = []

    print("Current Position Quantities for All Accounts:")
    date2 = input('[+] Enter Date1 | from where you want to start calculating PNL (yyyy-mm-dd): ')
    date1 = input('[+] Enter Date2 (yyyy-mm-dd): ')
    csv_df = None

    user_date1_str = 'Invalid'
    user_date2_str = 'Invalid'
    
    user_date1 = ''
    user_date2 = ''

    try:
        user_date1 = datetime.datetime.strptime(date1, "%Y-%m-%d")
        user_date1_str = user_date1.strftime("%Y-%m-%d")
    except:
        t_df = pd.read_csv(csv_path)
        latest_date = t_df.iloc[-1]['Date']
        latest_date = latest_date.replace('/','-').strip()
        try:
            user_date1 = datetime.datetime.strptime(latest_date, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                user_date1 = datetime.datetime.strptime(latest_date, "%Y-%m-%d %H:%M")
            except ValueError:
                try:
                    user_date1 = datetime.datetime.strptime(latest_date, "%Y-%m-%d  %H:%M:%S")
                except ValueError:
                    try:
                        user_date1 = datetime.datetime.strptime(latest_date, "%Y-%m-%d  %H:%M")
                    except ValueError:
                        user_date1 = datetime.datetime.strptime(latest_date, "%Y-%m-%d")
        
        user_date1_str = user_date1.strftime("%Y-%m-%d")
    
    try:
        user_date2 = datetime.datetime.strptime(date2, "%Y-%m-%d")
        user_date2_str = user_date2.strftime("%Y-%m-%d")
    except:
        user_date2 = datetime.datetime(year=user_date1.year, month=1, day=1)
        user_date2_str = user_date2.strftime("%Y-%m-%d")

    csv_df = prepare_df(user_date2, user_date1, csv_path)
    txt_op = []

    for acc in assets_state:

        orignal_name = None
        try:
            orignal_name = asset_state[acc]['ORIGINAL_NAME']
        except:
            pass

        if isinstance(acc, tuple):
            continue

        #print(f"Account: {acc}")
        total_pnl = 0
        data_exists = False

        txt_op1 = []
        txt_op2 = []

        txt_op1_assets = []
        for asset in assets_state[acc]:

            
            date = assets_state[acc][asset]['Date']
                
            realized_pnl, quantity, avg_price = get_sum_of_realized_pnl(csv_df, acc, asset)
            fee = get_sum_of_fee(csv_df, acc, asset)

            quantity = assets_state[acc][asset]['currentPositionQuantity']
            avg_price = assets_state[acc][asset]['averagePrice']

            if avg_price:
                avg_price = f'{avg_price:.5f}'
            else:
                avg_price = 'NaN'

            #print(f'Type: {type(date)}')
            #print(f'Data: {date}')
            #print(f'Space C: {date.count(" ")}')
            #print('New Line C: {}'.format(date.count('\n')))
            dt_object = prepare_date_object_check_format(date)
            #print(f'Result: {dt_object}')
            
            if quantity == Decimal('0') and avg_price == 'NaN' and realized_pnl == 0.0 and fee == 0.0:
                pass
            # and dt_object.date() >= user_date2.date()
            elif dt_object.date() <= user_date1.date():
                total_pnl += realized_pnl
                data_txt = f"  Asset: {asset}, Current Position Quantity: {quantity:.20f}, Average Price: {avg_price}, PNL: {realized_pnl}, Fee: {fee}"
                data_exists = True

                acc_name = acc
                if orignal_name:
                    acc_name = orignal_name
                """ if not OutputSameFormat:
                    mapping_name = ACCOUNT_NAME_MAPPING.get(acc)
                    if mapping_name:
                        acc_name = mapping_name """

                row1 = {
                    'Account': acc_name, 
                    'Asset': asset, 
                    'Current Postion Quantity': f'{quantity:.20f}',
                    'Average Price': avg_price, 
                    'PNL': realized_pnl, 
                    'Fee': format(fee, ".10f"), 
                    'from date-end date': f'{user_date2_str}-{user_date1_str}', 
                    'userinput(date1-date2)': f'{date2}-{date1}',
                    }
                txt_op1.append(row1)
                txt_op1_assets.append(asset)

        """ for row in txt_op1:
            print(row)
            print('\n\n\n') """
        
        """ with open('tmp.json', 'w') as tf:
            json.dump(asset_state, tf, indent=4) """

        txt_op2_assets = []
        for asset in asset_state[acc]:
            if asset == 'ORIGINAL_NAME':
                continue
            if str(asset) == 'nan':
                continue

            date = asset_state[acc][asset]['date']
            oa = asset_state[acc][asset]['original_asset']
            realized_pnl_v2, qp, avg_price_v2 = get_sum_of_realized_pnl_v2(csv_df, acc, asset, oa, txt_op1_assets)
            fee_v2 = get_sum_of_fee_v2(csv_df, acc, asset, oa, txt_op1_assets)

            #qp = asset_state[acc][asset]['currentFiatBalance']
            #avg_price_v2 = asset_state[acc][asset]['averagePrice'] if asset_state[acc][asset].get('averagePrice') else 0

            #print(f'Type: {type(date)}')
            #print(f'Data: {date}')
            #print(f'Space C: {date.count(" ")}')
            #print('New Line C: {}'.format(date.count('\n')))
            dt_object = prepare_date_object_check_format(date)
            #print(f'Result: {dt_object}')
            #print(f'User Date: {user_date1}')

            if qp == Decimal('0') and avg_price_v2 == 0 and realized_pnl_v2 == 0.0 and fee_v2 == 0.0:
                continue
            #not working
            #and dt_object.date() >= user_date2.date()
            #elif dt_object.date() <= user_date1.date():
            acc_name = acc
            if orignal_name:
                acc_name = orignal_name
            """ if not OutputSameFormat:
                mapping_name = ACCOUNT_NAME_MAPPING.get(acc)
                if mapping_name:
                    acc_name = mapping_name """
            txt_op2.append({
                'Account': acc_name, 
                'Asset': asset,
                'Average Price': avg_price_v2,
                'Current Postion Quantity': f'{qp}',
                'PNL': realized_pnl_v2,
                'Fee': format(fee_v2, ".10f"),
                'from date-end date': f'{user_date2_str}-{user_date1_str}', 
                'userinput(date1-date2)': f'{date2}-{date1}',
            })
            data_exists = True
            txt_op2_assets.append(asset)

        """ for row in txt_op2:
            print(row)
            print('\n\n\n') """

        txt_op3 = []
        for d_row in txt_op1:
            if d_row['Asset'] not in txt_op2_assets:
                txt_op3.append(d_row)

        txt_op3.extend(txt_op2)

        #fix nan
        txt_op4 = []
        for row in txt_op3:
            avg_price = row.get('Average Price')
            if avg_price and avg_price == 'NaN':
                row['Average Price'] == 0
            txt_op4.append(row)

        txt_op5 = sorted(txt_op3, key=lambda x: float(x['Average Price']) * float(x['Current Postion Quantity']), reverse=True)
        
        #imporved version #ref102
        if data_exists:
            txt_op5.append({'Account': ''})

        txt_op.extend(txt_op5)

    op_header_row.extend(list(set(tp_keys)))
    
    #modify account mapping | just for renaming
    """ if not OutputSameFormat:
        for row in txt_op:
            lk_acc = str(row['Account']).lower().replace(' ', '').strip()
            acc_new = ACCOUNT_NAME_MAPPING.get(lk_acc)
            if acc_new:
                row['Account'] = acc_new

        #now modify output.csv
        if os.path.exists(OUTPUT_CSV_PATH):
            df = pd.read_csv(OUTPUT_CSV_PATH)
            df['Account'] = df['Account'].apply(normalize_account_name)
            #df['action'] = df['action'].apply(normalize_action_name)
            df.to_csv(OUTPUT_CSV_PATH, index=False)

        df = pd.read_csv(OUTPUT_CSV_PATH_APP2)
        df['Account'] = df['Account'].apply(normalize_account_name)
        #df['action'] = df['action'].apply(normalize_action_name)
        df.to_csv(OUTPUT_CSV_PATH_APP2, index=False) """
    
    #ref102

    with open(RESULT_OUTPUT_CSV_PATH, 'w', newline='', encoding='utf-8') as csv_f:
        csv_writer = csv.DictWriter(csv_f, fieldnames=op_header_row)
        csv_writer.writeheader()
        csv_writer.writerows(txt_op)
    print('[+] Output Written to {}'.format(RESULT_OUTPUT_CSV_PATH))
    

def display_assets(csv_path, account=None):
    cal_acc = account.lower().replace(' ','') #make it lower and remove <space>, because we are using this type of name in calculation
    if account and cal_acc in assets_state:
        print(f"Current Position Quantities for Account: {account}")
        for asset in assets_state[cal_acc]:
            quantity = assets_state[cal_acc][asset]['currentPositionQuantity']
            avg_price = assets_state[cal_acc][asset]['averagePrice']
            if avg_price:
                avg_price = f'{avg_price:.5f}'
            else:
                avg_price = 'NAN'
            print(f"  Asset: {asset}, Current Position Quantity: {quantity:.20f}, Average Price: {avg_price}")
    elif not account:
        display_all_assets(csv_path)
    else:
        print("Account not found! Displaying All Assets")
        display_all_assets(csv_path)


# Correctly initialize DataFrame columns for additional data
def add_columns_to_dataframe(df):
    # df['state['averagePrice'']'] = Decimal('0')
    # df['state['Realized_PNL']'] = Decimal('0')
    # df['state['currentPositionQuantity']'] = Decimal('0')
    return df

# Define a function that captures prints based on a tag
def log_print(message, tag=None):
    # This function just returns the message as is.
    # The tag is used by the calling code to decide which list to append the message to.
    return message

########Modify User Input Here Main Program #############

def check_user_separately_advanced(row_i, df, col_suffix):
    #use to return all the matching columns, #use for Balance.
    relevant_columns = [col for col in df.columns if col.endswith(col_suffix)]
    result_columns = []
    for col_name in relevant_columns:
        if not pd.isna(df.iloc[row_i][col_name]) and df.iloc[row_i][col_name] != '':
            result_columns.append(col_name)
    return result_columns

def check_user_separately(row_i, df, col_name):
    return (col_name in df.columns) and not pd.isna(df.iloc[row_i][col_name]) and not df.iloc[row_i][col_name] == ''

def update_user_input_balance(index, df, balance_key, account, date):

    #check for other columns and update it.
    balance_columns = check_user_separately_advanced(index, df, ' Balance')
    for col in balance_columns:
        balance_key2 = col.replace(' Balance', '')
        if not asset_state[account].get(balance_key2):
            asset_state[account][balance_key2] = {
                'currentFiatBalance': Decimal('0'),
                'previousFiatBalance': Decimal('0'),
                'original_asset': set(),
                'date': ''
            }
        asset_state[account][balance_key2]['currentFiatBalance'] = Decimal(df.iloc[index][f'{balance_key2} Balance'])
        asset_state[account][balance_key2]['original_asset'].add(balance_key2)
        asset_state[account][balance_key2]['date'] = date

def update_user_input_second(row_i, df, state, pnl, averageprice_output, normal_output, costbasis_output):
    fee_output2 = []
    
    def check_input(col_name):
        return (col_name in df.columns) and not pd.isna(df.iloc[row_i][col_name]) and not df.iloc[row_i][col_name] == ''
    
    #CHECK USER INPUT DATA
    if check_input('Average entry price'):
        state['averagePrice'] = Decimal(df.iloc[row_i]['Average entry price'])
        state['previousAveragePrice'] = state['averagePrice']

    if check_input('Realized PNL'):
        d = Decimal(df.iloc[row_i]['Realized PNL'])
        state['Realized_PNL'] = d
        pnl = d

    if check_input('Current Position Quantity'):
        d = Decimal(df.iloc[row_i]['Current Position Quantity'])
        state['currentPositionQuantity'] = d
        state['previousPositionQuantity'] = d

    if check_input('Fee'):
        d = Decimal(df.iloc[row_i]['Fee'])
        state['Fee'] = d
        fee_output2.append(log_print(f"{d}"),)

    if Log:
        if check_input('Console log: Realized PNL'):
            normal_output = []
            normal_output.append(log_print(format(Decimal(df.iloc[row_i]['Console log: Realized PNL'])), '.5f'))

        if check_input('Average Price Output'):
            averageprice_output = []
            averageprice_output.append(log_print(format(Decimal(df.iloc[row_i]['Average Price Output'])), '.5f'))

        if check_input('Total Cost Basis Output'):
            costbasis_output = []
            costbasis_output.append(log_print(format(Decimal(df.iloc[row_i]['Total Cost Basis Output'])), '.5f'))

    return state, pnl, fee_output2, averageprice_output, normal_output, costbasis_output

########Modify User Input Ends Main Program #############
def add_missing_time(date_str):
    date_str = str(date_str).strip()
    if len(date_str) == 10:
        return date_str + ' 00:00'
    return date_str

def work_on_test_results(csv_path):
    account_input = input("Enter an account name to display its asset quantities, or press ENTER to display all: ").strip()
    display_assets(csv_path, account=account_input)

def read_and_get_df():
    global INPUT_CSV_PATH, INPUT_READ_PRIORITIES

    for input_type in INPUT_READ_PRIORITIES:
        print(f'[*] Trying {input_type}')
        i_path = INPUT_CSV_PATH + '.' + input_type
        if not os.path.exists(i_path):
            print('[-] Does not exists ...')
            continue

        readCSV = None
        try:
            if input_type in ['xlsx', 'xlsm']:
                readCSV = pd.read_excel(i_path, dtype={'action': str, 'quantity': str, 'price': str})
            elif input_type in ['csv']:
                readCSV = pd.read_csv(i_path, dtype={'action': str, 'quantity': str, 'price': str})
            else:
                print(f'[-] {input_type} if not vaild input file type! Skipping...')
        except Exception as e:
            print(f'[-] Error occur while reading {input_type} file...')
            print(e)

        if readCSV is not None:
            print(f'[+] Using {input_type} file ...')
            return readCSV

def main_app():
    global DF_COPY
    readCSV = read_and_get_df()

    if readCSV is None:
        print('[+] No File Found!')
        sys.exit()

    #clear df before processing further,
    readCSV = readCSV.dropna(how='all')
    readCSV.reset_index(drop=True, inplace=True)
    
    readCSV['Date'] = readCSV['Date'].apply(add_missing_time)

    #print('MAIAPP DATE INPUT')
    #print(readCSV['Date'])
    

    
    readCSV['quantity'] = readCSV['quantity'].apply(lambda x: Decimal(x))
    readCSV['price'] = readCSV['price'].apply(lambda x: Decimal(x))
    readCSV = add_columns_to_dataframe(readCSV)

    if not OutputSameFormat:
        readCSV['Account'] = readCSV['Account'].apply(normalize_account_name)
        readCSV['action'] = readCSV['action'].apply(normalize_action_name)

    readCSVI = readCSV.copy()
    DF_COPY = readCSV.copy()

    readCSV['Fee'] = ''
    #if Log:
        #readCSV['Liability'] = ''
    readCSV['Average entry price'] = ''
    readCSV['Current Position Quantity'] = ''
    readCSV['Realized PNL'] = ''
    if Log:
        readCSV['Average Price Output'] = ''
        readCSV['Total Cost Basis Output'] = ''
        readCSV['Console log: Realized PNL'] = ''
        

    # Add columns for different types of console output

    # Redirect stdout to capture print statements
    #TMP_C
    """ old_stdout = sys.stdout
    captured_output = StringIO()
    sys.stdout = captured_output """

    for index, row in readCSV.iterrows():
        # Clear the captured_output buffer before processing the new row
        asset = row['asset']  # Assuming 'asset' column exists in CSV
        side = str(row['action']).strip().lower()

        if any(side == word for word in ['open long', 'open_long', 'long', 'buy_long', 'buy long']):
            side = 'buy'
        elif any(side == word for word in ['open short', 'open_short', 'short', 'sell_short', 'sell short']):
            side = 'sell'

        quantity = row['quantity']
        amount = row['amount']
        price = row['price']
        fee = row['Fee Amount']
        feeCurrency = row['Fee Currency']
        account = str(row['Account']).lower().replace(' ','')
        original_account = row['Account']
        date = row['Date']

        memo1 = row['Memo1']
        memo2 = row['Memo2']
        memo3 = row['Memo3']
        #closeQuantityRow = row['Closed Quantity'] 
        #PositionCloseCheckRow = row['Position Close']
       

        #adjust rates
        if AdjustRates:
            if row.get('Quote Currency') and str(row['Quote Currency']) != 'nan':
                tmp_qc = row['Quote Currency']
                tmp_qc_rates = Decimal(get_exchange_rate(tmp_qc))
                price = Decimal(row['price']) * tmp_qc_rates
                amount = Decimal(row['amount']) * tmp_qc_rates
        
        #TMP_C
        """ captured_output.truncate(0)
        captured_output.seek(0) """

        # Perform the calculations by calling CalculatePNL
        # This function updates global variables and prints output to captured_output
    
        
        pnl, fee_output, averageprice_output, normal_output, costbasis_output, CurrentLiability, FiatBalance, test, closeQuantityOutput, PositionCloseCheckOutput  = CalculatePNL(asset, side, quantity, amount, price, fee, feeCurrency, account, date)
        state = get_asset_state(account, asset)

        #check and update user inputs
        #V0 #trigger user input
        state, pnl, fee_output2, averageprice_output, normal_output, costbasis_output  = update_user_input_second(index, readCSVI, state, pnl, averageprice_output, normal_output, costbasis_output)
        if fee_output2:
            fee_output = fee_output2
        
        # Assign calculated values to their respective columns

        
        readCSV.at[index, 'Fee'] = state['Fee']
    

        readCSV.at[index, 'Average entry price'] = state['averagePrice']
        readCSV.at[index, 'Current Position Quantity'] = state['currentPositionQuantity']
        readCSV.at[index, 'Realized PNL'] = pnl
       # readCSV.at[index, 'Closed Quantity'] = closeQuantity
       # readCSV.at[index, 'PositionCloseCheck'] = state['PositionCloseCheck']
    
        
        # Now that CalculatePNL has been called, captured_output contains all print statements
        # We take this output and add it to the 'Console Output' column

        readCSV.at[index, 'Fee'] = "\n".join(fee_output) if fee_output else ""

        if Log:
            readCSV.at[index, 'Console log: Realized PNL'] = "\n".join(normal_output) if normal_output else ""

        
        # The special output collected within CalculatePNL is added to 'Special Output'
        # Joining the list into a single string separated by newlines
        if Log:
            readCSV.at[index, 'Average Price Output'] = "\n".join(averageprice_output) if averageprice_output else ""
        
        if Log:
            readCSV.at[index, 'Total Cost Basis Output'] = "\n".join(costbasis_output) if costbasis_output else ""
         
        readCSV.at[index, 'Closed Quantity'] = "\n".join(closeQuantityOutput) if closeQuantityOutput else ""
        readCSV.at[index, 'Position Close Check'] = "\n".join(PositionCloseCheckOutput) if PositionCloseCheckOutput else ""



        #readCSV.at[index, 'CurrentLiability1'] = "\n".join(CurrentLiability) if CurrentLiability else ""

        #readCSV.at[index, 'Current Fiat Balance'] = "\n".join(FiatBalance) if FiatBalance else ""

        #readCSV.at[index, 'test1'] = "\n".join(test) if test else ""

        #rest amount and price to original

        amount = row['amount']
        price = row['price']

        #v4
        if not asset_state.get(account):
            asset_state[account] = {}
            asset_state[account]['ORIGINAL_NAME'] = original_account

        original_asset = row['asset']
        quote_currency = get_guote_currency(row, row['asset'])

        """ try:
            quote_currency = row['Quote Currency']
        except KeyError:
            quote_currency = None
        if (not quote_currency or str(quote_currency).lower() == 'nan') and not check_data_in_currencies(asset):
            quote_currency = Default_Quote_Currency
        elif (not quote_currency or str(quote_currency).lower() == 'nan') and check_data_in_currencies(asset):
            quote_currency = asset
        elif quote_currency and check_data_in_currencies(asset):
            quote_currency = asset """

        if not asset_state[account].get(quote_currency):
            asset_state[account][quote_currency] = {
                'currentFiatBalance': Decimal('0'),
                'previousFiatBalance': Decimal('0'),
                'original_asset': set(),
                'date': ''
            }
        asset_state[account][quote_currency]['original_asset'].add(original_asset)
        asset_state[account][quote_currency]['date'] = date

        if quote_currency == asset:
            asset_state[account][quote_currency]['averagePrice'] = state['averagePrice']
        else:
            asset_state[account][quote_currency]['averagePrice'] = 0
        
        #fees
        cal_fee = row['Fee Amount']
        if not cal_fee or str(cal_fee).lower() == 'nan':
            cal_fee = 0
        cal_fee = Decimal(cal_fee)
        cal_fee_abs = Decimal(abs(cal_fee))
        if(side == "withdraw" or side == "deposit") and not check_data_in_currencies(asset):
            asset_state[account][quote_currency]['currentFiatBalance'] += -cal_fee_abs
        elif (side == "deposit") and check_data_in_currencies(asset):
            asset_state[account][quote_currency]['currentFiatBalance'] += abs(Decimal(quantity)) -cal_fee_abs
        elif (side == "withdraw") and check_data_in_currencies(asset):
            asset_state[account][quote_currency]['currentFiatBalance'] += -abs(Decimal(quantity)) -cal_fee_abs
        elif(side == "buy") and not check_data_in_currencies(asset):
            if amount and str(amount).lower() != 'nan':
                asset_state[account][quote_currency]['currentFiatBalance'] += -abs(Decimal(amount)) + -cal_fee_abs
            else:
                asset_state[account][quote_currency]['currentFiatBalance'] += -abs(Decimal(price*quantity)) + -cal_fee_abs
        
        elif(side == "sell") and not check_data_in_currencies(asset):
            if amount and str(amount).lower() != 'nan':
                asset_state[account][quote_currency]['currentFiatBalance'] += abs(Decimal(amount)) + -cal_fee_abs
               
            else:
                asset_state[account][quote_currency]['currentFiatBalance'] += abs(Decimal(price*quantity)) + -cal_fee_abs

        elif(side == "buy") and check_data_in_currencies(asset):
            tq = row['Quote Currency'] if row.get('Quote Currency') else None
            fee_currency = row['Fee Currency']
            if not asset_state[account].get(tq):
                asset_state[account][tq] = {
                    'currentFiatBalance': Decimal('0'),
                    'previousFiatBalance': Decimal('0'),
                    'original_asset': set(),
                    'date': ''
                }
            asset_state[account][tq]['original_asset'].add(original_asset)
            asset_state[account][tq]['date'] = date

            if fee_currency and str(fee_currency).lower() != 'nan' and not asset_state[account].get(fee_currency):
                asset_state[account][fee_currency] = {
                    'currentFiatBalance': Decimal('0'),
                    'previousFiatBalance': Decimal('0'),
                    'original_asset': set(),
                    'date': ''
                }
            if fee_currency and str(fee_currency).lower() != 'nan':
                asset_state[account][fee_currency]['original_asset'].add(original_asset)
                asset_state[account][fee_currency]['date'] = date

            if (tq and str(tq).lower() != 'nan' and tq != quote_currency):
                if amount and str(amount).lower() != 'nan':
                    if (fee_currency and str(fee_currency).lower() != 'nan' and tq == fee_currency):
                        asset_state[account][quote_currency]['currentFiatBalance'] += abs(Decimal(quantity))
                        asset_state[account][tq]['currentFiatBalance'] += -abs(Decimal(amount)) + -cal_fee_abs
                    elif (fee_currency and str(fee_currency).lower() != 'nan' and tq != fee_currency):
                        asset_state[account][quote_currency]['currentFiatBalance'] += abs(Decimal(quantity))
                        asset_state[account][tq]['currentFiatBalance'] += -abs(Decimal(amount))
                        asset_state[account][fee_currency]['currentFiatBalance'] += -cal_fee_abs
                        asset_state[account][fee_currency]['averagePrice'] = 0
                    else:
                        asset_state[account][quote_currency]['currentFiatBalance'] += abs(Decimal(quantity)) -cal_fee_abs
                        asset_state[account][tq]['currentFiatBalance'] += -abs(Decimal(amount))
                    
                    #asset_data
                    if tq == asset:
                        asset_state[account][tq]['averagePrice'] = state['averagePrice']
                    else:
                        asset_state[account][tq]['averagePrice'] = 0
                else:
                    asset_state[account][quote_currency]['currentFiatBalance'] += abs(Decimal(price*quantity)) + -cal_fee_abs
            elif (tq != quote_currency):
                if amount and str(amount).lower() != 'nan':
                    asset_state[account][quote_currency]['currentFiatBalance'] += abs(Decimal(quantity)) + -cal_fee_abs
                else:
                    asset_state[account][quote_currency]['currentFiatBalance'] += abs(Decimal(price*quantity)) + -cal_fee_abs
            else:
                if amount and str(amount).lower() != 'nan':
                    asset_state[account][quote_currency]['currentFiatBalance'] += abs(Decimal(amount)) + -cal_fee_abs
                else:
                    asset_state[account][quote_currency]['currentFiatBalance'] += abs(Decimal(price*quantity)) + -cal_fee_abs

        elif(side == "sell") and check_data_in_currencies(asset):
            tq = row['Quote Currency'] if row.get('Quote Currency') else None
            fee_currency = row['Fee Currency']
            if not asset_state[account].get(tq):
                asset_state[account][tq] = {
                    'currentFiatBalance': Decimal('0'),
                    'previousFiatBalance': Decimal('0'),
                    'original_asset': set(),
                    'date': ''
                }
            asset_state[account][tq]['original_asset'].add(original_asset)
            asset_state[account][tq]['date'] = date

            if fee_currency and str(fee_currency).lower() != 'nan' and not asset_state[account].get(fee_currency):
                asset_state[account][fee_currency] = {
                    'currentFiatBalance': Decimal('0'),
                    'previousFiatBalance': Decimal('0'),
                    'original_asset': set(),
                    'date': ''
                }
            if fee_currency and str(fee_currency).lower() != 'nan':
                asset_state[account][fee_currency]['original_asset'].add(original_asset)
                asset_state[account][fee_currency]['date'] = date

            if (tq and str(tq).lower() != 'nan' and tq != quote_currency):
                if amount and str(amount).lower() != 'nan':
                    if (fee_currency and str(fee_currency).lower() != 'nan' and tq == fee_currency):
                        asset_state[account][quote_currency]['currentFiatBalance'] += -abs(Decimal(quantity))
                        asset_state[account][tq]['currentFiatBalance'] += abs(Decimal(amount)) + -cal_fee_abs
                    elif (fee_currency and str(fee_currency).lower() != 'nan' and tq != fee_currency):
                        asset_state[account][quote_currency]['currentFiatBalance'] += -abs(Decimal(quantity))
                        asset_state[account][tq]['currentFiatBalance'] += abs(Decimal(amount))
                        asset_state[account][fee_currency]['currentFiatBalance'] += -cal_fee_abs
                        asset_state[account][fee_currency]['averagePrice'] = 0
                    else:
                        asset_state[account][quote_currency]['currentFiatBalance'] += -abs(Decimal(quantity)) -cal_fee_abs
                        asset_state[account][tq]['currentFiatBalance'] += abs(Decimal(amount))

                    #asset_data
                    if tq == asset:
                        asset_state[account][tq]['averagePrice'] = state['averagePrice']
                    else:
                        asset_state[account][tq]['averagePrice'] = 0
                else:
                    asset_state[account][quote_currency]['currentFiatBalance'] += -abs(Decimal(price*quantity)) + -cal_fee_abs
            elif(tq != quote_currency):
                if amount and str(amount).lower() != 'nan':
                    asset_state[account][quote_currency]['currentFiatBalance'] += -abs(Decimal(quantity)) + -cal_fee_abs
                else:
                    asset_state[account][quote_currency]['currentFiatBalance'] += -abs(Decimal(price*quantity)) + -cal_fee_abs
            else:
                if amount and str(amount).lower() != 'nan':
                    asset_state[account][quote_currency]['currentFiatBalance'] += -abs(Decimal(amount)) + -cal_fee_abs
                else:
                    asset_state[account][quote_currency]['currentFiatBalance'] += -abs(Decimal(price*quantity)) + -cal_fee_abs
        
        elif(side == "realized_pnl" or side == "realized_lost"):
            asset_state[account][quote_currency]['currentFiatBalance'] += Decimal(pnl) -cal_fee_abs
        
        #or not asset_state[account][quote_currency]['currentFiatBalance']
        #if current currentFiatBalance is 0.0 then adding above line will take previousFiatBalance and that will cause issue.

        #update previous fiatbalance for user input
        update_user_input_balance(index, readCSVI, quote_currency, account, date)
        

        if str(asset_state[account][quote_currency]['currentFiatBalance']).lower() == 'nan':
            asset_state[account][quote_currency]['currentFiatBalance'] = asset_state[account][quote_currency]['previousFiatBalance']
        else:
            asset_state[account][quote_currency]['previousFiatBalance'] = asset_state[account][quote_currency]['currentFiatBalance']
        

        #adjust currency balance data
        if AdjustCurrencyBalance:
            cpq = Decimal(state['currentPositionQuantity'])
            aep = Decimal(state['averagePrice'])
            zero_decimal = Decimal('0')

            if AdjustRates:
                if row.get('Quote Currency') and str(row['Quote Currency']) != 'nan':
                    tmp_qc = row['Quote Currency']
                    tmp_qc_rates = Decimal(get_exchange_rate(tmp_qc))
                    aep = aep/tmp_qc_rates

            if not cpq.is_nan() and (cpq < zero_decimal):
                #OLD NOT WORKING
                #asset_state[account][quote_currency]['currentFiatBalance'] = asset_state[account][quote_currency]['currentFiatBalance'] + cpq*aep
                modification_qc = get_modification_qc(row, asset)
                if modification_qc and modification_qc != 'no_qc':
                    asset_state[account][modification_qc]['adjustedBalance'] = asset_state[account][modification_qc]['currentFiatBalance'] + (cpq*aep)

        #Deemed Disposition Code
        if any('Deemed Disposition'.lower().replace(' ', '') in str(memo).lower().replace(' ', '') for memo in [memo1, memo2, memo3]):
            tq = row['Quote Currency'] if row.get('Quote Currency') else None
            if check_data_in_currencies(asset) and (not tq or str(tq).lower() == 'nan'):
                if side == 'sell':
                    asset_state[account][quote_currency]['currentFiatBalance'] += abs(Decimal(amount))*0
                elif side == 'buy':
                    asset_state[account][quote_currency]['currentFiatBalance'] += -abs(Decimal(amount))*0
            else:
                if side == 'sell':
                    asset_state[account][quote_currency]['currentFiatBalance'] += -abs(Decimal(amount))
                elif side == 'buy':
                    asset_state[account][quote_currency]['currentFiatBalance'] += abs(Decimal(amount))

        if check_data_in_currencies(asset):
            
            rq = row['Quote Currency'] if row.get('Quote Currency') else None
            if (rq and str(rq).lower() != 'nan' and rq != quote_currency and side in ['buy', 'sell']):
                
                readCSV.at[index, f'{rq} Balance'] = asset_state[account][rq]['currentFiatBalance']
                readCSV.at[index, f'{quote_currency} Balance'] = asset_state[account][quote_currency]['currentFiatBalance']

            else:
                readCSV.at[index, f'{quote_currency} Balance'] = asset_state[account][quote_currency]['currentFiatBalance']
            #Overwrite Currency Position Quantity  
            #readCSV.at[index, f'Current Position Quantity'] = asset_state[account][quote_currency]['currentFiatBalance']

            for currency in asset_state[account]:
                if currency == 'ORIGINAL_NAME':
                    continue
                #V0 NOT WORKING FOR AdjustCurrencyBalance
                """ if asset_state[account][currency]['currentFiatBalance']:
                    readCSV.at[index, f'{currency} Balance'] = asset_state[account][currency]['currentFiatBalance'] """
                
                if 'adjustedBalance' in asset_state[account][currency]:
                    readCSV.at[index, f'{currency} Balance'] = asset_state[account][currency]['adjustedBalance']
                    del asset_state[account][currency]['adjustedBalance']
                elif asset_state[account][currency]['currentFiatBalance']:
                    readCSV.at[index, f'{currency} Balance'] = asset_state[account][currency]['currentFiatBalance']

        else:
            for currency in asset_state[account]:
                if currency == 'ORIGINAL_NAME':
                    continue
                #V0 NOT WORKING FOR AdjustCurrencyBalance
                """ if asset_state[account][currency]['currentFiatBalance']:
                    readCSV.at[index, f'{currency} Balance'] = asset_state[account][currency]['currentFiatBalance'] """
                if 'adjustedBalance' in asset_state[account][currency]:
                    readCSV.at[index, f'{currency} Balance'] = asset_state[account][currency]['adjustedBalance']
                    del asset_state[account][currency]['adjustedBalance']
                elif asset_state[account][currency]['currentFiatBalance']:
                    readCSV.at[index, f'{currency} Balance'] = asset_state[account][currency]['currentFiatBalance'] 
                    

       

    # Reset stdout to its original state after the loop ends
    #TMP_C
    """ sys.stdout = old_stdout """

    readCSV['Realized PNL'] = readCSV['Realized PNL'].map(lambda x: round(x, 5))

    readCSV['Realized PNL'] = readCSV['Realized PNL'].apply(lambda x: f"{x:.5f}")

    #not working when here
    """ if not OutputSameFormat:
        readCSV['Account'] = readCSV['Account'].apply(normalize_account_name)
        readCSV['action'] = readCSV['action'].apply(normalize_action_name) """

    # Export to CSV, including all the columns
    columns_to_drop = [col for col in readCSV.columns if 'Unnamed:' in col]
    readCSV2 = readCSV.drop(columns=columns_to_drop)
    readCSV2.to_csv(OUTPUT_CSV_PATH, index=False)  # Adjust the number of decimals as needed

    #use (?<=\.\d{7})\d+(?=,) to round to 7 decimals


    # Display all assets' current position quantities for all accounts
    # Ask the user if they want to specify an account or view all
    # User interaction for account specification

    # Ask the user if they want to specify an account or view all
    # User interaction for account specification
    #account_input = input("Enter an account name to display its asset quantities, or press ENTER to display all: ").strip()
    #display_assets(account_input)

################################################################ MAIN APP Code Ends

if __name__ == '__main__':

    #make it True, to Run App1
    App1 = config.getboolean('settings', 'App1')
    #make it True, to Run App2
    App2 = config.getboolean('settings', 'App2')

    ################################################################ APP1

    #App1 Data
    #ONLY MODIFY BELOW PARAMETERS IF NEEDED
    CSV_PATH = config.get('app1', 'CSV_PATH') #input .csv file path
    OP_CSV_PATH = config.get('app1', 'OP_CSV_PATH')

    COLUMN_NAME_TO_CHECK = config.get('app1', 'COLUMN_NAME_TO_CHECK') #column name you want to check for positive and negative values
    ASSET_NAME_TO_CHECK = config.get('app1', 'ASSET_NAME_TO_CHECK')
    PREV_COL_NAME_TO_CHECK = config.get('app1', 'PREV_COL_NAME_TO_CHECK')
    BUY_SELL_COL_NAME = config.get('app1', 'BUY_SELL_COL_NAME')
    DATE_ROW_NAME = config.get('app1', 'DATE_ROW_NAME')

    #for spliting file into rows
    SPLIT_FILE = config.getboolean('app1', 'SPLIT_FILE')
    SPLIT_ROW_COUNT = config.getint('app1', 'SPLIT_ROW_COUNT')

    #when this is False, script will overwrite input .csv file with outputme
    #if this is True, then it will create new .csv file with (OP_CSV_PATH) path
    MAKE_NEW_OUTPUT_FILE = config.getboolean('app1', 'MAKE_NEW_OUTPUT_FILE')

    #enable log in new column
    ENABLE_LOG = config.getboolean('app1', 'ENABLE_LOG')

    ################################################################ MAIN APP

    #(Main App) Data
    ACCOUNT_NAME_MAPPING = json.loads(config.get('app2', 'ACCOUNT_NAME_MAPPING'))

    #script is calculating for this ['open long', 'open_long', 'long', 'buy_long', 'buy long'] | buy
    #script is calculating for this ['open short', 'open_short', 'short', 'sell_short', 'sell short'] | sell
    ACTION_NAME_MAPPING = json.loads(config.get('app2', 'ACTION_NAME_MAPPING'))
    # New column for console output

    INPUT_CSV_PATH = config.get('app2', 'INPUT_CSV_PATH')
    INPUT_READ_PRIORITIES = json.loads(config.get('app2', 'INPUT_READ_PRIORITIES')) #this will look for input file prioritiy wise

    OUTPUT_CSV_PATH = config.get('app2', 'OUTPUT_CSV_PATH')
    RESULT_OUTPUT_CSV_PATH = config.get('app2', 'RESULT_OUTPUT_CSV_PATH')

    #when True, whatever account name is written in {INPUT_CSV_PATH} File, that will be used.
    #when False, mapping based data will be used
    OutputSameFormat = config.getboolean('app2', 'OutputSameFormat')
    Log = config.getboolean('app2', 'Log')

    #track realized pnl when it's True
    TrackRealizedPNL = config.getboolean('app2', 'TrackRealizedPNL')

    #adjust currency balance
    #when True
    #currentPositionquantity is negative (currencybalance = currencybalance + currentPositionquantity*averageprice)
    AdjustCurrencyBalance = config.getboolean('app2', 'AdjustCurrencyBalance')

    # price * (quote currency rates) & amount * (quote currency rates)
    """
    not applying for app1 (currency balance) | in app2 again multiple both. | in end of app2 divide average balance.
    """
    AdjustRates = config.getboolean('app2', 'AdjustRates')

    AdjustRates2 = config.getboolean('app2', 'AdjustRates2')

    #this will use exchage rates from csv file instead of script.
    AdjustRatesFromCSV = config.getboolean('app2', 'AdjustRatesFromCSV')
    AdjustRatesFromCSV_PATH = config.get('app2', 'AdjustRatesFromCSV_PATH')

    #default currency.
    #this is used to calculate number (could be Realized PNL, PoD-ACB etc ...)
    #formula number * quote currency rate / default currency rate.
    Default_Currency = config.get('app2', 'Default_Currency')

    #this will be consider when quote currency is blank, and asset not in dicitonary
    Default_Quote_Currency = config.get('app2', 'Default_Quote_Currency')

    ################################################################ APP2

    #APP2 DATA
    INPUT_CSV_PATH_APP2 = config.get('app2', 'INPUT_CSV_PATH_APP2')
    OUTPUT_CSV_PATH_APP2 = config.get('app2', 'OUTPUT_CSV_PATH_APP2')

    if AdjustRatesFromCSV:
        update_exchange_rate_data(AdjustRatesFromCSV_PATH)


    if App1:
        print('[+] Running App 1 #check_csv():')
        #do not modify below code
        check_csv()
    elif App2:
        print(f'[+] Running App 2 #program1() => #program2() => {OUTPUT_CSV_PATH_APP2}:')
        main_app()
        print('[+] Calculating POD ...')
        calculate_pod()
        delete_file(INPUT_CSV_PATH_APP2)
        work_on_test_results(OUTPUT_CSV_PATH_APP2)
    else:
        print(f'[*] App1 : {App1}')
        print(f'[*] App2 : {App2}')
        print(f'[*] Log : {Log}')
        print(f'[+] Running Main App #main_app() => {OUTPUT_CSV_PATH}:')
        main_app()
        work_on_test_results(OUTPUT_CSV_PATH)
