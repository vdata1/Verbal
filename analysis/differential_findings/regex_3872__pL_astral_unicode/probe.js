const cps = [0x18DEF,0x275D9,0x3038E,0x32777,0x32BCF,0x32C06,0x32D50];
const re = /[\p{L}0-9]/u;
const out = cps.map(cp => ({cp:"U+"+cp.toString(16).toUpperCase().padStart(5,"0"),
                            isL: re.test(String.fromCodePoint(cp))}));
console.log(JSON.stringify(out));
