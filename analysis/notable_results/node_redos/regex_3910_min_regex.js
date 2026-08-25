// Timeout or something on node and deno?
// Also, returns null?

// Regex: (?:\b[a-z\d](?:[_.:+]?[a-z\d]+)*_?_|`[^`]+`_?_|_`[^`]+`)(?=[\s\-.,:;!?\\\/'")\]}]|$)
// Input: le0i1xoa2bbhey0vg79f2mtujiqktmqt5gqwpa9g49vet63zwun2ancc0z87p_#}]
// T18: alternation precedence
try{

    const t_compile_start = performance.now();
    // const re = /(?:(?:[a-z]+)*)(?=:)/g; // bad timeout on node
    // const re = /(([a-z])+)*:/g // also bad timeout on node
    const re = /(a+)+:/g
    const t_compile_end = performance.now();
    
    // const input = "le0i1xoa2bbhey0vg79f2mtujiqktmqt5gqwpa9g49vet63zwun2ancc0z87p_#}]";
    // "leeeeeeeeeeeeeeeeeeeeeeeeeeee_#}]" -- takes 22s
    // "leeeeeeeeeeeeeeeeeeeeeeeeeee_#}]" -- takes 11s
    // "leeeeeeeeeeeeeeeeeeeeeeeeee_#}]" -- takes 5s
    // const input = "leeeeeeeeeeeeeeeeeeeeeeeeee_}]";

    const input =    "aaaaaaaaaaaaaaaaaaaaaaaaaaa_";

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
