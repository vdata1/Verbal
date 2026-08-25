const s1 = "é";          // U+00E9
const s2 = "e\u0301";   // decomposed

console.log(/é/u.test(s2));

