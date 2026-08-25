const re = /((a?){25}){25}/;
const input = "a".repeat(25);

try {
  re.test(input);
  console.log("finished");
} catch (e) {
  console.log(e.name);
}

