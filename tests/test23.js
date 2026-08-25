const re = /(a)+/g;
try { re.exec({ toString(){ throw 1 } }); } catch {}
console.log(re.lastIndex);

