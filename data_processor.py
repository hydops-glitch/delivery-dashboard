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
    
    try:
        df_trans = pd.read_excel(transactions_file_path)
    except Exception:
        df_trans = pd.read_csv(transactions_file_path)
        
    trans_clean = df_trans[[
        'ID', 'Delivery Partner', 'Created At', 'Delivered Time', 
        'On Time Delivered', 'Order State'
    ]].copy()
    trans_clean.rename(columns={'ID': 'Order_ID'}, inplace=True)
    
    master_df = pd.merge(pick_agg, trans_clean, on='Order_ID', how='inner')
    
    master_df['Order_Placing_Time'] = pd.to_datetime(master_df['Order_Placing_Time'])
    master_df['Pick_Confirmed_Time'] = pd.to_datetime(master_df['Pick_Confirmed_Time'])
    master_df['Delivered Time'] = pd.to_datetime(master_df['Delivered Time'])
    
    # Calculate picking duration in total seconds
    master_df['Pick_Duration_Sec'] = (
        (master_df['Pick_Confirmed_Time'] - master_df['Order_Placing_Time']).dt.total_seconds()
    ).fillna(0)
    
    # Format to readable string "X Min Y Sec"
    master_df['Pick Duration'] = master_df['Pick_Duration_Sec'].apply(format_duration)
    
    # Rule: Picking SLA met if duration <= 3 minutes (180 seconds)
    master_df['Pick_SLA_Met'] = np.where(master_df['Pick_Duration_Sec'] <= 180, 1, 0)
    master_df['Pick Status'] = np.where(master_df['Pick_SLA_Met'] == 1, 'On Time', 'Breached')
    
    # Delivery SLA formatting
    master_df['Delivery Status'] = np.where(master_df['On Time Delivered'] == 1, 'On Time', 'Breached')
    
    master_df['Rider_Channel'] = np.where(
        master_df['Delivery Partner'].astype(str).str.upper() == 'SELF', 'In-House Rider', '3PL Partner'
    )
    
    if 'Picking_Delay_Reason' not in master_df.columns:
        master_df['Picking_Delay_Reason'] = ''
    if 'Delivery_Delay_Reason' not in master_df.columns:
        master_df['Delivery_Delay_Reason'] = ''
        
    return master_df
