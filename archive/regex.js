const input1 = "$(?<_>(?!\\B[^]{3}(?<_>$\\f.|\\b)|^)|\\B)?|"

if (!input1) {
  console.log("Please provide a regex pattern as a command line argument.");
  process.exit(2);
}
//NFA input generator 
try {
  new RegExp(input1);
  let w = new RegExp(input1);
  w.exec("text");
  w.test("text");
  "text".match(w);
  "text".match(new RegExp(input1));
  "text".match(/x/);
  "text".test(/x/);
  "text".replace(/x/, "y");
  "text".search(/x/);
  "text".split(/x/);
  "text".matchAll(/x/);
  "text".replaceAll(/x/, "y");
  "text".toString().match(/x/);
  "text".toString().replace(/x/, "y");
  "text".toString().search(/x/);
  "text".toString().split(/x/);
  console.log("Valid regex");
  //process.exit(0)
} catch (e) {
  console.log("Invalid regex:", e.message);
  //process.exit(1)
}


