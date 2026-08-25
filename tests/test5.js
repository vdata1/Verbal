const re = /[\p{Letter}&&[^\p{ASCII}]]/g;
console.log(re.test("é"));

