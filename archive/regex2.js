const regex1 = /\x0B/; // Works because it's just the character VT
const regex2 = /\u000B/; // Syntax error if misused (not common but possible)

console.log(regex2.test('\v')); // true


