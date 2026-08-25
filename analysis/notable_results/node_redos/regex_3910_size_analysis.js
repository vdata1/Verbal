// Timeout or something on node and deno?
// Also, returns null?

// NOTE (2026-07-17): the 5s/11s/22s ladder recorded below is the prior art for
// micro_probe.py in this directory, which automates it. That sweep classifies this
// same regex as exponential base 1.99 from a 24-CHAR input in milliseconds, and
// extrapolates back to within 5-17% of the three figures measured by hand here --
// which is the point: the cheap regime already contains the answer. See also
// ../../differential_findings/DISCREPANCIES.md#f004, which came out of that work.

// Regex: (?:\b[a-z\d](?:[_.:+]?[a-z\d]+)*_?_|`[^`]+`_?_|_`[^`]+`)(?=[\s\-.,:;!?\\\/'")\]}]|$)
// Input: le0i1xoa2bbhey0vg79f2mtujiqktmqt5gqwpa9g49vet63zwun2ancc0z87p_#}]
// T18: alternation precedence
try{

    const t_compile_start = performance.now();
    const re = /(?:\b[a-z\d](?:[_.:+]?[a-z\d]+)*_?_|`[^`]+`_?_|_`[^`]+`)(?=[\s\-.,:;!?\\\/'")\]}]|$)/g;
    const t_compile_end = performance.now();
    
    // const input = "le0i1xoa2bbhey0vg79f2mtujiqktmqt5gqwpa9g49vet63zwun2ancc0z87p_#}]";
    // "leeeeeeeeeeeeeeeeeeeeeeeeeeee_#}]" -- takes 22s
    // "leeeeeeeeeeeeeeeeeeeeeeeeeee_#}]" -- takes 11s
    // "leeeeeeeeeeeeeeeeeeeeeeeeee_#}]" -- takes 5s
    const input = "leeeeeeeeeeeeeeeeeeeeeeeeee_#}]";
    

    const t_exec_start = performance.now();
    console.log(str_to_bytes_( re.exec(input) ));
    const t_exec_end = performance.now();

    console.log("COMPILE_MS:", t_compile_end - t_compile_start);
    console.log("EXEC_MS:", t_exec_end - t_exec_start);
}  catch (error) {
    console.log(error)
    // Go through the possible errors that could have occured, with a unique
    // ret code for each.
    if (error instanceof SyntaxError) {
        process.exit(11);
    }
    // Any other case, exit with -1
    process.exit(-1);
}

function str_to_bytes_(str) {
  return str;
}

function str_to_bytes(str) {
    const encoder = new TextEncoder();
    const byte_array = encoder.encode(str);
    // Return a string representation of the byte array, where each byte is represented as \xNN
    return Array.from(byte_array).map(byte => '\\x' + byte.toString(16).padStart(2, '0')).join('');
}
