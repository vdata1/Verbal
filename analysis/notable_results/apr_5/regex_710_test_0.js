// Regex: ^(?:((['](\\[']|[^'])*['])|(["](\\["]|[^"])*["]))(?=[!]))
// Input: "9U/\"53\"\"TA\"!.+\"\"\"94'P\"$\"\"51IQ\"'\"+\"\"\""!A
// T17: backreferences
try{

    const t_compile_start = performance.now();
    const re = /^(?:((['](\\[']|[^'])*['])|(["](\\["]|[^"])*["]))(?=[!]))/v;
    const t_compile_end = performance.now();
    
    const input = "\"9U/\\\"53\\\"\\\"TA\\\"!.+\\\"\\\"\\\"94\'P\\\"$\\\"\\\"51IQ\\\"\'\\\"+\\\"\\\"\\\"\"!A";

    const t_exec_start = performance.now();
    console.log(re.exec(input));
    const t_exec_end = performance.now();

    console.log("COMPILE_MS:", t_compile_end - t_compile_start);
    console.log("EXEC_MS:", t_exec_end - t_exec_start);
}catch(error){
  console.log(error)
}
