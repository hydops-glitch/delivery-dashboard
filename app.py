import streamlit as st
import pandas as pd
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from data_processor import process_and_merge_reports

st.set_page_config(page_title="Fulfilment & Delivery Dashboard", layout="wide")

# --- GOOGLE SHEETS CONNECTION ---
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

def load_saved_kpis():
    try:
        client = get_gspread_client()
        sheet_id = st.secrets["sheets"]["spreadsheet_id"]
        sheet = client.open_by_key(sheet_id).worksheet("Daily_KPIs")
        records = sheet.get_all_records()
        return pd.DataFrame(records)
    except Exception:
        return pd.DataFrame()

def save_daily_kpis(kpi_df):
    try:
        client = get_gspread_client()
        sheet_id = st.secrets["sheets"]["spreadsheet_id"]
        sheet = client.open_by_key(sheet_id).worksheet("Daily_KPIs")
        sheet.clear()
        sheet.update([kpi_df.columns.values.tolist()] + kpi_df.values.tolist())
        return True
    except Exception as e:
        st.error(f"Error saving KPIs: {e}")
        return False

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

# --- URL QUERY PARAMS FOR STORE ACCESS CONTROL ---
query_params = st.query_params
url_store = query_params.get("store", None)

# --- SIDEBAR CONTROLS ---
st.sidebar.header("📂 Data Controls")
st.sidebar.markdown("Upload daily reports to calculate metrics & log delays.")

picklist_files = st.sidebar.file_uploader("Upload Store Picklist Reports (.xls/.csv)", accept_multiple_files=True)
transaction_file = st.sidebar.file_uploader("Upload Order Transactions Report (.xlsx/.csv)")

saved_db = load_saved_remarks()
saved_order_ids = set(saved_db['Order_ID'].astype(str).unique()) if not saved_db.empty else set()

# Process uploaded files
if picklist_files and transaction_file:
    master_df = process_and_merge_reports(picklist_files, transaction_file)
    st.session_state['master_df'] = master_df
    
    daily_summary = []
    for (order_date, store), group in master_df.groupby([master_df['Order_Placing_Time'].dt.date, 'Store_Name']):
        exp_group = group[group['Order Type'].str.lower() == 'express']
        sched_group = group[group['Order Type'].str.lower() != 'express']
        
        exp_pack_sla = round((exp_group['Pick_SLA_Met'].sum() / len(exp_group) * 100), 1) if len(exp_group) > 0 else 0
        exp_del_sla = round((exp_group['On Time Delivered'].sum() / len(exp_group) * 100), 1) if len(exp_group) > 0 else 0
        sched_del_sla = round((sched_group['On Time Delivered'].sum() / len(sched_group) * 100), 1) if len(sched_group) > 0 else 0
        
        self_cnt = int((group['Rider_Channel'] == 'Self (In-House)').sum())
        tpl_cnt = int((group['Rider_Channel'] == '3PL Partner').sum())
        
        daily_summary.append({
            'Date': str(order_date),
            'Store_Name': store,
            'Express_Packed_SLA': exp_pack_sla,
            'Express_Delivered_SLA': exp_del_sla,
            'Scheduled_Delivered_SLA': sched_del_sla,
            'Self_Orders': self_cnt,
            'TPL_Orders': tpl_cnt,
            'Total_Orders': len(group)
        })
    
    new_kpi_df = pd.DataFrame(daily_summary)
    existing_kpi_df = load_saved_kpis()
    
    if not existing_kpi_df.empty:
        combined_kpis = pd.concat([existing_kpi_df, new_kpi_df]).drop_duplicates(subset=['Date', 'Store_Name'], keep='last')
    else:
        combined_kpis = new_kpi_df
        
    save_daily_kpis(combined_kpis)
    st.sidebar.success("Reports processed & KPIs saved to Google Sheets!")

# --- MAIN DASHBOARD VIEW ---
if 'master_df' in st.session_state:
    master_df = st.session_state['master_df']
    all_stores_list = sorted(list(master_df['Store_Name'].unique()))
    
    col_view, col_store, col_filter_type, col_picker = st.columns([2, 2, 2, 3])
    
    # Store Link Access Restriction Logic
    if url_store and url_store in all_stores_list:
        selected_view = "Store-Level View"
        selected_store = url_store
        st.info(f"🔒 Access Restricted View: **{selected_store}**")
    else:
        with col_view:
            selected_view = st.radio("👁️ View Mode", ["Overall Region View", "Store-Level View"], horizontal=True)
            
        with col_store:
            if selected_view == "Store-Level View":
                selected_store = st.selectbox("🏬 Select Store", all_stores_list)
            else:
                selected_store = "All Stores (HYD Region)"

    if selected_view == "Store-Level View":
        filtered_df = master_df[master_df['Store_Name'] == selected_store].copy()
        header_title = f"🏬 Store Performance: {selected_store}"
    else:
        filtered_df = master_df.copy()
        header_title = "🌐 HYD Region Overall Performance Overview"
        
    with col_filter_type:
        date_filter_mode = st.radio("📅 Date Filter", ["Reporting Cycle", "Custom Range"], horizontal=True)
        
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
    
    exp_packed_pct = (exp_df['Pick_SLA_Met'].sum() / len(exp_df) * 100) if len(exp_df) > 0 else 0
    exp_del_pct = (exp_df['On Time Delivered'].sum() / len(exp_df) * 100) if len(exp_df) > 0 else 0
    sched_del_pct = (sched_df['On Time Delivered'].sum() / len(sched_df) * 100) if len(sched_df) > 0 else 0
    
    num_days = max((filtered_df['Order_Placing_Time'].dt.date.nunique()), 1)
    total_orders_avg = round(len(filtered_df) / num_days)
    self_orders_avg = round((filtered_df['Rider_Channel'] == 'Self (In-House)').sum() / num_days)
    tpl_orders_avg = round((filtered_df['Rider_Channel'] == '3PL Partner').sum() / num_days)
    
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Express Packed SLA (≤3m)", f"{exp_packed_pct:.1f}%")
    k2.metric("Express Delivered %", f"{exp_del_pct:.1f}%")
    k3.metric("Scheduled Delivered %", f"{sched_del_pct:.1f}%")
    k4.metric("Avg Daily Orders (Total)", f"{total_orders_avg:,} / day", help=f"Self: {self_orders_avg} | 3PL: {tpl_orders_avg}")

    st.markdown("---")

    tab_pick, tab_del, tab_mgr = st.tabs([
        "⚡ Express Packing Delays (>3m)", 
        "🚚 Delivery Delays", 
        "📊 Manager Review (Saved Remarks)"
    ])
    
    with tab_pick:
        st.subheader("Express Packing Breaches")
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

    with tab_del:
        st.subheader("Delivery Breaches")
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
        if not saved_db.empty:
            display_db = saved_db[saved_db['Store_Name'] == selected_store] if selected_store != 'All Stores (HYD Region)' else saved_db.copy()
            st.dataframe(display_db, use_container_width=True)
        else:
            st.info("No saved remarks found in Google Sheets yet.")

# HISTORICAL VIEW (DEFAULT LANDING VIEW)
else:
    st.title("🌐 Delivery & Fulfillment Historical Performance")
    st.info("💡 Displaying historical performance trends. Upload fresh daily reports via the sidebar to process new orders.")
    
    kpi_history = load_saved_kpis()
    
    if not kpi_history.empty:
        all_hist_stores = sorted(list(kpi_history['Store_Name'].unique()))
        
        if url_store and url_store in all_hist_stores:
            selected_hist_store = url_store
            st.info(f"🔒 Access Restricted View: **{selected_hist_store}**")
        else:
            h_col1, h_col2 = st.columns([2, 2])
            with h_col1:
                hist_view_mode = st.radio("👁️ View Mode", ["Overall Region View", "Store-Level View"], horizontal=True)
            with h_col2:
                if hist_view_mode == "Store-Level View":
                    selected_hist_store = st.selectbox("🏬 Select Store", all_hist_stores)
                else:
                    selected_hist_store = "All Stores (HYD Region)"
        
        if selected_hist_store != 'All Stores (HYD Region)':
            filtered_kpi = kpi_history[kpi_history['Store_Name'] == selected_hist_store]
        else:
            filtered_kpi = kpi_history.copy()
            
        st.subheader("📈 Persistent Performance Metrics")
        
        exp_pack_avg = filtered_kpi['Express_Packed_SLA'].mean() if not filtered_kpi.empty else 0
        exp_del_avg = filtered_kpi['Express_Delivered_SLA'].mean() if not filtered_kpi.empty else 0
        sched_del_avg = filtered_kpi['Scheduled_Delivered_SLA'].mean() if not filtered_kpi.empty else 0
        
        total_vol = filtered_kpi['Total_Orders'].sum() if not filtered_kpi.empty else 0
        total_self = filtered_kpi['Self_Orders'].sum() if not filtered_kpi.empty else 0
        total_tpl = filtered_kpi['TPL_Orders'].sum() if not filtered_kpi.empty else 0
        
        hk1, hk2, hk3, hk4 = st.columns(4)
        hk1.metric("Avg Express Packed SLA", f"{exp_pack_avg:.1f}%")
        hk2.metric("Avg Express Delivered SLA", f"{exp_del_avg:.1f}%")
        hk3.metric("Avg Scheduled Delivered SLA", f"{sched_del_avg:.1f}%")
        hk4.metric("Total Volume (Self / 3PL)", f"{total_vol:,}", help=f"Self: {total_self:,} | 3PL: {total_tpl:,}")
        
        st.markdown("---")
        st.subheader("📋 Historical Daily KPI Table")
        st.dataframe(filtered_kpi, use_container_width=True)
    else:
        st.warning("No historical performance data saved yet. Upload your first report from the sidebar to store KPIs!")

    st.markdown("---")
    st.subheader("📋 Historical Delay Remarks Database")
    if not saved_db.empty:
        st.dataframe(saved_db, use_container_width=True)
    else:
        st.write("No historical delay records submitted yet.")
