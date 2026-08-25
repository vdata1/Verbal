const re = /(a)/g;
const m1 = re.exec("a");
const m2 = re.exec("a");

//console.log(m1[0], m2[0]);
console.log(m1, m2)
console.log(m1 === m2);

