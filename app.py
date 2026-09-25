import streamlit as st
import pandas as pd
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from data_processor import process_and_merge_reports

st.set_page_config(page_title="Hyd Region Performance Dashboard", layout="wide", initial_sidebar_state="expanded")

# --- EXECUTIVE MODERN SAAS STYLING ---
st.markdown("""
<style>
    /* Background & Font */
    .stApp {
        background-color: #f8fafc;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    
    /* Top Header */
    .dashboard-title {
        font-size: 1.75rem;
        font-weight: 800;
        color: #0f172a;
        margin-bottom: 2px;
    }
    .dashboard-subtitle {
        font-size: 0.9rem;
        color: #64748b;
        margin-bottom: 20px;
    }

    /* Modern SaaS KPI Card Design */
    .kpi-card {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 18px 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
        margin-bottom: 15px;
        height: 100%;
        transition: transform 0.1s ease, box-shadow 0.1s ease;
    }
    .kpi-card:hover {
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.08);
    }
    .kpi-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 10px;
    }
    .kpi-title {
        font-size: 0.82rem;
        font-weight: 600;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .kpi-icon-box {
        width: 36px;
        height: 36px;
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.1rem;
    }
    .icon-blue { background-color: #eff6ff; color: #2563eb; }
    .icon-green { background-color: #f0fdf4; color: #16a34a; }
    .icon-purple { background-color: #faf5ff; color: #9333ea; }
    .icon-orange { background-color: #fff7ed; color: #ea580c; }
    .icon-teal { background-color: #f0fdfa; color: #0d9488; }
    .icon-indigo { background-color: #eef2ff; color: #4f46e5; }

    .kpi-value {
        font-size: 1.75rem;
        font-weight: 800;
        color: #0f172a;
        line-height: 1.2;
    }
    .kpi-subtext {
        font-size: 0.82rem;
        font-weight: 500;
        color: #64748b;
        margin-top: 6px;
    }
    .kpi-subtext span {
        font-weight: 700;
    }

    /* Table Styling */
    .stDataFrame {
        border-radius: 10px;
        overflow: hidden;
        border: 1px solid #e2e8f0;
    }
</style>
""", unsafe_allow_html=True)

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
        df = pd.DataFrame(records)
        if not df.empty and 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        return df
    except Exception:
        return pd.DataFrame()

def save_daily_kpis(kpi_df):
    try:
        client = get_gspread_client()
        sheet_id = st.secrets["sheets"]["spreadsheet_id"]
        sheet = client.open_by_key(sheet_id).worksheet("Daily_KPIs")
        sheet.clear()
        export_df = kpi_df.copy()
        if 'Date' in export_df.columns:
            export_df['Date'] = export_df['Date'].astype(str)
        sheet.update([export_df.columns.values.tolist()] + export_df.values.tolist())
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
uploaded_files = st.sidebar.file_uploader("Upload Order Transitions Report (.xlsx / .csv)", accept_multiple_files=True)

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
        
        deliv_exp = exp_group[exp_group['Order_Status'] == 'DELIVERED']
        deliv_sched = sched_group[sched_group['Order_Status'] == 'DELIVERED']

        exp_pack_sla = round((exp_group['Pick_SLA_Met'].sum() / len(exp_group) * 100), 1) if len(exp_group) > 0 else 0.0
        exp_disp_sla = round((exp_group['Dispatch_SLA_Met'].sum() / len(exp_group) * 100), 1) if len(exp_group) > 0 else 0.0
        
        exp_del_sla = round((deliv_exp['On_Time_Delivered'].sum() / len(deliv_exp) * 100), 1) if len(deliv_exp) > 0 else 0.0
        std_del_sla = round((deliv_sched['On_Time_Delivered'].sum() / len(deliv_sched) * 100), 1) if len(deliv_sched) > 0 else 0.0
        
        active_riders = group[group['Rider_Name'] != 'Unassigned']['Rider_Name'].nunique()
        total_delivered = len(group[group['Order_Status'] == 'DELIVERED'])
        total_rider_cost = active_riders * 1050
        store_cpo = round(total_rider_cost / total_delivered, 2) if total_delivered > 0 else 0.0
        
        daily_summary.append({
            'Date': str(order_date),
            'Store_Name': store,
            'Express_Packed_SLA': exp_pack_sla,
            'Express_Dispatch_SLA': exp_disp_sla,
            'Express_Delivery_SLA': exp_del_sla,
            'Standard_Delivery_SLA': std_del_sla,
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
    st.sidebar.success("Report processed successfully!")

# --- DATASET LOAD & DATE DETERMINATION ---
has_live_data = 'master_df' in st.session_state
kpi_history = load_saved_kpis()

latest_available_date = datetime.date.today()
if has_live_data:
    latest_available_date = st.session_state['master_df']['Placed_Time'].dt.date.max()
elif not kpi_history.empty and 'Date' in kpi_history.columns:
    latest_available_date = kpi_history['Date'].dt.date.max()

# --- TOP DASHBOARD HEADER & CONTROLS ---
st.markdown('<div class="dashboard-title">Hyd Region Performance</div>', unsafe_allow_html=True)
st.markdown('<div class="dashboard-subtitle">Operational fulfillment metrics, rider allocation, and SLA breach insights</div>', unsafe_allow_html=True)

all_stores_list = []
if has_live_data:
    all_stores_list = sorted(list(st.session_state['master_df']['Store_Name'].dropna().unique()))
elif not kpi_history.empty and 'Store_Name' in kpi_history.columns:
    all_stores_list = sorted(list(kpi_history['Store_Name'].dropna().unique()))

ctrl_c1, ctrl_c2, ctrl_c3 = st.columns([2.5, 2.5, 4])

if url_store and url_store in all_stores_list:
    selected_view = "Single Store Restricted View"
    st.info(f"🔒 Access Restricted View: **{url_store}**")
else:
    with ctrl_c1:
        selected_view = st.radio("View Mode", ["Overall Region View", "All Stores Single View"], horizontal=True)

with ctrl_c2:
    selected_date_range = st.date_input(
        "Date Filter", 
        value=(latest_available_date, latest_available_date),
        max_value=latest_available_date
    )

def get_start_end_dates(d_range):
    if isinstance(d_range, tuple):
        if len(d_range) == 2:
            return d_range[0], d_range[1]
        elif len(d_range) == 1:
            return d_range[0], d_range[0]
    return latest_available_date, latest_available_date

start_date, end_date = get_start_end_dates(selected_date_range)

st.markdown("<hr style='margin-top:5px; margin-bottom:20px; border-color:#e2e8f0;'>", unsafe_allow_html=True)

# --- LIVE REPORT ANALYSIS & SAAS METRIC CARDS ---
if has_live_data:
    master_df = st.session_state['master_df']
    filtered_df = master_df[
        (master_df['Placed_Time'].dt.date >= start_date) & 
        (master_df['Placed_Time'].dt.date <= end_date)
    ].copy()

    if url_store and url_store in all_stores_list:
        filtered_df = filtered_df[filtered_df['Store_Name'] == url_store]

    # Calculate metric aggregates
    exp_df = filtered_df[filtered_df['Order_Type_Clean'] == 'express']
    sched_df = filtered_df[filtered_df['Order_Type_Clean'] != 'express']
    
    exp_packed_pct = (exp_df['Pick_SLA_Met'].sum() / len(exp_df) * 100) if len(exp_df) > 0 else 0.0
    exp_dispatch_pct = (exp_df['Dispatch_SLA_Met'].sum() / len(exp_df) * 100) if len(exp_df) > 0 else 0.0
    
    exp_deliv = exp_df[exp_df['Order_Status'] == 'DELIVERED']
    sched_deliv = sched_df[sched_df['Order_Status'] == 'DELIVERED']
    
    exp_del_sla_pct = (exp_deliv['On_Time_Delivered'].sum() / len(exp_deliv) * 100) if len(exp_deliv) > 0 else 0.0
    std_del_sla_pct = (sched_deliv['On_Time_Delivered'].sum() / len(sched_deliv) * 100) if len(sched_deliv) > 0 else 0.0
    
    delivered_orders = filtered_df[filtered_df['Order_Status'] == 'DELIVERED']
    active_riders_cnt = delivered_orders[delivered_orders['Rider_Name'] != 'Unassigned']['Rider_Name'].nunique()
    total_delivered_cnt = len(delivered_orders)
    overall_cpo = (active_riders_cnt * 1050 / total_delivered_cnt) if total_delivered_cnt > 0 else 0.0

    # Render Modern SaaS Metric Cards Row
    card1, card2, card3, card4, card5, card6 = st.columns(6)
    
    with card1:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-header">
                <span class="kpi-title">Express Pick SLA</span>
                <div class="kpi-icon-box icon-blue">⚡</div>
            </div>
            <div class="kpi-value">{exp_packed_pct:.1f}%</div>
            <div class="kpi-subtext">Target ≤3 Min | <span>{len(exp_df):,}</span> Orders</div>
        </div>
        """, unsafe_allow_html=True)

    with card2:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-header">
                <span class="kpi-title">Express Dispatch</span>
                <div class="kpi-icon-box icon-orange">🚀</div>
            </div>
            <div class="kpi-value">{exp_dispatch_pct:.1f}%</div>
            <div class="kpi-subtext">Target ≤6 Min SLA</div>
        </div>
        """, unsafe_allow_html=True)

    with card3:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-header">
                <span class="kpi-title">Express Del SLA</span>
                <div class="kpi-icon-box icon-green">📦</div>
            </div>
            <div class="kpi-value">{exp_del_sla_pct:.1f}%</div>
            <div class="kpi-subtext">Delivered: <span>{len(exp_deliv):,}</span> Express</div>
        </div>
        """, unsafe_allow_html=True)

    with card4:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-header">
                <span class="kpi-title">Standard Del SLA</span>
                <div class="kpi-icon-box icon-teal">🚚</div>
            </div>
            <div class="kpi-value">{std_del_sla_pct:.1f}%</div>
            <div class="kpi-subtext">Delivered: <span>{len(sched_deliv):,}</span> Standard</div>
        </div>
        """, unsafe_allow_html=True)

    with card5:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-header">
                <span class="kpi-title">Riders & CPO</span>
                <div class="kpi-icon-box icon-purple">🏍️</div>
            </div>
            <div class="kpi-value">₹{overall_cpo:.2f}</div>
            <div class="kpi-subtext">Reported Riders: <span>{active_riders_cnt}</span></div>
        </div>
        """, unsafe_allow_html=True)

    with card6:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-header">
                <span class="kpi-title">Order Volume Split</span>
                <div class="kpi-icon-box icon-indigo">📊</div>
            </div>
            <div class="kpi-value">{len(filtered_df):,}</div>
            <div class="kpi-subtext">Exp: <span>{len(exp_df):,}</span> | Std: <span>{len(sched_df):,}</span></div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Store Breakdown Table (When "All Stores Single View" selected)
    if selected_view == "All Stores Single View" and not url_store:
        st.subheader("📊 Store-Wise SLA & Cost Breakdown Table")
        all_store_rows = []
        for store, s_group in filtered_df.groupby('Store_Name'):
            s_exp_group = s_group[s_group['Order_Type_Clean'] == 'express']
            s_sched_group = s_group[s_group['Order_Type_Clean'] != 'express']
            s_deliv_exp = s_exp_group[s_exp_group['Order_Status'] == 'DELIVERED']
            s_deliv_sched = s_sched_group[s_sched_group['Order_Status'] == 'DELIVERED']
            
            exp_pack = round((s_exp_group['Pick_SLA_Met'].sum() / len(s_exp_group) * 100), 1) if len(s_exp_group) > 0 else 0.0
            exp_disp = round((s_exp_group['Dispatch_SLA_Met'].sum() / len(s_exp_group) * 100), 1) if len(s_exp_group) > 0 else 0.0
            exp_del = round((s_deliv_exp['On_Time_Delivered'].sum() / len(s_deliv_exp) * 100), 1) if len(s_deliv_exp) > 0 else 0.0
            std_del = round((s_deliv_sched['On_Time_Delivered'].sum() / len(s_deliv_sched) * 100), 1) if len(s_deliv_sched) > 0 else 0.0
            
            active_riders = s_group[s_group['Rider_Name'] != 'Unassigned']['Rider_Name'].nunique()
            tot_delivered = len(s_group[s_group['Order_Status'] == 'DELIVERED'])
            cpo = round((active_riders * 1050) / tot_delivered, 2) if tot_delivered > 0 else 0.0
            
            all_store_rows.append({
                'Store Name': store,
                'Express Pick SLA (%)': exp_pack,
                'Express Dispatch SLA (%)': exp_disp,
                'Express Delivery SLA (%)': exp_del,
                'Standard Delivery SLA (%)': std_del,
                'Express Orders': len(s_exp_group),
                'Standard Orders': len(s_sched_group),
                'Total Delivered': tot_delivered,
                'Active Riders': active_riders,
                'Store CPO (₹)': f"₹{cpo:.2f}"
            })
            
        st.dataframe(pd.DataFrame(all_store_rows), use_container_width=True)
        st.markdown("<br>", unsafe_allow_html=True)

    # Detailed Tabs
    tab_pick_disp, tab_del, tab_rider = st.tabs([
        "⚡ Express Pick & Dispatch Delays", 
        "🚚 Delivery Delays", 
        "🏍️ Rider Performance & CPO"
    ])
    
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
                reason_input = c5.text_input("Reason", key=f"pd_reason_{row['Order_ID']}", placeholder="Enter reason...")
                if c6.button("Submit", key=f"pd_btn_{row['Order_ID']}"):
                    if reason_input.strip() != "":
                        if append_saved_remark(row['Order_ID'], row['Store_Name'], "Express Delay", "Express", reason_input.strip()):
                            st.success(f"Saved: {row['Order_ID']}")
                            st.rerun()
                st.divider()
        else:
            st.success("🎉 Zero pending Express picking or dispatch breaches!")

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
                reason_input = c5.text_input("Reason", key=f"d_reason_{row['Order_ID']}", placeholder="Enter reason...")
                if c6.button("Submit", key=f"d_btn_{row['Order_ID']}"):
                    if reason_input.strip() != "":
                        if append_saved_remark(row['Order_ID'], row['Store_Name'], "Delivery Delay", row['Order_Type'], reason_input.strip()):
                            st.success(f"Saved: {row['Order_ID']}")
                            st.rerun()
                st.divider()
        else:
            st.success("🎉 Zero pending delivery breaches!")

    with tab_rider:
        st.subheader("🏍️ Rider Performance & Cost Per Order (CPO)")
        rider_df = filtered_df[filtered_df['Order_Status'] == 'DELIVERED'].copy()
        
        rider_summary = []
        for rider, r_group in rider_df.groupby('Rider_Name'):
            if rider == 'Unassigned':
                continue
            r_exp_cnt = int((r_group['Order_Type_Clean'] == 'express').sum())
            r_std_cnt = int((r_group['Order_Type_Clean'] != 'express').sum())
            tot_cnt = len(r_group)
            
            exp_r_group = r_group[r_group['Order_Type_Clean'] == 'express']
            avg_transit = exp_r_group['Transit_Duration_Min'].mean() if len(exp_r_group) > 0 else 0.0
            rider_cpo = round(1050.0 / tot_cnt, 2) if tot_cnt > 0 else 0.0
            
            rider_summary.append({
                'Rider Name': rider,
                'Express Delivered': r_exp_cnt,
                'Standard Delivered': r_std_cnt,
                'Total Delivered': tot_cnt,
                'Express Avg Delivery (Min)': f"{avg_transit:.1f} Min",
                'Rider CPO (₹)': f"₹{rider_cpo:.2f}"
            })
            
        if rider_summary:
            st.dataframe(pd.DataFrame(rider_summary), use_container_width=True)
        else:
            st.info("No active rider records found.")

# --- HISTORICAL SHEET DISPLAY (BEFORE UPLOAD) ---
else:
    if not kpi_history.empty:
        filtered_hist = kpi_history[
            (kpi_history['Date'].dt.date >= start_date) & 
            (kpi_history['Date'].dt.date <= end_date)
        ].copy()
        
        st.dataframe(filtered_hist, use_container_width=True)
    else:
        st.warning("No saved performance data available yet. Upload a report via the sidebar.")
