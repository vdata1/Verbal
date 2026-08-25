// Maybe trying to encode the discrepancy symbol directly? If it works in Bun but not the others. 

// Regex: [_$a-zA-Z\xA0-\uFFFF][_$a-zA-Z0-9\xA0-\uFFFF]*(?=\()
// Input: 凅蜐脏㋔萰봐���˰ꂄ̿ច쥛鵎嶪沕胣˔䫢ᣃ瓃륞ꇜ㺋釳킊猵䇌寰熜雈俎缵ㄽ匆婃舄뎾Ꜻ䑑���ꩣᓿ㊐欻ꊚ꿴羔糞㳰쵐㜘ᅑ琦쀻ੳ(
// T18: alternation precedence
try{

    const t_compile_start = performance.now();
    const re = /[_$a-zA-Z\xA0-\uFFFF][_$a-zA-Z0-9\xA0-\uFFFF]*(?=\()/g;
    const t_compile_end = performance.now();

    let input = "凅蜐脏㋔萰봐���˰ꂄ̿ច쥛鵎嶪沕胣˔䫢ᣃ瓃륞ꇜ㺋釳킊猵䇌寰熜雈俎缵ㄽ匆婃舄뎾Ꜻ䑑���ꩣᓿ㊐欻ꊚ꿴羔糞㳰쵐㜘ᅑ琦쀻ੳ(";
    input = input + input;

    const t_exec_start = performance.now();
    console.log(str_to_bytes_( re.exec(input) ));
    const t_exec_end = performance.now();

    for(const m of input.matchAll(re)) {
        console.log(m);
    }

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
