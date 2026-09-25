import pandas as pd
import numpy as np

def process_and_merge_reports(file_list):
    dfs = []
    for f in file_list:
        if f.name.endswith('.csv'):
            temp = pd.read_csv(f)
        else:
            temp = pd.read_excel(f)
        dfs.append(temp)
    
    df = pd.concat(dfs, ignore_index=True)
    
    # Standardize column names
    df.columns = [c.strip().replace(' ', '_').replace('.', '_') for c in df.columns]
    
    # Date parsing
    if 'Placed_Time' in df.columns:
        df['Placed_Time'] = pd.to_datetime(df['Placed_Time'], errors='coerce')
    elif 'Order_Date' in df.columns:
        df['Placed_Time'] = pd.to_datetime(df['Order_Date'], errors='coerce')
        
    # Order type identification
    if 'Order_Type' in df.columns:
        df['Order_Type_Clean'] = df['Order_Type'].astype(str).str.lower().apply(
            lambda x: 'express' if 'express' in x or '15' in x or '30' in x else 'standard'
        )
    else:
        df['Order_Type_Clean'] = 'standard'
        
    # Fulfillment Type (Self vs 3PL)
    if 'Delivery_Mode' in df.columns:
        df['Fulfillment_Type'] = df['Delivery_Mode'].astype(str).apply(
            lambda x: '3PL' if any(k in x.lower() for k in ['shadowfax', 'grab', 'porter', '3pl', 'third']) else 'Self'
        )
    elif 'Rider_Type' in df.columns:
        df['Fulfillment_Type'] = df['Rider_Type'].astype(str).apply(
            lambda x: '3PL' if '3pl' in x.lower() else 'Self'
        )
    else:
        df['Fulfillment_Type'] = 'Self'
        
    # SLA Metrics
    if 'Pick_SLA_Met' not in df.columns:
        df['Pick_SLA_Met'] = np.where(df.get('Pick_Duration_Min', 0) <= 3, 1, 0)
    if 'Dispatch_SLA_Met' not in df.columns:
        df['Dispatch_SLA_Met'] = np.where(df.get('Dispatch_Duration_Min', 0) <= 6, 1, 0)
    if 'On_Time_Delivered' not in df.columns:
        df['On_Time_Delivered'] = np.where(df.get('Delivery_Delay_Min', 0) <= 0, 1, 0)
        
    if 'Rider_Name' not in df.columns:
        df['Rider_Name'] = 'Unassigned'
        
    return df
