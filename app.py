import streamlit as st
import pandas as pd
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from data_processor import process_and_merge_reports

st.set_page_config(page_title="Fulfilment & Delivery Dashboard", layout="wide")

# --- GOOGLE SHEETS CONNECTION ---
@st.cache_resource
def get_gspread_client():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client

def load_saved_remarks():
    try:
        client = get_gspread_client()
        sheet_id = st.secrets["sheets"]["spreadsheet_id"]
        sheet = client.open_by_key(sheet_id).sheet1
        records = sheet.get_all_records()
        return pd.DataFrame(records)
    except Exception as e:
        return pd.DataFrame(columns=[
            'Order_ID', 'Store_Name', 'Delay_Type', 
            'Order_Type', 'Delay_Reason', 'Submitted_By', 'Timestamp'
        ])

def append_saved_remark(order_id, store_name, delay_type, order_type, delay_reason, submitted_by="Team"):
    try:
        client = get_gspread_client()
        sheet_id = st.secrets["sheets"]["spreadsheet_id"]
        sheet = client.open_by_key(sheet_id).sheet1
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([
            str(order_id), str(store_name), str(delay_type), 
            str(order_type), str(delay_reason), str(submitted_by), timestamp
        ])
        return True
    except Exception as e:
        st.error(f"Error saving to Google Sheet: {e}")
        return False

# --- SIDEBAR ---
st.sidebar.header("📁 Step 1: Upload Daily Data")
picklist_files = st.sidebar.file_uploader(
    "Upload Store Picklist Reports (.xls/.csv)", 
    accept_multiple_files=True
)
transaction_file = st.sidebar.file_uploader(
    "Upload Order Transactions Report (.xlsx/.csv)"
)

# Fetch current database of already submitted remarks
saved_db = load_saved_remarks()
saved_order_ids = set(saved_db['Order_ID'].astype(str).unique()) if not saved_db.empty else set()

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

    # --- TABS FOR TEAM & MANAGER REVIEW ---
    tab_pick, tab_del, tab_mgr = st.tabs([
        "🛒 Pending Picking Delays", 
        "🚚 Pending Delivery Delays", 
        "📊 Manager Review (Saved Remarks)"
    ])
    
    with tab_pick:
        st.subheader("Action Required: Submit Custom Picking Delay Reasons")
        # Filter out orders that already have saved remarks in Google Sheets
        pick_breached = filtered_df[
            (filtered_df['Pick_SLA_Met'] == 0) & 
            (~filtered_df['Order_ID'].astype(str).isin(saved_order_ids))
        ].copy()
        
        if not pick_breached.empty:
            for idx, row in pick_breached.iterrows():
                c1, c2, c3, c4, c5, c6 = st.columns([2, 2, 2, 2, 3, 2])
                c1.write(f"**{row['Order_ID']}**")
                c2.write(row['Store_Name'])
                c3.write(row['Order Type'])
                c4.write(row['Pick Duration'])
                reason_input = c5.text_input("Reason", key=f"p_reason_{row['Order_ID']}", placeholder="Enter custom reason...")
                
                if c6.button("Submit & Hide", key=f"p_btn_{row['Order_ID']}"):
                    if reason_input.strip() != "":
                        success = append_saved_remark(
                            order_id=row['Order_ID'],
                            store_name=row['Store_Name'],
                            delay_type="Picking Delay",
                            order_type=row['Order Type'],
                            delay_reason=reason_input.strip()
                        )
                        if success:
                            st.success(f"Saved & Hidden: {row['Order_ID']}")
                            st.rerun()
                    else:
                        st.warning("Please enter a reason before submitting.")
                st.divider()
        else:
            st.success("🎉 All picking delays have been resolved and submitted!")

    with tab_del:
        st.subheader("Action Required: Submit Custom Delivery Delay Reasons")
        # Filter out orders that already have saved remarks in Google Sheets
        del_breached = filtered_df[
            (filtered_df['On Time Delivered'] == 0) & 
            (~filtered_df['Order_ID'].astype(str).isin(saved_order_ids))
        ].copy()
        
        if not del_breached.empty:
            for idx, row in del_breached.iterrows():
                c1, c2, c3, c4, c5, c6 = st.columns([2, 2, 2, 2, 3, 2])
                c1.write(f"**{row['Order_ID']}**")
                c2.write(row['Store_Name'])
                c3.write(row['Order Type'])
                c4.write(row['Delivery Partner'])
                reason_input = c5.text_input("Reason", key=f"d_reason_{row['Order_ID']}", placeholder="Enter custom reason...")
                
                if c6.button("Submit & Hide", key=f"d_btn_{row['Order_ID']}"):
                    if reason_input.strip() != "":
                        success = append_saved_remark(
                            order_id=row['Order_ID'],
                            store_name=row['Store_Name'],
                            delay_type="Delivery Delay",
                            order_type=row['Order Type'],
                            delay_reason=reason_input.strip()
                        )
                        if success:
                            st.success(f"Saved & Hidden: {row['Order_ID']}")
                            st.rerun()
                    else:
                        st.warning("Please enter a reason before submitting.")
                st.divider()
        else:
            st.success("🎉 All delivery delays have been resolved and submitted!")

    with tab_mgr:
        st.subheader("📊 Submitted Delay Remarks Audit (Manager View)")
        current_remarks = load_saved_remarks()
        if not current_remarks.empty:
            if selected_store != 'All Stores (HYD Region)':
                current_remarks = current_remarks[current_remarks['Store_Name'] == selected_store]
            
            st.dataframe(current_remarks, use_container_width=True)
            
            # Export Option
            csv_data = current_remarks.to_csv(index=False).encode('utf-8')
            st.download_button(
                "📥 Export Submitted Remarks Report",
                data=csv_data,
                file_name=f"Delay_Remarks_{selected_store}_{datetime.date.today()}.csv",
                mime="text/csv"
            )
        else:
            st.info("No submitted delay remarks found in Google Sheets database yet.")

else:
    st.title("🚚 Fulfillment & Delivery Performance Dashboard")
    st.info("👈 Please upload your store picklists and transaction report from the sidebar to start.")
