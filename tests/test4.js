const re = /[\p{Letter}&&[^\p{ASCII}]]/u;
console.log(re.test("é"));

