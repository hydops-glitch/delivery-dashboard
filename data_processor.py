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
    df.columns = [str(c).strip() for c in df.columns]

    # Required Column Mapping based on exact file structure
    col_map = {str(c).lower(): c for c in df.columns}
    date_col = next((col_map[k] for k in col_map if 'placed time' in k or 'order date' in k), None)
    store_col = next((col_map[k] for k in col_map if 'store name' in k or 'store' in k), None)
    status_col = next((col_map[k] for k in col_map if 'order status' in k or 'status' in k), None)

    if not date_col or not store_col or not status_col:
        return pd.DataFrame(), ["Missing core columns ('Placed Time', 'Store Name', or 'Order Status')."]

    df['Placed_Time'] = pd.to_datetime(df[date_col], errors='coerce')
    df['Store_Name'] = df[store_col].astype(str)
    df['Raw_Status'] = df[status_col].astype(str).str.upper()

    # RULE 1 & 2: EXCLUDE PAYMENT FAILED AND CANCELLED
    df = df[~df['Raw_Status'].isin(['PAYMENT FAILED', 'CANCELLED'])].copy()

    # Order Type Mapping
    type_col = next((col_map[k] for k in col_map if 'order type' in k), None)
    if type_col:
        df['Order_Type_Clean'] = df[type_col].astype(str).str.lower().apply(
            lambda x: 'express' if any(k in x for k in ['express', '15', '30', 'exp', 'quick']) else 'standard'
        )
    else:
        df['Order_Type_Clean'] = 'standard'

    # Fulfillment Partner & Mode Mapping (3PL vs Self)
    partner_col = next((col_map[k] for k in col_map if 'delivery partner' in k or 'fulfillment mode' in k), None)
    if partner_col:
        p_str = df[partner_col].astype(str).str.upper()
        df['Fulfillment_Type'] = np.where(
            p_str.str.contains('SELF', na=False), 'Self', '3PL'
        )
    else:
        df['Fulfillment_Type'] = 'Self'

    # Rider Column
    rider_col = next((col_map[k] for k in col_map if 'rider name' in k), None)
    df['Rider_Name'] = df[rider_col].fillna('Unassigned').astype(str) if rider_col else 'Unassigned'

    # Order ID
    id_col = next((col_map[k] for k in col_map if 'order id' in k), None)
    df['Order_ID'] = df[id_col].astype(str) if id_col else [f"ORD_{i}" for i in range(len(df))]

    # TIMESTAMPS & EXACT DELAY MINUTE CALCULATIONS
    pick_time_col = next((col_map[k] for k in col_map if 'packed time' in k), None)
    disp_time_col = next((col_map[k] for k in col_map if 'dispatched time' in k), None)
    comp_time_col = next((col_map[k] for k in col_map if 'completed time' in k), None)

    df['Packed_Time'] = pd.to_datetime(df[pick_time_col], errors='coerce') if pick_time_col else pd.NaT
    df['Dispatched_Time'] = pd.to_datetime(df[disp_time_col], errors='coerce') if disp_time_col else pd.NaT
    df['Completed_Time'] = pd.to_datetime(df[comp_time_col], errors='coerce') if comp_time_col else pd.NaT

    # Exact Delay Minutes
    df['Pick_Delay_Min'] = (df['Packed_Time'] - df['Placed_Time']).dt.total_seconds() / 60.0
    df['Dispatch_Delay_Min'] = (df['Dispatched_Time'] - df['Packed_Time']).dt.total_seconds() / 60.0
    df['Delivery_Delay_Min'] = (df['Completed_Time'] - df['Dispatched_Time']).dt.total_seconds() / 60.0

    # SLAs (3 min pick, 6 min dispatch, 30 min delivery for express)
    df['Pick_SLA_Met'] = np.where(df['Pick_Delay_Min'] <= 15, 1, 0)
    df['Dispatch_SLA_Met'] = np.where(df['Dispatch_Delay_Min'] <= 10, 1, 0)
    df['On_Time_Delivered'] = np.where(df['Delivery_Delay_Min'] <= 45, 1, 0)

    df['Order_Status'] = np.where(df['Raw_Status'] == 'DELIVERED', 'DELIVERED', df['Raw_Status'])
    df['Order_Type'] = df['Order_Type_Clean']

    return df, []
