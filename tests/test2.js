const re = /(a|aa)+$/;
const input = "a".repeat(28) + "X";

console.time("test");
const result = re.test(input);
console.timeEnd("test");
console.log(result);

