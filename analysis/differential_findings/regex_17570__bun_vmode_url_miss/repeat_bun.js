"use strict";
const P="^(?:(?:http|https|ftp)://)(?:\\S+(?::\\S*)?@)?(?:(?:(?:[1-9]\\d?|1\\d\\d|2[01]\\d|22[0-3])(?:\\.(?:1?\\d{1,2}|2[0-4]\\d|25[0-5])){2}(?:\\.(?:[0-9]\\d?|1\\d\\d|2[0-4]\\d|25[0-4]))|(?:(?:[a-z\\u00a1-\\uffff0-9]+-?)*[a-z\\u00a1-\\uffff0-9]+)(?:\\.(?:[a-z\\u00a1-\\uffff0-9]+-?)*[a-z\\u00a1-\\uffff0-9]+)*(?:\\.(?:[a-z\\u00a1-\\uffff]{2,})))|localhost)(?::\\d{2,5})?(?:(/|\\?|#)[^\\s]*)?$", I="https://\ub000\ud865\u70e2\ufe70\uc197\uf03f\u8aeb\u0c75\udb1f\ucaf3\u4f89\u1491\uc11c\uc25e\u0679\u5e9c-\uedf1\u4414\u514d\u10bb\u6fcf\u06be\uf010\ue320-\u6034\ubf42\u573f\ue8fc\udd72\uff71\u6b72\u40ea\udd00\u194f\uff63\u3b72\ubf52\ub90a\u8ca1\ud48d\u902b\u15d8\udfd1\u0983\uce2f\ufb29\uddfc\u88b1\u987b\u2d1b-\u4577.\uc90b\ub1c2\u0ee2-\ue435.\u0da7\u62c1";
for (const flags of ["v",""]) {
  const vals=new Set(); const ts=[];
  for (let k=0;k<25;k++){
    const re=new RegExp(P,flags);          // fresh compile each iteration
    const t0=performance.now(); const v=re.test(I); ts.push(performance.now()-t0);
    vals.add(v);
  }
  ts.sort((a,b)=>a-b);
  console.log(JSON.stringify({flags:flags||"none", values:[...vals],
    min:+ts[0].toFixed(3), median:+ts[12].toFixed(3), max:+ts[24].toFixed(3)}));
}
