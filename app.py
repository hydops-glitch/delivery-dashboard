import streamlit as st
import pandas as pd
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from data_processor import process_and_merge_reports

st.set_page_config(
    page_title="Hyd Region Performance Dashboard", 
    layout="wide", 
    initial_sidebar_state="collapsed"
)

# --- MODERN EXECUTIVE UI STYLING (EXACT MATCH TO REFERENCE DASHBOARD) ---
st.markdown("""
<style>
    .stApp {
        background-color: #f4f6f9;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    
    /* Header Bar */
    .header-title {
        font-size: 1.75rem;
        font-weight: 800;
        color: #111827;
        margin: 0;
        line-height: 1.2;
    }
    .header-sub {
        font-size: 0.9rem;
        color: #6b7280;
        margin-top: 3px;
    }

    /* Executive SaaS Card Container */
    .saas-card {
        background-color: #ffffff;
        border-radius: 12px;
        padding: 16px 20px;
        border: 1px solid #e5e7eb;
        box-shadow: 0 1px 2px rgba(0,0,0,0.04);
        margin-bottom: 16px;
        height: 110px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
    }
    .saas-card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .saas-card-title {
        font-size: 0.78rem;
        font-weight: 600;
        color: #6b7280;
        text-transform: capitalize;
    }
    .saas-icon-badge {
        width: 32px;
        height: 32px;
        border-radius: 8px;
        background-color: #eff6ff;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.1rem;
    }
    .saas-card-val {
        font-size: 1.8rem;
        font-weight: 800;
        color: #111827;
        line-height: 1;
        margin-top: 2px;
    }
    .saas-card-sub-green {
        font-size: 0.8rem;
        font-weight: 600;
        color: #10b981;
    }
    .saas-card-sub-blue {
        font-size: 0.8rem;
        font-weight: 600;
        color: #2563eb;
    }
    .saas-card-sub-gray {
        font-size: 0.8rem;
        font-weight: 500;
        color: #6b7280;
    }

    /* Clean Table Styling */
    .stDataFrame {
        border-radius: 12px;
        border: 1px solid #e5e7eb;
        background-color: #ffffff;
    }
</style>
""", unsafe_allow_html=True)

# --- GOOGLE SHEETS CONNECTOR ---
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

# --- SIDEBAR CONTROLS ---
st.sidebar.header("📂 Data Import")
uploaded_files = st.sidebar.file_uploader("Upload Order Transitions Report (.xlsx / .csv)", accept_multiple_files=True)

saved_db = load_saved_remarks()
saved_order_ids = set(saved_db['Order_ID'].astype(str).unique()) if not saved_db.empty else set()

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
        
        # Two Separate Delivery SLAs
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
    st.sidebar.success("Data processed successfully!")

# --- LOAD DATA & LATEST DATE ---
has_live_data = 'master_df' in st.session_state
kpi_history = load_saved_kpis()

latest_date = datetime.date.today()
if has_live_data:
    latest_date = st.session_state['master_df']['Placed_Time'].dt.date.max()
elif not kpi_history.empty and 'Date' in kpi_history.columns:
    latest_date = kpi_history['Date'].dt.date.max()

# --- TOP HEADER BAR ---
col_head, col_mode, col_date, col_ref = st.columns([3.2, 2.3, 2.2, 1.3])

with col_head:
    st.markdown('<div class="header-title">Good evening 👋</div>', unsafe_allow_html=True)
    st.markdown('<div class="header-sub">Here\'s what\'s happening with your business today.</div>', unsafe_allow_html=True)

with col_mode:
    selected_view_mode = st.selectbox(
        "Select View Mode", 
        ["Overall Region View", "Store Level View"], 
        index=0, 
        label_visibility="collapsed"
    )

with col_date:
    selected_date_range = st.date_input(
        "Filter Date", 
        value=(latest_date, latest_date), 
        max_value=latest_date, 
        label_visibility="collapsed"
    )

with col_ref:
    if st.button("🔄 Refresh All", use_container_width=True):
        st.rerun()

st.markdown("<div style='margin-bottom: 20px;'></div>", unsafe_allow_html=True)

# Date bound resolver
def resolve_dates(d_range):
    if isinstance(d_range, tuple):
        if len(d_range) == 2:
            return d_range[0], d_range[1]
        elif len(d_range) == 1:
            return d_range[0], d_range[0]
    return latest_date, latest_date

start_date, end_date = resolve_dates(selected_date_range)

# --- CALCULATE AGGREGATES ---
if has_live_data:
    df_active = st.session_state['master_df']
    filtered_df = df_active[
        (df_active['Placed_Time'].dt.date >= start_date) & 
        (df_active['Placed_Time'].dt.date <= end_date)
    ].copy()
    
    exp_df = filtered_df[filtered_df['Order_Type_Clean'] == 'express']
    std_df = filtered_df[filtered_df['Order_Type_Clean'] != 'express']
    
    tot_orders = len(filtered_df)
    exp_orders = len(exp_df)
    std_orders = len(std_df)
    
    exp_pack_pct = (exp_df['Pick_SLA_Met'].sum() / exp_orders * 100) if exp_orders > 0 else 0.0
    exp_disp_pct = (exp_df['Dispatch_SLA_Met'].sum() / exp_orders * 100) if exp_orders > 0 else 0.0
    
    deliv_exp = exp_df[exp_df['Order_Status'] == 'DELIVERED']
    deliv_std = std_df[std_df['Order_Status'] == 'DELIVERED']
    
    exp_del_pct = (deliv_exp['On_Time_Delivered'].sum() / len(deliv_exp) * 100) if len(deliv_exp) > 0 else 0.0
    std_del_pct = (deliv_std['On_Time_Delivered'].sum() / len(deliv_std) * 100) if len(deliv_std) > 0 else 0.0
    
    delivered_total = len(filtered_df[filtered_df['Order_Status'] == 'DELIVERED'])
    active_riders_cnt = filtered_df[filtered_df['Rider_Name'] != 'Unassigned']['Rider_Name'].nunique()
    region_cpo = (active_riders_cnt * 1050 / delivered_total) if delivered_total > 0 else 0.0

else:
    if not kpi_history.empty:
        filtered_hist = kpi_history[
            (kpi_history['Date'].dt.date >= start_date) & 
            (kpi_history['Date'].dt.date <= end_date)
        ].copy()
    else:
        filtered_hist = pd.DataFrame()

    if not filtered_hist.empty:
        exp_orders = int(filtered_hist['Express_Orders'].sum())
        std_orders = int(filtered_hist['Standard_Orders'].sum())
        tot_orders = exp_orders + std_orders
        
        exp_pack_pct = filtered_hist['Express_Packed_SLA'].mean()
        exp_disp_pct = filtered_hist['Express_Dispatch_SLA'].mean()
        
        exp_del_pct = filtered_hist['Express_Delivery_SLA'].mean() if 'Express_Delivery_SLA' in filtered_hist.columns else filtered_hist['Delivery_SLA'].mean()
        std_del_pct = filtered_hist['Standard_Delivery_SLA'].mean() if 'Standard_Delivery_SLA' in filtered_hist.columns else filtered_hist['Delivery_SLA'].mean()
        
        active_riders_cnt = int(filtered_hist['Active_Riders'].sum())
        region_cpo = filtered_hist['Store_CPO'].mean()
    else:
        tot_orders, exp_orders, std_orders, exp_pack_pct, exp_disp_pct, exp_del_pct, std_del_pct, active_riders_cnt, region_cpo = 0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0, 0.0

# --- TOP ROW (5 METRIC CARDS) ---
r1_c1, r1_c2, r1_c3, r1_c4, r1_c5 = st.columns(5)

with r1_c1:
    st.markdown(f"""
    <div class="saas-card">
        <div class="saas-card-header">
            <span class="saas-card-title">Total Orders</span>
            <div class="saas-icon-badge">🛒</div>
        </div>
        <div class="saas-card-val">{tot_orders:,}</div>
        <div class="saas-card-sub-gray">Filtered range</div>
    </div>
    """, unsafe_allow_html=True)

with r1_c2:
    st.markdown(f"""
    <div class="saas-card">
        <div class="saas-card-header">
            <span class="saas-card-title">Express Pick SLA</span>
            <div class="saas-icon-badge">⚡</div>
        </div>
        <div class="saas-card-val">{exp_pack_pct:.1f}%</div>
        <div class="saas-card-sub-green">↑ Target ≤ 3m</div>
    </div>
    """, unsafe_allow_html=True)

with r1_c3:
    st.markdown(f"""
    <div class="saas-card">
        <div class="saas-card-header">
            <span class="saas-card-title">Express Dispatch SLA</span>
            <div class="saas-icon-badge">🚀</div>
        </div>
        <div class="saas-card-val">{exp_disp_pct:.1f}%</div>
        <div class="saas-card-sub-green">↑ Target ≤ 6m</div>
    </div>
    """, unsafe_allow_html=True)

with r1_c4:
    st.markdown(f"""
    <div class="saas-card">
        <div class="saas-card-header">
            <span class="saas-card-title">Express Delivery SLA</span>
            <div class="saas-icon-badge">🚚</div>
        </div>
        <div class="saas-card-val">{exp_del_pct:.1f}%</div>
        <div class="saas-card-sub-blue">Express orders</div>
    </div>
    """, unsafe_allow_html=True)

with r1_c5:
    st.markdown(f"""
    <div class="saas-card">
        <div class="saas-card-header">
            <span class="saas-card-title">Standard Delivery SLA</span>
            <div class="saas-icon-badge">📦</div>
        </div>
        <div class="saas-card-val">{std_del_pct:.1f}%</div>
        <div class="saas-card-sub-blue">Standard orders</div>
    </div>
    """, unsafe_allow_html=True)

# --- SECOND ROW (2 CARDS) ---
r2_c1, r2_c2, r2_c3, r2_c4, r2_c5 = st.columns(5)

with r2_c1:
    st.markdown(f"""
    <div class="saas-card">
        <div class="saas-card-header">
            <span class="saas-card-title">Riders & Region CPO</span>
            <div class="saas-icon-badge">🏍️</div>
        </div>
        <div class="saas-card-val">₹{region_cpo:.2f}</div>
        <div class="saas-card-sub-green">Active Riders: {active_riders_cnt}</div>
    </div>
    """, unsafe_allow_html=True)

with r2_c2:
    st.markdown(f"""
    <div class="saas-card">
        <div class="saas-card-header">
            <span class="saas-card-title">Orders Volume Split</span>
            <div class="saas-icon-badge">📊</div>
        </div>
        <div class="saas-card-val">{exp_orders:,} <span style="font-size:0.9rem; color:#6b7280;">Exp</span></div>
        <div class="saas-card-sub-blue">Standard: {std_orders:,}</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<div style='margin-bottom: 20px;'></div>", unsafe_allow_html=True)

# --- STORE LEVEL VIEW (INDEX NUMBERS COMPLETELY HIDDEN) ---
if selected_view_mode == "Store Level View":
    st.subheader("📊 Hyd Store Level Performance Breakdown")
    
    if has_live_data:
        store_rows = []
        for store, s_group in filtered_df.groupby('Store_Name'):
            s_exp = s_group[s_group['Order_Type_Clean'] == 'express']
            s_std = s_group[s_group['Order_Type_Clean'] != 'express']
            
            s_deliv_exp = s_exp[s_exp['Order_Status'] == 'DELIVERED']
            s_deliv_std = s_std[s_std['Order_Status'] == 'DELIVERED']
            
            p_pack = round((s_exp['Pick_SLA_Met'].sum() / len(s_exp) * 100), 1) if len(s_exp) > 0 else 0.0
            p_disp = round((s_exp['Dispatch_SLA_Met'].sum() / len(s_exp) * 100), 1) if len(s_exp) > 0 else 0.0
            p_del_exp = round((s_deliv_exp['On_Time_Delivered'].sum() / len(s_deliv_exp) * 100), 1) if len(s_deliv_exp) > 0 else 0.0
            p_del_std = round((s_deliv_std['On_Time_Delivered'].sum() / len(s_deliv_std) * 100), 1) if len(s_deliv_std) > 0 else 0.0
            
            s_riders = s_group[s_group['Rider_Name'] != 'Unassigned']['Rider_Name'].nunique()
            s_deliv_tot = len(s_group[s_group['Order_Status'] == 'DELIVERED'])
            s_cpo = round((s_riders * 1050) / s_deliv_tot, 2) if s_deliv_tot > 0 else 0.0
            
            store_rows.append({
                'Date': str(start_date),
                'Store Name': store,
                'Express Packed SLA (%)': p_pack,
                'Express Dispatch SLA (%)': p_disp,
                'Express Delivery SLA (%)': p_del_exp,
                'Standard Delivery SLA (%)': p_del_std,
                'Express Orders': len(s_exp),
                'Standard Orders': len(s_std),
                'Total Delivered': s_deliv_tot,
                'Active Riders': s_riders,
                'Store CPO (₹)': f"₹{s_cpo:.2f}"
            })
        st.dataframe(pd.DataFrame(store_rows), hide_index=True, use_container_width=True)
    
    else:
        if not filtered_hist.empty:
            display_hist = filtered_hist.copy()
            if 'Date' in display_hist.columns:
                display_hist['Date'] = display_hist['Date'].dt.strftime('%Y-%m-%d')
            st.dataframe(display_hist, hide_index=True, use_container_width=True)
        else:
            st.info("No store performance data available for this date range.")

# --- BREACH MANAGEMENT TABS ---
if has_live_data:
    st.markdown("<br>", unsafe_allow_html=True)
    t1, t2, t3 = st.tabs([
        "⚡ Express Breaches (Pick & Dispatch)", 
        "🚚 Delivery Breaches", 
        "🏍️ Rider Performance & CPO"
    ])
    
    with t1:
        breached_exp = exp_df[
            ((exp_df['Pick_SLA_Met'] == 0) | (exp_df['Dispatch_SLA_Met'] == 0)) & 
            (~exp_df['Order_ID'].astype(str).isin(saved_order_ids))
        ].copy()
        
        if not breached_exp.empty:
            for idx, row in breached_exp.iterrows():
                ca, cb, cc, cd, ce, cf = st.columns([2, 1.5, 2, 2, 3, 1.5])
                ca.write(f"**{row['Order_ID']}**")
                cb.write(row['Store_Name'])
                cc.write(f"Pick: {row['Pick_Duration_Formatted']}")
                cd.write(f"Dispatch: {row['Dispatch_Duration_Formatted']}")
                r_in = ce.text_input("Delay Reason", key=f"pd_reason_{row['Order_ID']}", placeholder="Reason...")
                if cf.button("Submit", key=f"pd_btn_{row['Order_ID']}"):
                    if r_in.strip() != "":
                        if append_saved_remark(row['Order_ID'], row['Store_Name'], "Express Delay", "Express", r_in.strip()):
                            st.success(f"Saved: {row['Order_ID']}")
                            st.rerun()
                st.divider()
        else:
            st.success("🎉 No pending Express pick/dispatch breaches!")

    with t2:
        del_breached = filtered_df[
            (filtered_df['On_Time_Delivered'] == 0) & 
            (~filtered_df['Order_ID'].astype(str).isin(saved_order_ids))
        ].copy()
        
        if not del_breached.empty:
            for idx, row in del_breached.iterrows():
                ca, cb, cc, cd, ce, cf = st.columns([2, 1.5, 1.5, 2, 3, 1.5])
                ca.write(f"**{row['Order_ID']}**")
                cb.write(row['Store_Name'])
                cc.write(row['Order_Type'])
                cd.write(f"Rider: {row['Rider_Name']}")
                r_in = ce.text_input("Delay Reason", key=f"d_reason_{row['Order_ID']}", placeholder="Reason...")
                if cf.button("Submit", key=f"d_btn_{row['Order_ID']}"):
                    if r_in.strip() != "":
                        if append_saved_remark(row['Order_ID'], row['Store_Name'], "Delivery Delay", row['Order_Type'], r_in.strip()):
                            st.success(f"Saved: {row['Order_ID']}")
                            st.rerun()
                st.divider()
        else:
            st.success("🎉 No pending delivery breaches!")

    with t3:
        rider_df = filtered_df[filtered_df['Order_Status'] == 'DELIVERED'].copy()
        rider_summary = []
        for rider, r_group in rider_df.groupby('Rider_Name'):
            if rider == 'Unassigned':
                continue
            e_cnt = int((r_group['Order_Type_Clean'] == 'express').sum())
            s_cnt = int((r_group['Order_Type_Clean'] != 'express').sum())
            tot_c = len(r_group)
            
            exp_r_group = r_group[r_group['Order_Type_Clean'] == 'express']
            avg_transit = exp_r_group['Transit_Duration_Min'].mean() if len(exp_r_group) > 0 else 0.0
            r_cpo = round(1050.0 / tot_c, 2) if tot_c > 0 else 0.0
            
            rider_summary.append({
                'Rider Name': rider,
                'Express Orders Delivered': e_cnt,
                'Standard Orders Delivered': s_cnt,
                'Total Delivered': tot_c,
                'Express Avg Delivery (Min)': f"{avg_transit:.1f} Min",
                'Rider CPO (₹)': f"₹{r_cpo:.2f}"
            })
            
        if rider_summary:
            st.dataframe(pd.DataFrame(rider_summary), hide_index=True, use_container_width=True)
