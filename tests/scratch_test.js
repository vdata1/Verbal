try {
    const input = "qr\n\!\J\\\n                             \\\n,\n\n\n x";
                            
    const t_compile_start = performance.now();
    const regex = new RegExp('r"\b(?:m|qr)\s*([^a-zA-Z0-9\s\{\(\[<])(\\?.)*?\s*\1[msixpodualgc]*"', 'g');
    const t_compile_end = performance.now();

    const t_exec_start = performance.now();
    console.log(regex.test(input));
    const t_exec_end = performance.now();

    console.log("COMPILE_MS:", t_compile_end - t_compile_start);
    console.log("EXEC_MS:", t_exec_end - t_exec_start);
} catch (e) {
	console.log(e)
}
