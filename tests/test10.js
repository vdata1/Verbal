const re = /(a)+/g;

try {
  re.exec({
    toString() {
      throw new Error("boom");
    }
  });
} catch {}

console.log(re.lastIndex);

