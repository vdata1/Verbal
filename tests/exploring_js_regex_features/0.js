

const a_str = "ቈ躷㐕學썬\udf61呭㱳躟뼱ೀ䂋ᗅ䒘畚눜䵿꧍赩屒數ᐘ쓌䙯䗧〜҄ボ倉讶ꀞ㹨㞍긴뼱돿ㄵ⅙臾巘糦Ⲏ轸흧댟ᳵ\udee4쏘ֆ\udff3䀻肈鼪\udb48￺聲帐䷵먚﮷᝙ኞ㪸時㢉쿝ዔ鈣ߴぅ홰멅袴閰"

const regex = /[a-zA-Z0-9]+/g

const matches = a_str.match(regex)

console.log(matches)