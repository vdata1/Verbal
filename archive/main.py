from fandango import Fandango
import subprocess
import json
import argparse
from regex_to_ebnf2 import generate_ebnf_from_regex, regex_to_ebnf
import os

#import sys

# Default .fan file path
default_fan_file = "./grammer/1.fan"

# Directory to store generated EBNF files
ebnf_dir = "generated_grammers"
os.makedirs(ebnf_dir, exist_ok=True)

def runScript_js(runtime, test_script):
    res = {}
    if runtime == "deno":
        res = subprocess.run(
            ["deno", "eval", test_script],
            capture_output=True,
            text=True
        )
    elif runtime == "bun" or runtime == "node":
        res = subprocess.run(
            [runtime, "-e", test_script],
            capture_output=True,
            text=True
        )
    return res

parser = argparse.ArgumentParser(
    description="Validate regexes across JS runtimes."
)
parser.add_argument(
    "-n", "--number", type=int, default=1000,
    help="Number of regex outputs to generate (default: 1000)"
)
parser.add_argument(
    "-i", "--inputs", type=int, default=5000,
    help="Number of regex inputs to generate (default: 5000)"
)
parser.add_argument(
    "-o", "--output", type=str, default="regex_validation_results.json",
    help="Output file name (default: regex_validation_results.json)"
)
parser.add_argument(
    "-g", "--grammar", type=str, default=default_fan_file,
    help="Path to .fan grammar file (default: %(default)s)"
)
args = parser.parse_args()

fan_file = args.grammar
desired_solutions = args.number
output_file = args.output
desired_inputs = args.inputs

# Read in a .fan spec from a file
with open(fan_file) as gram_file:
    fan = Fandango(gram_file)


results = {}
counter = 0   # keeps track of processed regex
ebnf_counter = 0  # keeps track of generated ebnf files
for regex in fan.fuzz(desired_solutions=desired_solutions):
    regex_str = str(regex)
    results[regex_str] = {}

    # Prepare a JS script to test regex validity
    node_script = f"""
    try {{
        new RegExp({regex_str});
        process.exit(0);
    }} catch (e) {{
        process.exit(1);
    }}
    """

    # Node.js
    node_res = runScript_js("node", node_script)
    results[regex_str]['node'] = (node_res.returncode == 0)

    # Deno
    deno_script = f"""
    try {{
        new RegExp({regex_str});
        Deno.exit(0);
    }} catch (e) {{
        Deno.exit(1);
    }}
    """
    deno_res = runScript_js("deno", deno_script)
    results[regex_str]['deno'] = (deno_res.returncode == 0)

    # Bun
    bun_script = node_script  # Bun supports Node.js style scripts
    bun_res = runScript_js("bun", bun_script)
    results[regex_str]['bun'] = (bun_res.returncode == 0)

    # Check for differences
    values = list(results[regex_str].values())
    if not all(v == values[0] for v in values):
        print(f"Discrepancy found for regex: {regex_str} -> {results[regex_str]}")

    elif all(v is True for v in values):
        print(f"All match for regex: {regex_str}, generating test cases...")
        try:
            ebnf = generate_ebnf_from_regex(regex_str)
            print("Generated EBNF1:", ebnf)

            ebnf_file_idx = ebnf_counter + 1
            ebnf_counter += 1
            ebnf_file_path = os.path.join(ebnf_dir, f"ebnf_{ebnf_file_idx}.txt")
            with open(ebnf_file_path, "w") as ebnf_file:
                ebnf_file.write(str(ebnf))
            results[regex_str]['ebnf_file'] = ebnf_file_path

            with open(ebnf_file_path, "r") as ebnf_file:
                ebnf_content = ebnf_file.read()
            try:
                fan_test = Fandango(str(ebnf_content))
                print(f"Generated EBNF for {regex_str}: {ebnf}")
                test_inputs = [str(s) for s in fan_test.fuzz(desired_solutions=desired_inputs)]
                print(f"Test inputs for {regex_str}: {test_inputs}")
                results[regex_str]['test_inputs'] = test_inputs
            except Exception as e:
                results[regex_str]['test_inputs'] = f"Error generating test inputs: {e}"
                print(f"Failed to generate test inputs for {regex_str}: {e}")
        except Exception as e:
            results[regex_str]['ebnf'] = f"Error: {e}"
            print(f"Failed to convert {regex_str} to EBNF: {e}")

    # increment counter
    counter += 1

    # flush every 20 regex
    if counter % 20 == 0:
        # Load old results if file exists
        if os.path.exists(output_file):
            with open(output_file, "r") as f:
                try:
                    old_results = json.load(f)
                except json.JSONDecodeError:
                    old_results = {}
        else:
            old_results = {}

        # Merge
        old_results.update(results)

        # Write back as single JSON
        with open(output_file, "w") as f:
            json.dump(old_results, f, indent=2)

        # Reset local results
        results.clear()

# dump any leftover results at the end
if results:
    if os.path.exists(output_file):
        with open(output_file, "r") as f:
            try:
                old_results = json.load(f)
            except json.JSONDecodeError:
                old_results = {}
    else:
        old_results = {}

    old_results.update(results)

    with open(output_file, "w") as f:
        json.dump(old_results, f, indent=2)
        results.clear()

