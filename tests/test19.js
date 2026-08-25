const re = /(?=(a))/g;
re.exec("a");
console.log(RegExp.$1);
re.exec("b");
console.log(RegExp.$1);

