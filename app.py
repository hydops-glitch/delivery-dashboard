import streamlit as st
import pandas as pd
import numpy as np
import datetime
import plotly.graph_objects as go
from streamlit_gsheets import GSheetsConnection

# ==========================================
# 1. PAGE CONFIGURATION & STYLING
# ==========================================
st.set_page_config(
    page_title="Hyd Region Operations Portal",
    page_icon="🥩",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .main { background-color: #f8fafc; }
    div[data-testid="stMetricValue"] { font-size: 26px; font-weight: 700; color: #0f172a; }
    div[data-testid="stMetricSubValue"] { font-size: 12px; font-weight: 600; }
    .card-box { background-color: #ffffff; border-radius: 10px; padding: 16px; border: 1px solid #e2e8f0; }
    .badge-pending { background-color: #fef3c7; color: #92400e; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }
    .badge-approved { background-color: #d1fae5; color: #065f46; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }
    .badge-rejected { background-color: #fee2e2; color: #991b1b; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

DAILY_RIDER_COST = 1050.0  # ₹1050 per rider per day

# ==========================================
# 2. AUTHENTICATION & ROLE-BASED ACCESS
# ==========================================
APPROVED_DOMAINS = ["@prasuma.com", "@meatigo.com"]

if 'user_email' not in st.session_state:
    st.session_state['user_email'] = None

if not st.session_state['user_email']:
    st.title("Operations Portal Login")
    with st.form("login_form"):
        email_input = st.text_input("Company Email Address", placeholder="sreekanth@prasuma.com")
        submit_button = st.form_submit_button("Access Portal")
        
        if submit_button:
            clean_email = email_input.strip().lower()
            if any(clean_email.endswith(domain) for domain in APPROVED_DOMAINS):
                st.session_state['user_email'] = clean_email
                st.success("Authentication successful!")
                st.rerun()
            else:
                st.error("Access Denied: Please use a valid @prasuma.com or @meatigo.com email.")
    st.stop()

# Time-Specific Dynamic Greeting
current_hour = datetime.datetime.now().hour
greeting = "Good Morning" if current_hour < 12 else ("Good Afternoon" if current_hour < 17 else "Good Evening")
raw_name = st.session_state['user_email'].split('@')[0].replace('.', ' ').title()
display_name = "Sreekanth" if "sreekanth" in raw_name.lower() else raw_name

# ==========================================
# 3. GOOGLE SHEETS DATA ENGINE
# ==========================================
def parse_zone_minutes(zone_str):
    if pd.isna(zone_str): return 45.0
    z = str(zone_str).lower().strip()
    if '30' in z: return 30.0
    if '40' in z: return 40.0
    if '60' in z: return 60.0
    if '90' in z: return 90.0
    if '2.5' in z or '150' in z: return 150.0
    return 45.0

@st.cache_data(ttl=120)
def load_all_data():
    conn = st.connection("gsheets", type=GSheetsConnection)
    
    # Load Orders from Google Sheet with updated column structure
    raw_df = conn.read(worksheet="Raw_Orders")
    
    # Filter out cancelled / failed orders
    df = raw_df[~raw_df['Order Status'].astype(str).str.upper().isin(['PAYMENT FAILED', 'CANCELLED'])].copy()
    if 'Was Cancelled' in df.columns:
        df = df[df['Was Cancelled'].astype(str).str.upper() != 'TRUE']
    
    # Datetime parse
    dt_cols = ['Order date time', 'Placed Time', 'InPicking Time', 'Packed Time', 'Dispatched Time', 'Completed Time']
    for col in dt_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce')
            
    # Derive Order_Date from 'Order date time' (fallback to 'Placed Time')
    if 'Order date time' in df.columns and df['Order date time'].notna().any():
        df['Order_Date'] = df['Order date time'].dt.date
    else:
        df['Order_Date'] = df['Placed Time'].dt.date
        
    df['Delivery_Partner_Norm'] = df['Delivery Partner'].fillna('').astype(str).str.strip().str.upper()
    df['Is_Self'] = df['Delivery_Partner_Norm'] == 'SELF'
    
    # Pick Duration (InPicking -> Packed, fallback Placed -> Packed)
    has_inpick = df['InPicking Time'].notna() & (df['InPicking Time'] <= df['Packed Time'])
    df['Pick_Start'] = np.where(has_inpick, df['InPicking Time'], df['Placed Time'])
    df['Pick_Mins'] = (df['Packed Time'] - df['Pick_Start']).dt.total_seconds() / 60.0
    df['Pick_SLA_Met'] = df['Pick_Mins'] <= 3.0
    
    # Dispatch Duration (Packed -> Dispatched)
    df['Dispatch_Mins'] = (df['Dispatched Time'] - df['Packed Time']).dt.total_seconds() / 60.0
    df['Dispatch_SLA_Met'] = df['Dispatch_Mins'] <= 6.0
    
    # Zone Delivery Duration (Placed -> Completed)
    df['Zone_Target'] = df['Zone'].apply(parse_zone_minutes)
    df['Delivery_Mins'] = (df['Completed Time'] - df['Placed Time']).dt.total_seconds() / 60.0
    df['Delivery_SLA_Met'] = df['Delivery_Mins'] <= df['Zone_Target']

    # Load Remarks & Mapping
    try:
        remarks_df = conn.read(worksheet="Delay_Remarks")
    except:
        remarks_df = pd.DataFrame(columns=['Timestamp', 'Order ID', 'Order Date', 'Store Name', 'Stage', 'Delay Duration (Mins)', 'Delay Reason', 'Status', 'Manager Feedback', 'Submitted By'])
        
    try:
        mapping_df = conn.read(worksheet="Store_Mapping")
    except:
        mapping_df = pd.DataFrame({'Store Email': [st.session_state['user_email']], 'Store Name': ['ALL'], 'Role': ['Manager']})

    return df, remarks_df, mapping_df

def write_remark_to_gsheets(new_row_dict):
    conn = st.connection("gsheets", type=GSheetsConnection)
    existing_remarks = conn.read(worksheet="Delay_Remarks")
    updated_df = pd.concat([existing_remarks, pd.DataFrame([new_row_dict])], ignore_index=True)
    conn.update(worksheet="Delay_Remarks", data=updated_df)
    st.cache_data.clear()

try:
    orders_df, remarks_df, mapping_df = load_all_data()
except Exception as e:
    st.error(f"Google Sheets Connection Error: {e}")
    st.stop()

# Determine User Role and Assigned Store Scope
user_mapping = mapping_df[mapping_df['Store Email'].str.lower() == st.session_state['user_email']]
if not user_mapping.empty:
    user_role = user_mapping.iloc[0]['Role']
    assigned_store = user_mapping.iloc[0]['Store Name']
else:
    user_role = "Store"
    assigned_store = "TGN_HYD_HiTech"  # Default fallback

# Sidebar Controls
with st.sidebar:
    st.markdown("### User Profile")
    st.write(f"**Email:** {st.session_state['user_email']}")
    st.write(f"**Role:** {user_role}")
    st.write(f"**Assigned Store:** {assigned_store}")
    st.divider()
    if st.button("Logout"):
        st.session_state['user_email'] = None
        st.rerun()

# Role-Based Tab Rendering
if user_role == "Manager":
    tab1, tab2, tab3 = st.tabs(["📊 Hyd Region Metrics View", "🏪 Store Level View", "🛡️ Manager Audit & Review"])
else:
    tab1, tab2 = st.tabs(["📊 Store Metrics View", "🏪 Store Action & Delay Remarks"])
    tab3 = None

# ==========================================
# TAB 1: REGIONAL / STORE OVERVIEW
# ==========================================
with tab1:
    h1, h2 = st.columns([3, 1])
    with h1:
        st.title(f"{greeting}, {display_name}! 👋")
        st.caption("Hyd Region Performance Overview" if user_role == "Manager" else f"Store Performance Overview ({assigned_store})")
    with h2:
        st.button("🔄 Refresh Data", key="t1_ref", on_click=st.cache_data.clear)

    # Date Scope Selector
    date_options = sorted(orders_df['Order_Date'].dropna().unique(), reverse=True)
    sel_date = st.selectbox("Select Target Date", options=date_options, index=0, key="t1_date") if date_options else datetime.date.today()

    # Scope Filter
    if user_role == "Manager":
        t1_df = orders_df[orders_df['Order_Date'] == sel_date].copy()
    else:
        t1_df = orders_df[(orders_df['Order_Date'] == sel_date) & (orders_df['Store Name'] == assigned_store)].copy()

    exp_t1 = t1_df[t1_df['Order Type'] == 'Express']
    std_t1 = t1_df[t1_df['Order Type'] == 'Standard']

    # Top KPI Row
    k1, k2, k3, k4 = st.columns(4)
    total_ord = len(t1_df)
    del_ord = len(t1_df[t1_df['Order Status'].astype(str).str.upper() == 'DELIVERED'])
    k1.metric("Today's Orders", f"{total_ord}")
    k2.metric("Delivered Today", f"{del_ord}", "All Stores Delivered" if user_role == "Manager" else "Store Delivered")
    
    exp_pick_sla = (exp_t1['Pick_SLA_Met'].mean() * 100) if len(exp_t1) > 0 else 0.0
    exp_disp_sla = (exp_t1['Dispatch_SLA_Met'].mean() * 100) if len(exp_t1) > 0 else 0.0
    k3.metric("⚡ Packing SLA (<=3m)", f"{exp_pick_sla:.1f}%")
    k4.metric("⚡ Dispatch SLA (<=6m)", f"{exp_disp_sla:.1f}%")

    st.markdown("<br>", unsafe_allow_html=True)
    s1, s2 = st.columns(2)
    exp_del_sla = (exp_t1['Delivery_SLA_Met'].mean() * 100) if len(exp_t1) > 0 else 0.0
    std_del_sla = (std_t1['Delivery_SLA_Met'].mean() * 100) if len(std_t1) > 0 else 0.0
    s1.metric("⚡ Express Delivered SLA", f"{exp_del_sla:.1f}%", "↓ Target: 95.0%")
    s2.metric("Standard Delivered SLA", f"{std_del_sla:.1f}%", "↓ Target: 99.0%")

    st.divider()

    # Trend Views (Last 7 Days)
    c1, c2 = st.columns(2)
    min_date = sel_date - datetime.timedelta(days=6)
    
    if user_role == "Manager":
        trend_df = orders_df[(orders_df['Order_Date'] >= min_date) & (orders_df['Order_Date'] <= sel_date)].copy()
    else:
        trend_df = orders_df[(orders_df['Order_Date'] >= min_date) & (orders_df['Order_Date'] <= sel_date) & (orders_df['Store Name'] == assigned_store)].copy()

    # Daily aggregation
    if not trend_df.empty:
        daily_trend = trend_df.groupby('Order_Date').apply(lambda g: pd.Series({
            'Pick_SLA': g[g['Order Type']=='Express']['Pick_SLA_Met'].mean() * 100 if len(g[g['Order Type']=='Express']) > 0 else 0.0,
            'Dispatch_SLA': g[g['Order Type']=='Express']['Dispatch_SLA_Met'].mean() * 100 if len(g[g['Order Type']=='Express']) > 0 else 0.0,
            'Exp_Del_SLA': g[g['Order Type']=='Express']['Delivery_SLA_Met'].mean() * 100 if len(g[g['Order Type']=='Express']) > 0 else 0.0,
            'Std_Del_SLA': g[g['Order Type']=='Standard']['Delivery_SLA_Met'].mean() * 100 if len(g[g['Order Type']=='Standard']) > 0 else 0.0
        })).reset_index()
    else:
        daily_trend = pd.DataFrame(columns=['Order_Date', 'Pick_SLA', 'Dispatch_SLA', 'Exp_Del_SLA', 'Std_Del_SLA'])

    with c1:
        st.subheader("Packing & Dispatch Trend (Last 7 Days)")
        fig1 = go.Figure()
        fig1.add_trace(go.Scatter(x=daily_trend['Order_Date'], y=daily_trend['Pick_SLA'], name="🟢 Packing SLA % (<=3m)", line=dict(color="green", width=3)))
        fig1.add_trace(go.Scatter(x=daily_trend['Order_Date'], y=daily_trend['Dispatch_SLA'], name="🔴 Dispatch SLA % (<=6m)", line=dict(color="red", width=3)))
        fig1.update_layout(yaxis_range=[0, 100], margin=dict(l=20, r=20, t=30, b=20), legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig1, use_container_width=True)

    with c2:
        st.subheader("Delivery SLA Trend (Last 7 Days)")
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=daily_trend['Order_Date'], y=daily_trend['Exp_Del_SLA'], name="⚡ Blue Line: Express Delivery SLA %", line=dict(color="blue", width=3)))
        fig2.add_trace(go.Scatter(x=daily_trend['Order_Date'], y=daily_trend['Std_Del_SLA'], name="Orange Line: Standard Delivery SLA %", line=dict(color="orange", width=3)))
        fig2.update_layout(yaxis_range=[0, 100], margin=dict(l=20, r=20, t=30, b=20), legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig2, use_container_width=True)

    st.divider()

    # Regional Rider Productivity (HYD Overall Scope)
    st.subheader("🏍️ Rider Productivity & Regional CPO")
    self_orders = t1_df[t1_df['Is_Self']]
    active_riders_cnt = self_orders['Rider Name'].dropna().nunique()
    self_del_cnt = len(self_orders)
    tpl_del_cnt = len(t1_df) - self_del_cnt
    
    total_rider_cost = active_riders_cnt * DAILY_RIDER_COST
    cpo = (total_rider_cost / self_del_cnt) if self_del_cnt > 0 else 0.0

    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Active Self Riders", f"{active_riders_cnt}")
    r2.metric("Self Delivered Orders", f"{self_del_cnt}")
    r3.metric("3PL Delivered Orders", f"{tpl_del_cnt}")
    r4.metric("Regional CPO (₹1,050/head)", f"₹{cpo:.2f}")

# ==========================================
# TAB 2: STORE ACTION & DELAY REMARKS
# ==========================================
with tab2:
    st.title("🏪 Store Action & Delay Remarks")
    
    # Store Filter Selection
    if user_role == "Manager":
        active_store = st.selectbox("Select Store Location", sorted(orders_df['Store Name'].dropna().unique()), key="t2_store")
    else:
        active_store = assigned_store
        st.info(f"Active Store Scope: **{active_store}**")

    # Date Filter Range
    date_range_type = st.radio("Date Scope", ["Today", "Yesterday", "Custom Date"], horizontal=True, key="t2_dt_type")
    today_dt = datetime.date.today()
    
    if date_range_type == "Today":
        filter_dt = today_dt
    elif date_range_type == "Yesterday":
        filter_dt = today_dt - datetime.timedelta(days=1)
    else:
        filter_dt = st.date_input("Select Date", value=today_dt - datetime.timedelta(days=1), key="t2_custom_dt")

    store_df = orders_df[(orders_df['Store Name'] == active_store) & (orders_df['Order_Date'] == filter_dt)].copy()

    # Store Header Metrics
    sm1, sm2, sm3, sm4 = st.columns(4)
    s_exp = store_df[store_df['Order Type'] == 'Express']
    s_std = store_df[store_df['Order Type'] == 'Standard']
    
    sm1.metric("Total Store Orders", f"{len(store_df)}")
    sm2.metric("⚡ Pick SLA (<=3m)", f"{((s_exp['Pick_SLA_Met'].mean()*100) if len(s_exp)>0 else 0):.1f}%")
    sm3.metric("⚡ Express Delivery SLA", f"{((s_exp['Delivery_SLA_Met'].mean()*100) if len(s_exp)>0 else 0):.1f}%", "↓ Target: 95.0%")
    sm4.metric("Standard Delivery SLA", f"{((s_std['Delivery_SLA_Met'].mean()*100) if len(s_std)>0 else 0):.1f}%", "↓ Target: 99.0%")

    st.divider()

    # ACTION REQUIRED: PENDING & SAVED REMARKS
    st.subheader("ACTION REQUIRED: DELAY REMARKS MANAGEMENT")
    st.caption("Breached orders requiring delay reason updates or manager re-evaluations")

    sub_t1, sub_t2, sub_t3, sub_t4 = st.tabs(["📦 Packing Delays", "🚚 Dispatch Delays", "🚴 Delivery Delays", "📁 Saved / Audit History"])

    def render_delay_table(stage_name, df_breach):
        if df_breach.empty:
            st.success(f"No pending {stage_name} SLA breaches for this date!")
            return
            
        for idx, row in df_breach.iterrows():
            with st.container():
                c1, c2, c3, c4 = st.columns([1.5, 2, 3, 1.5])
                c1.write(f"**Order ID:** {row['Order ID']}")
                c1.write(f"**Date:** {row['Order_Date']}")
                c2.write(f"**Delay Duration:** `{row['Delay_Mins']:.1f} mins`")
                c2.write(f"**Rider/Partner:** {row['Delivery Partner']}")
                
                # Check existing status in remarks
                existing = remarks_df[(remarks_df['Order ID'] == row['Order ID']) & (remarks_df['Stage'] == stage_name)]
                current_reason = existing.iloc[-1]['Delay Reason'] if not existing.empty else ""
                mgr_feedback = existing.iloc[-1]['Manager Feedback'] if (not existing.empty and 'Manager Feedback' in existing.columns) else ""
                
                reason_input = c3.text_input(f"Delay Reason ({row['Order ID']})", value=current_reason, key=f"input_{stage_name}_{row['Order ID']}")
                if mgr_feedback:
                    c3.caption(f"⚠️ Manager Rejection Note: {mgr_feedback}")
                
                if c4.button("Save Remark", key=f"btn_{stage_name}_{row['Order ID']}"):
                    new_entry = {
                        'Timestamp': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'Order ID': row['Order ID'],
                        'Order Date': str(row['Order_Date']),
                        'Store Name': active_store,
                        'Stage': stage_name,
                        'Delay Duration (Mins)': round(row['Delay_Mins'], 1),
                        'Delay Reason': reason_input,
                        'Status': 'PENDING',
                        'Manager Feedback': '',
                        'Submitted By': st.session_state['user_email']
                    }
                    write_remark_to_gsheets(new_entry)
                    st.success("Remark Submitted!")
                    st.rerun()
            st.divider()

    # 1. Packing Delays (Express Orders > 3 mins)
    with sub_t1:
        p_breach = store_df[(store_df['Order Type'] == 'Express') & (store_df['Pick_SLA_Met'] == False)].copy()
        p_breach['Delay_Mins'] = p_breach['Pick_Mins'] - 3.0
        render_delay_table("Packing", p_breach)

    # 2. Dispatch Delays (Express Orders > 6 mins)
    with sub_t2:
        d_breach = store_df[(store_df['Order Type'] == 'Express') & (store_df['Dispatch_SLA_Met'] == False)].copy()
        d_breach['Delay_Mins'] = d_breach['Dispatch_Mins'] - 6.0
        render_delay_table("Dispatch", d_breach)

    # 3. Delivery Delays (All Orders > Zone SLA)
    with sub_t3:
        del_breach = store_df[store_df['Delivery_SLA_Met'] == False].copy()
        del_breach['Delay_Mins'] = del_breach['Delivery_Mins'] - del_breach['Zone_Target']
        render_delay_table("Delivery", del_breach)

    # 4. Saved / Audit History (View all saved remarks for selected date)
    with sub_t4:
        st.write(f"**Saved Remarks History for {active_store} on {filter_dt}**")
        saved_history = remarks_df[(remarks_df['Store Name'] == active_store) & (remarks_df['Order Date'] == str(filter_dt))]
        if not saved_history.empty:
            st.dataframe(saved_history[['Order ID', 'Stage', 'Delay Duration (Mins)', 'Delay Reason', 'Status', 'Manager Feedback', 'Submitted By']], hide_index=True, use_container_width=True)
        else:
            st.info("No saved remarks found for this date.")

    st.divider()

    # Rider Productivity & Store CPO
    st.subheader("🏍️ Store Rider Productivity & Performance")
    store_self = store_df[store_df['Is_Self']]
    s_riders = store_self['Rider Name'].dropna().nunique()
    s_self_cnt = len(store_self)
    s_3pl_cnt = len(store_df) - s_self_cnt
    
    s_cost = s_riders * DAILY_RIDER_COST
    s_cpo = (s_cost / s_self_cnt) if s_self_cnt > 0 else 0.0

    rc1, rc2, rc3, rc4 = st.columns(4)
    rc1.metric("Store Active Riders", f"{s_riders}")
    rc2.metric("Self Delivered", f"{s_self_cnt}")
    rc3.metric("3PL Delivered", f"{s_3pl_cnt}")
    rc4.metric("Store CPO (₹1,050/head)", f"₹{s_cpo:.2f}")

# ==========================================
# TAB 3: MANAGER AUDIT VIEW (MANAGERS ONLY)
# ==========================================
if user_role == "Manager" and tab3 is not None:
    with tab3:
        st.title("🛡️ Manager Audit & Review Portal")
        st.caption("Review, approve, or reject store-submitted delay remarks")

        pending_remarks = remarks_df[remarks_df['Status'] == 'PENDING'].copy()

        if pending_remarks.empty:
            st.success("All submitted delay remarks have been audited! No pending reviews.")
        else:
            for idx, r_row in pending_remarks.iterrows():
                with st.container():
                    mc1, mc2, mc3 = st.columns([2, 3, 2])
                    mc1.write(f"**Order ID:** {r_row['Order ID']} | **Date:** {r_row['Order Date']}")
                    mc1.write(f"**Store:** {r_row['Store Name']} | **Stage:** {r_row['Stage']}")
                    
                    mc2.write(f"**Delay:** `{r_row['Delay Duration (Mins)']} mins`")
                    mc2.write(f"**Submitted Reason:** {r_row['Delay Reason']}")
                    
                    feedback = mc2.text_input("Rejection Feedback (Required if Rejecting)", key=f"mgr_fb_{idx}")
                    
                    btn_col1, btn_col2 = mc3.columns(2)
                    if btn_col1.button("✅ Approve", key=f"app_{idx}"):
                        remarks_df.loc[idx, 'Status'] = 'APPROVED'
                        conn = st.connection("gsheets", type=GSheetsConnection)
                        conn.update(worksheet="Delay_Remarks", data=remarks_df)
                        st.cache_data.clear()
                        st.success("Remark Approved!")
                        st.rerun()
                        
                    if btn_col2.button("❌ Reject", key=f"rej_{idx}"):
                        if not feedback:
                            st.warning("Please provide feedback for rejection.")
                        else:
                            remarks_df.loc[idx, 'Status'] = 'REJECTED'
                            remarks_df.loc[idx, 'Manager Feedback'] = feedback
                            conn = st.connection("gsheets", type=GSheetsConnection)
                            conn.update(worksheet="Delay_Remarks", data=remarks_df)
                            st.cache_data.clear()
                            st.error("Remark Rejected & Sent Back to Store Tab!")
                            st.rerun()
                st.divider()
