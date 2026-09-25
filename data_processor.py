import pandas as pd
import numpy as np

def process_and_merge_reports(file_list):
    dfs = []
    validation_errors = []
    
    for f in file_list:
        try:
            if f.name.endswith('.csv'):
                temp = pd.read_csv(f)
            else:
                temp = pd.read_excel(f)
            dfs.append(temp)
        except Exception as e:
            validation_errors.append(f"Could not read file {f.name}: {str(e)}")
            continue
            
    if not dfs:
        return pd.DataFrame(), ["No readable CSV or Excel files found."]
    
    df = pd.concat(dfs, ignore_index=True)
    
    # Standardize column headers for matching
    df.columns = [str(c).strip().replace(' ', '_').replace('.', '_') for c in df.columns]
    col_map = {str(c).lower(): c for c in df.columns}

    # Strict dynamic column identification
    date_col = next((col_map[k] for k in col_map if any(x in k for x in ['placed', 'order_date', 'created_at', 'order_time', 'date'])), None)
    store_col = next((col_map[k] for k in col_map if any(x in k for x in ['store', 'hub', 'facility', 'branch'])), None)
    
    if not date_col:
        validation_errors.append("Missing required date/time column in uploaded report (e.g., 'Placed_Time', 'Order_Date').")
    if not store_col:
        validation_errors.append("Missing required store identifier column in uploaded report (e.g., 'Store_Name', 'Hub').")

    if validation_errors:
        return pd.DataFrame(), validation_errors

    # Process Date & Store
    df['Placed_Time'] = pd.to_datetime(df[date_col], errors='coerce')
    df['Store_Name'] = df[store_col].astype(str)

    # Order Type Identification
    type_col = next((col_map[k] for k in col_map if any(x in k for x in ['type', 'channel', 'category', 'service'])), None)
    if type_col:
        df['Order_Type_Clean'] = df[type_col].astype(str).str.lower().apply(
            lambda x: 'express' if any(k in x for k in ['express', '15', '30', 'exp', 'quick']) else 'standard'
        )
    else:
        df['Order_Type_Clean'] = 'standard'

    # Fulfillment Type
    deliv_mode_col = next((col_map[k] for k in col_map if any(x in k for x in ['mode', 'rider_type', 'fulfillment', 'fleet', '3pl', 'partner'])), None)
    if deliv_mode_col:
        df['Fulfillment_Type'] = df[deliv_mode_col].astype(str).apply(
            lambda x: '3PL' if any(k in x.lower() for k in ['shadowfax', 'grab', 'porter', '3pl', 'third', 'external']) else 'Self'
        )
    else:
        df['Fulfillment_Type'] = 'Self'

    # Order Status
    status_col = next((col_map[k] for k in col_map if any(x in k for x in ['status', 'state', 'stage'])), None)
    if status_col:
        df['Order_Status'] = df[status_col].astype(str).str.upper().apply(
            lambda x: 'DELIVERED' if any(k in x for k in ['DELIVERED', 'COMPLETED', 'DISPATCHED', 'SUCCESS']) else x
        )
    else:
        df['Order_Status'] = 'DELIVERED'

    # STRICT SLA CALCULATION - NO FAKE DEFAULT 100%
    pick_col = next((col_map[k] for k in col_map if any(x in k for x in ['pick_duration', 'pack_duration', 'pick_sla', 'pack_time'])), None)
    if pick_col and pd.api.types.is_numeric_dtype(df[pick_col]):
        df['Pick_SLA_Met'] = np.where(df[pick_col] <= 3, 1, 0)
    else:
        # Check boolean or status string column if numeric duration is absent
        pick_status_col = next((col_map[k] for k in col_map if 'pick' in k or 'pack' in k), None)
        if pick_status_col:
            df['Pick_SLA_Met'] = df[pick_status_col].astype(str).str.lower().apply(
                lambda x: 1 if any(k in x for k in ['met', 'pass', '1', 'true', 'on_time']) else 0
            )
        else:
            df['Pick_SLA_Met'] = np.nan  # Set as NaN so missing SLA data isn't disguised as 100%

    disp_col = next((col_map[k] for k in col_map if any(x in k for x in ['dispatch_duration', 'dispatch_sla', 'dispatch_time'])), None)
    if disp_col and pd.api.types.is_numeric_dtype(df[disp_col]):
        df['Dispatch_SLA_Met'] = np.where(df[disp_col] <= 6, 1, 0)
    else:
        disp_status_col = next((col_map[k] for k in col_map if 'dispatch' in k), None)
        if disp_status_col:
            df['Dispatch_SLA_Met'] = df[disp_status_col].astype(str).str.lower().apply(
                lambda x: 1 if any(k in x for k in ['met', 'pass', '1', 'true', 'on_time']) else 0
            )
        else:
            df['Dispatch_SLA_Met'] = np.nan

    delay_col = next((col_map[k] for k in col_map if any(x in k for x in ['delay', 'delivery_sla', 'on_time', 'breach'])), None)
    if delay_col and pd.api.types.is_numeric_dtype(df[delay_col]):
        df['On_Time_Delivered'] = np.where(df[delay_col] <= 0, 1, 0)
    else:
        del_status_col = next((col_map[k] for k in col_map if 'delivery' in k or 'sla' in k), None)
        if del_status_col:
            df['On_Time_Delivered'] = df[del_status_col].astype(str).str.lower().apply(
                lambda x: 1 if any(k in x for k in ['met', 'pass', '1', 'true', 'on_time']) else 0
            )
        else:
            df['On_Time_Delivered'] = np.nan

    # Transit duration & Rider columns
    transit_col = next((col_map[k] for k in col_map if any(x in k for x in ['transit', 'delivery_time', 'duration'])), None)
    df['Transit_Duration_Min'] = pd.to_numeric(df[transit_col], errors='coerce').fillna(0.0) if transit_col else 0.0

    rider_col = next((col_map[k] for k in col_map if any(x in k for x in ['rider', 'driver', 'agent', 'fleet'])), None)
    df['Rider_Name'] = df[rider_col].astype(str) if rider_col else 'Unassigned'

    id_col = next((col_map[k] for k in col_map if any(x in k for x in ['order_id', 'order_number', 'id', 'code'])), None)
    df['Order_ID'] = df[id_col].astype(str) if id_col else [f"ORD_{i}" for i in range(len(df))]

    df['Pick_Duration_Formatted'] = df[pick_col].astype(str) if pick_col else "N/A"
    df['Dispatch_Duration_Formatted'] = df[disp_col].astype(str) if disp_col else "N/A"
    df['Order_Type'] = df['Order_Type_Clean']

    return df, []
