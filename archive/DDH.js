// delta_debug.js
const fs = require("fs");
const { execSync } = require("child_process");

/**
 * Run the test on given code string.
 * The `testFunc` must return true if the bug is still present, false otherwise.
 */
function runTest(code, testFunc) {
    try {
        return testFunc(code);
    } catch (e) {
        return false;
    }
}

/**
 * Split the code into N chunks
 */
function splitCode(codeLines, n) {
    const size = Math.ceil(codeLines.length / n);
    let chunks = [];
    for (let i = 0; i < codeLines.length; i += size) {
        chunks.push(codeLines.slice(i, i + size));
    }
    return chunks;
}

/**
 * Delta debugging algorithm
 */
function deltaDebug(codeLines, testFunc) {
    let n = 2;

    while (codeLines.length >= 2) {
        let chunks = splitCode(codeLines, n);
        let reduced = false;

        // Try removing each chunk
        for (let i = 0; i < chunks.length; i++) {
            let candidate = chunks
                .filter((_, idx) => idx !== i)
                .flat();

            if (runTest(candidate.join("\n"), testFunc)) {
                codeLines = candidate;
                n = Math.max(n - 1, 2);
                reduced = true;
                break;
            }
        }

        if (!reduced) {
            if (n >= codeLines.length) break;
            n = Math.min(n * 2, codeLines.length);
        }
    }

    return codeLines;
}

// Example usage:
if (require.main === module) {
    // Example buggy program
    let code = `
const pattern = "/$$(|.?||\u068b\u067d\u06d2\u06d2+|)+/"


try {
  const regex = new RegExp(pattern);
} catch (e) {
  console.error("Invalid regex pattern:", e.message);
}
`.trim();

    // Test function: returns true if code still throws
    function testFunc(jsCode) {
        try {
            fs.writeFileSync("temp.js", jsCode);
            execSync("node temp.js", { stdio: "pipe" });
            return false;
        } catch {
            return true; // bug still happens
        }
    }

    let codeLines = code.split("\n");
    let minimized = deltaDebug(codeLines, testFunc);
    console.log("=== Minimized Code ===\n" + minimized.join("\n"));
}

