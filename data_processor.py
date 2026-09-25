import pandas as pd
import numpy as np

def process_and_merge_reports(file_list):
    dfs = []
    for f in file_list:
        try:
            if f.name.endswith('.csv'):
                temp = pd.read_csv(f)
            else:
                temp = pd.read_excel(f)
            dfs.append(temp)
        except Exception:
            continue
            
    if not dfs:
        return pd.DataFrame()
    
    df = pd.concat(dfs, ignore_index=True)
    
    # Standardize column names (strip whitespace & replace spaces/dots)
    df.columns = [str(c).strip().replace(' ', '_').replace('.', '_') for c in df.columns]
    
    # Lowercase lookup map
    col_map = {str(c).lower(): c for c in df.columns}
    
    # Date parsing
    date_col = next((col_map[k] for k in col_map if any(x in k for x in ['placed', 'order_date', 'created', 'date'])), None)
    if date_col:
        df['Placed_Time'] = pd.to_datetime(df[date_col], errors='coerce')
    else:
        df['Placed_Time'] = pd.Timestamp.now()

    # Store Name mapping
    store_col = next((col_map[k] for k in col_map if 'store' in k or 'hub' in k or 'facility' in k), None)
    if store_col:
        df['Store_Name'] = df[store_col].astype(str)
    elif 'Store_Name' not in df.columns:
        df['Store_Name'] = 'TGN_HYD_BHills'
        
    # Order type identification
    type_col = next((col_map[k] for k in col_map if 'type' in k or 'channel' in k or 'category' in k), None)
    if type_col:
        df['Order_Type_Clean'] = df[type_col].astype(str).str.lower().apply(
            lambda x: 'express' if any(k in x for k in ['express', '15', '30', 'exp', 'quick']) else 'standard'
        )
    else:
        df['Order_Type_Clean'] = 'standard'
        
    # Fulfillment Type (Self vs 3PL)
    deliv_mode_col = next((col_map[k] for k in col_map if any(x in k for x in ['mode', 'rider_type', 'fulfillment', 'fleet', '3pl'])), None)
    if deliv_mode_col:
        df['Fulfillment_Type'] = df[deliv_mode_col].astype(str).apply(
            lambda x: '3PL' if any(k in x.lower() for k in ['shadowfax', 'grab', 'porter', '3pl', 'third', 'external']) else 'Self'
        )
    else:
        df['Fulfillment_Type'] = 'Self'
        
    # Order Status mapping
    status_col = next((col_map[k] for k in col_map if 'status' in k or 'state' in k), None)
    if status_col:
        df['Order_Status'] = df[status_col].astype(str).str.upper().apply(
            lambda x: 'DELIVERED' if any(k in x for k in ['DELIVERED', 'COMPLETED', 'DISPATCHED', 'SUCCESS']) else x
        )
    else:
        df['Order_Status'] = 'DELIVERED'

    # SLA Metrics
    pick_col = next((col_map[k] for k in col_map if 'pick' in k or 'pack' in k), None)
    if pick_col and pd.api.types.is_numeric_dtype(df[pick_col]):
        df['Pick_SLA_Met'] = np.where(df[pick_col] <= 3, 1, 0)
    else:
        df['Pick_SLA_Met'] = 1

    disp_col = next((col_map[k] for k in col_map if 'dispatch' in k), None)
    if disp_col and pd.api.types.is_numeric_dtype(df[disp_col]):
        df['Dispatch_SLA_Met'] = np.where(df[disp_col] <= 6, 1, 0)
    else:
        df['Dispatch_SLA_Met'] = 1

    delay_col = next((col_map[k] for k in col_map if 'delay' in k or 'sla' in k or 'on_time' in k), None)
    if delay_col and pd.api.types.is_numeric_dtype(df[delay_col]):
        df['On_Time_Delivered'] = np.where(df[delay_col] <= 0, 1, 0)
    else:
        df['On_Time_Delivered'] = 1

    # Defensive Transit Duration Column
    transit_col = next((col_map[k] for k in col_map if 'transit' in k or 'delivery_time' in k or 'duration' in k), None)
    if transit_col and pd.api.types.is_numeric_dtype(df[transit_col]):
        df['Transit_Duration_Min'] = pd.to_numeric(df[transit_col], errors='coerce').fillna(0.0)
    else:
        df['Transit_Duration_Min'] = 0.0

    # Rider Name Column
    rider_col = next((col_map[k] for k in col_map if 'rider' in k or 'driver' in k or 'agent' in k), None)
    if rider_col:
        df['Rider_Name'] = df[rider_col].astype(str)
    else:
        df['Rider_Name'] = 'Unassigned'
        
    if 'Order_ID' not in df.columns:
        id_col = next((col_map[k] for k in col_map if 'id' in k or 'number' in k or 'code' in k), None)
        df['Order_ID'] = df[id_col].astype(str) if id_col else [f"ORD_{i}" for i in range(len(df))]

    # Formatting helpers
    df['Pick_Duration_Formatted'] = df[pick_col].astype(str) if pick_col else "0m"
    df['Dispatch_Duration_Formatted'] = df[disp_col].astype(str) if disp_col else "0m"
    if 'Order_Type' not in df.columns:
        df['Order_Type'] = df['Order_Type_Clean']
        
    return df
