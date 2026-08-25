#!/usr/bin/env python3
import atheris
import sys
import subprocess
import json
import argparse


def run_runtime(runtime: str, regex: str, test_input: str):
    """
    Run a JS runtime (node/deno/bun) with the given regex and test input.
    Returns the result of RegExp.test() as a string: "true", "false", or "error:*".
    """
    code = f"""
        try {{
            const re = new RegExp({json.dumps(regex)});
            const input = {json.dumps(test_input)};
            console.log(re.test(input));
        }} catch (e) {{
            console.error("ERROR:" + e.message);
            process.exit(2);
        }}
    """

    cmd_map = {
        "node": ["node", "-e", code],
        "deno": ["deno", "eval", code],
        "bun":  ["bun", "eval", code],
    }

    try:
        proc = subprocess.run(
            cmd_map[runtime],
            capture_output=True,
            text=True,
            timeout=2
        )
        if proc.returncode != 0:
            return f"error:{proc.stderr.strip()}"
        return proc.stdout.strip()
    except subprocess.TimeoutExpired:
        return "timeout"
    except Exception as e:
        return f"error:{str(e)}"


def test_one_input(data):
    """
    The fuzzing callback: receives a bytes input, converts to string,
    runs regex test across Node/Deno/Bun, and compares results.
    """
    fdp = atheris.FuzzedDataProvider(data)
    test_input = fdp.ConsumeUnicodeNoSurrogates(50)

    regex = REGEX_UNDER_TEST

    node_res = run_runtime("node", regex, test_input)
    deno_res = run_runtime("deno", regex, test_input)
    bun_res = run_runtime("bun", regex, test_input)

    results = {"input": test_input, "node": node_res, "deno": deno_res, "bun": bun_res}

    # If they differ, print discrepancy
    if len({node_res, deno_res, bun_res}) > 1:
        print("\n=== Discrepancy Found ===")
        print(json.dumps(results, indent=2))
        sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(
        description="Fuzz regex behavior across Node.js, Deno, and Bun using Atheris."
    )
    parser.add_argument(
        "-r", "--regex",
        required=True,
        help="Regex pattern to test (in JS syntax, e.g. 'a+b?')."
    )
    args, atheris_args = parser.parse_known_args()

    global REGEX_UNDER_TEST
    REGEX_UNDER_TEST = args.regex

    print(f"[+] Starting differential fuzzing")
    print(f"    Regex under test: {REGEX_UNDER_TEST}")
    sys.stdout.flush()

    atheris.Setup([sys.argv[0]] + atheris_args, test_one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
