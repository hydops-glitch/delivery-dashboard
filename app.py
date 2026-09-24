import streamlit as st
import pandas as pd
import datetime
from data_processor import process_and_merge_reports

st.set_page_config(page_title="Fulfilment & Delivery Dashboard", layout="wide")

st.title("🚚 Fulfillment & Delivery Performance Dashboard")

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

    st.sidebar.header("🔍 Step 2: Filter Dashboard")

    stores = ['All Stores'] + list(master_df['Store_Name'].unique())
    selected_store = st.sidebar.selectbox("Select Store/Center", stores)

    if selected_store != 'All Stores':
        filtered_df = master_df[master_df['Store_Name'] == selected_store]
    else:
        filtered_df = master_df.copy()

    cycle_period = st.sidebar.selectbox(
        "Reporting Cycle",
        ["Full Range", "Cycle 1 (1st - 7th)", "Cycle 2 (8th - 14th)", "Cycle 3 (15th - 21st)", "Cycle 4 (22nd - End)"]
    )

    if cycle_period == "Cycle 1 (1st - 7th)":
        filtered_df = filtered_df[filtered_df['Order_Placing_Time'].dt.day.between(1, 7)]
    elif cycle_period == "Cycle 2 (8th - 14th)":
        filtered_df = filtered_df[filtered_df['Order_Placing_Time'].dt.day.between(8, 14)]
    elif cycle_period == "Cycle 3 (15th - 21st)":
        filtered_df = filtered_df[filtered_df['Order_Placing_Time'].dt.day.between(15, 21)]
    elif cycle_period == "Cycle 4 (22nd - End)":
        filtered_df = filtered_df[filtered_df['Order_Placing_Time'].dt.day >= 22]

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

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Express Pick SLA (<5m)", f"{exp_pick_sla:.1f}%")
    col2.metric("Standard Pick SLA", f"{std_pick_sla:.1f}%")
    col3.metric("Express Delivery SLA", f"{exp_del_sla:.1f}%")
    col4.metric("Standard Delivery SLA", f"{std_del_sla:.1f}%")
    col5.metric("In-House vs 3PL Split", f"{inhouse_pct:.0f}% / {tpl_pct:.0f}%")

    st.markdown("---")

    st.subheader("📝 Delayed Orders Action Table (Add Remarks for Manager Review)")

    delayed_orders = filtered_df[
        (filtered_df['Pick_SLA_Met'] == 0) | (filtered_df['On Time Delivered'] == 0)
    ].copy()

    if not delayed_orders.empty:
        edited_df = st.data_editor(
            delayed_orders[[
                'Order_ID', 'Store_Name', 'Order Type', 'Pick_Duration_Mins', 
                'Delivery Partner', 'On Time Delivered', 'Delay_Reason'
            ]],
            column_config={
                "Delay_Reason": st.column_config.SelectboxColumn(
                    "Delay Reason",
                    options=[
                        "Picker Shortage", "Stock Out", "System/App Issue", 
                        "Rider Delay", "Traffic/Weather", "Customer Unavailable"
                    ],
                    required=True
                )
            },
            disabled=['Order_ID', 'Store_Name', 'Order Type', 'Pick_Duration_Mins', 'Delivery Partner', 'On Time Delivered'],
            hide_index=True,
            key="delay_editor"
        )

        csv = edited_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Performance & Delay Report (CSV)",
            data=csv,
            file_name=f"Performance_Report_{selected_store}_{datetime.date.today()}.csv",
            mime="text/csv"
        )
    else:
        st.success("🎉 No delayed orders found for the selected store and cycle period!")

else:
    st.info("👈 Please upload your store picklists and transaction report from the sidebar to start.")
