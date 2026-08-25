const re = /^(a|ab|aba|abab|ababa|ababab)+$/;
const input = "ab".repeat(18) + "X";

console.time("alt");
re.test(input);
console.timeEnd("alt");

