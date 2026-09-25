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
    
    # 1. Clean Column Names aggressively (removes non-breaking space '\xa0', carriage returns, spaces)
    raw_picklist.columns = (
        raw_picklist.columns.astype(str)
        .str.replace('\xa0', ' ', regex=True)
        .str.replace('\r', '', regex=True)
        .str.replace('\n', '', regex=True)
        .str.strip()
    )

    # 2. Identify Order Reference Column
    order_ref_col = None
    for c in raw_picklist.columns:
        if c.lower() in ['order reference', 'order_reference', 'order ref', 'order id', 'order_id', 'picklist']:
            order_ref_col = c
            break
            
    if not order_ref_col:
        order_ref_col = raw_picklist.columns[0]

    # Filter out blank Order References
    raw_picklist[order_ref_col] = raw_picklist[order_ref_col].astype(str).str.strip()
    raw_picklist = raw_picklist[
        raw_picklist[order_ref_col].notna() & 
        (raw_picklist[order_ref_col] != '') & 
        (raw_picklist[order_ref_col] != 'nan') &
        (raw_picklist[order_ref_col] != 'None')
    ]
    
    # Ensure numeric 'Picking Time In Seconds'
    time_col = None
    for c in raw_picklist.columns:
        if 'picking time' in c.lower() and 'second' in c.lower():
            time_col = c
            break
            
    if time_col:
        raw_picklist['Picking Time In Seconds'] = pd.to_numeric(raw_picklist[time_col], errors='coerce').fillna(0)
    else:
        raw_picklist['Picking Time In Seconds'] = 0

    # 3. Safe Dynamic Aggregation Map (builds ONLY using columns that exist)
    agg_dict = {'Picking Time In Seconds': 'max'}
    
    for col in raw_picklist.columns:
        c_lower = col.lower()
        if col == order_ref_col or col == 'Picking Time In Seconds':
            continue
        elif 'store' in c_lower or 'warehouse' in c_lower or 'picklist' in c_lower:
            if 'Store_Name_Col' not in agg_dict:
                agg_dict[col] = 'first'
        elif 'order type' in c_lower:
            agg_dict[col] = 'first'
        elif 'order date' in c_lower or 'creation' in c_lower:
            agg_dict[col] = 'first'
        elif 'confirmation' in c_lower or 'confirmed' in c_lower:
            agg_dict[col] = 'max'
        elif 'start time' in c_lower:
            agg_dict[col] = 'min'

    # Safely perform GroupBy
    pick_agg = raw_picklist.groupby(order_ref_col, as_index=False).agg(agg_dict)

    # 4. Standardize Main Column Names
    pick_agg.rename(columns={order_ref_col: 'Order_ID'}, inplace=True)

    # Identify and assign Store_Name
    store_col_found = None
    for c in pick_agg.columns:
        if c.lower() in ['warehouse', 'store', 'store name', 'picklist']:
            store_col_found = c
            break

    if store_col_found:
        pick_agg['Store_Name'] = pick_agg[store_col_found].astype(str).apply(normalize_store_name)
    else:
        pick_agg['Store_Name'] = 'TGN_HYD_HiTech'

    # Identify and assign Order_Placing_Time
    date_col_found = None
    for c in pick_agg.columns:
        if 'order date' in c.lower() or 'creation' in c.lower():
            date_col_found = c
            break

    if date_col_found:
        pick_agg['Order_Placing_Time'] = pd.to_datetime(pick_agg[date_col_found], errors='coerce').dt.tz_localize(None)
    else:
        pick_agg['Order_Placing_Time'] = pd.Timestamp.now()

    # Identify and assign Pick_Confirmed_Time
    confirm_col_found = None
    for c in pick_agg.columns:
        if 'confirmation' in c.lower() or 'confirmed' in c.lower():
            confirm_col_found = c
            break

    if confirm_col_found:
        pick_agg['Pick_Confirmed_Time'] = pd.to_datetime(pick_agg[confirm_col_found], errors='coerce').dt.tz_localize(None)

    # Identify and assign Order Type
    type_col_found = None
    for c in pick_agg.columns:
        if 'order type' in c.lower():
            type_col_found = c
            break

    if type_col_found:
        pick_agg['Order Type'] = pick_agg[type_col_found]
    else:
        pick_agg['Order Type'] = 'Express'

    # 5. Read & Process Transactions File
    df_trans = read_file_safely(transactions_file_path)
    trans_clean = df_trans.copy()
    trans_clean.columns = (
        trans_clean.columns.astype(str)
        .str.replace('\xa0', ' ', regex=True)
        .str.replace('\r', '', regex=True)
        .str.replace('\n', '', regex=True)
        .str.strip()
    )
    
    trans_id_col = 'ID' if 'ID' in trans_clean.columns else trans_clean.columns[0]
    trans_clean.rename(columns={trans_id_col: 'Order_ID'}, inplace=True)
    trans_clean['Order_ID'] = trans_clean['Order_ID'].astype(str).str.strip()
        
    status_col = 'Order State' if 'Order State' in trans_clean.columns else (trans_clean.columns[2] if len(trans_clean.columns) >= 3 else trans_clean.columns[0])

    # Filter out CANCELLED / PAYMENT FAILED
    excluded_statuses = ['PAYMENT FAILED', 'CANCELLED']
    trans_filtered = trans_clean[~trans_clean[status_col].astype(str).str.strip().str.upper().isin(excluded_statuses)].copy()

    # Left Merge Datasets
    master_df = pd.merge(pick_agg, trans_filtered, on='Order_ID', how='left')

    if 'Delivered Time' in master_df.columns:
        master_df['Delivered Time'] = pd.to_datetime(master_df['Delivered Time'], errors='coerce').dt.tz_localize(None)
    
    # 6. SLAs & Calculation Rules
    master_df['Pick_Duration_Sec'] = pd.to_numeric(master_df['Picking Time In Seconds'], errors='coerce').fillna(0)
    master_df['Pick Duration'] = master_df['Pick_Duration_Sec'].apply(format_duration)
    
    # Express SLA: Pick time <= 3 mins (180 secs)
    master_df['Pick_SLA_Met'] = np.where(master_df['Pick_Duration_Sec'] <= 180, 1, 0)
    master_df['Order_Type_Clean'] = master_df['Order Type'].astype(str).str.strip().str.lower()

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
