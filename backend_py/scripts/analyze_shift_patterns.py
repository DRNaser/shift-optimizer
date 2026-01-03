import pandas as pd
import os
import re
from datetime import datetime, timedelta

FILE_PATH = r"c:\Users\n.zaher\OneDrive - LTS Transport u. Logistik GmbH\Desktop\shift-optimizer\traindata.xlsx"

def analyze_patterns():
    print(f"Analyzing Patterns in: {FILE_PATH}")
    if not os.path.exists(FILE_PATH):
        print("File not found!")
        return

    try:
        # Load summary to find range
        xls = pd.ExcelFile(FILE_PATH)
        df = pd.read_excel(xls, sheet_name=xls.sheet_names[0])
        
        # Assumption: Data starts after summary. We'll iterate all cells and filter for time-strings
        # Regex for time range: HH:MM-HH:MM
        # Pattern for blocks: range(/range)*
        
        time_pattern = re.compile(r'\d{2}:\d{2}-\d{2}:\d{2}')
        
        counts = {
            "single": 0,
            "double": 0,
            "triple": 0,
            "split": 0,
            "krank": 0,
            "urlaub": 0,
            "frei": 0,
            "other": 0
        }
        
        split_gaps = []
        
        total_cells = 0
        valid_cells = 0
        
        print("Scanning cells for shift patterns...")
        
        # We iterate through the values directly, ignoring headers/index for speed
        # Flatten the dataframe to a list of values
        all_values = df.values.flatten()
        
        for val in all_values:
            s_val = str(val).strip()
            total_cells += 1
            
            if pd.isna(val) or s_val == 'nan':
                continue
                
            # Classify
            lower_val = s_val.lower()
            if "krank" in lower_val:
                counts["krank"] += 1
                continue
            if "urlaub" in lower_val:
                counts["urlaub"] += 1
                continue
            if "frei" in lower_val:
                counts["frei"] += 1
                continue
            
            # Check for Time Pattern
            if time_pattern.search(s_val):
                valid_cells += 1
                parts = s_val.split('/')
                num_parts = len(parts)
                
                is_split = False
                
                # Analyze Gaps for Split classification
                if num_parts > 1:
                    # Parse times to find gaps
                    # Format: 08:30-13:00
                    try:
                        last_end = None
                        for p in parts:
                            t_str = p.strip()
                            # robustness for 08:30-13:00 (extract times)
                            match = time_pattern.search(t_str)
                            if match:
                                rng = match.group(0)
                                start_s, end_s = rng.split('-')
                                start_dt = datetime.strptime(start_s, "%H:%M")
                                end_dt = datetime.strptime(end_s, "%H:%M")
                                
                                if last_end:
                                    # Calc gap
                                    gap_min = (start_dt - last_end).total_seconds() / 60
                                    # Handle Day wrap if needed (unlikely in single cell string but possible)
                                    if gap_min < 0: gap_min += 24*60
                                    
                                    if gap_min >= 180: # > 3 hours = Split
                                        is_split = True
                                        split_gaps.append(gap_min)
                                
                                last_end = end_dt
                    except:
                        pass # Ignore parse errors for simple counting

                if is_split:
                    counts["split"] += 1
                
                # Block Type Counting
                if num_parts == 1:
                    counts["single"] += 1
                elif num_parts == 2:
                    counts["double"] += 1
                elif num_parts >= 3:
                     counts["triple"] += 1
                else:
                    counts["other"] += 1
                    
        print("\n--- ANALYSIS RESULTS ---")
        print(f"Total Cells Scanned: {total_cells}")
        print(f"Valid Shift Cells: {valid_cells}")
        print("-" * 20)
        print(f"1er (Single): {counts['single']} ({counts['single']/valid_cells*100:.1f}%)")
        print(f"2er (Double): {counts['double']} ({counts['double']/valid_cells*100:.1f}%)")
        print(f"3er (Triple): {counts['triple']} ({counts['triple']/valid_cells*100:.1f}%)")
        print("-" * 20)
        print(f"Split Shifts (>3h gap): {counts['split']} ({counts['split']/valid_cells*100:.1f}%)")
        if split_gaps:
             avg_gap = sum(split_gaps)/len(split_gaps)
             print(f"Avg Split Gap: {avg_gap:.1f} min (Min: {min(split_gaps)}, Max: {max(split_gaps)})")
        print("-" * 20)
        print(f"Krank: {counts['krank']}")
        print(f"Urlaub: {counts['urlaub']}")
        print(f"Frei: {counts['frei']}")

    except Exception as e:
        print(f"Error Analyzing: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    analyze_patterns()
