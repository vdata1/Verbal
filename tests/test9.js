const re = /(?=a)/gu;
const s = "aaa";

let count = 0;
while (re.exec(s)) {
  count++;
}
console.log(count);

