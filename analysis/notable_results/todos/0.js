// Regex: \[\[[!gbiuso]*;[^;]*;[^\]]*\]?$
// Input: [[!bbsoboubussiiiggusgbuoissis!uu!iuuig!ugb!!obo!bobgiobiu!sso!is!u!!sogbso!soio!busgi!gsss!obis;c;]]
try {
  const t_compile_start = performance.now();
  const w = /\[\[[!gbiuso]*;[^;]*;[^\]]*\]?$/i;
  const t_compile_end = performance.now();

  const input = "[[!bbsoboubussiiiggusgbuoissis!uu!iuuig!ugb!!obo!bobgiobiu!sso!is!u!!sogbso!soio!busgi!gsss!obis;c;]]";

  const t_exec_start = performance.now();
  console.log(input.toString().split(w));
  const t_exec_end = performance.now();

  console.log("COMPILE_MS:", t_compile_end - t_compile_start);
  console.log("EXEC_MS:", t_exec_end - t_exec_start);
} catch (error) {
  console.log(error);
}

