import pandas as pd
import numpy as np

def format_duration(seconds):
    if pd.isna(seconds) or seconds < 0:
        return "0 Min 00 Sec"
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins} Min {secs:02d} Sec"

def process_and_merge_reports(picklist_files_list, transactions_file_path):
    picklist_frames = []
    for file in picklist_files_list:
        try:
            df = pd.read_excel(file)
        except Exception:
            df = pd.read_csv(file, sep='\t')
        picklist_frames.append(df)
    
    raw_picklist = pd.concat(picklist_frames, ignore_index=True)
    
    # Aggregate Picklist Data
    pick_agg = raw_picklist.groupby('Order Reference').agg({
        'Warehouse': 'first',
        'Order Date': 'first',
        'Order Type': 'first',
        'Picklist Creation Date&Time': 'first',
        'Picking Start Time': 'min',
        'Picklist Confirmation Date&Time': 'max',
        'Picking Time In Seconds': 'sum',
        'Picker Name': 'first',
        'Picklist Status': 'first'
    }).reset_index()
    
    pick_agg.rename(columns={
        'Order Reference': 'Order_ID',
        'Warehouse': 'Store_Name',
        'Order Date': 'Order_Placing_Time',
        'Picklist Creation Date&Time': 'Pick_Created_Time',
        'Picklist Confirmation Date&Time': 'Pick_Confirmed_Time'
    }, inplace=True)
    
    # Read Transactions Data
    try:
        df_trans = pd.read_excel(transactions_file_path)
    except Exception:
        df_trans = pd.read_csv(transactions_file_path)
        
    trans_clean = df_trans.copy()
    if 'ID' in trans_clean.columns:
        trans_clean.rename(columns={'ID': 'Order_ID'}, inplace=True)
    
    # Merge Picklist and Transactions
    master_df = pd.merge(pick_agg, trans_clean, on='Order_ID', how='inner')
    
    # Strip Timezone info & convert to Datetime for accurate calculations
    master_df['Order_Placing_Time'] = pd.to_datetime(master_df['Order_Placing_Time']).dt.tz_localize(None)
    master_df['Pick_Confirmed_Time'] = pd.to_datetime(master_df['Pick_Confirmed_Time']).dt.tz_localize(None)
    
    if 'Delivered Time' in master_df.columns:
        master_df['Delivered Time'] = pd.to_datetime(master_df['Delivered Time']).dt.tz_localize(None)
    
    # 1. Picking Duration Calculation
    master_df['Pick_Duration_Sec'] = (
        (master_df['Pick_Confirmed_Time'] - master_df['Order_Placing_Time']).dt.total_seconds()
    ).fillna(0)
    master_df['Pick_Duration_Sec'] = master_df['Pick_Duration_Sec'].apply(lambda x: max(x, 0))
    master_df['Pick Duration'] = master_df['Pick_Duration_Sec'].apply(format_duration)
    
    # Pick SLA Rule: Express <= 3 mins (180 secs)
    master_df['Pick_SLA_Met'] = np.where(master_df['Pick_Duration_Sec'] <= 180, 1, 0)
    
    # 2. Dispatch Duration Calculation (Detect correct dispatch timestamp)
    dispatch_col = None
    for col in ['Dispatched At', 'Dispatch Time', 'Handover Time', 'Out For Delivery Time', 'Created At']:
        if col in master_df.columns:
            dispatch_col = col
            break

    if dispatch_col:
        master_df['Dispatch_Time'] = pd.to_datetime(master_df[dispatch_col]).dt.tz_localize(None)
        
        # Calculate time elapsed between Pick Confirmation and Dispatch
        master_df['Dispatch_Duration_Sec'] = (
            (master_df['Dispatch_Time'] - master_df['Pick_Confirmed_Time']).dt.total_seconds()
        ).fillna(0)
        
        # Prevent negative durations if time stamps are out of order
        master_df['Dispatch_Duration_Sec'] = master_df['Dispatch_Duration_Sec'].apply(lambda x: max(x, 0))
    else:
        master_df['Dispatch_Duration_Sec'] = 0

    master_df['Dispatch Duration'] = master_df['Dispatch_Duration_Sec'].apply(format_duration)
    
    # Express Dispatch SLA Rule: <= 6 minutes (360 seconds)
    master_df['Dispatch_SLA_Met'] = np.where(master_df['Dispatch_Duration_Sec'] <= 360, 1, 0)
    
    # 3. Delivery SLA & Channel
    if 'On Time Delivered' in master_df.columns:
        master_df['Delivery Status'] = np.where(master_df['On Time Delivered'] == 1, 'On Time', 'Breached')
    else:
        master_df['On Time Delivered'] = 0
        master_df['Delivery Status'] = 'Breached'

    if 'Delivery Partner' in master_df.columns:
        master_df['Rider_Channel'] = np.where(
            master_df['Delivery Partner'].astype(str).str.upper() == 'SELF', 'Self (In-House)', '3PL Partner'
        )
    else:
        master_df['Delivery Partner'] = 'Unknown'
        master_df['Rider_Channel'] = '3PL Partner'
    
    return master_df
