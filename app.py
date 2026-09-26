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

st.markdown("""
<style>
    .main { background-color: #f8fafc; padding: 10px; }
    
    .metric-card {
        background-color: #ffffff;
        border: 1.5px solid #cbd5e1;
        border-radius: 10px;
        padding: 16px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.04);
        margin-bottom: 15px;
    }
    
    .metric-title {
        font-size: 11px;
        font-weight: 700;
        color: #475569;
        text-transform: uppercase;
        letter-spacing: 0.6px;
        margin-bottom: 6px;
    }
    
    .metric-value {
        font-size: 26px;
        font-weight: 800;
        color: #0f172a;
        line-height: 1.1;
    }
    
    .metric-target-green { font-size: 12px; font-weight: 600; color: #16a34a; margin-top: 6px; }
    .metric-target-red { font-size: 12px; font-weight: 600; color: #dc2626; margin-top: 6px; }
    .metric-target-neutral { font-size: 12px; font-weight: 600; color: #0284c7; margin-top: 6px; }

    .user-header-badge {
        font-size: 13px;
        font-weight: 600;
        color: #1e293b;
        background: #e2e8f0;
        padding: 5px 14px;
        border-radius: 20px;
        border: 1px solid #cbd5e1;
        display: inline-block;
    }
</style>
""", unsafe_allow_html=True)

DAILY_RIDER_COST = 1050.0
SHEET_ID = "1RUxzJbHW7HHUxbT2sJzNvBrNatLsvgBss6W86CdgMzo"

# Target SLA Definitions
TARGET_EXPRESS_PACK = 99.0
TARGET_EXPRESS_DISPATCH = 95.0
TARGET_EXPRESS_DELIVERY = 95.0
TARGET_STANDARD_DELIVERY = 99.0

APPROVED_DOMAINS = ["@prasuma.com", "@meatigo.com"]

# Default Access Passwords
MANAGER_PASSWORD = "Manager@Meatigo2026"
STORE_PASSWORD = "Meatigo@2026"

# ==========================================
# 2. STATE & REMARKS DATA PERSISTENCE
# ==========================================
if "user_email" not in st.session_state:
    st.session_state["user_email"] = None

if "remarks_data" not in st.session_state:
    st.session_state["remarks_data"] = pd.DataFrame(columns=[
        'Timestamp', 'Order ID', 'Order Date', 'Store Name', 
        'Stage', 'Delay Duration (Mins)', 'Delay Reason', 
        'Status', 'Manager Feedback', 'Submitted By'
    ])

# Login Interface
if not st.session_state["user_email"]:
    st.title("🥩 Meatigo Operations Portal")
    st.subheader("Authorized Personnel Login")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        with st.form("password_login_form"):
            email_input = st.text_input("Company Email", placeholder="hyd_ops@prasuma.com")
            password_input = st.text_input("Access Password", type="password")
            submit_login = st.form_submit_button("Login to Portal", type="primary", use_container_width=True)
            
            if submit_login:
                clean_email = email_input.strip().lower()
                
                if not any(clean_email.endswith(dom) for dom in APPROVED_DOMAINS):
                    st.error("Access Denied: Email domain must be @prasuma.com or @meatigo.com")
                elif any(k in clean_email for k in ["hyd_ops", "sreekanth", "manager"]):
                    if password_input == MANAGER_PASSWORD:
                        st.session_state["user_email"] = clean_email
                        st.success("Manager Login Successful!")
                        st.rerun()
                    else:
                        st.error("Incorrect Manager Password.")
                else:
                    if password_input in [STORE_PASSWORD, MANAGER_PASSWORD]:
                        st.session_state["user_email"] = clean_email
                        st.success("Store Login Successful!")
                        st.rerun()
                    else:
                        st.error("Incorrect Password.")

    st.stop()

user_email = st.session_state["user_email"].strip().lower()

# ==========================================
# 3. DATA ENGINE & DYNAMIC STORE MAPPING
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
    
    df = raw_df[~raw_df['Order Status'].astype(str).str.upper().isin(['PAYMENT FAILED', 'CANCELLED'])].copy()
    if 'Was Cancelled' in df.columns:
        df = df[df['Was Cancelled'].astype(str).str.upper() != 'TRUE']

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
    
    has_inpick = df['InPicking Time'].notna() & (df['InPicking Time'] <= df['Packed Time'])
    df['Pick_Start'] = np.where(has_inpick, df['InPicking Time'], df['Placed Time'])
    df['Pick_Mins'] = (df['Packed Time'] - df['Pick_Start']).dt.total_seconds() / 60.0
    df['Pick_SLA_Met'] = df['Pick_Mins'] <= 3.0
    
    df['Dispatch_Mins'] = (df['Dispatched Time'] - df['Packed Time']).dt.total_seconds() / 60.0
    df['Dispatch_SLA_Met'] = df['Dispatch_Mins'] <= 6.0
    
    df['Zone_Target'] = df['Zone'].apply(parse_zone_minutes)
    df['Delivery_Mins'] = (df['Completed Time'] - df['Placed Time']).dt.total_seconds() / 60.0
    df['Delivery_SLA_Met'] = df['Delivery_Mins'] <= df['Zone_Target']

    try:
        fetched_remarks = pd.read_csv(delay_remarks_url)
    except Exception:
        fetched_remarks = pd.DataFrame(columns=['Timestamp', 'Order ID', 'Order Date', 'Store Name', 'Stage', 'Delay Duration (Mins)', 'Delay Reason', 'Status', 'Manager Feedback', 'Submitted By'])
        
    try:
        mapping_df = pd.read_csv(store_mapping_url)
    except Exception:
        mapping_df = pd.DataFrame({'Store Email': [user_email], 'Store Name': ['ALL'], 'Role': ['Manager']})

    return df, fetched_remarks, mapping_df

try:
    orders_df, fetched_remarks, mapping_df = load_all_data()
    if st.session_state["remarks_data"].empty and not fetched_remarks.empty:
        st.session_state["remarks_data"] = fetched_remarks
except Exception as e:
    st.error(f"Data loading error: {e}")
    st.stop()

remarks_df = st.session_state["remarks_data"]

# Mapping user scope
user_mapping = mapping_df[mapping_df['Store Email'].astype(str).str.lower() == user_email]

if not user_mapping.empty:
    user_role = str(user_mapping.iloc[0]['Role']).strip().title()
    assigned_store = str(user_mapping.iloc[0]['Store Name']).strip()
else:
    if any(k in user_email for k in ["hyd_ops", "sreekanth", "manager"]):
        user_role = "Manager"
        assigned_store = "ALL"
    else:
        user_role = "Store"
        available_stores = list(orders_df['Store Name'].dropna().unique())
        email_prefix = user_email.split('@')[0].replace('hyd_', '').replace('_ops', '').replace('store_', '').replace('_', '').lower()
        
        matched_store = None
        for store in available_stores:
            clean_store = store.lower().replace('_', '')
            if email_prefix in clean_store or clean_store in email_prefix:
                matched_store = store
                break
        
        assigned_store = matched_store if matched_store else (available_stores[0] if available_stores else "TGN_HYD_BHills")

raw_name = user_email.split('@')[0].replace('.', ' ').replace('_', ' ').title()
display_name = "Sreekanth" if any(k in raw_name.lower() for k in ["sreekanth", "hyd ops"]) else raw_name

# Helper Functions for Remark Submissions & Approvals
def submit_store_remark(order_id, order_date, store_name, stage, delay_mins, reason):
    df = st.session_state["remarks_data"]
    # Check if entry already exists
    idx = df[(df['Order ID'].astype(str) == str(order_id)) & (df['Stage'] == stage)].index
    
    new_entry = {
        'Timestamp': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'Order ID': str(order_id),
        'Order Date': str(order_date),
        'Store Name': store_name,
        'Stage': stage,
        'Delay Duration (Mins)': round(delay_mins, 1),
        'Delay Reason': reason,
        'Status': 'PENDING',
        'Manager Feedback': '',
        'Submitted By': user_email
    }

    if not idx.empty:
        for k, v in new_entry.items():
            df.loc[idx, k] = v
    else:
        df = pd.concat([df, pd.DataFrame([new_entry])], ignore_index=True)
        
    st.session_state["remarks_data"] = df

def update_manager_action(order_id, stage, new_status, feedback=""):
    df = st.session_state["remarks_data"]
    idx = df[(df['Order ID'].astype(str) == str(order_id)) & (df['Stage'] == stage)].index
    if not idx.empty:
        df.loc[idx, 'Status'] = new_status
        df.loc[idx, 'Manager Feedback'] = feedback
    st.session_state["remarks_data"] = df

# ==========================================
# 4. SIDEBAR NAVIGATION
# ==========================================
with st.sidebar:
    st.title("🥩 Meatigo Portal")
    
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
    if st.button("🚪 Logout"):
        st.session_state.clear()
        st.rerun()

# ==========================================
# 5. HEADER BAR & DATE SELECTION
# ==========================================
top_c1, top_c2 = st.columns([2, 3])

with top_c1:
    greeting = "Good Morning" if datetime.datetime.now().hour < 12 else ("Good Afternoon" if datetime.datetime.now().hour < 17 else "Good Evening")
    st.title(f"{greeting}, {display_name}!")

available_dates = sorted([d for d in orders_df['Order_Date'].dropna().unique()], reverse=True)
latest_date = available_dates[0] if len(available_dates) > 0 else datetime.date.today()
yesterday_date = available_dates[1] if len(available_dates) > 1 else latest_date

latest_formatted = latest_date.strftime("%A %d %b %Y")
yesterday_formatted = yesterday_date.strftime("%A %d %b %Y")

with top_c2:
    st.markdown(f"<div style='text-align: right;'><span class='user-header-badge'>👤 {user_email} ({user_role})</span></div>", unsafe_allow_html=True)
    st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
    
    d_col1, d_col2, d_col3 = st.columns([2, 3, 1])
    
    with d_col1:
        date_preset = st.selectbox(
            "Select Date Preset", 
            [latest_formatted, yesterday_formatted, "Custom Date Range"], 
            index=0, 
            key="global_date_preset"
        )
    
    if date_preset == latest_formatted:
        start_date, end_date = latest_date, latest_date
    elif date_preset == yesterday_formatted:
        start_date, end_date = yesterday_date, yesterday_date
    else:
        with d_col2:
            date_range_input = st.date_input(
                "Select Range (From - To)",
                value=(yesterday_date, latest_date),
                key="custom_date_range_picker"
            )
            if isinstance(date_range_input, tuple) and len(date_range_input) == 2:
                start_date, end_date = date_range_input
            elif isinstance(date_range_input, tuple) and len(date_range_input) == 1:
                start_date, end_date = date_range_input[0], date_range_input[0]
            else:
                start_date, end_date = latest_date, latest_date

    with d_col3:
        st.markdown("<div style='height: 25px;'></div>", unsafe_allow_html=True)
        st.button("🔄 Refresh", on_click=st.cache_data.clear)

st.divider()

def render_metric_card(col, title, value, target_text, status_type="green"):
    if status_type == "green":
        target_class = "metric-target-green"
    elif status_type == "red":
        target_class = "metric-target-red"
    else:
        target_class = "metric-target-neutral"

    col.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">{title}</div>
        <div class="metric-value">{value}</div>
        <div class="{target_class}">{target_text}</div>
    </div>
    """, unsafe_allow_html=True)

# Filter by Date
orders_range_df = orders_df[(orders_df['Order_Date'] >= start_date) & (orders_df['Order_Date'] <= end_date)].copy()

# ==========================================
# PAGE 1: HYD REGION / STORE METRICS VIEW
# ==========================================
if nav_choice in ["📊 Hyd Region Metrics View", "📊 Store Metrics View"]:
    if user_role == "Manager" or assigned_store == "ALL":
        t1_df = orders_range_df.copy()
    else:
        t1_df = orders_range_df[
            orders_range_df['Store Name'].astype(str).str.strip().str.lower() == assigned_store.strip().lower()
        ].copy()

    exp_t1 = t1_df[t1_df['Order Type'] == 'Express']
    std_t1 = t1_df[t1_df['Order Type'] == 'Standard']

    exp_count = len(exp_t1)
    std_count = len(std_t1)

    exp_pack_sla = (exp_t1['Pick_SLA_Met'].mean() * 100) if exp_count > 0 else 0.0
    exp_disp_sla = (exp_t1['Dispatch_SLA_Met'].mean() * 100) if exp_count > 0 else 0.0
    exp_del_sla = (exp_t1['Delivery_SLA_Met'].mean() * 100) if exp_count > 0 else 0.0
    std_del_sla = (std_t1['Delivery_SLA_Met'].mean() * 100) if std_count > 0 else 0.0

    self_orders_df = t1_df[t1_df['Is_Self']]
    tpl_orders_count = len(t1_df) - len(self_orders_df)
    unique_riders = self_orders_df['Rider Name'].dropna().unique() if 'Rider Name' in self_orders_df.columns else []
    active_rider_count = len(unique_riders)
    avg_orders_per_rider = (len(self_orders_df) / active_rider_count) if active_rider_count > 0 else 0.0

    r1c1, r1c2, r1c3, r1c4 = st.columns(4)
    render_metric_card(r1c1, "TOTAL ORDERS PLACED", f"{len(t1_df)}", f"⚡ Express: {exp_count} | Standard: {std_count}", "neutral")
    render_metric_card(r1c2, "DELIVERED ORDERS", f"{len(t1_df[t1_df['Order Status'] == 'DELIVERED'])}", "Completed Deliveries", "green")
    render_metric_card(r1c3, "⚡ EXPRESS PACKING SLA (≤3M)", f"{exp_pack_sla:.1f}%", f"{'🟢' if exp_pack_sla>=TARGET_EXPRESS_PACK else '🔴'} Target: {TARGET_EXPRESS_PACK}%", "green" if exp_pack_sla>=TARGET_EXPRESS_PACK else "red")
    render_metric_card(r1c4, "⚡ EXPRESS DISPATCH SLA (≤6M)", f"{exp_disp_sla:.1f}%", f"{'🟢' if exp_disp_sla>=TARGET_EXPRESS_DISPATCH else '🔴'} Target: {TARGET_EXPRESS_DISPATCH}%", "green" if exp_disp_sla>=TARGET_EXPRESS_DISPATCH else "red")

    r2c1, r2c2, r2c3 = st.columns(3)
    render_metric_card(r2c1, "⚡ EXPRESS DELIVERED SLA", f"{exp_del_sla:.1f}%", f"{'🟢' if exp_del_sla>=TARGET_EXPRESS_DELIVERY else '🔴'} Target: {TARGET_EXPRESS_DELIVERY}%", "green" if exp_del_sla>=TARGET_EXPRESS_DELIVERY else "red")
    render_metric_card(r2c2, "STANDARD DELIVERED SLA", f"{std_del_sla:.1f}%", f"{'🟢' if std_del_sla>=TARGET_STANDARD_DELIVERY else '🔴'} Target: {TARGET_STANDARD_DELIVERY}%", "green" if std_del_sla>=TARGET_STANDARD_DELIVERY else "red")
    render_metric_card(r2c3, "🏍️ RIDER PRODUCTIVITY & FLEET", f"{len(self_orders_df)} Self | {tpl_orders_count} 3PL", f"Active Riders: {active_rider_count} | Avg Delivered: {avg_orders_per_rider:.1f}/Rider", "neutral")

    st.divider()

    ch1, ch2 = st.columns(2)
    min_trend_dt = end_date - datetime.timedelta(days=6)
    trend_df = orders_df[(orders_df['Order_Date'] >= min_trend_dt) & (orders_df['Order_Date'] <= end_date)].copy()

    if not trend_df.empty:
        daily_trend = trend_df.groupby('Order_Date').apply(lambda g: pd.Series({
            'Pick_SLA': (g[g['Order Type']=='Express']['Pick_SLA_Met'].mean() * 100) if len(g[g['Order Type']=='Express']) > 0 else 0.0,
            'Dispatch_SLA': (g[g['Order Type']=='Express']['Dispatch_SLA_Met'].mean() * 100) if len(g[g['Order Type']=='Express']) > 0 else 0.0,
            'Exp_Del_SLA': (g[g['Order Type']=='Express']['Delivery_SLA_Met'].mean() * 100) if len(g[g['Order Type']=='Express']) > 0 else 0.0,
            'Std_Del_SLA': (g[g['Order Type']=='Standard']['Delivery_SLA_Met'].mean() * 100) if len(g[g['Order Type']=='Standard']) > 0 else 0.0
        })).reset_index()
    else:
        daily_trend = pd.DataFrame(columns=['Order_Date', 'Pick_SLA', 'Dispatch_SLA', 'Exp_Del_SLA', 'Std_Del_SLA'])

    with ch1:
        st.subheader("Packing & Dispatch Trend (7-Day Rolling)")
        fig1 = go.Figure()
        fig1.add_trace(go.Scatter(x=daily_trend['Order_Date'], y=daily_trend['Pick_SLA'], name="🟢 Packing SLA % (<=3m)", line=dict(color="green", width=3)))
        fig1.add_trace(go.Scatter(x=daily_trend['Order_Date'], y=daily_trend['Dispatch_SLA'], name="🔴 Dispatch SLA % (<=6m)", line=dict(color="red", width=3)))
        fig1.update_layout(yaxis_range=[0, 100], margin=dict(l=20, r=20, t=20, b=20), legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig1, use_container_width=True)

    with ch2:
        st.subheader("Delivery SLA Trend (7-Day Rolling)")
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=daily_trend['Order_Date'], y=daily_trend['Exp_Del_SLA'], name="⚡ Express Delivery SLA %", line=dict(color="blue", width=3)))
        fig2.add_trace(go.Scatter(x=daily_trend['Order_Date'], y=daily_trend['Std_Del_SLA'], name="Standard Delivery SLA %", line=dict(color="orange", width=3)))
        fig2.update_layout(yaxis_range=[0, 100], margin=dict(l=20, r=20, t=20, b=20), legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig2, use_container_width=True)

    st.divider()

    st.subheader(f"Store Wise Performance Summary ({start_date} to {end_date})")
    if not t1_df.empty:
        summary_rows = []
        for sname, grp in t1_df.groupby('Store Name'):
            eg = grp[grp['Order Type'] == 'Express']
            sg = grp[grp['Order Type'] == 'Standard']
            
            p_s = (eg['Pick_SLA_Met'].mean() * 100) if len(eg) > 0 else 0.0
            d_s = (eg['Dispatch_SLA_Met'].mean() * 100) if len(eg) > 0 else 0.0
            ex_d = (eg['Delivery_SLA_Met'].mean() * 100) if len(eg) > 0 else 0.0
            st_d = (sg['Delivery_SLA_Met'].mean() * 100) if len(sg) > 0 else 0.0
            
            summary_rows.append({
                "Store Name": sname,
                "Total Orders": len(grp),
                "Express Orders": len(eg),
                "Standard Orders": len(sg),
                "Pack SLA": f"{p_s:.1f}%",
                "Disp SLA": f"{d_s:.1f}%",
                "Exp Del SLA": f"{ex_d:.1f}%",
                "Std Del SLA": f"{st_d:.1f}%",
                "Self Orders": len(grp[grp['Is_Self']]),
                "3PL Orders": len(grp[~grp['Is_Self']])
            })
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No orders found for the selected date range.")

# ==========================================
# PAGE 2: STORE LEVEL VIEW
# ==========================================
elif nav_choice == "🏪 Store Level View":
    if user_role == "Manager":
        active_store = st.selectbox("Select Store Scope", sorted(orders_df['Store Name'].dropna().unique()))
    else:
        active_store = assigned_store
        st.info(f"Store Scope: **{active_store}**")

    store_df = orders_range_df[
        orders_range_df['Store Name'].astype(str).str.strip().str.lower() == active_store.strip().lower()
    ].copy()
    
    s_exp = store_df[store_df['Order Type'] == 'Express']
    s_std = store_df[store_df['Order Type'] == 'Standard']

    exp_cnt_store = len(s_exp)
    std_cnt_store = len(s_std)

    sm1, sm2, sm3, sm4, sm5 = st.columns(5)
    render_metric_card(sm1, "TOTAL STORE ORDERS", f"{len(store_df)}", f"⚡ Express: {exp_cnt_store} | Standard: {std_cnt_store}", "neutral")
    
    p_val = (s_exp['Pick_SLA_Met'].mean()*100) if exp_cnt_store > 0 else 0.0
    render_metric_card(sm2, "PACK SLA", f"{p_val:.1f}%", f"{'🟢' if p_val>=TARGET_EXPRESS_PACK else '🔴'} Target: {TARGET_EXPRESS_PACK}%", "green" if p_val>=TARGET_EXPRESS_PACK else "red")

    d_val = (s_exp['Dispatch_SLA_Met'].mean()*100) if exp_cnt_store > 0 else 0.0
    render_metric_card(sm3, "DISPATCH SLA", f"{d_val:.1f}%", f"{'🟢' if d_val>=TARGET_EXPRESS_DISPATCH else '🔴'} Target: {TARGET_EXPRESS_DISPATCH}%", "green" if d_val>=TARGET_EXPRESS_DISPATCH else "red")

    ex_val = (s_exp['Delivery_SLA_Met'].mean()*100) if exp_cnt_store > 0 else 0.0
    render_metric_card(sm4, "EXPRESS DEL SLA", f"{ex_val:.1f}%", f"{'🟢' if ex_val>=TARGET_EXPRESS_DELIVERY else '🔴'} Target: {TARGET_EXPRESS_DELIVERY}%", "green" if ex_val>=TARGET_EXPRESS_DELIVERY else "red")

    st_val = (s_std['Delivery_SLA_Met'].mean()*100) if std_cnt_store > 0 else 0.0
    render_metric_card(sm5, "STANDARD DEL SLA", f"{st_val:.1f}%", f"{'🟢' if st_val>=TARGET_STANDARD_DELIVERY else '🔴'} Target: {TARGET_STANDARD_DELIVERY}%", "green" if st_val>=TARGET_STANDARD_DELIVERY else "red")

    st.divider()

    st.subheader(f"ACTION REQUIRED: PENDING DELAYED ORDERS ({start_date} to {end_date})")
    
    dt1, dt2, dt3, dt4 = st.tabs(["📦 Packing Delays", "🚚 Dispatch Delays", "🚴 Delivery Delays", "📁 Audit History"])

    def render_delay_entry(stage, breach_df):
        rem_df = st.session_state["remarks_data"]
        
        # Hide orders that are already submitted and marked as PENDING or APPROVED
        # Show only orders with no record or with REJECTED status from manager
        active_entries = []
        for idx, row in breach_df.iterrows():
            oid = str(row['Order ID'])
            existing = rem_df[(rem_df['Order ID'].astype(str) == oid) & (rem_df['Stage'] == stage)]
            
            if existing.empty:
                active_entries.append((row, "", "", None))
            else:
                last_rec = existing.iloc[-1]
                status = str(last_rec['Status']).upper()
                if status == 'REJECTED':
                    active_entries.append((row, last_rec['Delay Reason'], last_rec.get('Manager Feedback', ''), 'REJECTED'))
                # PENDING & APPROVED are hidden from the store action queue

        if not active_entries:
            st.success(f"No pending {stage} SLA breaches requiring action!")
            return

        for row, prev_reason, manager_fb, status_flag in active_entries:
            oid = str(row['Order ID'])
            with st.container():
                c1, c2, c3, c4 = st.columns([2, 2, 3, 1])
                
                c1.write(f"**Order ID:** {oid}")
                c1.write(f"**Date:** {row['Order_Date']}")
                c2.write(f"**Delayed Time:** `+{row['Delay_Mins']:.1f} mins`")
                c2.write(f"**Handler:** {row.get('Rider Name', 'In-House Pack')}")
                
                if status_flag == 'REJECTED':
                    c3.warning(f"⚠️ Rejected by Manager: {manager_fb}")
                
                reason_input = c3.text_input("Delay Reason (Store Entry)", value=prev_reason, key=f"inp_{stage}_{oid}")
                
                if c4.button("Submit", key=f"btn_{stage}_{oid}"):
                    if not reason_input.strip():
                        st.error("Please enter a valid reason.")
                    else:
                        submit_store_remark(
                            order_id=oid,
                            order_date=row['Order_Date'],
                            store_name=active_store,
                            stage=stage,
                            delay_mins=row['Delay_Mins'],
                            reason=reason_input
                        )
                        st.success("Submitted to Manager Queue!")
                        st.rerun()
            st.divider()

    with dt1:
        p_b = store_df[(store_df['Order Type'] == 'Express') & (store_df['Pick_SLA_Met'] == False)].copy()
        p_b['Delay_Mins'] = p_b['Pick_Mins'] - 3.0
        render_delay_entry("Packing", p_b)

    with dt2:
        d_b = store_df[(store_df['Order Type'] == 'Express') & (store_df['Dispatch_SLA_Met'] == False)].copy()
        d_b['Delay_Mins'] = d_b['Dispatch_Mins'] - 6.0
        render_delay_entry("Dispatch", d_b)

    with dt3:
        del_b = store_df[store_df['Delivery_SLA_Met'] == False].copy()
        del_b['Delay_Mins'] = del_b['Delivery_Mins'] - del_b['Zone_Target']
        render_delay_entry("Delivery", del_b)

    with dt4:
        hist = st.session_state["remarks_data"]
        hist_filtered = hist[(hist['Store Name'] == active_store)]
        if not hist_filtered.empty:
            st.dataframe(hist_filtered, hide_index=True, use_container_width=True)
        else:
            st.info("No saved remarks found for this store.")

    st.divider()

    st.subheader(f"🏍️ Rider Productivity & Performance ({start_date} to {end_date})")
    store_self = store_df[store_df['Is_Self']]
    if not store_self.empty:
        r_list = []
        for rname, rgrp in store_self.groupby('Rider Name'):
            rcnt = len(rgrp)
            ontime = (rgrp['Delivery_SLA_Met'].mean() * 100) if rcnt > 0 else 0.0
            avg_t = rgrp['Delivery_Mins'].mean() if rcnt > 0 else 0.0
            cpo = DAILY_RIDER_COST / rcnt if rcnt > 0 else 0.0
            
            r_list.append({
                "Rider Name": rname,
                "Active Status": "ACTIVE",
                "Self Orders": f"{rcnt} Orders",
                "On-Time Del %": f"{ontime:.1f}%",
                "Avg Delivery Time": f"{avg_t:.1f} mins",
                "CPO (Cost/Order)": f"₹{cpo:.2f}"
            })
        st.dataframe(pd.DataFrame(r_list), use_container_width=True, hide_index=True)
    else:
        st.info("No self-rider order logs found for this date range.")

# ==========================================
# PAGE 3: MANAGER AUDIT VIEW
# ==========================================
elif nav_choice == "🛡️ Manager Audit & Review" and user_role == "Manager":
    st.title("🛡️ Manager Audit & Review View")
    st.caption(f"Review submitted store delay remarks")
    
    rem_df = st.session_state["remarks_data"]
    pending_items = rem_df[rem_df['Status'] == 'PENDING']
    
    st.subheader("📋 PENDING REMARKS FOR APPROVAL")
    
    if pending_items.empty:
        st.success("All submitted store delay remarks have been reviewed!")
    else:
        for idx, row in pending_items.iterrows():
            oid = str(row['Order ID'])
            stage = row['Stage']
            
            with st.container():
                c1, c2, c3, c4 = st.columns([2, 3, 2, 2])
                
                c1.write(f"**Order ID:** {oid}")
                c1.write(f"**Store:** {row['Store Name']}")
                c1.write(f"**Stage:** {stage}")
                
                c2.write(f"**Delay:** `+{row['Delay Duration (Mins)']} mins`")
                c2.write(f"**Store Reason:** {row['Delay Reason']}")
                c2.write(f"**Submitted By:** {row['Submitted By']}")
                
                feedback = c3.text_input("Manager Feedback (Optional if rejecting)", key=f"mfb_{oid}_{stage}")
                
                with c4:
                    col_app, col_rej = st.columns(2)
                    if col_app.button("✅ Approve", key=f"app_{oid}_{stage}", type="primary"):
                        update_manager_action(oid, stage, "APPROVED", feedback)
                        st.success("Approved!")
                        st.rerun()
                    if col_rej.button("❌ Reject", key=f"rej_{oid}_{stage}"):
                        update_manager_action(oid, stage, "REJECTED", feedback)
                        st.warning("Rejected! Sent back to Store Queue.")
                        st.rerun()
            st.divider()

    st.subheader("📁 AUDIT LOG HISTORY")
    reviewed_items = rem_df[rem_df['Status'].isin(['APPROVED', 'REJECTED'])]
    if not reviewed_items.empty:
        st.dataframe(reviewed_items, use_container_width=True, hide_index=True)
    else:
        st.info("No approved or rejected logs yet.")
