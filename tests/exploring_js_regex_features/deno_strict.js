// Regex: (?:('|").*?\1)
// Input: 'wÂ ?å¤ôºò¡­Çàª'
try {
  const t_compile_start = performance.now();
  const w = new RegExp("(?:(\'|\").*?\1)", "g");
  const t_compile_end = performance.now();

  const input = "\'wÂ ?å¤ôºò¡­Çàª\'";

  const t_exec_start = performance.now();
  console.log(str_to_bytes( w.exec(input) ));
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


function str_to_bytes(str) {
    const encoder = new TextEncoder();
    const byte_array = encoder.encode(str);
    // Return a string representation of the byte array, where each byte is represented as \xNN
    return Array.from(byte_array).map(byte => '\\x' + byte.toString(16).padStart(2, '0')).join('');
}
