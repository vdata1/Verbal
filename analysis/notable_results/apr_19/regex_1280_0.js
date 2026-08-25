// Bun has one question mark, deno and node have three.

// Regex: [_$a-zA-Z\xA0-\uFFFF][_$a-zA-Z0-9\xA0-\uFFFF]*(?=\s*=\s*(?:function\b|(?:\([^()]*\)|[_$a-zA-Z\xA0-\uFFFF][_$a-zA-Z0-9\xA0-\uFFFF]*)\s*=>))
// Input: Ⲧ횆弶鸥菛⧃ᧆ㛹郗ั飃䘱㜫橛ẍ勘쥮闪懁灳ԓ奊Đ蒐㟃漒ᖳ◵\r\r \n\n	\n\n \n\n  \r=	\r\r\r  function
// T13: replaceAll()
try{

    const t_compile_start = performance.now();
    const re = /[_$a-zA-Z\xA0-\uFFFF][_$a-zA-Z0-9\xA0-\uFFFF]*(?=\s*=\s*(?:function\b|(?:\([^()]*\)|[_$a-zA-Z\xA0-\uFFFF][_$a-zA-Z0-9\xA0-\uFFFF]*)\s*=>))/g;
    const t_compile_end = performance.now();
    
    const input = "Ⲧ횆弶鸥菛⧃ᧆ㛹郗ั飃䘱㜫橛ẍ勘쥮闪懁灳ԓ奊Đ蒐㟃漒ᖳ◵\r\r \n\n	\n\n \n\n  \r=	\r\r\r  function";

    const t_exec_start = performance.now();
    console.log(str_to_bytes_( input.replaceAll(re, "륇⃅䀩첯獴撵촼ꌑἦẓ刔㾗옾杙虄槑쁠괞䇥ಚ䱵���უ䘓釀関ퟎ죘┆䴉 \r\r\r\n	\r\r \r	\n\r\n	    \n\n=	function") ));
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

function str_to_bytes_(str) { return str; }

function str_to_bytes(str) {
    const encoder = new TextEncoder();
    const byte_array = encoder.encode(str);
    // Return a string representation of the byte array, where each byte is represented as \xNN
    return Array.from(byte_array).map(byte => '\\x' + byte.toString(16).padStart(2, '0')).join('');
}
