import pandas as pd
import os

FILE_PATH = r"c:\Users\n.zaher\OneDrive - LTS Transport u. Logistik GmbH\Desktop\shift-optimizer\traindata.xlsx"

def inspect_excel():
    print(f"Inspecting: {FILE_PATH}")
    if not os.path.exists(FILE_PATH):
        print("File not found!")
        return

    try:
        # Load Excel file (all sheets)
        xls = pd.ExcelFile(FILE_PATH)
        print(f"Sheets found: {xls.sheet_names}")

        for sheet in xls.sheet_names:
            print(f"\n--- SHEET: {sheet} ---")
            df = pd.read_excel(xls, sheet_name=sheet, nrows=100)
            print("Columns:", df.columns.tolist())
            print("Row 0-5:\n", df.head())
            print("Row 90-100:\n", df.tail(10))
            
            # Check for potential data block starts (non-empty rows after empty ones)
            print("\nScanning first column for keywords...")
            print(df.iloc[:, 0].dropna().tolist())
            print("-" * 30)

    except Exception as e:
        print(f"Error reading Excel: {e}")

if __name__ == "__main__":
    inspect_excel()
