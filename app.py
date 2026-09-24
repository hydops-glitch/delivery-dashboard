import streamlit as st
import pandas as pd
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from data_processor import process_and_merge_reports

st.set_page_config(page_title="Fulfilment & Delivery Dashboard", layout="wide")

@st.cache_resource
def get_gspread_client():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def load_saved_remarks():
    try:
        client = get_gspread_client()
        sheet_id = st.secrets["sheets"]["spreadsheet_id"]
        sheet = client.open_by_key(sheet_id).sheet1
        records = sheet.get_all_records()
        return pd.DataFrame(records)
    except Exception:
        return pd.DataFrame(columns=[
            'Order_ID', 'Store_Name', 'Delay_Type', 
            'Order_Type', 'Delay_Reason', 'Submitted_By', 'Timestamp'
        ])

def append_saved_remark(order_id, store_name, delay_type, order_type, delay_reason):
    try:
        client = get_gspread_client()
        sheet_id = st.secrets["sheets"]["spreadsheet_id"]
        sheet = client.open_by_key(sheet_id).sheet1
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([
            str(order_id), str(store_name), str(delay_type), 
            str(order_type), str(delay_reason), "Team", timestamp
        ])
        return True
    except Exception as e:
        st.error(f"Error saving remark: {e}")
        return False

# --- SIDEBAR ---
st.sidebar.header("📁 Step 1: Upload Daily Data")
picklist_files = st.sidebar.file_uploader("Upload Store Picklist Reports (.xls/.csv)", accept_multiple_files=True)
transaction_file = st.sidebar.file_uploader("Upload Order Transactions Report (.xlsx/.csv)")

saved_db = load_saved_remarks()
saved_order_ids = set(saved_db['Order_ID'].astype(str).unique()) if not saved_db.empty else set()

if picklist_files and transaction_file:
    master_df = process_and_merge_reports(picklist_files, transaction_file)
    st.sidebar.success("Reports processed successfully!")
    
    # --- TOP ROW CONTROLS ---
    col_store, col_filter_type, col_picker = st.columns([2, 2, 3])
    
    stores = ['All Stores (HYD Region)'] + sorted(list(master_df['Store_Name'].unique()))
    with col_store:
        selected_store = st.selectbox("🏬 Select Store / Location", stores)
    
    if selected_store != 'All Stores (HYD Region)':
        filtered_df = master_df[master_df['Store_Name'] == selected_store].copy()
        header_title = f"🏬 Store Performance: {selected_store}"
    else:
        filtered_df = master_df.copy()
        header_title = "🌐 HYD Region Performance Overview"
        
    with col_filter_type:
        date_filter_mode = st.radio("📅 Date Filter Mode", ["Reporting Cycle", "Custom Date Range"], horizontal=True)
        
    today_day = datetime.date.today().day
    default_cycle_idx = 0 if today_day <= 7 else (1 if today_day <= 14 else (2 if today_day <= 21 else 3))

    with col_picker:
        if date_filter_mode == "Reporting Cycle":
            cycle_period = st.selectbox(
                "Select Cycle",
                ["Cycle 1 (1st - 7th)", "Cycle 2 (8th - 14th)", "Cycle 3 (15th - 21st)", "Cycle 4 (22nd - End)"],
                index=default_cycle_idx
            )
            if cycle_period == "Cycle 1 (1st - 7th)":
                filtered_df = filtered_df[filtered_df['Order_Placing_Time'].dt.day.between(1, 7)]
            elif cycle_period == "Cycle 2 (8th - 14th)":
                filtered_df = filtered_df[filtered_df['Order_Placing_Time'].dt.day.between(8, 14)]
            elif cycle_period == "Cycle 3 (15th - 21st)":
                filtered_df = filtered_df[filtered_df['Order_Placing_Time'].dt.day.between(15, 21)]
            elif cycle_period == "Cycle 4 (22nd - End)":
                filtered_df = filtered_df[filtered_df['Order_Placing_Time'].dt.day >= 22]
        else:
            date_range = st.date_input("Select Date Range", value=(datetime.date.today() - datetime.timedelta(days=7), datetime.date.today()))
            if isinstance(date_range, tuple) and len(date_range) == 2:
                start_date, end_date = date_range
                filtered_df = filtered_df[
                    (filtered_df['Order_Placing_Time'].dt.date >= start_date) & 
                    (filtered_df['Order_Placing_Time'].dt.date <= end_date)
                ]

    st.title(header_title)
    st.markdown("---")

    # --- KPI HIGHLIGHTS ---
    st.subheader("🎯 KPI Highlights")
    
    exp_df = filtered_df[filtered_df['Order Type'].str.lower() == 'express']
    sched_df = filtered_df[filtered_df['Order Type'].str.lower() != 'express']
    
    # 1. Express Packed %
    exp_packed_pct = (exp_df['Pick_SLA_Met'].sum() / len(exp_df) * 100) if len(exp_df) > 0 else 0
    # 2. Express Dispatch % (> 6 min considered breach)
    exp_dispatch_pct = (exp_df['Dispatch_SLA_Met'].sum() / len(exp_df) * 100) if len(exp_df) > 0 else 0
    # 3. Express & Scheduled Delivered %
    exp_del_pct = (exp_df['On Time Delivered'].sum() / len(exp_df) * 100) if len(exp_df) > 0 else 0
    sched_del_pct = (sched_df['On Time Delivered'].sum() / len(sched_df) * 100) if len(sched_df) > 0 else 0
    # 4. Avg Orders done by Self and 3PL
    num_days = max((filtered_df['Order_Placing_Time'].dt.date.nunique()), 1)
    self_orders_avg = (filtered_df['Rider_Channel'] == 'Self (In-House)').sum() / num_days
    tpl_orders_avg = (filtered_df['Rider_Channel'] == '3PL Partner').sum() / num_days
    
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Express Packed SLA (≤3m)", f"{exp_packed_pct:.1f}%")
    k2.metric("Express Dispatch SLA (≤6m)", f"{exp_dispatch_pct:.1f}%")
    k3.metric("Express Delivered %", f"{exp_del_pct:.1f}%")
    k4.metric("Scheduled Delivered %", f"{sched_del_pct:.1f}%")
    k5.metric("Avg Orders (Self / 3PL)", f"{self_orders_avg:.0f} / {tpl_orders_avg:.0f} per day")

    st.markdown("---")

    # --- TABS FOR REMARKS ---
    tab_pick, tab_disp, tab_del, tab_mgr = st.tabs([
        "⚡ Express Packing Delays (>3m)", 
        "🚀 Express Dispatch Delays (>6m)",
        "🚚 Delivery Delays", 
        "📊 Manager Review"
    ])
    
    with tab_pick:
        st.subheader("Express Packing Breaches (Only Express)")
        exp_pick_breached = exp_df[
            (exp_df['Pick_SLA_Met'] == 0) & 
            (~exp_df['Order_ID'].astype(str).isin(saved_order_ids))
        ].copy()
        
        if not exp_pick_breached.empty:
            for idx, row in exp_pick_breached.iterrows():
                c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 3, 2])
                c1.write(f"**{row['Order_ID']}**")
                c2.write(row['Store_Name'])
                c3.write(f"Duration: {row['Pick Duration']}")
                reason_input = c4.text_input("Reason", key=f"p_reason_{row['Order_ID']}", placeholder="Enter packing delay reason...")
                if c5.button("Submit & Hide", key=f"p_btn_{row['Order_ID']}"):
                    if reason_input.strip() != "":
                        if append_saved_remark(row['Order_ID'], row['Store_Name'], "Express Packing Delay", "Express", reason_input.strip()):
                            st.success(f"Saved: {row['Order_ID']}")
                            st.rerun()
                st.divider()
        else:
            st.success("🎉 Zero pending Express packing delays!")

    with tab_disp:
        st.subheader("Express Dispatch Breaches (> 6 Min)")
        exp_disp_breached = exp_df[
            (exp_df['Dispatch_SLA_Met'] == 0) & 
            (~exp_df['Order_ID'].astype(str).isin(saved_order_ids))
        ].copy()
        
        if not exp_disp_breached.empty:
            for idx, row in exp_disp_breached.iterrows():
                c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 3, 2])
                c1.write(f"**{row['Order_ID']}**")
                c2.write(row['Store_Name'])
                c3.write(f"Dispatch Time: {row['Dispatch Duration']}")
                reason_input = c4.text_input("Reason", key=f"disp_reason_{row['Order_ID']}", placeholder="Enter dispatch delay reason...")
                if c5.button("Submit & Hide", key=f"disp_btn_{row['Order_ID']}"):
                    if reason_input.strip() != "":
                        if append_saved_remark(row['Order_ID'], row['Store_Name'], "Express Dispatch Delay", "Express", reason_input.strip()):
                            st.success(f"Saved: {row['Order_ID']}")
                            st.rerun()
                st.divider()
        else:
            st.success("🎉 Zero pending Express dispatch delays!")

    with tab_del:
        st.subheader("Delivery Breaches (Express & Scheduled)")
        del_breached = filtered_df[
            (filtered_df['On Time Delivered'] == 0) & 
            (~filtered_df['Order_ID'].astype(str).isin(saved_order_ids))
        ].copy()
        
        if not del_breached.empty:
            for idx, row in del_breached.iterrows():
                c1, c2, c3, c4, c5, c6 = st.columns([2, 2, 2, 2, 3, 2])
                c1.write(f"**{row['Order_ID']}**")
                c2.write(row['Store_Name'])
                c3.write(row['Order Type'])
                c4.write(row['Delivery Partner'])
                reason_input = c5.text_input("Reason", key=f"d_reason_{row['Order_ID']}", placeholder="Enter delivery delay reason...")
                if c6.button("Submit & Hide", key=f"d_btn_{row['Order_ID']}"):
                    if reason_input.strip() != "":
                        if append_saved_remark(row['Order_ID'], row['Store_Name'], "Delivery Delay", row['Order Type'], reason_input.strip()):
                            st.success(f"Saved: {row['Order_ID']}")
                            st.rerun()
                st.divider()
        else:
            st.success("🎉 Zero pending delivery delays!")

    with tab_mgr:
        st.subheader("📊 Manager Review (Saved Remarks Audit)")
        current_remarks = load_saved_remarks()
        if not current_remarks.empty:
            if selected_store != 'All Stores (HYD Region)':
                current_remarks = current_remarks[current_remarks['Store_Name'] == selected_store]
            st.dataframe(current_remarks, use_container_width=True)
        else:
            st.info("No saved remarks found in Google Sheets yet.")

else:
    st.title("🚚 Fulfillment & Delivery Performance Dashboard")
    st.info("👈 Upload your store picklists and transaction report from the sidebar to start.")
