// Interesting bc \u____

// Regex: ([^\s\u0080-\uFFFF]*[\u0080-\uFFFF]+[^\s\u0080-\uFFFF]*(?:\s+[^\s\u0080-\uFFFF]*[\u0080-\uFFFF]+[^\s\u0080-\uFFFF]*\s*)?)+(?=\s|$)
// Input: Q㪻䁳彚妚滳䈧䡒宲﨨䱤跩쨵탾껿䅗妺졒劈鿯ꃗذ���淀醨㘝燛뻯꾇㶜㡎⼦ฯ꾃禇컦䙩긾穟宇撋褲䬎㜢竿冨蛙᭖꨼셩㷛핉螑ꃰ걎듂疓赖e
// T18: alternation precedence
try{

    const t_compile_start = performance.now();
    const re = /([^\s\u0080-\uFFFF]*[\u0080-\uFFFF]+[^\s\u0080-\uFFFF]*(?:\s+[^\s\u0080-\uFFFF]*[\u0080-\uFFFF]+[^\s\u0080-\uFFFF]*\s*)?)+(?=\s|$)/g;
    const t_compile_end = performance.now();
    
    const input = "Q㪻䁳彚妚滳䈧䡒宲﨨䱤跩쨵탾껿䅗妺졒劈鿯ꃗذ���淀醨㘝燛뻯꾇㶜㡎⼦ฯ꾃禇컦䙩긾穟宇撋褲䬎㜢竿冨蛙᭖꨼셩㷛핉螑ꃰ걎듂疓赖e";

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
    return str ;
}

function str_to_bytes(str) {
    const encoder = new TextEncoder();
    const byte_array = encoder.encode(str);
    // Return a string representation of the byte array, where each byte is represented as \xNN
    return Array.from(byte_array).map(byte => '\\x' + byte.toString(16).padStart(2, '0')).join('');
}
