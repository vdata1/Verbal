import json
import subprocess
import tempfile
import os

def collect_regex(data):
    results = {}
    for regex, obj in data.items():
        if "test_inputs" in obj.keys():
            if isinstance(obj["test_inputs"], list) and obj["test_inputs"]:
                results[regex] = obj["test_inputs"]
    return results

def run_js_on_runtime(runtime, regex, input_test):
    js_code = f"""
const Regex = new RegExp({regex});
const result = Regex.test({input_test});
console.log(result);
"""
    with tempfile.NamedTemporaryFile(delete=False, suffix='.js', mode='w') as f:
        f.write(js_code)
        temp_js_path = f.name
    try:
        if runtime == "node":
            cmd = ["node", temp_js_path]
        elif runtime == "deno":
            cmd = ["deno", "run", "--allow-all", temp_js_path]
        elif runtime == "bun":
            cmd = ["bun", temp_js_path]
        else:
            return None
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        output = result.stdout.strip()
        print(f"Output for {runtime} with regex {regex} and input {input_test}: {output}")
        return output
    except Exception as e:
        return str(e)
    finally:
        os.remove(temp_js_path)

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run regex tests on Node, Deno, and Bun.")
    parser.add_argument("-r", "--resource", required=True, help="Path to JSON resource file")
    parser.add_argument("-o", "--output", required=True, help="Path to output JSON file")
    args = parser.parse_args()

    json_path = args.resource
    outputFile = args.output

    with open(json_path, 'r') as f:
        data = json.load(f)
    objects = collect_regex(data)
    output = {}
    print(f"Found {len(objects)} objects with 'test_inputs' key.")
    print(objects)
    #counter = 0
    for regex, test_inputs in objects.items():
        #if counter >= 10:
        #    break
        
        output[regex] = {}
        for input_test in test_inputs:
            output[regex][input_test] = {}
            for runtime in ["node", "deno", "bun"]:
                result = run_js_on_runtime(runtime, json.dumps(regex), json.dumps(input_test))
                output[regex][input_test][runtime] = result
        #counter += 1
    with open(outputFile, "w") as f:
        json.dump(output, f, indent=2)

if __name__ == "__main__":
    main()