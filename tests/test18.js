const re = /^(?<x>a|aa)\k<x>$/;
console.log(re.test("aa"));
console.log(re.test("aaaa"));

