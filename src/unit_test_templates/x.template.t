try{

    const t_compile_start = performance.now();

    const t_compile_end = performance.now();
    
    const input = "$input";

    const t_exec_start = performance.now();


    const t_exec_end = performance.now();

    console.log("COMPILE_MS:", t_compile_end - t_compile_start);
    console.log("EXEC_MS:", t_exec_end - t_exec_start);
}catch(error){
  console.log(error)
}
