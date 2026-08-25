const re = /(?<x>a|aa)+$/;
const input = "a".repeat(20) + "X";

try {
  re.exec(input);
} catch {}

console.log(RegExp.$<x>);

