#!/usr/bin/env bash
set -euo pipefail

# === CONFIG ===
NODE_VERSION="v22.5.0"                   # Change if needed
WORKDIR="$PWD/node_coverage"             # Build & coverage workspace
NODE_SRC="$WORKDIR/node"                 # Node.js source dir
TEST_CMD="./node path/to/test.js"        # Command to run (relative to Node build dir)
LCOV_OUTPUT="$WORKDIR/total.info"
HTML_OUTPUT="$WORKDIR/html_report"

# === PREPARE WORKDIR ===
mkdir -p "$WORKDIR"

# === 1. Clone Node.js if not present ===
if [[ ! -d "$NODE_SRC" ]]; then
    echo "[*] Cloning Node.js $NODE_VERSION..."
    git clone https://github.com/nodejs/node.git "$NODE_SRC"
    cd "$NODE_SRC"
    git checkout "$NODE_VERSION"
else
    echo "[*] Using existing Node.js source."
    cd "$NODE_SRC"
    git fetch --all --tags
    git checkout "$NODE_VERSION"
fi

# === 2. Configure and build if not already built with coverage ===
if ! grep -q -- "--coverage" config.mk 2>/dev/null; then
    echo "[*] Configuring Node.js with coverage flags..."
    make distclean || true
    CFLAGS="--coverage" \
    CXXFLAGS="--coverage" \
    LDFLAGS="--coverage" \
    ./configure
    make -j"$(nproc)"
else
    echo "[*] Node.js already built with coverage. Skipping full rebuild."
fi

# === 3. Clear old coverage data ===
echo "[*] Clearing old coverage data..."
find . -name "*.gcda" -type f -delete
rm -rf "$WORKDIR/v8_js_coverage"
mkdir -p "$WORKDIR/v8_js_coverage"

# === 4. Run test/fuzzer ===
echo "[*] Running workload..."
NODE_V8_COVERAGE="$WORKDIR/v8_js_coverage" bash -c "$TEST_CMD"

# === 5. Collect C++ coverage ===
echo "[*] Collecting C++ coverage..."
lcov --capture --directory . --output-file "$WORKDIR/cpp_coverage.info"

# === 6. Convert JS coverage to LCOV ===
echo "[*] Converting JS coverage to LCOV..."
npm install -g @bcoe/v8-coverage-lcov >/dev/null 2>&1
npx @bcoe/v8-coverage-lcov "$WORKDIR/v8_js_coverage" > "$WORKDIR/js_coverage.info"

# === 7. Merge C++ and JS coverage ===
echo "[*] Merging coverage..."
lcov --add-tracefile "$WORKDIR/cpp_coverage.info" \
     --add-tracefile "$WORKDIR/js_coverage.info" \
     --output-file "$LCOV_OUTPUT"

# === 8. Generate HTML report ===
echo "[*] Generating HTML report..."
genhtml "$LCOV_OUTPUT" --output-directory "$HTML_OUTPUT"

echo "[+] Coverage HTML report available at: $HTML_OUTPUT/index.html"

