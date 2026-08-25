// Displays the unicode differently, \u____ in bun, ??? in deno/node

// Regex: ^(?!\d)[$\w\x7f-\uffff]+$
// Input: ﹉뼘♥뙉撌ￋ秦䤤藶癥���ọ䑋犀쑲ኅැ숓伻┲즐忪Ń轏磯๺陮䕁㧒ꯣሁ惨ꅺ뚖鑧ո졀︞���閍䏳���풛祏쯫ื䖰봤ᄫꩭꕳท聱✺딡ᙄ蠰ㆤ
// T18: alternation precedence
try{

    const t_compile_start = performance.now();
    const re = /^(?!\d)[$\w\x7f-\uffff]+$/g;
    const t_compile_end = performance.now();
    
    const input = "﹉뼘♥뙉撌ￋ秦䤤藶癥���ọ䑋犀쑲ኅැ숓伻┲즐忪Ń轏磯๺陮䕁㧒ꯣሁ惨ꅺ뚖鑧ո졀︞���閍䏳���풛祏쯫ื䖰봤ᄫꩭꕳท聱✺딡ᙄ蠰ㆤ";

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
