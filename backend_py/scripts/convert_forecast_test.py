"""
Convert forecast-test.txt to CSV format for optimizer testing.
"""
import re
from pathlib import Path

def convert_forecast_test_to_csv():
    input_file = Path(r"c:\Users\n.zaher\OneDrive - LTS Transport u. Logistik GmbH\Desktop\shift-optimizer\forecast-test.txt")
    output_file = Path(r"c:\Users\n.zaher\OneDrive - LTS Transport u. Logistik GmbH\Desktop\shift-optimizer\forecast_test.csv")
    
    # German day names to match original parser
    day_mapping = {
        "Montag": "Montag",
        "Dienstag": "Dienstag",
        "Mittwoch": "Mittwoch",
        "Donnerstag": "Donnerstag",
        "Freitag": "Freitag",
        "Samstag": "Samstag",
        "Sonntag": "Sonntag",
    }
    
    current_day = None
    lines_out = []
    
    with open(input_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            # Check if it's a day header
            day_found = False
            for day_de in day_mapping.keys():
                if day_de in line:
                    current_day = day_mapping[day_de]
                    lines_out.append(f"{current_day};Anzahl")
                    day_found = True
                    break
            
            if day_found:
                continue
            
            # Parse tour line: TIME-TIME\tCOUNT
            parts = line.split('\t')
            if len(parts) >= 2:
                time_range = parts[0].strip()
                count = parts[1].strip()
                
                if time_range and count and current_day:
                    lines_out.append(f"{time_range};{count}")
    
    # Write output
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines_out))
    
    print(f"[OK] Converted {input_file.name} -> {output_file.name}")
    print(f"  {len(lines_out)} lines written")
    return str(output_file)

if __name__ == "__main__":
    csv_path = convert_forecast_test_to_csv()
    print(f"\nCSV file: {csv_path}")
