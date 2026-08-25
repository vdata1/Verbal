import json
import os
import re

def normalize_output(val):
    # Replace escaped double quotes with single quotes
    val = val.replace('\"', "'").strip()          #replace \" with ' 
    val = val.replace('\n', '')                   #remove \n
    val = re.sub(r'\s+([\]\)\}\,:])', r'\1', val) #remove space before ending brackets like )]} .etc. 
    val = val.replace("\\'", "'")                 #replace \\' with ' 
    val = val.replace("\\x0B","\\v")              #unicode escape seq x0B represnted as v in bun
    val = val.replace("\\u000b","\\v")              #unicode escape seq x0B represnted as \u000b in bun
    val = val.replace("\\u0007","\\x07")
    val = val.replace("`","'")                   #replace ` with '
    return re.sub(r'\s{2,}', ' ', val)            #replace 2 spaces with single space
    
    
def find_diff_entries(input_filepath, output_filepath):
    
    if not os.path.exists(input_filepath):
        print(f"Error: Input file '{input_filepath}' not found.")
        return

    try:
        with open(input_filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Could not decode JSON from '{input_filepath}'. Please check if it's a valid JSON file. Error: {e}")
        return
    except Exception as e:
        print(f"An unexpected error occurred while reading the input file: {e}")
        return

    diff_entries = {}
    for entry_key, entry_data in data.items():
        # Ensure 'node', 'deno', and 'bun' keys exist to avoid KeyError
        node_val = normalize_output(entry_data.get("node"))
        deno_val = normalize_output(entry_data.get("deno"))
        bun_val = normalize_output(entry_data.get("bun"))

        if deno_val.endswith('--'):
            if not node_val.endswith('--') and not bun_val.endswith('--'):
                continue
        elif node_val.endswith('\\'):
            if not deno_val.endswith('\\') and not bun_val.endswith('\\'):
                continue
        elif "Last match (RegExp.$&): '" in node_val:
            if not "Last match (RegExp.$&): '" in deno_val:
                if not "Last match (RegExp.$&): '" in bun_val:
                    continue
        elif "Error: Command" in node_val and "Error: Command" in deno_val and "Error: Command" in bun_val:
            continue 
        elif "/String.match(): " in bun_val and (not "/String.match(): " in deno_val) and (not "/String.match(): " in node_val):
            continue
        elif not (node_val == deno_val and deno_val == bun_val):
            entry_data["node"] = node_val
            entry_data["deno"] = deno_val
            entry_data["bun"] = bun_val
            diff_entries[entry_key] = entry_data

    if diff_entries:
        try:
            with open(output_filepath, 'w', encoding='utf-8') as f:
                json.dump(diff_entries, f, indent=2)
            print(f"Found {len(diff_entries)} entries with differences. Saved to '{output_filepath}'.")
        except Exception as e:
            print(f"Error: Could not write to output file '{output_filepath}'. Error: {e}")
    else:
        print("No entries with differences found. 'diff.json' will not be created.")

# --- Configuration ---
input_json_file = 'op.json'  # <--- Set your input JSON file name here
output_json_file = 'diff.json'      # Output file name

# --- Run the function ---
find_diff_entries(input_json_file, output_json_file)