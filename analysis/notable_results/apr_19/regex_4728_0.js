// Same, display \u____ and question marks.

// Regex: [_$a-zA-Z\xA0-\uFFFF][_$a-zA-Z0-9\xA0-\uFFFF]*(?=\s*\()
// Input: 尤絬ꇈ嘂ﾘ膅雁ͱ㜏眨⣴ݬ긲졺愕傲嚧䎇訧喋솲樦ബ牭䡾䟐름叟㕜〰ᔲ巯짼둿ζ縤锷瘃鲡튢뿠ꉇ抅駮鴌ȡ���疎⫗޶呠䣶씋媆���坰ゴ禔旍(
try {
  const t_compile_start = performance.now();
  const w = new RegExp("[_$a-zA-Z\\xA0-\\uFFFF][_$a-zA-Z0-9\\xA0-\\uFFFF]*(?=\\s*\\()", "g");
  const t_compile_end = performance.now();

  const input = "尤絬ꇈ嘂ﾘ膅雁ͱ㜏眨⣴ݬ긲졺愕傲嚧䎇訧喋솲樦ബ牭䡾䟐름叟㕜〰ᔲ巯짼둿ζ縤锷瘃鲡튢뿠ꉇ抅駮鴌ȡ���疎⫗޶呠䣶씋媆���坰ゴ禔旍(";

  const t_exec_start = performance.now();
  console.log(str_to_bytes_( w.exec(input) ));
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
