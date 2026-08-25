// Display again

// Regex: [_$a-zA-Z\xA0-\uFFFF][$\w\xA0-\uFFFF]*(?=\s*\(|\.(?:apply|bind|call)\()
// Input: 馬럏鶴解䆵쳄䱫覣ﴲ㭄ɞ硖ꑵ䶬赅ﭥⷦ핈㈸毺譐ۏ⃓痯岁嶊䳜姶턧敬됍Ѥ吾Ⓐପ싑䀃硌挅⬆���뉸냘轴ꋛ㧳⽒疛啜鰐䥞砵飦\r(

// T14: replace() with function
try{
  const t_compile_start = performance.now();
  const re = /[_$a-zA-Z\xA0-\uFFFF][$\w\xA0-\uFFFF]*(?=\s*\(|\.(?:apply|bind|call)\()/i;
  const t_compile_end = performance.now();
  
  const input = "馬럏鶴解䆵쳄䱫覣ﴲ㭄ɞ硖ꑵ䶬赅ﭥⷦ핈㈸毺譐ۏ⃓痯岁嶊䳜姶턧敬됍Ѥ吾Ⓐପ싑䀃硌挅⬆���뉸냘轴ꋛ㧳⽒疛啜鰐䥞砵飦\r(";

  const t_exec_start = performance.now();
  const result = input.replace(re, (...args) => {
    console.log(str_to_bytes_( args ));
    return "X";
  });
  console.log(result);
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
