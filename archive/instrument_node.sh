#!/usr/bin/env bash
set -euo pipefail

# === CONFIG ===
NODE_VERSION="v22.5.0"          # Change if needed
WORKDIR="$PWD/node_coverage"    # Build & coverage workspace
TEST_CMD="./node path/to/test.js"  # Command to run (relative to Node build dir)
LCOV_OUTPUT="$WORKDIR/total.info"
HTML_OUTPUT="$WORKDIR/html_report"

# === PREPARE WORKDIR ===
rm -rf "$WORKDIR"
mkdir -p "$WORKDIR"
cd "$WORKDIR"

# === 1. Get Node.js source ===
echo "[*] Cloning Node.js $NODE_VERSION..."
git clone https://github.com/nodejs/node.git
cd node
git checkout "$NODE_VERSION"

# === 2. Build with coverage flags ===
echo "[*] Building Node.js with coverage flags..."
make distclean || true
CFLAGS="--coverage" \
CXXFLAGS="--coverage" \
LDFLAGS="--coverage" \
./configure
make -j"$(nproc)"

# === 3. Run test/fuzzer with V8 JS coverage ===
echo "[*] Running workload..."
mkdir -p "$WORKDIR/v8_js_coverage"
NODE_V8_COVERAGE="$WORKDIR/v8_js_coverage" bash -c "$TEST_CMD"

# === 4. Collect C++ coverage ===
echo "[*] Collecting C++ coverage..."
lcov --capture --directory . --output-file "$WORKDIR/cpp_coverage.info"

# === 5. Convert JS coverage to LCOV ===
echo "[*] Converting JS coverage to LCOV..."
npm install -g @bcoe/v8-coverage-lcov >/dev/null 2>&1
npx @bcoe/v8-coverage-lcov "$WORKDIR/v8_js_coverage" > "$WORKDIR/js_coverage.info"

# === 6. Merge C++ and JS coverage ===
echo "[*] Merging coverage..."
lcov --add-tracefile "$WORKDIR/cpp_coverage.info" \
     --add-tracefile "$WORKDIR/js_coverage.info" \
     --output-file "$LCOV_OUTPUT"

# === 7. Generate HTML report ===
echo "[*] Generating HTML report..."
genhtml "$LCOV_OUTPUT" --output-directory "$HTML_OUTPUT"

echo "[+] Coverage HTML report generated at: $HTML_OUTPUT/index.html"

