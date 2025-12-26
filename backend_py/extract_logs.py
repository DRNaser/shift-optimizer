import sys

def main():
    queries = [
        "BEST_BALANCED: TWO-PASS SOLVE", 
        "Pass 1 overhead", 
        "Remaining budget", 
        "Insufficient budget",
        "PASS 2 INFEASIBLE",
        "PASS 1 FAILED", 
        "PASS 2 RESULT",
        "solve_capacity_twopass_balanced RETURNING",
        "Budget:"
    ]
    
    try:
        # Try UTF-16 (PowerShell default)
        with open("server_log.txt", "r", encoding="utf-16") as f:
            for line in f:
                if any(q in line for q in queries):
                    print(line.strip())
    except Exception:
        # Fallback to UTF-8
        try:
            with open("server_log.txt", "r", encoding="utf-8") as f:
                for line in f:
                    if any(q in line for q in queries):
                        print(line.strip())
        except Exception as e:
            print(f"Error reading file: {e}")

if __name__ == "__main__":
    main()
