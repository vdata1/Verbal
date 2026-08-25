let x =  "a".replace(/(a)/g, () => {
  console.log(RegExp.$1);
  return "b";
});

console.log(x)

