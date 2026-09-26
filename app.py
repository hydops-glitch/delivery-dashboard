import streamlit as st
import pandas as pd
import numpy as np
import datetime
import plotly.graph_objects as go

# ==========================================
# 1. PAGE CONFIGURATION & STYLING
# ==========================================
st.set_page_config(
    page_title="Meatigo Operations Portal",
    page_icon="🥩",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for UI layout enhancement
st.markdown("""
<style>
    .main { background-color: #f8fafc; }
    div[data-testid="stMetricValue"] { font-size: 26px; font-weight: 700; color: #0f172a; }
    div[data-testid="stMetricSubValue"] { font-size: 13px; font-weight: 600; }
    .stTable { background-color: #ffffff; border-radius: 8px; }
</style>
""", unsafe_allow_html=True)

DAILY_RIDER_COST = 1050.0  # ₹1050 per rider per day
SHEET_ID = "1RUxzJbHW7HHUxbT2sJzNvBrNatLsvgBss6W86CdgMzo"

# Target Definitions
TARGET_EXPRESS_PACK = 99.0
TARGET_EXPRESS_DISPATCH = 95.0
TARGET_EXPRESS_DELIVERY = 95.0
TARGET_STANDARD_DELIVERY = 99.0

# ==========================================
# 2. AUTHENTICATION & ROLE MANAGEMENT
# ==========================================
APPROVED_DOMAINS = ["@prasuma.com", "@meatigo.com"]

if 'user_email' not in st.session_state:
    st.session_state['user_email'] = None

if not st.session_state['user_email']:
    st.title("Meatigo Operations Portal Login")
    with st.form("login_form"):
        email_input = st.text_input("Company Email Address", placeholder="hyd_ops@prasuma.com")
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

# Dynamic Greeting Logic
current_hour = datetime.datetime.now().hour
greeting = "Good Morning" if current_hour < 12 else ("Good Afternoon" if current_hour < 17 else "Good Evening")
raw_name = st.session_state['user_email'].split('@')[0].replace('.', ' ').replace('_', ' ').title()
display_name = "Sreekanth" if "sreekanth" in raw_name.lower() or "hyd_ops" in raw_name.lower() else raw_name

# ==========================================
# 3. DATA ENGINE
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

@st.cache_data(ttl=60)
def load_all_data():
    raw_orders_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=Raw_Orders"
    delay_remarks_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=Delay_Remarks"
    store_mapping_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=Store_Mapping"

    raw_df = pd.read_csv(raw_orders_url)
    
    # Exclude PAYMENT FAILED and CANCELLED
    df = raw_df[~raw_df['Order Status'].astype(str).str.upper().isin(['PAYMENT FAILED', 'CANCELLED'])].copy()
    if 'Was Cancelled' in df.columns:
        df = df[df['Was Cancelled'].astype(str).str.upper() != 'TRUE']

    # Date parsing
    if 'Order date time' in df.columns:
        df['Parsed_DateTime'] = pd.to_datetime(df['Order date time'], errors='coerce')
    else:
        df['Parsed_DateTime'] = pd.to_datetime(df['Placed Time'], errors='coerce')
        
    df['Order_Date'] = df['Parsed_DateTime'].dt.date

    dt_cols = ['Placed Time', 'InPicking Time', 'Packed Time', 'Dispatched Time', 'Completed Time']
    for col in dt_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce')

    df['Delivery_Partner_Norm'] = df['Delivery Partner'].fillna('').astype(str).str.strip().str.upper()
    df['Is_Self'] = df['Delivery_Partner_Norm'] == 'SELF'
    
    # Packing SLA (<= 3 mins)
    has_inpick = df['InPicking Time'].notna() & (df['InPicking Time'] <= df['Packed Time'])
    df['Pick_Start'] = np.where(has_inpick, df['InPicking Time'], df['Placed Time'])
    df['Pick_Mins'] = (df['Packed Time'] - df['Pick_Start']).dt.total_seconds() / 60.0
    df['Pick_SLA_Met'] = df['Pick_Mins'] <= 3.0
    
    # Dispatch SLA (<= 6 mins)
    df['Dispatch_Mins'] = (df['Dispatched Time'] - df['Packed Time']).dt.total_seconds() / 60.0
    df['Dispatch_SLA_Met'] = df['Dispatch_Mins'] <= 6.0
    
    # Delivery SLA
    df['Zone_Target'] = df['Zone'].apply(parse_zone_minutes)
    df['Delivery_Mins'] = (df['Completed Time'] - df['Placed Time']).dt.total_seconds() / 60.0
    df['Delivery_SLA_Met'] = df['Delivery_Mins'] <= df['Zone_Target']

    try:
        remarks_df = pd.read_csv(delay_remarks_url)
    except Exception:
        remarks_df = pd.DataFrame(columns=['Timestamp', 'Order ID', 'Order Date', 'Store Name', 'Stage', 'Delay Duration (Mins)', 'Delay Reason', 'Status', 'Manager Feedback', 'Submitted By'])
        
    try:
        mapping_df = pd.read_csv(store_mapping_url)
    except Exception:
        mapping_df = pd.DataFrame({'Store Email': [st.session_state['user_email']], 'Store Name': ['ALL'], 'Role': ['Manager']})

    return df, remarks_df, mapping_df

try:
    orders_df, remarks_df, mapping_df = load_all_data()
except Exception as e:
    st.error(f"Error loading data from Google Sheet: {e}")
    st.stop()

# Determine User Role and Assigned Store
user_mapping = mapping_df[mapping_df['Store Email'].astype(str).str.lower() == st.session_state['user_email'].lower()]
if not user_mapping.empty:
    user_role = user_mapping.iloc[0]['Role'].strip().title()
    assigned_store = user_mapping.iloc[0]['Store Name'].strip()
else:
    if "ops" in st.session_state['user_email'] or "manager" in st.session_state['user_email']:
        user_role = "Manager"
        assigned_store = "ALL"
    else:
        user_role = "Store"
        assigned_store = "TGN_HYD_BHills"

# ==========================================
# 4. SIDEBAR NAVIGATION (PDF SPEC)
# ==========================================
with st.sidebar:
    st.title("Meatigo Portal")
    st.markdown(f"**Email:** {st.session_state['user_email']}")
    st.markdown(f"**Role:** {user_role}")
    st.markdown(f"**Assigned Store:** {assigned_store}")
    st.divider()

    # Navigation Options matching PDF Tab Names
    if user_role == "Manager":
        nav_choice = st.radio(
            "Navigation Menu",
            ["📊 Hyd Region Metrics View", "🏪 Store Level View", "🛡️ Manager Audit & Review"],
            index=0
        )
    else:
        nav_choice = st.radio(
            "Navigation Menu",
            ["📊 Store Metrics View", "🏪 Store Level View"],
            index=0
        )

    st.divider()
    if st.button("Logout"):
        st.session_state['user_email'] = None
        st.rerun()

# ==========================================
# PAGE 1: HYD REGION METRICS VIEW
# ==========================================
if nav_choice in ["📊 Hyd Region Metrics View", "📊 Store Metrics View"]:
    h1, h2 = st.columns([3, 1])
    with h1:
        st.title(f"{greeting}, {display_name}!")
        st.caption("Hyd Region Operations Portal" if user_role == "Manager" else f"Store Performance Overview ({assigned_store})")
    with h2:
        st.button("🔄 Refresh Data", key="t1_ref", on_click=st.cache_data.clear)

    date_options = sorted([d for d in orders_df['Order_Date'].dropna().unique()], reverse=True)
    if len(date_options) > 0:
        sel_date = st.selectbox("Select Date Target", options=date_options, index=0, key="t1_date")
    else:
        sel_date = datetime.date.today()

    # Scope Filter
    if user_role == "Manager" or assigned_store == "ALL":
        t1_df = orders_df[orders_df['Order_Date'] == sel_date].copy()
    else:
        t1_df = orders_df[(orders_df['Order_Date'] == sel_date) & (orders_df['Store Name'] == assigned_store)].copy()

    exp_t1 = t1_df[t1_df['Order Type'] == 'Express']
    std_t1 = t1_df[t1_df['Order Type'] == 'Standard']

    # SLA Calculations
    exp_pack_sla = (exp_t1['Pick_SLA_Met'].mean() * 100) if len(exp_t1) > 0 else 0.0
    exp_disp_sla = (exp_t1['Dispatch_SLA_Met'].mean() * 100) if len(exp_t1) > 0 else 0.0
    exp_del_sla = (exp_t1['Delivery_SLA_Met'].mean() * 100) if len(exp_t1) > 0 else 0.0
    std_del_sla = (std_t1['Delivery_SLA_Met'].mean() * 100) if len(std_t1) > 0 else 0.0

    # 6-KPI GRID LAYOUT
    col1, col2, col3 = st.columns(3)
    col4, col5, col6 = st.columns(3)

    # Row 1 KPIs
    col1.metric("TOTAL ORDERS PLACED", f"{len(t1_df)}", "All Stores Today")
    col2.metric("DELIVERED TODAY", f"{len(t1_df[t1_df['Order Status'] == 'DELIVERED'])}", "All Stores Delivered")
    
    # Express Packing SLA (Target 99.0%)
    pack_delta = f"{'🟢' if exp_pack_sla >= TARGET_EXPRESS_PACK else '🔴'} Target: {TARGET_EXPRESS_PACK}%"
    col3.metric("⚡ EXPRESS PACKING SLA (≤3M)", f"{exp_pack_sla:.1f}%", pack_delta)

    # Row 2 KPIs
    # Express Dispatch SLA (Target 95.0%)
    disp_delta = f"{'🟢' if exp_disp_sla >= TARGET_EXPRESS_DISPATCH else '🔴'} Target: {TARGET_EXPRESS_DISPATCH}%"
    col4.metric("⚡ EXPRESS DISPATCH SLA (≤6M)", f"{exp_disp_sla:.1f}%", disp_delta)

    # Express Delivery SLA (Target 95.0%)
    exp_del_delta = f"{'🟢' if exp_del_sla >= TARGET_EXPRESS_DELIVERY else '🔴'} Target: {TARGET_EXPRESS_DELIVERY}%"
    col5.metric("⚡ EXPRESS DELIVERED SLA", f"{exp_del_sla:.1f}%", exp_del_delta)

    # Standard Delivery SLA (Target 99.0%)
    std_del_delta = f"{'🟢' if std_del_sla >= TARGET_STANDARD_DELIVERY else '🔴'} Target: {TARGET_STANDARD_DELIVERY}%"
    col6.metric("STANDARD DELIVERED SLA", f"{std_del_sla:.1f}%", std_del_delta)

    st.divider()

    # Trend Charts (Last 7 Days)
    c1, c2 = st.columns(2)
    min_date = sel_date - datetime.timedelta(days=6)
    
    if user_role == "Manager" or assigned_store == "ALL":
        trend_df = orders_df[(orders_df['Order_Date'] >= min_date) & (orders_df['Order_Date'] <= sel_date)].copy()
    else:
        trend_df = orders_df[(orders_df['Order_Date'] >= min_date) & (orders_df['Order_Date'] <= sel_date) & (orders_df['Store Name'] == assigned_store)].copy()

    if not trend_df.empty:
        daily_trend = trend_df.groupby('Order_Date').apply(lambda g: pd.Series({
            'Pick_SLA': (g[g['Order Type']=='Express']['Pick_SLA_Met'].mean() * 100) if len(g[g['Order Type']=='Express']) > 0 else 0.0,
            'Dispatch_SLA': (g[g['Order Type']=='Express']['Dispatch_SLA_Met'].mean() * 100) if len(g[g['Order Type']=='Express']) > 0 else 0.0,
            'Exp_Del_SLA': (g[g['Order Type']=='Express']['Delivery_SLA_Met'].mean() * 100) if len(g[g['Order Type']=='Express']) > 0 else 0.0,
            'Std_Del_SLA': (g[g['Order Type']=='Standard']['Delivery_SLA_Met'].mean() * 100) if len(g[g['Order Type']=='Standard']) > 0 else 0.0
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
        fig2.add_trace(go.Scatter(x=daily_trend['Order_Date'], y=daily_trend['Exp_Del_SLA'], name="⚡ Express Delivery SLA %", line=dict(color="blue", width=3)))
        fig2.add_trace(go.Scatter(x=daily_trend['Order_Date'], y=daily_trend['Std_Del_SLA'], name="Standard Delivery SLA %", line=dict(color="orange", width=3)))
        fig2.update_layout(yaxis_range=[0, 100], margin=dict(l=20, r=20, t=30, b=20), legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig2, use_container_width=True)

    st.divider()

    # STORE WISE PERFORMANCE SUMMARY TABLE
    st.subheader("Store Wise Performance Summary")
    
    if not t1_df.empty:
        store_summary = []
        for store_name, group in t1_df.groupby('Store Name'):
            e_grp = group[group['Order Type'] == 'Express']
            s_grp = group[group['Order Type'] == 'Standard']
            
            p_sla = (e_grp['Pick_SLA_Met'].mean() * 100) if len(e_grp) > 0 else 0.0
            d_sla = (e_grp['Dispatch_SLA_Met'].mean() * 100) if len(e_grp) > 0 else 0.0
            ex_del = (e_grp['Delivery_SLA_Met'].mean() * 100) if len(e_grp) > 0 else 0.0
            st_del = (s_grp['Delivery_SLA_Met'].mean() * 100) if len(s_grp) > 0 else 0.0
            
            self_cnt = len(group[group['Is_Self']])
            tpl_cnt = len(group) - self_cnt
            
            store_summary.append({
                "Store Name": store_name,
                "Pack SLA": f"{p_sla:.1f}%",
                "Disp SLA": f"{d_sla:.1f}%",
                "Exp Del SLA": f"{ex_del:.1f}%",
                "Std Del SLA": f"{st_del:.1f}%",
                "Self Orders": self_cnt,
                "3PL Orders": tpl_cnt
            })
        st.dataframe(pd.DataFrame(store_summary), use_container_width=True, hide_index=True)
    else:
        st.info("No store data available for selected date.")

# ==========================================
# PAGE 2: STORE LEVEL VIEW
# ==========================================
elif nav_choice == "🏪 Store Level View":
    st.title("🏪 Store Level View")
    
    if user_role == "Manager":
        active_store = st.selectbox("Select Store Scope", sorted(orders_df['Store Name'].dropna().unique()), key="t2_store")
    else:
        active_store = assigned_store
        st.info(f"Store View: **{active_store}**")

    date_options = sorted([d for d in orders_df['Order_Date'].dropna().unique()], reverse=True)
    if len(date_options) > 0:
        filter_dt = st.selectbox("Date Scope", date_options, key="t2_sel_dt")
    else:
        filter_dt = datetime.date.today()

    store_df = orders_df[(orders_df['Store Name'] == active_store) & (orders_df['Order_Date'] == filter_dt)].copy()

    # Store KPIs
    sm1, sm2, sm3, sm4, sm5 = st.columns(5)
    s_exp = store_df[store_df['Order Type'] == 'Express']
    s_std = store_df[store_df['Order Type'] == 'Standard']
    
    sm1.metric("TOTAL STORE ORDERS", f"{len(store_df)}")
    
    p_val = (s_exp['Pick_SLA_Met'].mean()*100) if len(s_exp)>0 else 0.0
    sm2.metric("PACK SLA", f"{p_val:.1f}%", f"{'🟢' if p_val>=TARGET_EXPRESS_PACK else '🔴'} Target: {TARGET_EXPRESS_PACK}%")
    
    d_val = (s_exp['Dispatch_SLA_Met'].mean()*100) if len(s_exp)>0 else 0.0
    sm3.metric("DISPATCH SLA", f"{d_val:.1f}%", f"{'🟢' if d_val>=TARGET_EXPRESS_DISPATCH else '🔴'} Target: {TARGET_EXPRESS_DISPATCH}%")
    
    ex_val = (s_exp['Delivery_SLA_Met'].mean()*100) if len(s_exp)>0 else 0.0
    sm4.metric("EXPRESS DEL SLA", f"{ex_val:.1f}%", f"{'🟢' if ex_val>=TARGET_EXPRESS_DELIVERY else '🔴'} Target: {TARGET_EXPRESS_DELIVERY}%")

    st_val = (s_std['Delivery_SLA_Met'].mean()*100) if len(s_std)>0 else 0.0
    sm5.metric("STANDARD DEL SLA", f"{st_val:.1f}%", f"{'🟢' if st_val>=TARGET_STANDARD_DELIVERY else '🔴'} Target: {TARGET_STANDARD_DELIVERY}%")

    st.divider()

    # ACTION REQUIRED SECTION
    st.subheader("ACTION REQUIRED: PENDING DELAYED ORDERS REMARKS")
    
    sub_t1, sub_t2, sub_t3, sub_t4 = st.tabs(["📦 Packing Delays", "🚚 Dispatch Delays", "🚴 Delivery Delays", "📁 Saved / Audit History"])

    def render_action_table(stage_name, df_breach):
        if df_breach.empty:
            st.success(f"No pending {stage_name} SLA breaches for this date!")
            return
            
        for idx, row in df_breach.iterrows():
            with st.container():
                c1, c2, c3, c4 = st.columns([2, 2, 3, 1])
                c1.write(f"**Order ID:** {row['Order ID']}")
                c1.write(f"**Date:** {row['Order_Date']}")
                c2.write(f"**Delay:** `+{row['Delay_Mins']:.1f} mins`")
                c2.write(f"**Handler:** {row.get('Rider Name', 'In-House')}")
                
                existing = remarks_df[(remarks_df['Order ID'] == row['Order ID']) & (remarks_df['Stage'] == stage_name)]
                current_reason = existing.iloc[-1]['Delay Reason'] if not existing.empty else ""
                reason_val = c3.text_input("Delay Reason (Store Entry)", value=current_reason, key=f"input_{stage_name}_{row['Order ID']}")
                
                if c4.button("Submit", key=f"sub_{stage_name}_{row['Order ID']}"):
                    st.success("Submitted to Manager Queue!")
            st.divider()

    with sub_t1:
        p_breach = store_df[(store_df['Order Type'] == 'Express') & (store_df['Pick_SLA_Met'] == False)].copy()
        p_breach['Delay_Mins'] = p_breach['Pick_Mins'] - 3.0
        render_action_table("Packing", p_breach)

    with sub_t2:
        d_breach = store_df[(store_df['Order Type'] == 'Express') & (store_df['Dispatch_SLA_Met'] == False)].copy()
        d_breach['Delay_Mins'] = d_breach['Dispatch_Mins'] - 6.0
        render_action_table("Dispatch", d_breach)

    with sub_t3:
        del_breach = store_df[store_df['Delivery_SLA_Met'] == False].copy()
        del_breach['Delay_Mins'] = del_breach['Delivery_Mins'] - del_breach['Zone_Target']
        render_action_table("Delivery", del_breach)

    with sub_t4:
        saved_history = remarks_df[(remarks_df['Store Name'] == active_store) & (remarks_df['Order Date'].astype(str) == str(filter_dt))]
        if not saved_history.empty:
            st.dataframe(saved_history, hide_index=True, use_container_width=True)
        else:
            st.info("No saved remarks found for this date.")

    st.divider()

    # RIDER PRODUCTIVITY SECTION
    st.subheader("🏍️ Rider Productivity & Performance (Today)")
    store_self = store_df[store_df['Is_Self']]
    
    if not store_self.empty:
        rider_summary = []
        for rider_name, r_group in store_self.groupby('Rider Name'):
            r_orders = len(r_group)
            r_ontime = (r_group['Delivery_SLA_Met'].mean() * 100) if r_orders > 0 else 0.0
            r_avg_time = r_group['Delivery_Mins'].mean() if r_orders > 0 else 0.0
            cpo_val = DAILY_RIDER_COST / r_orders if r_orders > 0 else 0.0
            
            rider_summary.append({
                "Rider Name": rider_name,
                "Active Status": "ACTIVE",
                "Self Orders": f"{r_orders} Orders",
                "On-Time Del %": f"{r_ontime:.1f}%",
                "Avg Delivery Time": f"{r_avg_time:.1f} mins",
                "CPO (Cost/Order)": f"₹{cpo_val:.2f}"
            })
        st.dataframe(pd.DataFrame(rider_summary), use_container_width=True, hide_index=True)
    else:
        st.info("No self rider data recorded for this date.")

# ==========================================
# PAGE 3: MANAGER AUDIT VIEW
# ==========================================
elif nav_choice == "🛡️ Manager Audit & Review" and user_role == "Manager":
    st.title("🛡️ Manager Audit & Review View")
    st.caption("Review, approve, or reject store-submitted delay remarks")

    pending_remarks = remarks_df[remarks_df['Status'] == 'PENDING'].copy() if 'Status' in remarks_df.columns else pd.DataFrame()

    st.subheader("📋 PENDING REMARKS FOR APPROVAL")
    if pending_remarks.empty:
        st.success("All submitted delay remarks have been audited! No pending reviews.")
    else:
        st.dataframe(pending_remarks, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("📁 HISTORICAL APPROVED DELAY LOGS")
    approved_remarks = remarks_df[remarks_df['Status'] == 'APPROVED'].copy() if 'Status' in remarks_df.columns else pd.DataFrame()
    if not approved_remarks.empty:
        st.dataframe(approved_remarks, use_container_width=True, hide_index=True)
    else:
        st.info("No approved remarks found.")
