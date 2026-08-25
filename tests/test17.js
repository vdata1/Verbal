for (let i = 0; i < 1e6; i++) {
  new RegExp("(a+)+$").test("a".repeat(10));
}
console.log("done");

