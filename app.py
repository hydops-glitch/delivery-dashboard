import streamlit as st
import pandas as pd
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from data_processor import process_and_merge_reports

st.set_page_config(page_title="Fulfilment, Rider & Delivery Dashboard", layout="wide")

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
            str(order_type), str(delay_reason), "Operations", timestamp
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
st.sidebar.markdown("Upload Order Transitions Report (.xlsx / .csv)")

uploaded_files = st.sidebar.file_uploader("Upload Report Files", accept_multiple_files=True)

saved_db = load_saved_remarks()
saved_order_ids = set(saved_db['Order_ID'].astype(str).unique()) if not saved_db.empty else set()

# Process uploaded files
if uploaded_files:
    master_df = process_and_merge_reports(uploaded_files)
    st.session_state['master_df'] = master_df
    
    daily_summary = []
    for (order_date, store), group in master_df.groupby([master_df['Placed_Time'].dt.date, 'Store_Name']):
        exp_group = group[group['Order_Type_Clean'] == 'express']
        sched_group = group[group['Order_Type_Clean'] != 'express']
        
        exp_pack_sla = round((exp_group['Pick_SLA_Met'].sum() / len(exp_group) * 100), 1) if len(exp_group) > 0 else 0.0
        exp_disp_sla = round((exp_group['Dispatch_SLA_Met'].sum() / len(exp_group) * 100), 1) if len(exp_group) > 0 else 0.0
        del_sla = round((group['On_Time_Delivered'].sum() / len(group) * 100), 1) if len(group) > 0 else 0.0
        
        # Calculate Store CPO
        active_riders = group[group['Rider_Name'] != 'Unassigned']['Rider_Name'].nunique()
        total_delivered = len(group[group['Order_Status'] == 'DELIVERED'])
        total_rider_cost = active_riders * 1050
        store_cpo = round(total_rider_cost / total_delivered, 2) if total_delivered > 0 else 0.0
        
        daily_summary.append({
            'Date': str(order_date),
            'Store_Name': store,
            'Express_Packed_SLA': exp_pack_sla,
            'Express_Dispatch_SLA': exp_disp_sla,
            'Delivery_SLA': del_sla,
            'Express_Orders': len(exp_group),
            'Standard_Orders': len(sched_group),
            'Total_Delivered': total_delivered,
            'Active_Riders': active_riders,
            'Store_CPO': store_cpo
        })
    
    new_kpi_df = pd.DataFrame(daily_summary)
    existing_kpi_df = load_saved_kpis()
    
    if not existing_kpi_df.empty:
        combined_kpis = pd.concat([existing_kpi_df, new_kpi_df]).drop_duplicates(subset=['Date', 'Store_Name'], keep='last')
    else:
        combined_kpis = new_kpi_df
        
    save_daily_kpis(combined_kpis)
    st.sidebar.success("Report processed & metrics updated successfully!")

# --- TOP FILTER BAR ---
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

# --- LIVE DATA DISPLAY ---
if has_live_data:
    master_df = st.session_state['master_df']
    filtered_df = master_df.copy()

    if date_filter_mode == "Reporting Cycle":
        if selected_cycle == "Cycle 1 (1st - 7th)":
            filtered_df = filtered_df[filtered_df['Placed_Time'].dt.day.between(1, 7)]
        elif selected_cycle == "Cycle 2 (8th - 14th)":
            filtered_df = filtered_df[filtered_df['Placed_Time'].dt.day.between(8, 14)]
        elif selected_cycle == "Cycle 3 (15th - 21st)":
            filtered_df = filtered_df[filtered_df['Placed_Time'].dt.day.between(15, 21)]
        elif selected_cycle == "Cycle 4 (22nd - End)":
            filtered_df = filtered_df[filtered_df['Placed_Time'].dt.day >= 22]
    elif date_filter_mode == "Custom Range" and isinstance(selected_date_range, tuple) and len(selected_date_range) == 2:
        filtered_df = filtered_df[
            (filtered_df['Placed_Time'].dt.date >= selected_date_range[0]) & 
            (filtered_df['Placed_Time'].dt.date <= selected_date_range[1])
        ]

    if url_store and url_store in all_stores_list:
        filtered_df = filtered_df[filtered_df['Store_Name'] == url_store]
        st.title(f"🏬 Store Performance: {url_store}")
    elif selected_view == "Overall Region View":
        st.title("🌐 Regional Performance & SLA Dashboard")
    else:
        st.title("🏬 All Stores View")

    st.markdown("---")

    exp_df = filtered_df[filtered_df['Order_Type_Clean'] == 'express']
    
    exp_packed_pct = (exp_df['Pick_SLA_Met'].sum() / len(exp_df) * 100) if len(exp_df) > 0 else 0.0
    exp_dispatch_pct = (exp_df['Dispatch_SLA_Met'].sum() / len(exp_df) * 100) if len(exp_df) > 0 else 0.0
    del_sla_pct = (filtered_df['On_Time_Delivered'].sum() / len(filtered_df) * 100) if len(filtered_df) > 0 else 0.0
    
    delivered_orders = filtered_df[filtered_df['Order_Status'] == 'DELIVERED']
    active_riders_cnt = delivered_orders[delivered_orders['Rider_Name'] != 'Unassigned']['Rider_Name'].nunique()
    total_delivered_cnt = len(delivered_orders)
    overall_cpo = (active_riders_cnt * 1050 / total_delivered_cnt) if total_delivered_cnt > 0 else 0.0

    st.subheader("🎯 SLA & Cost Metrics")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Express Pick SLA (≤3m)", f"{exp_packed_pct:.1f}%")
    k2.metric("Express Dispatch SLA (≤6m)", f"{exp_dispatch_pct:.1f}%")
    k3.metric("Delivery SLA Compliance", f"{del_sla_pct:.1f}%")
    k4.metric("Overall CPO (₹1050 Salary)", f"₹{overall_cpo:.2f}")

    st.markdown("---")

    tab_pick_disp, tab_del, tab_rider = st.tabs([
        "⚡ Express Pick & Dispatch Delays", 
        "🚚 Delivery Delays", 
        "🏍️ Rider Performance & CPO"
    ])
    
    # --- TAB 1: EXPRESS PICK & DISPATCH BREACHES ---
    with tab_pick_disp:
        st.subheader("Express SLA Breaches (Pick >3m OR Dispatch >6m)")
        breached_exp = exp_df[
            ((exp_df['Pick_SLA_Met'] == 0) | (exp_df['Dispatch_SLA_Met'] == 0)) & 
            (~exp_df['Order_ID'].astype(str).isin(saved_order_ids))
        ].copy()
        
        if not breached_exp.empty:
            for idx, row in breached_exp.iterrows():
                c1, c2, c3, c4, c5, c6 = st.columns([2, 1.5, 2, 2, 3, 1.5])
                c1.write(f"**{row['Order_ID']}**")
                c2.write(row['Store_Name'])
                c3.write(f"Pick: {row['Pick_Duration_Formatted']}")
                c4.write(f"Dispatch: {row['Dispatch_Duration_Formatted']}")
                reason_input = c5.text_input("Enter Delay Reason", key=f"pd_reason_{row['Order_ID']}", placeholder="Type reason here...")
                if c6.button("Submit", key=f"pd_btn_{row['Order_ID']}"):
                    if reason_input.strip() != "":
                        if append_saved_remark(row['Order_ID'], row['Store_Name'], "Express Pick/Dispatch Delay", "Express", reason_input.strip()):
                            st.success(f"Saved: {row['Order_ID']}")
                            st.rerun()
                st.divider()
        else:
            st.success("🎉 Zero pending Express picking or dispatch delays!")

    # --- TAB 2: DELIVERY DELAYS ---
    with tab_del:
        st.subheader("Delivery Breaches")
        del_breached = filtered_df[
            (filtered_df['On_Time_Delivered'] == 0) & 
            (~filtered_df['Order_ID'].astype(str).isin(saved_order_ids))
        ].copy()
        
        if not del_breached.empty:
            for idx, row in del_breached.iterrows():
                c1, c2, c3, c4, c5, c6 = st.columns([2, 1.5, 1.5, 2, 3, 1.5])
                c1.write(f"**{row['Order_ID']}**")
                c2.write(row['Store_Name'])
                c3.write(row['Order_Type'])
                c4.write(f"Rider: {row['Rider_Name']}")
                reason_input = c5.text_input("Enter Delivery Delay Reason", key=f"d_reason_{row['Order_ID']}", placeholder="Type reason here...")
                if c6.button("Submit", key=f"d_btn_{row['Order_ID']}"):
                    if reason_input.strip() != "":
                        if append_saved_remark(row['Order_ID'], row['Store_Name'], "Delivery Delay", row['Order_Type'], reason_input.strip()):
                            st.success(f"Saved: {row['Order_ID']}")
                            st.rerun()
                st.divider()
        else:
            st.success("🎉 Zero pending delivery delays!")

    # --- TAB 3: RIDER PERFORMANCE & CPO BREAKDOWN ---
    with tab_rider:
        st.subheader("🏍️ Rider Performance & Cost Per Order (CPO)")
        
        # Rider-Level Table
        rider_df = filtered_df[filtered_df['Order_Status'] == 'DELIVERED'].copy()
        
        rider_summary = []
        for rider, r_group in rider_df.groupby('Rider_Name'):
            if rider == 'Unassigned':
                continue
            exp_cnt = int((r_group['Order_Type_Clean'] == 'express').sum())
            std_cnt = int((r_group['Order_Type_Clean'] != 'express').sum())
            tot_cnt = len(r_group)
            
            # Express Avg Transit Duration (Dispatched to Completed)
            exp_r_group = r_group[r_group['Order_Type_Clean'] == 'express']
            avg_transit = exp_r_group['Transit_Duration_Min'].mean() if len(exp_r_group) > 0 else 0.0
            
            # Rider CPO Calculation: 1050 / Total Delivered Orders
            rider_cpo = round(1050.0 / tot_cnt, 2) if tot_cnt > 0 else 0.0
            
            rider_summary.append({
                'Rider Name': rider,
                'Express Delivered Orders': exp_cnt,
                'Standard Delivered Orders': std_cnt,
                'Total Delivered Orders': tot_cnt,
                'Express Avg Delivery Time (Min)': f"{avg_transit:.1f} Min",
                'Rider CPO (₹)': f"₹{rider_cpo:.2f}"
            })
            
        st.markdown("##### **Individual Rider Performance & CPO (Fixed ₹1,050 Day Salary)**")
        if rider_summary:
            st.dataframe(pd.DataFrame(rider_summary), use_container_width=True)
        else:
            st.info("No active rider records found for selected filter.")
            
        st.markdown("---")
        st.markdown("##### **Store-Wise CPO Summary Table**")
        
        store_cpo_summary = []
        for store, s_group in filtered_df[filtered_df['Order_Status'] == 'DELIVERED'].groupby('Store_Name'):
            s_active_riders = s_group[s_group['Rider_Name'] != 'Unassigned']['Rider_Name'].nunique()
            s_tot_orders = len(s_group)
            s_tot_cost = s_active_riders * 1050
            s_cpo = round(s_tot_cost / s_tot_orders, 2) if s_tot_orders > 0 else 0.0
            
            store_cpo_summary.append({
                'Store Name': store,
                'Active Riders Count': s_active_riders,
                'Total Rider Cost (₹)': f"₹{s_tot_cost:,}",
                'Total Delivered Orders': s_tot_orders,
                'Store CPO (₹)': f"₹{s_cpo:.2f}"
            })
        st.dataframe(pd.DataFrame(store_cpo_summary), use_container_width=True)

# --- HISTORICAL DATA DISPLAY ---
else:
    st.title("🌐 Delivery & Fulfillment Historical Dashboard")
    st.info("💡 Upload `ORDER_STATUS_TRANSITIONS` reports via the sidebar to calculate live metrics.")
    
    if not kpi_history.empty:
        st.subheader("📋 Historical Store Performance & CPO")
        st.dataframe(filter_kpi_history(kpi_history), use_container_width=True)
