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

# --- ALWAYS-VISIBLE TOP FILTER BAR ---
has_live_data = 'master_df' in st.session_state
kpi_history = load_saved_kpis()

col_view, col_filter_type, col_picker = st.columns([3, 2, 3])

all_stores_list = []
if has_live_data:
    all_stores_list = sorted(list(st.session_state['master_df']['Store_Name'].dropna().unique()))
elif not kpi_history.empty and 'Store_Name' in kpi_history.columns:
    all_stores_list = sorted(list(kpi_history['Store_Name'].dropna().unique()))

if url_store and url_store in all_stores_list:
    selected_view = "Single Store Restricted View"
    st.info(f"🔒 Access Restricted View: **{url_store}**")
else:
    with col_view:
        selected_view = st.radio("👁️ View Mode", ["Overall Region View", "All Stores Single View"], horizontal=True)

with col_filter_type:
    date_filter_mode = st.radio("📅 Date Filter", ["Reporting Cycle", "Custom Range"], horizontal=True)

today_day = datetime.date.today().day
default_cycle_idx = 0 if today_day <= 7 else (1 if today_day <= 14 else (2 if today_day <= 21 else 3))

selected_cycle = None
selected_date_range = None

with col_picker:
    if date_filter_mode == "Reporting Cycle":
        selected_cycle = st.selectbox(
            "Select Cycle",
            ["Cycle 1 (1st - 7th)", "Cycle 2 (8th - 14th)", "Cycle 3 (15th - 21st)", "Cycle 4 (22nd - End)"],
            index=default_cycle_idx
        )
    else:
        selected_date_range = st.date_input(
            "Select Date Range", 
            value=(datetime.date.today(), datetime.date.today())
        )

# Helper function to filter historical Google Sheets KPI dataframe
def filter_kpi_history(df):
    if df.empty:
        return df
    res = df.copy()
    res['Date'] = pd.to_datetime(res['Date'], errors='coerce')
    
    if date_filter_mode == "Reporting Cycle" and selected_cycle:
        if selected_cycle == "Cycle 1 (1st - 7th)":
            res = res[res['Date'].dt.day.between(1, 7)]
        elif selected_cycle == "Cycle 2 (8th - 14th)":
            res = res[res['Date'].dt.day.between(8, 14)]
        elif selected_cycle == "Cycle 3 (15th - 21st)":
            res = res[res['Date'].dt.day.between(15, 21)]
        elif selected_cycle == "Cycle 4 (22nd - End)":
            res = res[res['Date'].dt.day >= 22]
    elif date_filter_mode == "Custom Range" and isinstance(selected_date_range, tuple) and len(selected_date_range) == 2:
        res = res[(res['Date'].dt.date >= selected_date_range[0]) & (res['Date'].dt.date <= selected_date_range[1])]
    return res

# --- HELPER FUNCTION TO GENERATE STORE METRICS TABLE ---
def build_store_summary_table(df):
    store_stats = []
    num_days = max(df['Order_Placing_Time'].dt.date.nunique(), 1)
    
    for store, group in df.groupby('Store_Name'):
        exp_group = group[group['Order Type'].str.lower() == 'express']
        sched_group = group[group['Order Type'].str.lower() != 'express']
        
        exp_pack_pct = (exp_group['Pick_SLA_Met'].sum() / len(exp_group) * 100) if len(exp_group) > 0 else 0
        exp_del_pct = (exp_group['On Time Delivered'].sum() / len(exp_group) * 100) if len(exp_group) > 0 else 0
        sched_del_pct = (sched_group['On Time Delivered'].sum() / len(sched_group) * 100) if len(sched_group) > 0 else 0
        
        tot_avg = round(len(group) / num_days)
        self_avg = round((group['Rider_Channel'] == 'Self (In-House)').sum() / num_days)
        tpl_avg = round((group['Rider_Channel'] == '3PL Partner').sum() / num_days)
        
        store_stats.append({
            'Store Name': store,
            'Express Packed SLA (≤3m)': f"{exp_pack_pct:.1f}%",
            'Express Delivered SLA': f"{exp_del_pct:.1f}%",
            'Scheduled Delivered SLA': f"{sched_del_pct:.1f}%",
            'Avg Total Orders / Day': tot_avg,
            'Avg Self Orders / Day': self_avg,
            'Avg 3PL Orders / Day': tpl_avg
        })
    return pd.DataFrame(store_stats)

# --- LIVE DATA VIEW ---
if has_live_data:
    master_df = st.session_state['master_df']
    filtered_df = master_df.copy()

    if date_filter_mode == "Reporting Cycle":
        if selected_cycle == "Cycle 1 (1st - 7th)":
            filtered_df = filtered_df[filtered_df['Order_Placing_Time'].dt.day.between(1, 7)]
        elif selected_cycle == "Cycle 2 (8th - 14th)":
            filtered_df = filtered_df[filtered_df['Order_Placing_Time'].dt.day.between(8, 14)]
        elif selected_cycle == "Cycle 3 (15th - 21st)":
            filtered_df = filtered_df[filtered_df['Order_Placing_Time'].dt.day.between(15, 21)]
        elif selected_cycle == "Cycle 4 (22nd - End)":
            filtered_df = filtered_df[filtered_df['Order_Placing_Time'].dt.day >= 22]
    elif date_filter_mode == "Custom Range" and isinstance(selected_date_range, tuple) and len(selected_date_range) == 2:
        filtered_df = filtered_df[
            (filtered_df['Order_Placing_Time'].dt.date >= selected_date_range[0]) & 
            (filtered_df['Order_Placing_Time'].dt.date <= selected_date_range[1])
        ]

    if url_store and url_store in all_stores_list:
        filtered_df = filtered_df[filtered_df['Store_Name'] == url_store]
        st.title(f"🏬 Store Performance: {url_store}")
    elif selected_view == "Overall Region View":
        st.title("🌐 HYD Region Overall Performance Overview")
    else:
        st.title("🏬 All Stores Performance (Single View)")

    st.markdown("---")

    exp_df = filtered_df[filtered_df['Order Type'].str.lower() == 'express']
    sched_df = filtered_df[filtered_df['Order Type'].str.lower() != 'express']
    
    exp_packed_pct = (exp_df['Pick_SLA_Met'].sum() / len(exp_df) * 100) if len(exp_df) > 0 else 0
    exp_del_pct = (exp_df['On Time Delivered'].sum() / len(exp_df) * 100) if len(exp_df) > 0 else 0
    sched_del_pct = (sched_df['On Time Delivered'].sum() / len(sched_df) * 100) if len(sched_df) > 0 else 0
    
    num_days = max((filtered_df['Order_Placing_Time'].dt.date.nunique()), 1)
    tot_avg = round(len(filtered_df) / num_days)
    self_avg = round((filtered_df['Rider_Channel'] == 'Self (In-House)').sum() / num_days)
    tpl_avg = round((filtered_df['Rider_Channel'] == '3PL Partner').sum() / num_days)
    
    st.subheader("🎯 Region Summary Metrics")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Express Packed SLA (≤3m)", f"{exp_packed_pct:.1f}%")
    k2.metric("Express Delivered %", f"{exp_del_pct:.1f}%")
    k3.metric("Scheduled Delivered %", f"{sched_del_pct:.1f}%")
    k4.metric("Avg Daily Orders (Total / Self / 3PL)", f"{tot_avg} / {self_avg} / {tpl_avg}")

    st.markdown("---")

    if selected_view == "All Stores Single View" and not url_store:
        st.subheader("📊 Store-by-Store Comparison (Single View)")
        store_comparison_df = build_store_summary_table(filtered_df)
        st.dataframe(store_comparison_df, use_container_width=True)
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
            st.dataframe(saved_db, use_container_width=True)
        else:
            st.info("No saved remarks found in Google Sheets yet.")

# --- HISTORICAL VIEW (DEFAULT LANDING VIEW) ---
else:
    st.title("🌐 Delivery & Fulfillment Historical Performance")
    st.info("💡 Displaying historical performance trends from Google Sheets. Upload fresh daily reports via the sidebar to process new orders.")
    
    if not kpi_history.empty:
        filtered_kpi = filter_kpi_history(kpi_history)
        
        if url_store and url_store in all_stores_list:
            filtered_kpi = filtered_kpi[filtered_kpi['Store_Name'] == url_store]

        st.subheader("📈 Persistent Performance Metrics")
        
        exp_pack_avg = filtered_kpi['Express_Packed_SLA'].mean() if not filtered_kpi.empty else 0
        exp_del_avg = filtered_kpi['Express_Delivered_SLA'].mean() if not filtered_kpi.empty else 0
        sched_del_avg = filtered_kpi['Scheduled_Delivered_SLA'].mean() if not filtered_kpi.empty else 0
        
        tot_vol = filtered_kpi['Total_Orders'].sum() if not filtered_kpi.empty else 0
        self_vol = filtered_kpi['Self_Orders'].sum() if not filtered_kpi.empty else 0
        tpl_vol = filtered_kpi['TPL_Orders'].sum() if not filtered_kpi.empty else 0
        
        hk1, hk2, hk3, hk4 = st.columns(4)
        hk1.metric("Avg Express Packed SLA", f"{exp_pack_avg:.1f}%")
        hk2.metric("Avg Express Delivered SLA", f"{exp_del_avg:.1f}%")
        hk3.metric("Avg Scheduled Delivered SLA", f"{sched_del_avg:.1f}%")
        hk4.metric("Total Volume (Total / Self / 3PL)", f"{tot_vol:,} / {self_vol:,} / {tpl_vol:,}")
        
        st.markdown("---")
        st.subheader("📋 Store-by-Store Historical Table")
        st.dataframe(filtered_kpi, use_container_width=True)
    else:
        st.warning("No historical performance data saved yet. Upload your first report from the sidebar to store KPIs!")

    st.markdown("---")
    st.subheader("📋 Historical Delay Remarks Database")
    if not saved_db.empty:
        st.dataframe(saved_db, use_container_width=True)
    else:
        st.write("No historical delay records submitted yet.")
