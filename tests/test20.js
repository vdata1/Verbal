const t_compile_start = performance.now();
/^(a+)+$/.test("a".repeat(30) + "X")
const t_compile_end = performance.now();
console.log("time: ", (t_compile_end - t_compile_start)/1000)
