import json
import subprocess
import hashlib
import os

def load_json(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        return json.load(f)

def update_script_js(pattern, test_string, js_filename='script_getting_modified.js'):
    js_code = f'''\
const pattern = {json.dumps(pattern)};
const testString = {json.dumps(test_string)};

if (!pattern || !testString) {{
  console.error("Usage: node testRegex.js <pattern> <testString>");
  process.exit(1);
}}

try {{
  const regex = new RegExp(pattern);
  const result = regex.test(testString);
  const match = regex.exec(testString)
  const index = testString.search(regex);
  const parts = testString.split(regex);

  console.log(`Regex Test: " ${{result}}`);

  if (match) {{
    console.log("Regex.exec():", match[0]);
    console.log("Capture groups:", match.slice(1));
  }}


  if (index !== -1) {{
    console.log("Search index:", index);
  }}

  if (parts) {{
    console.log("Split parts:", parts);
  }}

  console.log("Last match (RegExp.$&):", RegExp["$&"]);

  const matches = testString.match(regex);
  if (matches) {{
    console.log("String.match():", matches);
  }}

  const matches2 = [...testString.matchAll(regex)];
  if (matches2.length > 0) {{
    console.log("String.matchAll():", matches2);
  }}

}} catch (e) {{
  console.error("Invalid regex pattern:", e.message);
}}
'''
    with open(js_filename, 'w', encoding='utf-8') as f:
        f.write(js_code)

def run_valid_js(runtime, regex_pattern, test_string):
    try:
        update_script_js(regex_pattern, test_string)

        if runtime == "node":
            result = subprocess.run(
                [runtime, 'script_getting_modified.js'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
                timeout=5,
                encoding='utf-8'
            )
        elif runtime == "deno":
            result = subprocess.run(
                [runtime, "run", "-A", 'script_getting_modified.js'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
                timeout=5,
                encoding='utf-8'
            )
        else:  # default for bun or others
            result = subprocess.run(
                [runtime, "run", 'script_getting_modified.js'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
                timeout=5,
                encoding='utf-8'
            )

        return {
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip()
        }
        #return result.stdout.strip()

    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr.strip()}"
    except subprocess.TimeoutExpired as e:
        return f"Error (Timeout): Command timed out after {e.timeout} seconds"
    except Exception as e:
        return f"Error (Other): {str(e)}"

def main():
    input_file = 'string_samples_cleaned.json'
    regex_file = 'valid_regex_named.json'
    output_file = 'op.json'

    input_data = load_json(input_file)
    regex_list = load_json(regex_file)

    results = {}
    entry_count = 1

    for key, strings in input_data.items():
        pattern = regex_list.get(key)
        if pattern is None:
            print("No regex found for key: ", key)
            continue

        for test_str in strings:
            print(f"{key} : {pattern} : {test_str}")
            node_out = run_valid_js('node', pattern, test_str)
            deno_out = run_valid_js('deno', pattern, test_str)
            bun_out = run_valid_js('bun', pattern, test_str)

            results[f"entry{entry_count}"] = {
                "regex": pattern,
                "regex_len": len(pattern),
                "string": test_str,
                "string_len": len(test_str),
                "node": node_out,
                "deno": deno_out,
                "bun": bun_out
            }
            entry_count += 1

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Results saved to {output_file}")

if __name__ == '__main__':
    main()
