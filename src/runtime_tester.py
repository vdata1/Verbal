import subprocess
import json
import os
import re
import codecs
import unicodedata

from paths import GENERATED_UNIT_TESTS_DIR, RESULTS_DIR

# A lot of this is probably unnecessary now that the tests themselves report raw bytes.
# So, TODO consider cleaning it up.

ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

class runtime_tester:
    def __init__(self, generated_unit_tests_path: str = GENERATED_UNIT_TESTS_DIR, runtime: str = "node"):
        self.unit_tests_results = {}
        self.tests_list = []
        self.runtime = runtime
        self.generated_unit_tests_path = generated_unit_tests_path
        self.results_filename = os.path.join(RESULTS_DIR, f"{self.runtime}_test_results.json")
        self.timeout_seconds = 5

    def collect_tests(self, numOfTests=-1) -> list:
        # Directory structure is:
        # generated_unit_tests/
        #   ... many regexes ...
        #   regex_114/
        #     ... many grammars ...
        #     mutated_grammar_0/
        #       ... many tests ...
        #       generated_unit_tests_0.js
        
        collected_tests = []
        limit = int(numOfTests) if numOfTests != -1 else None

        if not os.path.isdir(self.generated_unit_tests_path):
            print(f"Test directory does not exist: {self.generated_unit_tests_path}")
            return collected_tests

        # For each regex
        for regex_dir in sorted(os.listdir(self.generated_unit_tests_path)):
            print(f"Collecting tests from directory: {regex_dir}")
            regex_dir_path = os.path.join(self.generated_unit_tests_path, regex_dir)
            if not os.path.isdir(regex_dir_path):
                continue

            # For each mutated grammar of the regex
            for grammar_dir in sorted(os.listdir(regex_dir_path)):
                grammar_dir_path = os.path.join(regex_dir_path, grammar_dir)
                if not os.path.isdir(grammar_dir_path):
                    continue

                # For each test file of the mutated grammar
                num_tests_collected_for_this_grammar = 0
                for test_file in sorted(os.listdir(grammar_dir_path)):
                    if test_file.endswith(".js"):
                        test_file_path = os.path.join(grammar_dir_path, test_file)
                        collected_tests.append(test_file_path)
                        num_tests_collected_for_this_grammar += 1
                        if limit is not None and num_tests_collected_for_this_grammar >= limit:
                            print(f"Collected {len(collected_tests)} tests, reached the limit of numOfTests={numOfTests}. Stopping collection.")
                            break # And then do next grammar

        print(f"Collected a total of {len(collected_tests)} tests.")
        return collected_tests

    def _strip_ansi(self, text: str) -> str:
        return ANSI_ESCAPE_RE.sub("", text)

    def _decode_js_escape_sequences(self, text: str) -> str:
        """
        Best-effort decode for JS-style escaped output such as \\xNN and \\uNNNN.
        If decoding fails, return the original text unchanged.
        """
        try:
            return codecs.decode(text, "unicode_escape")
        except Exception:
            return text

    def _extract_payload_and_timings(self, stdout: str) -> tuple[str, str, str]:
        compile_time = "N/A"
        exec_time = "N/A"
        payload_lines = []

        for line in stdout.splitlines():
            if line.startswith("COMPILE_MS:"):
                compile_time = line.split("COMPILE_MS:", 1)[1].strip() or "N/A"
                continue
            if line.startswith("EXEC_MS:"):
                exec_time = line.split("EXEC_MS:", 1)[1].strip() or "N/A"
                continue
            if line.strip() == "END":
                continue
            payload_lines.append(line)

        payload = "\n".join(payload_lines).strip()
        return payload, compile_time, exec_time

    def _canonical_codepoints(self, text: str) -> str:
        return " ".join(f"U+{ord(ch):04X}" for ch in text)

    def normalize_output(self, output: str) -> str:
        # Cosmetic normalization for output comparisons across runtimes.
        cleaned = self._strip_ansi(output).replace("\r\n", "\n").replace("\r", "\n")
        cleaned = unicodedata.normalize("NFC", cleaned)
        decoded = self._decode_js_escape_sequences(cleaned)

        # Keep legacy "loose" normalization behavior to avoid changing downstream usage.
        normalized_space = decoded.replace(" ", "").replace("\n", "")
        normalized = normalized_space.replace("\"", "").replace("\'", "")
        return normalized

    def _runtime_command(self, runtime: str, testfile_path: str) -> list[str]:
        if runtime == "node":
            return ["node", testfile_path]
        if runtime == "deno":
            return ["deno", "run", testfile_path]
        if runtime == "bun":
            return ["bun", "run", testfile_path]
        raise ValueError(f"Unsupported runtime: {runtime}")

    def run_test(self, runtime: str, testfile_path: str) -> dict:
        try:
            cmd = self._runtime_command(runtime, testfile_path)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout_seconds,
                encoding="utf-8",
                errors="replace",
            )

            cleaned_stdout = self._strip_ansi(result.stdout or "")
            cleaned_stderr = self._strip_ansi(result.stderr or "")
            payload, compile_time, exec_time = self._extract_payload_and_timings(cleaned_stdout)

            # Cosmetic normalization used for differential comparisons.
            output = self.normalize_output(payload)

            # A strict canonical form that helps with escape-style differences.
            decoded_payload = self._decode_js_escape_sequences(unicodedata.normalize("NFC", payload))
            canonical_output = self._canonical_codepoints(decoded_payload)

            # If there's anything in stderr, output it here so we can think about it while a campaign is running. 
            # Sometimes there are interesting warnings that don't cause the test to fail but are still worth knowing about.
            if cleaned_stderr.strip():
                print(f"Warnings/Errors in {testfile_path} on {runtime}:\n{cleaned_stderr.strip()}")

            return {
                "output": output,
                "raw_output": payload,
                "canonical_output": canonical_output,
                "compile_time": compile_time,
                "exec_time": exec_time,
                "stderr": cleaned_stderr.strip(),
                "returncode": result.returncode,
                "runtime": runtime,
                "command": cmd,
                "status": "ok" if result.returncode == 0 else "runtime_error",
            }
        except subprocess.TimeoutExpired as e:
            return {
                "output": "",
                "raw_output": "",
                "canonical_output": "",
                "compile_time": "N/A",
                "exec_time": "N/A",
                "stderr": "",
                "returncode": None,
                "runtime": runtime,
                "command": self._runtime_command(runtime, testfile_path),
                "status": "timeout",
                "error": f"Command timed out after {e.timeout} seconds",
            }
        except ValueError as e:
            return {
                "output": "",
                "raw_output": "",
                "canonical_output": "",
                "compile_time": "N/A",
                "exec_time": "N/A",
                "stderr": "",
                "returncode": None,
                "runtime": runtime,
                "command": [],
                "status": "invalid_runtime",
                "error": str(e),
            }
        except Exception as e:
            return {
                "output": "",
                "raw_output": "",
                "canonical_output": "",
                "compile_time": "N/A",
                "exec_time": "N/A",
                "stderr": "",
                "returncode": None,
                "runtime": runtime,
                "command": [],
                "status": "error",
                "error": str(e),
            }

    def test_runtime(self, runtime: str, numOfTests="all") -> None:
        print(f"Testing runtime: {runtime}")
        self.tests_list = self.collect_tests(numOfTests=numOfTests)
        print(f"Collected {len(self.tests_list)} tests for runtime {runtime}.")
    
        for testfile_path in self.tests_list:
            print(f"Running test file: {testfile_path} on runtime: {runtime}")
            self.unit_tests_results[testfile_path] = self.run_test(runtime, testfile_path)
        with open(self.results_filename, "w") as f:
            json.dump(self.unit_tests_results, f, indent=4)
            



__all__ = ["runtime_tester"]