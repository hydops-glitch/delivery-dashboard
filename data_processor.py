import pandas as pd
import numpy as np
import io

def format_duration(minutes):
    if pd.isna(minutes) or minutes < 0:
        return "0 Min 00 Sec"
    total_seconds = int(minutes * 60)
    mins = int(total_seconds // 60)
    secs = int(total_seconds % 60)
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

def process_and_merge_reports(file_input, secondary_file=None):
    """
    Processes the ORDER_STATUS_TRANSITIONS report primary source.
    Handles single or multi-file uploads safely.
    """
    if isinstance(file_input, list) and len(file_input) > 0:
        df_list = [read_file_safely(f) for f in file_input]
        if secondary_file is not None:
            df_list.append(read_file_safely(secondary_file))
        df = pd.concat(df_list, ignore_index=True)
    else:
        df = read_file_safely(file_input)

    df.columns = (
        df.columns.astype(str)
        .str.replace('\xa0', ' ', regex=True)
        .str.replace('\r', '', regex=True)
        .str.replace('\n', '', regex=True)
        .str.strip()
    )

    # Standardize Column Names
    col_mapping = {
        'Order ID': 'Order_ID',
        'Order Type': 'Order_Type',
        'Order Status': 'Order_Status',
        'Store Name': 'Store_Name',
        'Delivery Partner': 'Delivery_Partner',
        'Rider Name': 'Rider_Name',
        'Placed Time': 'Placed_Time',
        'Packed Time': 'Packed_Time',
        'Dispatched Time': 'Dispatched_Time',
        'Completed Time': 'Completed_Time'
    }
    df.rename(columns=col_mapping, inplace=True)

    # Clean IDs & Store Names
    df['Order_ID'] = df['Order_ID'].astype(str).str.strip()
    df['Store_Name'] = df['Store_Name'].apply(normalize_store_name)
    df['Order_Type_Clean'] = df['Order_Type'].astype(str).str.strip().str.lower()
    df['Rider_Name'] = df['Rider_Name'].fillna('Unassigned').astype(str).str.strip()

    # Filter out Failed / Cancelled Orders
    df['Order_Status'] = df['Order_Status'].astype(str).str.strip().str.upper()
    df = df[~df['Order_Status'].isin(['PAYMENT FAILED', 'CANCELLED'])].copy()

    # Parse Timestamps
    time_cols = ['Placed_Time', 'Packed_Time', 'Dispatched_Time', 'Completed_Time']
    for tc in time_cols:
        if tc in df.columns:
            df[tc] = pd.to_datetime(df[tc], errors='coerce').dt.tz_localize(None)

    # 1. Express Pick SLA (Placed to Packed <= 3 Min)
    df['Pick_Duration_Min'] = (df['Packed_Time'] - df['Placed_Time']).dt.total_seconds() / 60.0
    df['Pick_Duration_Formatted'] = df['Pick_Duration_Min'].apply(format_duration)
    df['Pick_SLA_Met'] = np.where(
        (df['Order_Type_Clean'] == 'express') & (df['Pick_Duration_Min'] <= 3.0), 1, 0
    )

    # 2. Express Dispatch SLA (Placed to Dispatched <= 6 Min)
    df['Dispatch_Duration_Min'] = (df['Dispatched_Time'] - df['Placed_Time']).dt.total_seconds() / 60.0
    df['Dispatch_Duration_Formatted'] = df['Dispatch_Duration_Min'].apply(format_duration)
    df['Dispatch_SLA_Met'] = np.where(
        (df['Order_Type_Clean'] == 'express') & (df['Dispatch_Duration_Min'] <= 6.0), 1, 0
    )

    # 3. Rider Express Delivery Performance (Dispatched to Completed)
    df['Transit_Duration_Min'] = (df['Completed_Time'] - df['Dispatched_Time']).dt.total_seconds() / 60.0

    # 4. Delivery SLA Compliance (Customer Slot / Promised Delivery)
    if 'Was Undelivered' in df.columns:
        df['On_Time_Delivered'] = np.where(df['Was Undelivered'].astype(str).str.upper() == 'N', 1, 0)
    else:
        df['On_Time_Delivered'] = 1

    # Rider Channel Mapping
    if 'Delivery_Partner' in df.columns:
        df['Rider_Channel'] = np.where(
            df['Delivery_Partner'].astype(str).str.upper() == 'SELF', 'Self (In-House)', '3PL Partner'
        )
    else:
        df['Rider_Channel'] = 'Self (In-House)'

    return df
