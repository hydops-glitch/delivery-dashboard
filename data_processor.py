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
        return "TGN_HYD_HiTech"
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
    
    # Clean column header spaces
    raw_picklist.columns = raw_picklist.columns.astype(str).str.strip()

    # 1. Detect Order Reference column
    order_ref_col = None
    for c in ['Order Reference', 'Order_Reference', 'Order Ref', 'Order ID', 'Order_ID', 'Picklist']:
        if c in raw_picklist.columns:
            order_ref_col = c
            break
            
    if not order_ref_col:
        order_ref_col = raw_picklist.columns[0]

    # Filter out blank Order Reference values
    raw_picklist[order_ref_col] = raw_picklist[order_ref_col].astype(str).str.strip()
    raw_picklist = raw_picklist[
        raw_picklist[order_ref_col].notna() & 
        (raw_picklist[order_ref_col] != '') & 
        (raw_picklist[order_ref_col] != 'nan') &
        (raw_picklist[order_ref_col] != 'None')
    ]
    
    # 2. Convert Picking Time In Seconds
    if 'Picking Time In Seconds' in raw_picklist.columns:
        raw_picklist['Picking Time In Seconds'] = pd.to_numeric(raw_picklist['Picking Time In Seconds'], errors='coerce').fillna(0)
    else:
        raw_picklist['Picking Time In Seconds'] = 0

    # 3. Build Dynamic Aggregation Map (ONLY for columns present in the file)
    agg_dict = {}
    
    # Store / Warehouse detection
    store_col = None
    for sc in ['Store Name', 'Store', 'Warehouse', 'Picklist']:
        if sc in raw_picklist.columns:
            store_col = sc
            agg_dict[sc] = 'first'
            break

    # Order type detection
    if 'Order Type' in raw_picklist.columns:
        agg_dict['Order Type'] = 'first'
        
    # Date/Time Column Mappings
    if 'Order Date' in raw_picklist.columns:
        agg_dict['Order Date'] = 'first'
    if 'Picklist Creation Date&Time' in raw_picklist.columns:
        agg_dict['Picklist Creation Date&Time'] = 'first'
    if 'Picking Start Time' in raw_picklist.columns:
        agg_dict['Picking Start Time'] = 'min'
    if 'Picklist Confirmation Date&Time' in raw_picklist.columns:
        agg_dict['Picklist Confirmation Date&Time'] = 'max'
        
    # Standard mandatory duration metric
    agg_dict['Picking Time In Seconds'] = 'max'

    # Perform Safe Deduplication Groupby
    pick_agg = raw_picklist.groupby(order_ref_col).agg(agg_dict).reset_index()

    # Rename Key Columns
    rename_dict = {order_ref_col: 'Order_ID'}
    if 'Order Date' in pick_agg.columns:
        rename_dict['Order Date'] = 'Order_Placing_Time'
    elif 'Picklist Creation Date&Time' in pick_agg.columns:
        rename_dict['Picklist Creation Date&Time'] = 'Order_Placing_Time'

    if 'Picklist Confirmation Date&Time' in pick_agg.columns:
        rename_dict['Picklist Confirmation Date&Time'] = 'Pick_Confirmed_Time'

    pick_agg.rename(columns=rename_dict, inplace=True)

    # Normalize Store Name
    if store_col and store_col in pick_agg.columns:
        pick_agg['Store_Name'] = pick_agg[store_col].astype(str).apply(normalize_store_name)
    else:
        pick_agg['Store_Name'] = 'TGN_HYD_HiTech'

    # Ensure Order Type exists
    if 'Order Type' not in pick_agg.columns:
        pick_agg['Order Type'] = 'Express'

    # 4. Read Transactions Data
    df_trans = read_file_safely(transactions_file_path)
    trans_clean = df_trans.copy()
    trans_clean.columns = trans_clean.columns.astype(str).str.strip()
    
    trans_id_col = 'ID' if 'ID' in trans_clean.columns else trans_clean.columns[0]
    trans_clean.rename(columns={trans_id_col: 'Order_ID'}, inplace=True)
    trans_clean['Order_ID'] = trans_clean['Order_ID'].astype(str).str.strip()
        
    status_col = 'Order State' if 'Order State' in trans_clean.columns else (trans_clean.columns[2] if len(trans_clean.columns) >= 3 else trans_clean.columns[0])

    # Filter out CANCELLED / PAYMENT FAILED
    excluded_statuses = ['PAYMENT FAILED', 'CANCELLED']
    trans_filtered = trans_clean[~trans_clean[status_col].astype(str).str.strip().str.upper().isin(excluded_statuses)].copy()

    # Merge Datasets
    master_df = pd.merge(pick_agg, trans_filtered, on='Order_ID', how='left')

    # Parse Dates
    if 'Order_Placing_Time' in master_df.columns:
        master_df['Order_Placing_Time'] = pd.to_datetime(master_df['Order_Placing_Time'], errors='coerce').dt.tz_localize(None)
    else:
        master_df['Order_Placing_Time'] = pd.Timestamp.now()

    if 'Pick_Confirmed_Time' in master_df.columns:
        master_df['Pick_Confirmed_Time'] = pd.to_datetime(master_df['Pick_Confirmed_Time'], errors='coerce').dt.tz_localize(None)
    
    if 'Delivered Time' in master_df.columns:
        master_df['Delivered Time'] = pd.to_datetime(master_df['Delivered Time'], errors='coerce').dt.tz_localize(None)
    
    # 5. Calculate Picking Durations & SLAs
    master_df['Pick_Duration_Sec'] = pd.to_numeric(master_df['Picking Time In Seconds'], errors='coerce').fillna(0)
    master_df['Pick Duration'] = master_df['Pick_Duration_Sec'].apply(format_duration)
    
    # Express SLA: Pick time <= 3 mins (180 secs)
    master_df['Pick_SLA_Met'] = np.where(master_df['Pick_Duration_Sec'] <= 180, 1, 0)
    master_df['Order_Type_Clean'] = master_df['Order Type'].astype(str).str.strip().str.lower()

    # Delivery SLA & Channel Parsing
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
