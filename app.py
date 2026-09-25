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

st.markdown("""
<style>
    .stApp { background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    .header-title { font-size: 1.8rem; font-weight: 800; color: #0f172a; margin: 0; }
    .header-sub { font-size: 0.9rem; color: #64748b; margin-top: 2px; }
    .saas-card {
        background-color: #ffffff; border-radius: 12px; padding: 14px 18px;
        border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.03);
        margin-bottom: 14px; height: 110px; display: flex; flex-direction: column; justify-content: space-between;
    }
    .saas-card-header { display: flex; justify-content: space-between; align-items: center; }
    .saas-card-title { font-size: 0.78rem; font-weight: 600; color: #64748b; text-transform: capitalize; }
    .saas-icon-badge { width: 30px; height: 30px; border-radius: 8px; background-color: #eff6ff; display: flex; align-items: center; justify-content: center; font-size: 1rem; }
    .saas-card-val { font-size: 1.6rem; font-weight: 800; color: #0f172a; line-height: 1; }
    .saas-card-sub-neutral { font-size: 0.8rem; font-weight: 500; color: #475569; }
    .saas-card-sub-blue { font-size: 0.8rem; font-weight: 600; color: #2563eb; }
    .saas-card-sub-gray { font-size: 0.8rem; font-weight: 500; color: #64748b; }
</style>
""", unsafe_allow_html=True)

# DYNAMIC EVENING / MORNING GREETING
def get_dynamic_greeting():
    current_hour = datetime.datetime.now().hour
    if current_hour < 12: return "Good morning 🌅"
    elif current_hour < 17: return "Good afternoon ☀️"
    else: return "Good evening 🌙"

# Sidebar Setup
st.sidebar.header("👤 User & Store Profile")
user_profile_name = st.sidebar.text_input("User / Manager Name", value="J Sreekanth")
store_profile_select = st.sidebar.selectbox("Active Store Scope", ["All Regional Stores", "TGN_HYD_BHills", "TGN_HYD_HiTech", "TGN_HYD_Manikonda"])

st.sidebar.markdown("---")
st.sidebar.header("📂 Data Upload")
uploaded_files = st.sidebar.file_uploader("Upload Order Reports (.xlsx / .csv)", accept_multiple_files=True)

if uploaded_files:
    master_df, errors = process_and_merge_reports(uploaded_files)
    if errors:
        st.sidebar.error("❌ Processing Errors:")
        for err in errors: st.sidebar.error(f"- {err}")
    elif not master_df.empty:
        st.session_state['master_df'] = master_df
        st.sidebar.success("Report successfully parsed!")

has_live_data = 'master_df' in st.session_state and not st.session_state['master_df'].empty

# AUTO-DETECT LATEST AVAILABLE DATE
if has_live_data:
    placed_dates = st.session_state['master_df']['Placed_Time'].dropna().dt.date
    latest_date = placed_dates.max()
    earliest_date = placed_dates.min()
else:
    latest_date = datetime.date.today()
    earliest_date = datetime.date.today()

# Top Header Controls
col_head, col_mode, col_date, col_ref = st.columns([3.2, 2.3, 2.2, 1.3])
greeting_str = get_dynamic_greeting()

with col_head:
    st.markdown(f'<div class="header-title">{greeting_str}, {user_profile_name}</div>', unsafe_allow_html=True)
    st.markdown('<div class="header-sub">Here\'s what\'s happening with your business today.</div>', unsafe_allow_html=True)

with col_mode:
    selected_view_mode = st.selectbox("Select View Mode", ["Overall Region View", "Store Level View"], index=1, label_visibility="collapsed")

with col_date:
    selected_date_range = st.date_input("Filter Date", value=(latest_date, latest_date), min_value=earliest_date, max_value=latest_date, label_visibility="collapsed")

with col_ref:
    if st.button("🔄 Refresh All", use_container_width=True): st.rerun()

st.markdown("<div style='margin-bottom: 18px;'></div>", unsafe_allow_html=True)

# Process Active Filtered Data
if has_live_data:
    df_active = st.session_state['master_df']
    if store_profile_select != "All Regional Stores":
        df_active = df_active[df_active['Store_Name'] == store_profile_select]

    start_d = selected_date_range[0] if isinstance(selected_date_range, (tuple, list)) else selected_date_range
    end_d = selected_date_range[1] if isinstance(selected_date_range, (tuple, list)) and len(selected_date_range) > 1 else start_d

    filtered_df = df_active[(df_active['Placed_Time'].dt.date >= start_d) & (df_active['Placed_Time'].dt.date <= end_d)].copy()

    exp_df = filtered_df[filtered_df['Order_Type_Clean'] == 'express']
    std_df = filtered_df[filtered_df['Order_Type_Clean'] != 'express']

    tot_placed_orders = len(filtered_df)
    exp_orders = len(exp_df)
    std_orders = len(std_df)

    deliv_all = filtered_df[filtered_df['Order_Status'] == 'DELIVERED']
    delivered_total = len(deliv_all)
    self_deliv_cnt = len(deliv_all[deliv_all['Fulfillment_Type'] == 'Self'])
    tpl_deliv_cnt = len(deliv_all[deliv_all['Fulfillment_Type'] == '3PL'])

    exp_pack_pct = (exp_df['Pick_SLA_Met'].dropna().mean() * 100) if not exp_df['Pick_SLA_Met'].dropna().empty else 0.0
    exp_disp_pct = (exp_df['Dispatch_SLA_Met'].dropna().mean() * 100) if not exp_df['Dispatch_SLA_Met'].dropna().empty else 0.0

    deliv_exp = exp_df[exp_df['Order_Status'] == 'DELIVERED']
    deliv_std = std_df[std_df['Order_Status'] == 'DELIVERED']

    exp_del_pct = (deliv_exp['On_Time_Delivered'].dropna().mean() * 100) if not deliv_exp['On_Time_Delivered'].dropna().empty else 0.0
    std_del_pct = (deliv_std['On_Time_Delivered'].dropna().mean() * 100) if not deliv_std['On_Time_Delivered'].dropna().empty else 0.0

    active_riders_cnt = filtered_df[filtered_df['Rider_Name'] != 'Unassigned']['Rider_Name'].nunique()
    region_cpo = (active_riders_cnt * 1050 / delivered_total) if delivered_total > 0 else 0.0
else:
    tot_placed_orders, exp_orders, std_orders, delivered_total, self_deliv_cnt, tpl_deliv_cnt = 0, 0, 0, 0, 0, 0
    exp_pack_pct, exp_disp_pct, exp_del_pct, std_del_pct, active_riders_cnt, region_cpo = 0.0, 0.0, 0.0, 0.0, 0, 0.0
    filtered_df = pd.DataFrame()

# KPI Cards
c1, c2, c3, c4, c5 = st.columns(5)
with c1: st.markdown(f'<div class="saas-card"><div class="saas-card-header"><span class="saas-card-title">Total Orders</span><div class="saas-icon-badge">🛒</div></div><div class="saas-card-val">{tot_placed_orders:,}</div><div class="saas-card-sub-gray">Delivered: {delivered_total} | Placed: {tot_placed_orders}</div></div>', unsafe_allow_html=True)
with c2: st.markdown(f'<div class="saas-card"><div class="saas-card-header"><span class="saas-card-title">Express Pick SLA</span><div class="saas-icon-badge">⚡</div></div><div class="saas-card-val">{exp_pack_pct:.1f}%</div><div class="saas-card-sub-gray">Pick compliance</div></div>', unsafe_allow_html=True)
with c3: st.markdown(f'<div class="saas-card"><div class="saas-card-header"><span class="saas-card-title">Express Dispatch SLA</span><div class="saas-icon-badge">🚀</div></div><div class="saas-card-val">{exp_disp_pct:.1f}%</div><div class="saas-card-sub-gray">Dispatch compliance</div></div>', unsafe_allow_html=True)
with c4: st.markdown(f'<div class="saas-card"><div class="saas-card-header"><span class="saas-card-title">Express Delivery SLA</span><div class="saas-icon-badge">🚚</div></div><div class="saas-card-val">{exp_del_pct:.1f}%</div><div class="saas-card-sub-blue">Express orders</div></div>', unsafe_allow_html=True)
with c5: st.markdown(f'<div class="saas-card"><div class="saas-card-header"><span class="saas-card-title">Standard Delivery SLA</span><div class="saas-icon-badge">📦</div></div><div class="saas-card-val">{std_del_pct:.1f}%</div><div class="saas-card-sub-blue">Standard orders</div></div>', unsafe_allow_html=True)

rc1, rc2 = st.columns(2)
with rc1: st.markdown(f'<div class="saas-card"><div class="saas-card-header"><span class="saas-card-title">Riders & Region CPO</span><div class="saas-icon-badge">🏍️</div></div><div class="saas-card-val">₹{region_cpo:.2f}</div><div class="saas-card-sub-neutral">Self Riders Delivered: {self_deliv_cnt} | Active Riders: {active_riders_cnt}</div></div>', unsafe_allow_html=True)
with rc2: st.markdown(f'<div class="saas-card"><div class="saas-card-header"><span class="saas-card-title">Orders Volume Split</span><div class="saas-icon-badge">📊</div></div><div class="saas-card-val">{exp_orders:,} <span style="font-size:1.1rem; color:#64748b; font-weight:500;">Exp</span> &nbsp;|&nbsp; {std_orders:,} <span style="font-size:1.1rem; color:#64748b; font-weight:500;">Standard</span></div><div class="saas-card-sub-neutral">Self Delivered: {self_deliv_cnt} | 3PL Delivered: {tpl_deliv_cnt}</div></div>', unsafe_allow_html=True)

st.markdown("<div style='margin-bottom: 20px;'></div>", unsafe_allow_html=True)

# Store Level View
if selected_view_mode == "Store Level View" and has_live_data:
    st.subheader("📊 Hyd Store Level Performance Breakdown")
    store_rows = []
    for (order_date, store), s_group in filtered_df.groupby([filtered_df['Placed_Time'].dt.date, 'Store_Name']):
        s_exp = s_group[s_group['Order_Type_Clean'] == 'express']
        s_std = s_group[s_group['Order_Type_Clean'] != 'express']
        s_deliv_exp = s_exp[s_exp['Order_Status'] == 'DELIVERED']
        s_deliv_std = s_std[s_std['Order_Status'] == 'DELIVERED']

        p_pack = round((s_exp['Pick_SLA_Met'].dropna().mean() * 100), 1) if not s_exp['Pick_SLA_Met'].dropna().empty else 0.0
        p_disp = round((s_exp['Dispatch_SLA_Met'].dropna().mean() * 100), 1) if not s_exp['Dispatch_SLA_Met'].dropna().empty else 0.0
        p_del_exp = round((s_deliv_exp['On_Time_Delivered'].dropna().mean() * 100), 1) if not s_deliv_exp['On_Time_Delivered'].dropna().empty else 0.0
        p_del_std = round((s_deliv_std['On_Time_Delivered'].dropna().mean() * 100), 1) if not s_deliv_std['On_Time_Delivered'].dropna().empty else 0.0

        s_deliv_group = s_group[s_group['Order_Status'] == 'DELIVERED']
        s_self_deliv = len(s_deliv_group[s_deliv_group['Fulfillment_Type'] == 'Self'])
        s_3pl_deliv = len(s_deliv_group[s_deliv_group['Fulfillment_Type'] == '3PL'])

        s_riders = s_group[s_group['Rider_Name'] != 'Unassigned']['Rider_Name'].nunique()
        s_deliv_tot = len(s_deliv_group)
        s_cpo = round((s_riders * 1050) / s_deliv_tot, 2) if s_deliv_tot > 0 else 0.0

        store_rows.append({
            'Date': str(order_date),
            'Store_Name': store,
            'Express_Packed_SLA': f"{p_pack}%",
            'Express_Dispatch_SLA': f"{p_disp}%",
            'Express_Delivery_SLA': f"{p_del_exp}%",
            'Standard_Delivery_SLA': f"{p_del_std}%",
            'Express_Orders': len(s_exp),
            'Standard_Orders': len(s_std),
            'Total_Delivered': s_deliv_tot,
            'Self_Delivered': s_self_deliv,
            '3PL_Delivered': s_3pl_deliv,
            'Active_Riders': s_riders,
            'Store_CPO': f"₹{s_cpo:.2f}"
        })
    st.dataframe(pd.DataFrame(store_rows), hide_index=True, use_container_width=True)

# Tabs with Delay Minutes & Rider/3PL Performance
st.markdown("<br>", unsafe_allow_html=True)
t1, t2, t3 = st.tabs(["⚡ Express Breaches (Delay Min Included)", "🚚 Delivery Breaches", "🏍️ Rider & 3PL Performance Breakdown"])

if has_live_data:
    with t1:
        pick_breach = filtered_df[filtered_df['Pick_SLA_Met'] == 0][['Order_ID', 'Store_Name', 'Order_Type', 'Pick_Delay_Min']].copy()
        pick_breach['Pick_Delay_Min'] = pick_breach['Pick_Delay_Min'].apply(lambda x: f"{x:.1f} Mins" if pd.notna(x) else "N/A")
        st.write("### Pick SLA Breaches")
        st.dataframe(pick_breach, hide_index=True, use_container_width=True) if not pick_breach.empty else st.success("No Pick Breaches!")

    with t2:
        del_breach = filtered_df[filtered_df['On_Time_Delivered'] == 0][['Order_ID', 'Store_Name', 'Order_Type', 'Rider_Name', 'Fulfillment_Type', 'Delivery_Delay_Min']].copy()
        del_breach['Delivery_Delay_Min'] = del_breach['Delivery_Delay_Min'].apply(lambda x: f"{x:.1f} Mins" if pd.notna(x) else "N/A")
        st.write("### Delivery SLA Breaches")
        st.dataframe(del_breach, hide_index=True, use_container_width=True) if not del_breach.empty else st.success("No Delivery Breaches!")

    with t3:
        st.write("### Rider & 3PL Performance Summary")
        rider_df = filtered_df[filtered_df['Order_Status'] == 'DELIVERED'].copy()
        r_summary = []
        for rider, r_group in rider_df.groupby('Rider_Name'):
            if rider == 'Unassigned': continue
            e_cnt = int((r_group['Order_Type_Clean'] == 'express').sum())
            s_cnt = int((r_group['Order_Type_Clean'] != 'express').sum())
            tot_c = len(r_group)
            avg_del_time = r_group['Delivery_Delay_Min'].mean()
            r_type = r_group['Fulfillment_Type'].iloc[0]
            r_summary.append({
                'Rider / Partner Name': rider,
                'Fulfillment Type': r_type,
                'Express Delivered': e_cnt,
                'Standard Delivered': s_cnt,
                'Total Delivered': tot_c,
                'Avg Delivery Duration': f"{avg_del_time:.1f} Mins" if pd.notna(avg_del_time) else "N/A"
            })
        st.dataframe(pd.DataFrame(r_summary).sort_values(by='Total Delivered', ascending=False), hide_index=True, use_container_width=True)
