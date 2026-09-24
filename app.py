import streamlit as st
import pandas as pd
import datetime
from data_processor import process_and_merge_reports

st.set_page_config(page_title="Fulfilment & Delivery Dashboard", layout="wide")

st.sidebar.header("📁 Step 1: Upload Daily Data")
picklist_files = st.sidebar.file_uploader(
    "Upload Store Picklist Reports (.xls/.csv)", 
    accept_multiple_files=True
)
transaction_file = st.sidebar.file_uploader(
    "Upload Order Transactions Report (.xlsx/.csv)"
)

if picklist_files and transaction_file:
    master_df = process_and_merge_reports(picklist_files, transaction_file)
    st.sidebar.success("All raw files cleaned & merged successfully!")
    
    # --- TOP ROW CONTROLS ---
    col_store, col_filter_type, col_picker = st.columns([2, 2, 3])
    
    stores = ['All Stores (HYD Region)'] + sorted(list(master_df['Store_Name'].unique()))
    with col_store:
        selected_store = st.selectbox("🏬 Select Store / Location", stores)
    
    if selected_store != 'All Stores (HYD Region)':
        filtered_df = master_df[master_df['Store_Name'] == selected_store].copy()
        header_title = f"🏬 Store Performance: {selected_store}"
    else:
        filtered_df = master_df.copy()
        header_title = "🌐 HYD Region Performance Overview"
        
    with col_filter_type:
        date_filter_mode = st.radio("📅 Date Filter Mode", ["Reporting Cycle", "Custom Date Range"], horizontal=True)
        
    today_day = datetime.date.today().day
    if today_day <= 7:
        default_cycle_idx = 0
    elif today_day <= 14:
        default_cycle_idx = 1
    elif today_day <= 21:
        default_cycle_idx = 2
    else:
        default_cycle_idx = 3

    with col_picker:
        if date_filter_mode == "Reporting Cycle":
            cycle_period = st.selectbox(
                "Select Cycle",
                ["Cycle 1 (1st - 7th)", "Cycle 2 (8th - 14th)", "Cycle 3 (15th - 21st)", "Cycle 4 (22nd - End)"],
                index=default_cycle_idx
            )
            if cycle_period == "Cycle 1 (1st - 7th)":
                filtered_df = filtered_df[filtered_df['Order_Placing_Time'].dt.day.between(1, 7)]
            elif cycle_period == "Cycle 2 (8th - 14th)":
                filtered_df = filtered_df[filtered_df['Order_Placing_Time'].dt.day.between(8, 14)]
            elif cycle_period == "Cycle 3 (15th - 21st)":
                filtered_df = filtered_df[filtered_df['Order_Placing_Time'].dt.day.between(15, 21)]
            elif cycle_period == "Cycle 4 (22nd - End)":
                filtered_df = filtered_df[filtered_df['Order_Placing_Time'].dt.day >= 22]
        else:
            date_range = st.date_input(
                "Select Date Range",
                value=(datetime.date.today() - datetime.timedelta(days=7), datetime.date.today())
            )
            if isinstance(date_range, tuple) and len(date_range) == 2:
                start_date, end_date = date_range
                filtered_df = filtered_df[
                    (filtered_df['Order_Placing_Time'].dt.date >= start_date) & 
                    (filtered_df['Order_Placing_Time'].dt.date <= end_date)
                ]

    st.title(header_title)
    st.markdown("---")

    # --- KPI HIGHLIGHTS ---
    st.subheader("🎯 KPI Highlights")
    
    exp_df = filtered_df[filtered_df['Order Type'].str.lower() == 'express']
    std_df = filtered_df[filtered_df['Order Type'].str.lower() != 'express']
    
    exp_pick_sla = (exp_df['Pick_SLA_Met'].sum() / len(exp_df) * 100) if len(exp_df) > 0 else 0
    std_pick_sla = (std_df['Pick_SLA_Met'].sum() / len(std_df) * 100) if len(std_df) > 0 else 0
    
    exp_del_sla = (exp_df['On Time Delivered'].sum() / len(exp_df) * 100) if len(exp_df) > 0 else 0
    std_del_sla = (std_df['On Time Delivered'].sum() / len(std_df) * 100) if len(std_df) > 0 else 0
    
    inhouse_count = (filtered_df['Rider_Channel'] == 'In-House Rider').sum()
    tpl_count = (filtered_df['Rider_Channel'] == '3PL Partner').sum()
    total_orders = len(filtered_df)
    
    inhouse_pct = (inhouse_count / total_orders * 100) if total_orders > 0 else 0
    tpl_pct = (tpl_count / total_orders * 100) if total_orders > 0 else 0
    
    kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
    kpi1.metric("Express Pick SLA (≤3m)", f"{exp_pick_sla:.1f}%")
    kpi2.metric("Standard Pick SLA", f"{std_pick_sla:.1f}%")
    kpi3.metric("Express Delivery SLA", f"{exp_del_sla:.1f}%")
    kpi4.metric("Standard Delivery SLA", f"{std_del_sla:.1f}%")
    kpi5.metric("In-House vs 3PL Split", f"{inhouse_pct:.0f}% / {tpl_pct:.0f}%")

    st.markdown("---")

    # --- SEPARATE TABLES FOR PICKING & DELIVERY DELAYS WITH CUSTOM TEXT INPUT ---
    tab_pick, tab_del = st.tabs(["🛒 Picking Delays (> 3 Min)", "🚚 Delivery Delays"])
    
    with tab_pick:
        st.subheader("Picking Breached Orders")
        pick_breached = filtered_df[filtered_df['Pick_SLA_Met'] == 0].copy()
        
        if not pick_breached.empty:
            edited_pick = st.data_editor(
                pick_breached[[
                    'Order_ID', 'Store_Name', 'Order Type', 'Pick Duration', 
                    'Pick Status', 'Picking_Delay_Reason'
                ]],
                column_config={
                    "Picking_Delay_Reason": st.column_config.TextColumn(
                        "Picking Delay Reason (Type custom reason)",
                        help="Double-click to type any custom delay remark"
                    )
                },
                disabled=['Order_ID', 'Store_Name', 'Order Type', 'Pick Duration', 'Pick Status'],
                hide_index=True,
                key="pick_editor"
            )
        else:
            st.success("🎉 Zero picking delays found!")

    with tab_del:
        st.subheader("Delivery Breached Orders")
        del_breached = filtered_df[filtered_df['On Time Delivered'] == 0].copy()
        
        if not del_breached.empty:
            edited_del = st.data_editor(
                del_breached[[
                    'Order_ID', 'Store_Name', 'Order Type', 'Delivery Partner', 
                    'Delivery Status', 'Delivery_Delay_Reason'
                ]],
                column_config={
                    "Delivery_Delay_Reason": st.column_config.TextColumn(
                        "Delivery Delay Reason (Type custom reason)",
                        help="Double-click to type any custom delay remark"
                    )
                },
                disabled=['Order_ID', 'Store_Name', 'Order Type', 'Delivery Partner', 'Delivery Status'],
                hide_index=True,
                key="del_editor"
            )
        else:
            st.success("🎉 Zero delivery delays found!")

else:
    st.title("🚚 Fulfillment & Delivery Performance Dashboard")
    st.info("👈 Please upload your store picklists and transaction report from the sidebar to start.")
