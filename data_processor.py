import pandas as pd
import numpy as np
import io

def format_duration(seconds):
    if pd.isna(seconds) or seconds < 0:
        return "0 Min 00 Sec"
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins} Min {secs:02d} Sec"

def read_file_safely(file):
    """Robust file reader handling .xlsx, .xls, CSV, and varied text encodings."""
    if hasattr(file, 'read'):
        content = file.read()
        if hasattr(file, 'seek'):
            file.seek(0)
    else:
        content = file

    # 1. Try standard Excel
    try:
        return pd.read_excel(io.BytesIO(content))
    except Exception:
        pass

    # 2. Try CSV/TSV with various encodings
    encodings = ['utf-8', 'latin-1', 'iso-8859-1', 'cp1252', 'utf-16']
    separators = [None, '\t', ',', ';']

    for enc in encodings:
        for sep in separators:
            try:
                if sep is None:
                    df = pd.read_csv(io.BytesIO(content), encoding=enc, engine='python')
                else:
                    df = pd.read_csv(io.BytesIO(content), encoding=enc, sep=sep)
                if df.shape[1] > 1:
                    return df
            except Exception:
                continue

    return pd.read_csv(io.BytesIO(content), encoding='latin-1', on_bad_lines='skip')

def process_and_merge_reports(picklist_files_list, transactions_file_path):
    picklist_frames = []
    for file in picklist_files_list:
        df = read_file_safely(file)
        picklist_frames.append(df)
    
    raw_picklist = pd.concat(picklist_frames, ignore_index=True)
    
    # Ensure numeric picking time in seconds
    if 'Picking Time In Seconds' in raw_picklist.columns:
        raw_picklist['Picking Time In Seconds'] = pd.to_numeric(raw_picklist['Picking Time In Seconds'], errors='coerce').fillna(0)
    else:
        raw_picklist['Picking Time In Seconds'] = 0

    # Aggregate Picklist Data directly using Picking Time In Seconds
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
    df_trans = read_file_safely(transactions_file_path)
    trans_clean = df_trans.copy()
    
    if 'ID' in trans_clean.columns:
        trans_clean.rename(columns={'ID': 'Order_ID'}, inplace=True)
        
    status_col = 'Order State' if 'Order State' in trans_clean.columns else (trans_clean.columns[2] if len(trans_clean.columns) >= 3 else 'Status')

    # Filter out PAYMENT FAILED and CANCELLED orders
    excluded_statuses = ['PAYMENT FAILED', 'CANCELLED']
    trans_filtered = trans_clean[~trans_clean[status_col].astype(str).str.strip().str.upper().isin(excluded_statuses)].copy()

    # Merge Picklist and Filtered Transactions
    master_df = pd.merge(pick_agg, trans_filtered, on='Order_ID', how='inner')
    
    # Date Handling
    if 'Order_Placing_Time' in master_df.columns:
        master_df['Order_Placing_Time'] = pd.to_datetime(master_df['Order_Placing_Time'], errors='coerce').dt.tz_localize(None)
        
    master_df['Pick_Confirmed_Time'] = pd.to_datetime(master_df['Pick_Confirmed_Time'], errors='coerce').dt.tz_localize(None)
    
    if 'Delivered Time' in master_df.columns:
        master_df['Delivered Time'] = pd.to_datetime(master_df['Delivered Time'], errors='coerce').dt.tz_localize(None)
    
    # 1. Picking Duration Calculation directly from Picking Time In Seconds column
    master_df['Pick_Duration_Sec'] = master_df['Picking Time In Seconds']
    master_df['Pick Duration'] = master_df['Pick_Duration_Sec'].apply(format_duration)
    
    # Pick SLA Rule: Express <= 3 mins (180 secs)
    master_df['Pick_SLA_Met'] = np.where(master_df['Pick_Duration_Sec'] <= 180, 1, 0)
    
    # 2. Dispatch Duration Calculation
    dispatch_col = None
    for col in ['Dispatched At', 'Dispatch Time', 'Handover Time', 'Out For Delivery Time', 'Created At']:
        if col in master_df.columns:
            dispatch_col = col
            break

    if dispatch_col:
        master_df['Dispatch_Time'] = pd.to_datetime(master_df[dispatch_col], errors='coerce').dt.tz_localize(None)
        master_df['Dispatch_Duration_Sec'] = (
            (master_df['Dispatch_Time'] - master_df['Pick_Confirmed_Time']).dt.total_seconds()
        ).fillna(0)
        master_df['Dispatch_Duration_Sec'] = master_df['Dispatch_Duration_Sec'].apply(lambda x: max(x, 0))
    else:
        master_df['Dispatch_Duration_Sec'] = 0

    master_df['Dispatch Duration'] = master_df['Dispatch_Duration_Sec'].apply(format_duration)
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
