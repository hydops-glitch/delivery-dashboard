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

    try:
        return pd.read_excel(io.BytesIO(content))
    except Exception:
        pass

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

def normalize_store_name(name):
    """Normalizes store name variations across different source reports."""
    if pd.isna(name):
        return "Unknown Store"
    s = str(name).strip().upper()
    if 'HITECH' in s or 'HI_TECH' in s:
        return 'TGN_HYD_HiTech'
    elif 'BHILLS' in s or 'BANJARA' in s:
        return 'TGN_HYD_BHills'
    elif 'MANIKONDA' in s:
        return 'TGN_HYD_Manikonda'
    return str(name).strip()

def process_and_merge_reports(picklist_files_list, transactions_file_path):
    picklist_frames = []
    for file in picklist_files_list:
        df = read_file_safely(file)
        picklist_frames.append(df)
    
    raw_picklist = pd.concat(picklist_frames, ignore_index=True)
    
    # 1. Clean Order Reference & drop blank/empty values
    if 'Order Reference' in raw_picklist.columns:
        raw_picklist['Order Reference'] = raw_picklist['Order Reference'].astype(str).str.strip()
        raw_picklist = raw_picklist[
            raw_picklist['Order Reference'].notna() & 
            (raw_picklist['Order Reference'] != '') & 
            (raw_picklist['Order Reference'] != 'nan') &
            (raw_picklist['Order Reference'] != 'None')
        ]
    
    # 2. Ensure numeric picking time in seconds
    if 'Picking Time In Seconds' in raw_picklist.columns:
        raw_picklist['Picking Time In Seconds'] = pd.to_numeric(raw_picklist['Picking Time In Seconds'], errors='coerce').fillna(0)
    else:
        raw_picklist['Picking Time In Seconds'] = 0

    # 3. Deduplicate at Order Level to resolve SKU duplicate rows
    pick_agg = raw_picklist.groupby('Order Reference').agg({
        'Warehouse': 'first',
        'Picklist': 'first',
        'Order Date': 'first',
        'Order Type': 'first',
        'Picklist Creation Date&Time': 'first',
        'Picking Start Time': 'min',
        'Picklist Confirmation Date&Time': 'max',
        'Picking Time In Seconds': 'max',
        'Picker Name': 'first' if 'Picker Name' in raw_picklist.columns else 'first'
    }).reset_index()
    
    # Resolve warehouse name mismatch between Picklist/Warehouse columns
    if 'Picklist' in pick_agg.columns:
        pick_agg['Warehouse_Clean'] = pick_agg['Picklist'].astype(str).apply(normalize_store_name)
    else:
        pick_agg['Warehouse_Clean'] = pick_agg['Warehouse'].astype(str).apply(normalize_store_name)
    
    pick_agg.rename(columns={
        'Order Reference': 'Order_ID',
        'Warehouse_Clean': 'Store_Name',
        'Order Date': 'Order_Placing_Time',
        'Picklist Creation Date&Time': 'Pick_Created_Time',
        'Picklist Confirmation Date&Time': 'Pick_Confirmed_Time'
    }, inplace=True)
    
    # 4. Read Transactions Data
    df_trans = read_file_safely(transactions_file_path)
    trans_clean = df_trans.copy()
    
    if 'ID' in trans_clean.columns:
        trans_clean.rename(columns={'ID': 'Order_ID'}, inplace=True)
    
    trans_clean['Order_ID'] = trans_clean['Order_ID'].astype(str).str.strip()
        
    status_col = 'Order State' if 'Order State' in trans_clean.columns else (trans_clean.columns[2] if len(trans_clean.columns) >= 3 else 'Status')

    # Exclude PAYMENT FAILED and CANCELLED orders
    excluded_statuses = ['PAYMENT FAILED', 'CANCELLED']
    trans_filtered = trans_clean[~trans_clean[status_col].astype(str).str.strip().str.upper().isin(excluded_statuses)].copy()

    # Left Merge to maintain all orders from Picklist
    master_df = pd.merge(pick_agg, trans_filtered, on='Order_ID', how='left')
    
    if 'Store_Name' not in master_df.columns or master_df['Store_Name'].isna().all():
        master_df['Store_Name'] = master_df['Warehouse'].apply(normalize_store_name)

    # Date Parsing
    if 'Order_Placing_Time' in master_df.columns:
        master_df['Order_Placing_Time'] = pd.to_datetime(master_df['Order_Placing_Time'], errors='coerce').dt.tz_localize(None)
        
    master_df['Pick_Confirmed_Time'] = pd.to_datetime(master_df['Pick_Confirmed_Time'], errors='coerce').dt.tz_localize(None)
    
    if 'Delivered Time' in master_df.columns:
        master_df['Delivered Time'] = pd.to_datetime(master_df['Delivered Time'], errors='coerce').dt.tz_localize(None)
    
    # 5. Picking Duration & SLA Calculation
    master_df['Pick_Duration_Sec'] = master_df['Picking Time In Seconds']
    master_df['Pick Duration'] = master_df['Pick_Duration_Sec'].apply(format_duration)
    
    # Pick SLA: Express <= 3 mins (180 seconds)
    master_df['Pick_SLA_Met'] = np.where(master_df['Pick_Duration_Sec'] <= 180, 1, 0)
    
    # Clean Order Type column
    if 'Order Type' in master_df.columns:
        master_df['Order_Type_Clean'] = master_df['Order Type'].astype(str).str.strip().str.lower()
    else:
        master_df['Order_Type_Clean'] = 'planned'

    # 6. Delivery SLA & Channel
    if 'On Time Delivered' in master_df.columns:
        master_df['On Time Delivered'] = pd.to_numeric(master_df['On Time Delivered'], errors='coerce').fillna(0)
    else:
        master_df['On Time Delivered'] = 0

    if 'Delivery Partner' in master_df.columns:
        master_df['Rider_Channel'] = np.where(
            master_df['Delivery Partner'].astype(str).str.upper() == 'SELF', 'Self (In-House)', '3PL Partner'
        )
    else:
        master_df['Delivery Partner'] = 'Unknown'
        master_df['Rider_Channel'] = '3PL Partner'
    
    return master_df
