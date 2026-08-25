const re = /^(a+)+$/;
const input = "a".repeat(30) + "X";

console.time("test");
re.test(input);
console.timeEnd("test");

