try {
  new RegExp("a**");
  console.log("compiled");
} catch (e) {
  console.log(e.name);
}

