try {
  new RegExp("(?<=ab|a)c");
  console.log("compiled");
} catch (e) {
  console.log(e.name);
}

