import streamlit as st
import pandas as pd
import numpy as np
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from data_processor import process_and_merge_reports

st.set_page_config(
    page_title="Hyd Region Performance Dashboard", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# --- MODERN SAAS STYLING ---
st.markdown("""
<style>
    .stApp {
        background-color: #f8fafc;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    .header-title {
        font-size: 1.8rem;
        font-weight: 800;
        color: #0f172a;
        margin: 0;
    }
    .header-sub {
        font-size: 0.9rem;
        color: #64748b;
        margin-top: 2px;
    }
    .saas-card {
        background-color: #ffffff;
        border-radius: 12px;
        padding: 14px 18px;
        border: 1px solid #e2e8f0;
        box-shadow: 0 1px 3px rgba(0,0,0,0.03);
        margin-bottom: 14px;
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
        color: #64748b;
        text-transform: capitalize;
    }
    .saas-icon-badge {
        width: 30px;
        height: 30px;
        border-radius: 8px;
        background-color: #eff6ff;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1rem;
    }
    .saas-card-val {
        font-size: 1.6rem;
        font-weight: 800;
        color: #0f172a;
        line-height: 1;
    }
    .saas-card-sub-neutral { font-size: 0.8rem; font-weight: 500; color: #475569; }
    .saas-card-sub-blue { font-size: 0.8rem; font-weight: 600; color: #2563eb; }
    .saas-card-sub-gray { font-size: 0.8rem; font-weight: 500; color: #64748b; }
</style>
""", unsafe_allow_html=True)

# --- DYNAMIC TIME GREETING ---
def get_dynamic_greeting():
    current_hour = datetime.datetime.now().hour
    if current_hour < 12:
        return "Good morning 🌅"
    elif current_hour < 17:
        return "Good afternoon ☀️"
    else:
        return "Good evening 🌙"

# --- GOOGLE SHEETS SYNC ---
@st.cache_resource
def get_gspread_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def load_saved_remarks():
    try:
        client = get_gspread_client()
        sheet_id = st.secrets["sheets"]["spreadsheet_id"]
        sheet = client.open_by_key(sheet_id).sheet1
        records = sheet.get_all_records()
        df = pd.DataFrame(records)
        if not df.empty and 'Timestamp' in df.columns:
            df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce')
        return df
    except Exception:
        return pd.DataFrame(columns=['Order_ID', 'Store_Name', 'Delay_Type', 'Order_Type', 'Delay_Reason', 'Submitted_By', 'Timestamp'])

def append_saved_remark(order_id, store_name, delay_type, order_type, delay_reason, user_name):
    try:
        client = get_gspread_client()
        sheet_id = st.secrets["sheets"]["spreadsheet_id"]
        sheet = client.open_by_key(sheet_id).sheet1
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([str(order_id), str(store_name), str(delay_type), str(order_type), str(delay_reason), str(user_name), timestamp])
        return True
    except Exception as e:
        st.error(f"Error saving remark: {e}")
        return False

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
        
        # FIX FOR JSON SERIALIZATION: Clean NaN and Inf values
        export_df = export_df.fillna(0.0)
        export_df = export_df.replace([np.inf, -np.inf], 0.0)
        
        if 'Date' in export_df.columns:
            export_df['Date'] = export_df['Date'].astype(str)
            
        sheet.update([export_df.columns.values.tolist()] + export_df.values.tolist())
        return True
    except Exception as e:
        st.error(f"Error saving KPIs: {e}")
        return False

# --- SIDEBAR CONTROLS ---
st.sidebar.header("👤 User & Store Profile")
user_profile_name = st.sidebar.text_input("User / Manager Name", value="J Sreekanth")
store_profile_select = st.sidebar.selectbox("Active Store Scope", ["All Regional Stores", "TGN_HYD_BHills", "TGN_HYD_HiTech", "TGN_HYD_Manikonda"])

st.sidebar.markdown("---")
st.sidebar.header("📂 Data Upload")
uploaded_files = st.sidebar.file_uploader("Upload Order Reports (.xlsx / .csv)", accept_multiple_files=True)

saved_db = load_saved_remarks()
saved_order_ids = set(saved_db['Order_ID'].astype(str).unique()) if not saved_db.empty else set()

if uploaded_files:
    master_df = process_and_merge_reports(uploaded_files)
    if not master_df.empty:
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
            
            deliv_group = group[group['Order_Status'] == 'DELIVERED']
            self_delivered = len(deliv_group[deliv_group['Fulfillment_Type'] == 'Self'])
            tpl_delivered = len(deliv_group[deliv_group['Fulfillment_Type'] == '3PL'])
            
            active_riders = group[group['Rider_Name'] != 'Unassigned']['Rider_Name'].nunique()
            total_delivered = len(deliv_group)
            store_cpo = round((active_riders * 1050) / total_delivered, 2) if total_delivered > 0 else 0.0
            
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
                'Self_Delivered': self_delivered,
                '3PL_Delivered': tpl_delivered,
                'Store_CPO': store_cpo
            })
        
        new_kpi_df = pd.DataFrame(daily_summary)
        existing_kpi_df = load_saved_kpis()
        
        if not existing_kpi_df.empty:
            combined_kpis = pd.concat([existing_kpi_df, new_kpi_df]).drop_duplicates(subset=['Date', 'Store_Name'], keep='last')
        else:
            combined_kpis = new_kpi_df
            
        save_daily_kpis(combined_kpis)
        st.sidebar.success("Reports parsed & synced to Google Sheets!")

# --- LOAD ACTIVE DATASET & DYNAMIC FULL DATE RANGE ---
has_live_data = 'master_df' in st.session_state and isinstance(st.session_state['master_df'], pd.DataFrame) and not st.session_state['master_df'].empty
kpi_history = load_saved_kpis()

earliest_date = datetime.date.today()
latest_date = datetime.date.today()

if has_live_data:
    try:
        placed_times = pd.to_datetime(st.session_state['master_df']['Placed_Time'], errors='coerce').dropna()
        if not placed_times.empty:
            earliest_date = placed_times.dt.date.min()
            latest_date = placed_times.dt.date.max()
    except Exception:
        pass
elif isinstance(kpi_history, pd.DataFrame) and not kpi_history.empty and 'Date' in kpi_history.columns:
    try:
        parsed_dates = pd.to_datetime(kpi_history['Date'], errors='coerce').dropna()
        if not parsed_dates.empty:
            earliest_date = parsed_dates.dt.date.min()
            latest_date = parsed_dates.dt.date.max()
    except Exception:
        pass

# Fallback check
if pd.isna(earliest_date) or not isinstance(earliest_date, datetime.date):
    earliest_date = datetime.date.today()
if pd.isna(latest_date) or not isinstance(latest_date, datetime.date):
    latest_date = datetime.date.today()

# --- HEADER BAR ---
col_head, col_mode, col_date, col_ref = st.columns([3.2, 2.3, 2.2, 1.3])

greeting_str = get_dynamic_greeting()
display_identity = user_profile_name if store_profile_select == "All Regional Stores" else f"{user_profile_name} ({store_profile_select})"

with col_head:
    st.markdown(f'<div class="header-title">{greeting_str}, {display_identity}</div>', unsafe_allow_html=True)
    st.markdown('<div class="header-sub">Here\'s what\'s happening with your business today.</div>', unsafe_allow_html=True)

with col_mode:
    selected_view_mode = st.selectbox("Select View Mode", ["Overall Region View", "Store Level View"], index=1, label_visibility="collapsed")

with col_date:
    # Set default date range to cover whole uploaded dataset (July to till date)
    selected_date_range = st.date_input(
        "Filter Date", 
        value=(earliest_date, latest_date), 
        min_value=earliest_date,
        max_value=latest_date, 
        label_visibility="collapsed"
    )

with col_ref:
    if st.button("🔄 Refresh All", use_container_width=True):
        st.rerun()

st.markdown("<div style='margin-bottom: 18px;'></div>", unsafe_allow_html=True)

def resolve_dates(d_range):
    if isinstance(d_range, (tuple, list)):
        if len(d_range) == 2: return d_range[0], d_range[1]
        elif len(d_range) == 1: return d_range[0], d_range[0]
    return earliest_date, latest_date

start_date, end_date = resolve_dates(selected_date_range)

# --- CALCULATE METRICS ---
if has_live_data:
    df_active = st.session_state['master_df']
    if store_profile_select != "All Regional Stores":
        df_active = df_active[df_active['Store_Name'] == store_profile_select]
        
    filtered_df = df_active[
        (df_active['Placed_Time'].dt.date >= start_date) & 
        (df_active['Placed_Time'].dt.date <= end_date)
    ].copy()
    
    exp_df = filtered_df[filtered_df['Order_Type_Clean'] == 'express']
    std_df = filtered_df[filtered_df['Order_Type_Clean'] != 'express']
    
    tot_placed_orders = len(filtered_df)
    exp_orders = len(exp_df)
    std_orders = len(std_df)
    
    deliv_all = filtered_df[filtered_df['Order_Status'] == 'DELIVERED']
    delivered_total = len(deliv_all)
    self_deliv_cnt = len(deliv_all[deliv_all['Fulfillment_Type'] == 'Self'])
    tpl_deliv_cnt = len(deliv_all[deliv_all['Fulfillment_Type'] == '3PL'])
    
    exp_pack_pct = (exp_df['Pick_SLA_Met'].sum() / exp_orders * 100) if exp_orders > 0 else 0.0
    exp_disp_pct = (exp_df['Dispatch_SLA_Met'].sum() / exp_orders * 100) if exp_orders > 0 else 0.0
    
    deliv_exp = exp_df[exp_df['Order_Status'] == 'DELIVERED']
    deliv_std = std_df[std_df['Order_Status'] == 'DELIVERED']
    
    exp_del_pct = (deliv_exp['On_Time_Delivered'].sum() / len(deliv_exp) * 100) if len(deliv_exp) > 0 else 0.0
    std_del_pct = (deliv_std['On_Time_Delivered'].sum() / len(deliv_std) * 100) if len(deliv_std) > 0 else 0.0
    
    active_riders_cnt = filtered_df[filtered_df['Rider_Name'] != 'Unassigned']['Rider_Name'].nunique()
    region_cpo = (active_riders_cnt * 1050 / delivered_total) if delivered_total > 0 else 0.0

else:
    if isinstance(kpi_history, pd.DataFrame) and not kpi_history.empty:
        filtered_hist = kpi_history.copy()
        if 'Date' in filtered_hist.columns:
            filtered_hist['Date_Parsed'] = pd.to_datetime(filtered_hist['Date'], errors='coerce').dt.date
            filtered_hist = filtered_hist[
                (filtered_hist['Date_Parsed'] >= start_date) & 
                (filtered_hist['Date_Parsed'] <= end_date)
            ]
        if store_profile_select != "All Regional Stores" and 'Store_Name' in filtered_hist.columns:
            filtered_hist = filtered_hist[filtered_hist['Store_Name'] == store_profile_select]
    else:
        filtered_hist = pd.DataFrame()

    if not filtered_hist.empty:
        exp_orders = int(filtered_hist['Express_Orders'].sum()) if 'Express_Orders' in filtered_hist.columns else 0
        std_orders = int(filtered_hist['Standard_Orders'].sum()) if 'Standard_Orders' in filtered_hist.columns else 0
        delivered_total = int(filtered_hist['Total_Delivered'].sum()) if 'Total_Delivered' in filtered_hist.columns else 0
        tot_placed_orders = exp_orders + std_orders
        
        self_deliv_cnt = int(filtered_hist['Self_Delivered'].sum()) if 'Self_Delivered' in filtered_hist.columns else 0
        tpl_deliv_cnt = int(filtered_hist['3PL_Delivered'].sum()) if '3PL_Delivered' in filtered_hist.columns else 0
        
        exp_pack_pct = filtered_hist['Express_Packed_SLA'].mean() if 'Express_Packed_SLA' in filtered_hist.columns else 0.0
        exp_disp_pct = filtered_hist['Express_Dispatch_SLA'].mean() if 'Express_Dispatch_SLA' in filtered_hist.columns else 0.0
        exp_del_pct = filtered_hist['Express_Delivery_SLA'].mean() if 'Express_Delivery_SLA' in filtered_hist.columns else 0.0
        std_del_pct = filtered_hist['Standard_Delivery_SLA'].mean() if 'Standard_Delivery_SLA' in filtered_hist.columns else 0.0
        
        active_riders_cnt = int(filtered_hist['Active_Riders'].sum()) if 'Active_Riders' in filtered_hist.columns else 0
        region_cpo = filtered_hist['Store_CPO'].mean() if 'Store_CPO' in filtered_hist.columns else 0.0
    else:
        tot_placed_orders, exp_orders, std_orders, delivered_total, self_deliv_cnt, tpl_deliv_cnt = 0, 0, 0, 0, 0, 0
        exp_pack_pct, exp_disp_pct, exp_del_pct, std_del_pct, active_riders_cnt, region_cpo = 0.0, 0.0, 0.0, 0.0, 0, 0.0

# --- TOP ROW CARDS ---
c1, c2, c3, c4, c5 = st.columns(5)

with c1:
    st.markdown(f"""
    <div class="saas-card">
        <div class="saas-card-header">
            <span class="saas-card-title">Total Orders</span>
            <div class="saas-icon-badge">🛒</div>
        </div>
        <div class="saas-card-val">{tot_placed_orders:,}</div>
        <div class="saas-card-sub-gray">Delivered: {delivered_total} | Placed: {tot_placed_orders}</div>
    </div>
    """, unsafe_allow_html=True)

with c2:
    st.markdown(f"""
    <div class="saas-card">
        <div class="saas-card-header">
            <span class="saas-card-title">Express Pick SLA</span>
            <div class="saas-icon-badge">⚡</div>
        </div>
        <div class="saas-card-val">{exp_pack_pct:.1f}%</div>
        <div class="saas-card-sub-gray">Pick compliance</div>
    </div>
    """, unsafe_allow_html=True)

with c3:
    st.markdown(f"""
    <div class="saas-card">
        <div class="saas-card-header">
            <span class="saas-card-title">Express Dispatch SLA</span>
            <div class="saas-icon-badge">🚀</div>
        </div>
        <div class="saas-card-val">{exp_disp_pct:.1f}%</div>
        <div class="saas-card-sub-gray">Dispatch compliance</div>
    </div>
    """, unsafe_allow_html=True)

with c4:
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

with c5:
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

# --- SECOND ROW CARDS ---
rc1, rc2 = st.columns(2)

with rc1:
    st.markdown(f"""
    <div class="saas-card">
        <div class="saas-card-header">
            <span class="saas-card-title">Riders & Region CPO</span>
            <div class="saas-icon-badge">🏍️</div>
        </div>
        <div class="saas-card-val">₹{region_cpo:.2f}</div>
        <div class="saas-card-sub-neutral">Self Riders Delivered: {self_deliv_cnt} | Active Riders: {active_riders_cnt}</div>
    </div>
    """, unsafe_allow_html=True)

with rc2:
    st.markdown(f"""
    <div class="saas-card">
        <div class="saas-card-header">
            <span class="saas-card-title">Orders Volume Split</span>
            <div class="saas-icon-badge">📊</div>
        </div>
        <div class="saas-card-val">{exp_orders:,} <span style="font-size:1.1rem; color:#64748b; font-weight:500;">Exp</span> &nbsp;|&nbsp; {std_orders:,} <span style="font-size:1.1rem; color:#64748b; font-weight:500;">Standard</span></div>
        <div class="saas-card-sub-neutral">Self Delivered: {self_deliv_cnt} | 3PL Delivered: {tpl_deliv_cnt}</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<div style='margin-bottom: 20px;'></div>", unsafe_allow_html=True)

# --- STORE LEVEL BREAKDOWN ---
if selected_view_mode == "Store Level View":
    st.subheader("📊 Hyd Store Level Performance Breakdown")
    
    if has_live_data:
        store_rows = []
        for (order_date, store), s_group in filtered_df.groupby([filtered_df['Placed_Time'].dt.date, 'Store_Name']):
            s_exp = s_group[s_group['Order_Type_Clean'] == 'express']
            s_std = s_group[s_group['Order_Type_Clean'] != 'express']
            
            s_deliv_exp = s_exp[s_exp['Order_Status'] == 'DELIVERED']
            s_deliv_std = s_std[s_std['Order_Status'] == 'DELIVERED']
            
            p_pack = round((s_exp['Pick_SLA_Met'].sum() / len(s_exp) * 100), 1) if len(s_exp) > 0 else 0.0
            p_disp = round((s_exp['Dispatch_SLA_Met'].sum() / len(s_exp) * 100), 1) if len(s_exp) > 0 else 0.0
            p_del_exp = round((s_deliv_exp['On_Time_Delivered'].sum() / len(s_deliv_exp) * 100), 1) if len(s_deliv_exp) > 0 else 0.0
            p_del_std = round((s_deliv_std['On_Time_Delivered'].sum() / len(s_deliv_std) * 100), 1) if len(s_deliv_std) > 0 else 0.0
            
            s_deliv_group = s_group[s_group['Order_Status'] == 'DELIVERED']
            s_self_deliv = len(s_deliv_group[s_deliv_group['Fulfillment_Type'] == 'Self'])
            s_3pl_deliv = len(s_deliv_group[s_deliv_group['Fulfillment_Type'] == '3PL'])
            
            s_riders = s_group[s_group['Rider_Name'] != 'Unassigned']['Rider_Name'].nunique()
            s_deliv_tot = len(s_deliv_group)
            s_cpo = round((s_riders * 1050) / s_deliv_tot, 2) if s_deliv_tot > 0 else 0.0
            
            store_rows.append({
                'Date': str(order_date),
                'Store_Name': store,
                'Express_Packed_SLA': p_pack,
                'Express_Dispatch_SLA': p_disp,
                'Express_Delivery_SLA': p_del_exp,
                'Standard_Delivery_SLA': p_del_std,
                'Express_Orders': len(s_exp),
                'Standard_Orders': len(s_std),
                'Total_Delivered': s_deliv_tot,
                'Active_Riders': s_riders,
                'Self_Delivered': s_self_deliv,
                '3PL_Delivered': s_3pl_deliv,
                'Store_CPO': f"{s_cpo:.2f}"
            })
        st.dataframe(pd.DataFrame(store_rows), hide_index=True, use_container_width=True)
    
    else:
        if isinstance(filtered_hist, pd.DataFrame) and not filtered_hist.empty:
            display_hist = filtered_hist.copy()
            if 'Date_Parsed' in display_hist.columns:
                display_hist = display_hist.drop(columns=['Date_Parsed'])
            st.dataframe(display_hist, hide_index=True, use_container_width=True)
        else:
            st.info("No store performance data available for this date range.")

# --- TABS FOR REMARKS & BREACHES ---
st.markdown("<br>", unsafe_allow_html=True)
t1, t2, t3, t4 = st.tabs([
    "⚡ Express Breaches (Pick & Dispatch)", 
    "🚚 Delivery Breaches", 
    "📋 Manager Remarks Audit", 
    "🏍️ Rider Performance & CPO"
])

if has_live_data:
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
                cc.write(f"Pick: {row.get('Pick_Duration_Formatted', 'N/A')}")
                cd.write(f"Dispatch: {row.get('Dispatch_Duration_Formatted', 'N/A')}")
                r_in = ce.text_input("Delay Reason", key=f"pd_reason_{row['Order_ID']}", placeholder="Reason...")
                if cf.button("Submit", key=f"pd_btn_{row['Order_ID']}"):
                    if r_in.strip() != "":
                        if append_saved_remark(row['Order_ID'], row['Store_Name'], "Express Delay", "Express", r_in.strip(), display_identity):
                            st.success(f"Remark saved! Order {row['Order_ID']} removed from queue.")
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
                cc.write(row.get('Order_Type', 'Standard'))
                cd.write(f"Rider: {row.get('Rider_Name', 'Unassigned')}")
                r_in = ce.text_input("Delay Reason", key=f"d_reason_{row['Order_ID']}", placeholder="Reason...")
                if cf.button("Submit", key=f"d_btn_{row['Order_ID']}"):
                    if r_in.strip() != "":
                        if append_saved_remark(row['Order_ID'], row['Store_Name'], "Delivery Delay", row.get('Order_Type', 'Standard'), r_in.strip(), display_identity):
                            st.success(f"Remark saved! Order {row['Order_ID']} removed from queue.")
                            st.rerun()
                st.divider()
        else:
            st.success("🎉 No pending delivery breaches!")

# TAB 3: MANAGER REMARKS AUDIT
with t3:
    st.subheader("📋 Manager Audit - Submitted Store Remarks")
    audit_db = load_saved_remarks()
    
    if isinstance(audit_db, pd.DataFrame) and not audit_db.empty:
        if 'Timestamp' in audit_db.columns and pd.api.types.is_datetime64_any_dtype(audit_db['Timestamp']):
            audit_filtered = audit_db[
                (audit_db['Timestamp'].dt.date >= start_date) & 
                (audit_db['Timestamp'].dt.date <= end_date)
            ]
        else:
            audit_filtered = audit_db
            
        if store_profile_select != "All Regional Stores" and 'Store_Name' in audit_filtered.columns:
            audit_filtered = audit_filtered[audit_filtered['Store_Name'] == store_profile_select]
            
        if not audit_filtered.empty:
            st.dataframe(audit_filtered, hide_index=True, use_container_width=True)
        else:
            st.info("No store remarks submitted for the selected date range.")
    else:
        st.info("No store remarks stored in Google Sheets yet.")

if has_live_data:
    with t4:
        rider_df = filtered_df[filtered_df['Order_Status'] == 'DELIVERED'].copy()
        rider_summary = []
        for rider, r_group in rider_df.groupby('Rider_Name'):
            if rider == 'Unassigned':
                continue
            e_cnt = int((r_group['Order_Type_Clean'] == 'express').sum())
            s_cnt = int((r_group['Order_Type_Clean'] != 'express').sum())
            tot_c = len(r_group)
            
            exp_r_group = r_group[r_group['Order_Type_Clean'] == 'express']
            avg_transit = exp_r_group['Transit_Duration_Min'].mean() if ('Transit_Duration_Min' in exp_r_group.columns and len(exp_r_group) > 0) else 0.0
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
        else:
            st.info("No rider breakdown available for selected dataset.")
