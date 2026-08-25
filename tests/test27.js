try {
  /(a\p{NonexistentProperty})/u;
  console.log("compiled");
} catch (e) {
  console.log(e.name);
}

