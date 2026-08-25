// Regex: ^case(?=\s)
// Input: case äºò¢©ÈTÛØã²³ÞÊ¾hË]!î ¢à¹¥äó¼£±Ô¦ò½¡
try {
  const t_compile_start = performance.now();
  const w = /^case(?=\s)/g;
  const t_compile_end = performance.now();

  const input = "case äºò¢©ÈTÛØã²³ÞÊ¾hË]!î ¢à¹¥äó¼£±Ô¦ò½¡";

  const t_exec_start = performance.now();
  console.log(input.toString().split(w));
  const t_exec_end = performance.now();

  console.log("COMPILE_MS:", t_compile_end - t_compile_start);
  console.log("EXEC_MS:", t_exec_end - t_exec_start);
} catch (error) {
  console.log(error);
}

