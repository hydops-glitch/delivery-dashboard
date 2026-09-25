import streamlit as st
import pandas as pd
import numpy as np

# Set Streamlit page layout
st.set_page_config(page_title="Store Operations Dashboard", layout="wide")

# ==========================================
# 1. HELPER FUNCTIONS & METRIC CALCULATIONS
# ==========================================

def parse_zone_minutes(zone_str):
    """Extracts target SLA minutes directly from Zone/Zone F string."""
    if pd.isna(zone_str):
        return 45.0  # Default SLA fallback
    z = str(zone_str).lower().strip()
    if '30' in z:
        return 30.0
    elif '40' in z:
        return 40.0
    elif '60' in z:
        return 60.0
    elif '90' in z:
        return 90.0
    elif '2.5' in z or '150' in z:
        return 150.0
    return 45.0


def process_order_data(df):
    """Cleans data and computes exact SLA metrics and delivery splits."""
    # Filter out cancelled / failed orders
    df_clean = df[~df['Order Status'].isin(['PAYMENT FAILED', 'CANCELLED'])].copy()

    # Parse key datetime columns
    dt_cols = ['Order date time', 'Placed Time', 'InPicking Time', 'Packed Time', 'Dispatched Time', 'Completed Time']
    for col in dt_cols:
        if col in df_clean.columns:
            df_clean[col] = pd.to_datetime(df_clean[col], errors='coerce')

    # Placed Date for filtering
    df_clean['Order_Date'] = df_clean['Placed Time'].dt.date

    # Normalize Delivery Partner & classify Self vs 3PL
    df_clean['Delivery_Partner_Norm'] = df_clean['Delivery Partner'].fillna('').astype(str).str.strip().str.upper()
    df_clean['Is_Self_Delivered'] = df_clean['Delivery_Partner_Norm'] == 'SELF'

    # Compute Time Durations (in Minutes)
    # Pick Duration: Placed Time to Packed Time
    df_clean['Pick_Duration_Mins'] = (df_clean['Packed Time'] - df_clean['Placed Time']).dt.total_seconds() / 60.0
    df_clean['Pick_SLA_Met'] = df_clean['Pick_Duration_Mins'] <= 3.0

    # Dispatch Duration: Packed Time to Dispatched Time
    df_clean['Dispatch_Duration_Mins'] = (df_clean['Dispatched Time'] - df_clean['Packed Time']).dt.total_seconds() / 60.0
    df_clean['Dispatch_SLA_Met'] = df_clean['Dispatch_Duration_Mins'] <= 6.0

    # Zone Target & Total Delivery Duration: Placed Time to Completed Time
    df_clean['Zone_SLA_Target'] = df_clean['Zone'].apply(parse_zone_minutes)
    df_clean['Delivery_Duration_Mins'] = (df_clean['Completed Time'] - df_clean['Placed Time']).dt.total_seconds() / 60.0
    df_clean['Delivery_SLA_Met'] = df_clean['Delivery_Duration_Mins'] <= df_clean['Zone_SLA_Target']

    return df_clean


# ==========================================
# 2. FILE UPLOAD & SIDEBAR CONTROLS
# ==========================================

st.sidebar.header("User & Store Profile")
uploaded_file = st.sidebar.file_uploader("Upload Order Reports (.xlsx / .csv)", type=['xlsx', 'csv'])

if uploaded_file is not None:
    try:
        if uploaded_file.name.endswith('.csv'):
            raw_df = pd.read_csv(uploaded_file)
        else:
            raw_df = pd.read_excel(uploaded_file)

        df = process_order_data(raw_df)
        st.sidebar.success("Report successfully parsed!")

        # Filters
        available_stores = sorted(df['Store Name'].dropna().unique().tolist())
        selected_store = st.sidebar.selectbox("Active Store Scope", ["All Stores"] + available_stores)

        available_dates = sorted(df['Order_Date'].dropna().unique())
        selected_date = st.sidebar.date_input("Select Date", value=available_dates[-1] if available_dates else None)

        # Apply Filters
        filtered_df = df.copy()
        if selected_store != "All Stores":
            filtered_df = filtered_df[filtered_df['Store Name'] == selected_store]
        if selected_date:
            filtered_df = filtered_df[filtered_df['Order_Date'] == selected_date]

        # Order Type Split
        express_orders = filtered_df[filtered_df['Order Type'] == 'Express']
        standard_orders = filtered_df[filtered_df['Order Type'] == 'Standard']

        # ==========================================
        # 3. METRIC CARDS HEADER
        # ==========================================
        st.title("Store Performance Dashboard")

        m1, m2, m3, m4, m5 = st.columns(5)

        total_placed = len(filtered_df)
        total_delivered = len(filtered_df[filtered_df['Order Status'] == 'DELIVERED'])
        m1.metric("Total Orders", f"{total_placed}", f"Delivered: {total_delivered}")

        # Pick SLA
        pick_pct = (express_orders['Pick_SLA_Met'].mean() * 100) if len(express_orders) > 0 else 0.0
        m2.metric("Express Pick SLA", f"{pick_pct:.1f}%", f"{express_orders['Pick_SLA_Met'].sum()}/{len(express_orders)} Met (<=3m)")

        # Dispatch SLA
        dispatch_pct = (express_orders['Dispatch_SLA_Met'].mean() * 100) if len(express_orders) > 0 else 0.0
        m3.metric("Express Dispatch SLA", f"{dispatch_pct:.1f}%", f"{express_orders['Dispatch_SLA_Met'].sum()}/{len(express_orders)} Met (<=6m)")

        # Express Delivery SLA
        exp_del_pct = (express_orders['Delivery_SLA_Met'].mean() * 100) if len(express_orders) > 0 else 0.0
        m4.metric("Express Delivery SLA", f"{exp_del_pct:.1f}%", f"{len(express_orders)} Express orders")

        # Standard Delivery SLA
        std_del_pct = (standard_orders['Delivery_SLA_Met'].mean() * 100) if len(standard_orders) > 0 else 0.0
        m5.metric("Standard Delivery SLA", f"{std_del_pct:.1f}%", f"{len(standard_orders)} Standard orders")

        st.divider()

        # Volume Split Cards
        c1, c2 = st.columns(2)

        self_count = filtered_df['Is_Self_Delivered'].sum()
        tpl_count = len(filtered_df) - self_count
        active_riders = filtered_df['Rider Name'].dropna().nunique()

        c1.subheader("Riders & Self Delivery")
        c1.write(f"**Self Riders Delivered:** {self_count} | **Active Riders:** {active_riders}")

        c2.subheader("Orders Volume Split")
        c2.write(f"**{len(express_orders)}** Exp | **{len(standard_orders)}** Standard")
        c2.write(f"Self Delivered: **{self_count}** | 3PL Delivered: **{tpl_count}**")

        st.divider()

        # ==========================================
        # 4. STORE LEVEL BREAKDOWN TABLE
        # ==========================================
        st.subheader("📊 Store Level Performance Breakdown")

        summary_table = filtered_df.groupby(['Order_Date', 'Store Name']).apply(lambda g: pd.Series({
            'Express_Packed_SLA': f"{(g[g['Order Type']=='Express']['Pick_SLA_Met'].mean()*100):.1f}%" if len(g[g['Order Type']=='Express']) > 0 else "N/A",
            'Express_Dispatch_SLA': f"{(g[g['Order Type']=='Express']['Dispatch_SLA_Met'].mean()*100):.1f}%" if len(g[g['Order Type']=='Express']) > 0 else "N/A",
            'Express_Delivery_SLA': f"{(g[g['Order Type']=='Express']['Delivery_SLA_Met'].mean()*100):.1f}%" if len(g[g['Order Type']=='Express']) > 0 else "N/A",
            'Standard_Delivery_SLA': f"{(g[g['Order Type']=='Standard']['Delivery_SLA_Met'].mean()*100):.1f}%" if len(g[g['Order Type']=='Standard']) > 0 else "N/A",
            'Express_Orders': (g['Order Type'] == 'Express').sum(),
            'Standard_Orders': (g['Order Type'] == 'Standard').sum(),
            'Total_Delivered': (g['Order Status'] == 'DELIVERED').sum(),
            'Self_Delivered': g['Is_Self_Delivered'].sum(),
            '3PL_Delivered': (~g['Is_Self_Delivered']).sum()
        })).reset_index()

        st.dataframe(summary_table, hide_index=True, use_container_width=True)

        st.divider()

        # ==========================================
        # 5. DELIVERY BREACHES TABLE (FIXED CODE)
        # ==========================================
        st.subheader("⚠️ Delivery Breach Details")

        del_breach = filtered_df[filtered_df['Delivery_SLA_Met'] == False][
            ['Order ID', 'Store Name', 'Order Type', 'Zone', 'Placed Time', 'Completed Time', 'Delivery_Duration_Mins', 'Zone_SLA_Target', 'Delivery Partner']
        ].copy()

        # FIX: Explicit if/else statement eliminates the returned DeltaGenerator object
        if not del_breach.empty:
            st.dataframe(del_breach, hide_index=True, use_container_width=True)
        else:
            st.success("No Delivery Breaches!")

    except Exception as e:
        st.error(f"Error processing file: {e}")
else:
    st.info("Please upload an order transitions file (.xlsx or .csv) from the sidebar to view metrics.")
